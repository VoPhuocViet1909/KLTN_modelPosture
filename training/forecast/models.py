"""C3 – bốn mô hình/mốc so sánh. Cùng giao diện: fit(train, val) / predict(ds) -> xác suất y = 1.

(a) giống phút hiện tại: tần suất dương của train theo nhóm tỷ lệ BAD của phút t.
(b) Markov bậc 1 theo trạng thái phút, xác suất >= bad_fraction BAD trong H phút bằng liệt kê mọi đường đi
    (mỗi trạng thái dùng tỷ lệ BAD trung bình của train; trạng thái X = phút không phân loại đủ, không tính vào mẫu số).
(c) logistic regression L2 trên đặc trưng phẳng C2 (chuẩn hóa fit trên train).
(d) GRU nhỏ (PyTorch CPU) trên chuỗi history_min phút, early stopping theo validation (tách theo người).
Tham số đều từ protocol.json. Seed cố định.
"""
import itertools

import numpy as np


def _const(ds, p):
    return np.full(len(ds["y"]), float(p))


class BaselineA:
    name = "a"

    def __init__(self, P):
        self.edges = np.array(P["baseline_a"]["bad_rate_bin_edges"])

    def _bin(self, ds):
        return np.clip(np.searchsorted(self.edges, ds["bad_rate"], side="right") - 1, 0, len(self.edges) - 2)

    def fit(self, train, val=None):
        b, y = self._bin(train), train["y"]
        self.glob = float(y.mean())
        self.freq = np.array([y[b == k].mean() if (b == k).any() else self.glob for k in range(len(self.edges) - 1)])
        return self

    def predict(self, ds):
        return self.freq[self._bin(ds)]


class MarkovB:
    name = "b"
    MIDS = [0.05, 0.175, 0.375, 0.625, 0.875]      # dự phòng khi nhóm không có phút nào trong train

    def __init__(self, P):
        self.lap = P["baseline_b"]["laplace"]
        self.H = P["label"]["horizon_min"]
        self.thr = P["label"]["bad_fraction"]
        self.K = len(P["baseline_b"]["state_edges"]) + 2     # các nhóm tỷ lệ BAD + X
        self.X = self.K - 1

    def fit(self, train, val=None):
        T = np.full((self.K, self.K), self.lap)
        for st in train["session_states"].values():
            for a, b in zip(st[:-1], st[1:]):
                T[a, b] += 1
        self.T = T / T.sum(1, keepdims=True)
        self.rate = np.zeros(self.K)
        for k in range(self.K - 1):
            r = [v for _, v in train["minute_rates"].get(k, [])]
            self.rate[k] = float(np.mean(r)) if r else self.MIDS[min(k, len(self.MIDS) - 1)]
        self.p_start = np.array([self._prob(s) for s in range(self.K)])
        return self

    def _prob(self, s0):
        total = 0.0
        for path in itertools.product(range(self.K), repeat=self.H):
            pr, prev = 1.0, s0
            for s in path:
                pr *= self.T[prev, s]
                prev = s
            obs = [s for s in path if s != self.X]
            if obs and sum(self.rate[s] for s in obs) >= self.thr * len(obs):
                total += pr
        return total

    def predict(self, ds):
        return self.p_start[ds["state"]]


class LogisticC:
    name = "c"

    def __init__(self, P):
        self.cfg = P["logistic"]
        self.seed = P["seed"]

    def fit(self, train, val=None):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        self.rate = float(train["y"].mean())
        self.const = len(np.unique(train["y"])) < 2
        if not self.const:
            self.sc = StandardScaler().fit(train["F"])
            self.m = LogisticRegression(C=self.cfg["C"], max_iter=self.cfg["max_iter"], random_state=self.seed).fit(
                self.sc.transform(train["F"]), train["y"])
        return self

    def predict(self, ds):
        if self.const:
            return _const(ds, self.rate)
        return self.m.predict_proba(self.sc.transform(ds["F"]))[:, 1]


class GruD:
    name = "d"

    def __init__(self, P):
        self.cfg = P["gru"]
        self.seed = P["seed"]

    def _net(self, c_in):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(s, c, h, layers):
                super().__init__()
                s.gru = nn.GRU(c, h, num_layers=layers, batch_first=True)
                s.out = nn.Linear(h, 1)

            def forward(s, x):
                o, _ = s.gru(x)
                return s.out(o[:, -1]).squeeze(-1)
        return Net(c_in, self.cfg["hidden"], self.cfg["layers"])

    def _norm(self, S):
        return ((S - self.mu) / self.sd).astype(np.float32)

    def fit(self, train, val=None):
        import torch
        torch.set_num_threads(self.cfg["threads"])
        torch.manual_seed(self.seed)
        S = train["S"]
        flat = S.reshape(-1, S.shape[-1])
        self.mu, self.sd = flat.mean(0), flat.std(0) + 1e-6
        net = self._net(S.shape[-1])
        opt = torch.optim.Adam(net.parameters(), lr=self.cfg["lr"], weight_decay=self.cfg["weight_decay"])
        loss_fn = torch.nn.BCEWithLogitsLoss()
        Xt, yt = torch.tensor(self._norm(S)), torch.tensor(train["y"], dtype=torch.float32)
        Xv = torch.tensor(self._norm(val["S"])) if val is not None else None
        yv = torch.tensor(val["y"], dtype=torch.float32) if val is not None else None
        best, best_state, bad, ep = np.inf, None, 0, 0
        g = torch.Generator().manual_seed(self.seed)
        for ep in range(self.cfg["max_epochs"]):
            net.train()
            perm = torch.randperm(len(Xt), generator=g)
            for i in range(0, len(Xt), self.cfg["batch"]):
                idx = perm[i:i + self.cfg["batch"]]
                opt.zero_grad()
                loss_fn(net(Xt[idx]), yt[idx]).backward()
                opt.step()
            if Xv is None:
                continue
            net.eval()
            with torch.no_grad():
                vl = float(loss_fn(net(Xv), yv))
            if vl < best - 1e-5:
                best, bad = vl, 0
                best_state = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= self.cfg["patience"]:
                    break
        if best_state is not None:
            net.load_state_dict(best_state)
        self.net, self.epochs, self.best_val_loss = net.eval(), ep + 1, best
        return self

    def predict(self, ds):
        import torch
        with torch.no_grad():
            return torch.sigmoid(self.net(torch.tensor(self._norm(ds["S"])))).numpy().astype(float)


MODELS = {"a": BaselineA, "b": MarkovB, "c": LogisticC, "d": GruD}
