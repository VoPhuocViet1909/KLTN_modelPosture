"""D3 – dự báo thời điểm xuống sức (onset) từ 30 phút đầu, LOSO theo người.

(m0) luôn nhắc ở phút 50. (m1) phút nhắc = trung vị onset của train (Kaplan–Meier). (m2) hazard rời rạc theo khối 10 phút: logistic L2 trên đặc trưng 30 phút đầu + chỉ số khối,
phiên kiểm duyệt đóng góp các khối tới cuối khối đủ cuối cùng với nhãn 0 (xử lý kiểm duyệt đúng cách); phút nhắc = đầu khối đầu tiên có xác suất tích lũy >= 0,5, trừ lề 5 phút.
Chỉ xét phiên đủ điều kiện có onset >= 30 phút hoặc kiểm duyệt. Đặc trưng tính trên bản CẮT 30 phút đầu (`common.truncate`) nên không thể dùng dữ liệu sau phút 29.
"""
import math

import numpy as np

import common as C
import blocks as BL
import survival as SV

METHODS = ("m0", "m1", "m2")
RATE_KEYS = ("timely_rate", "late_rate", "early_rate", "none_rate", "mae_min", "c_index", "reminders_per_hour")


def split_groups(analyses, P):
    """-> (compared, onset_early, ineligible): khóa phiên theo nhóm. onset sớm (< min_onset_min) báo riêng, không so sánh, không train."""
    lim = P["d3"]["min_onset_min"]
    cmp_, early, inel = [], [], []
    for k, a in analyses.items():
        if not a["eligible"]:
            inel.append(k)
        elif a["onset"] is not None and a["onset"] < lim:
            early.append(k)
        else:
            cmp_.append(k)
    return cmp_, early, inel


def session_features(s, P, Pf):
    """Vector đặc trưng (theo P["d3"]["features"]) từ chỉ phút 0..history_min-1 của phiên s."""
    H = P["d3"]["history_min"]
    s30 = C.truncate(s, H)
    assert s30.n <= H
    rows = BL.block_rows(s30, P, Pf)[:H // P["block"]["minutes"]]
    rates = np.array([r["bad_rate"] if not r["missing"] else np.nan for r in rows])
    ok = np.isfinite(rates)
    fill = float(rates[ok].mean()) if ok.any() else 0.0
    b = np.where(ok, rates, fill)
    b = np.concatenate([b, np.full(3 - len(b), fill)])[:3]
    slope = float(np.polyfit(np.arange(len(rows))[ok], rates[ok], 1)[0]) if ok.sum() >= 2 else 0.0
    cl = s30.classified
    share = np.nan_to_num(s30.cls, nan=0.0).sum(0) / cl.sum() if cl.sum() > 0 else np.zeros(6)
    tab = C.FE.minute_table(s30, Pf)
    hour = s30.hour_of_day(0)
    feats = dict(bad_b0=b[0], bad_b1=b[1], bad_b2=b[2], bad_slope=slope,
                 **{f"share_{c}": float(share[i]) for i, c in enumerate(C.D.CLASSES)},
                 longest_sitting_min=float(tab["sitting"].max()), alerts_total=float(s30.alerts.sum()),
                 missing_frac=float(1.0 - tab["obs"].mean()), hour_sin=math.sin(2 * math.pi * hour / 24),
                 hour_cos=math.cos(2 * math.pi * hour / 24))
    return np.array([feats[n] for n in P["d3"]["features"]], float)


# ---------------------------------------------------------------- hazard rời rạc (m2)
def person_period(items, P):
    """items: list dict(feat, onset, censor_min). -> X (n, F+1: đặc trưng + chỉ số khối), y. Phiên onset: các khối từ khối đầu hazard tới khối onset
    (nhãn 1 ở khối onset); phiên kiểm duyệt: tới khối đủ cuối cùng với nhãn 0."""
    B, first = P["block"]["minutes"], P["d3"]["first_hazard_block"]
    X, y = [], []
    for it in items:
        last = it["onset"] // B if it["onset"] is not None else it["censor_min"] // B - 1
        for k in range(first, last + 1):
            X.append([*it["feat"], k])
            y.append(int(it["onset"] is not None and k == last))
    return np.array(X, float).reshape(-1, len(P["d3"]["features"]) + 1), np.array(y, int)


class Hazard:
    def __init__(self, P):
        self.P = P

    def fit(self, items):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        X, y = person_period(items, self.P)
        self.n_rows, self.n_events = int(len(y)), int(y.sum())
        self.const = None
        if self.n_events == 0 or self.n_events == len(y):
            self.const = float(y.mean()) if len(y) else 0.0
            return self
        h = self.P["d3"]["hazard"]
        self.sc = StandardScaler().fit(X)
        self.m = LogisticRegression(C=h["C"], max_iter=h["max_iter"], random_state=self.P["seed"]).fit(self.sc.transform(X), y)
        self.coef = dict(zip([*self.P["d3"]["features"], "block_idx"], self.m.coef_[0].tolist()))
        return self

    def hazards(self, feat):
        d3 = self.P["d3"]
        ks = np.arange(d3["first_hazard_block"], d3["max_block_idx"] + 1)
        if self.const is not None:
            return ks, np.full(len(ks), self.const)
        X = np.column_stack([np.tile(feat, (len(ks), 1)), ks])
        return ks, self.m.predict_proba(self.sc.transform(X))[:, 1]

    def reminder(self, feat):
        """-> (phút nhắc hoặc None, rủi ro = hazard tích lũy). Phút nhắc = đầu khối đầu tiên có F >= ngưỡng trừ lề, không sớm hơn earliest_reminder_min."""
        d3, B = self.P["d3"], self.P["block"]["minutes"]
        ks, h = self.hazards(feat)
        F = 1 - np.cumprod(1 - h)
        hit = np.where(F >= d3["cum_prob_threshold"] - 1e-12)[0]
        r = None if not len(hit) else float(max(d3["earliest_reminder_min"], ks[hit[0]] * B - d3["margin_min"]))
        return r, float(h.sum())


def m1_reminder(items):
    """Trung vị onset của train theo Kaplan–Meier làm phút nhắc; None nếu đường cong không xuống tới 0,5."""
    t = [it["onset"] if it["onset"] is not None else it["censor_min"] for it in items]
    e = [it["onset"] is not None for it in items]
    return SV.kaplan_meier(t, e)["median"]


# ---------------------------------------------------------------- chấm điểm
def score_rows(rows, P):
    """rows: list dict(onset, censor_min, r, risk, hours). -> chỉ số gộp. Onset: đúng lúc / trễ / sớm quá / bỏ lỡ theo cửa sổ protocol."""
    win = P["timely_window_min"]
    on = [x for x in rows if x["onset"] is not None]
    timely = sum(x["r"] is not None and x["onset"] - win <= x["r"] <= x["onset"] for x in on)
    late = sum(x["r"] is not None and x["r"] > x["onset"] for x in on)
    early = sum(x["r"] is not None and x["r"] < x["onset"] - win for x in on)
    none = sum(x["r"] is None for x in on)
    err = [abs(x["r"] - x["onset"]) for x in on if x["r"] is not None]
    hours = sum(x["hours"] for x in rows)
    t = [x["onset"] if x["onset"] is not None else x["censor_min"] for x in rows]
    e = [x["onset"] is not None for x in rows]
    n = len(on)
    return dict(n_sessions=len(rows), n_onset=n, n_censored=len(rows) - n, timely=int(timely), late=int(late), early=int(early), none=int(none),
                timely_rate=timely / n if n else float("nan"), late_rate=late / n if n else float("nan"),
                early_rate=early / n if n else float("nan"), none_rate=none / n if n else float("nan"),
                mae_min=float(np.mean(err)) if err else float("nan"),
                c_index=SV.c_index(t, e, [x["risk"] for x in rows]),
                reminders=int(sum(x["r"] is not None for x in rows)),
                reminders_per_hour=sum(x["r"] is not None for x in rows) / hours if hours > 0 else float("nan"), hours=float(hours))


def bootstrap(rows_by_method_person, boot, P):
    """{method: {person: rows}} -> (CI từng chỉ số, CI chênh lệch m1-m0 và m2-m0). Lấy mẫu NGƯỜI có hoàn lại."""
    persons = sorted(next(iter(rows_by_method_person.values())))
    vals = {m: {k: [] for k in RATE_KEYS} for m in METHODS}
    diffs = {m: {k: [] for k in RATE_KEYS} for m in METHODS if m != "m0"}
    for pick in C.BT.resample_people(persons, boot):
        res = {m: score_rows([x for q in pick for x in rows_by_method_person[m][q]], P) for m in METHODS}
        for m in METHODS:
            for k in RATE_KEYS:
                vals[m][k].append(res[m][k])
                if m != "m0":
                    diffs[m][k].append(res[m][k] - res["m0"][k])
    return ({m: {k: C.BT.percentile_ci(v, boot) for k, v in d.items()} for m, d in vals.items()},
            {m: {k: C.BT.percentile_ci(v, boot) for k, v in d.items()} for m, d in diffs.items()})


def run_d3(sessions, analyses, P, Pf, log=print):
    cmp_keys, early_keys, inel = split_groups(analyses, P)
    items = {}
    for k in cmp_keys:
        a = analyses[k]
        items[k] = dict(participant=a["participant"], session_id=a["session_id"], onset=a["onset"], censor_min=a["censor_min"],
                        feat=session_features(sessions[k], P, Pf), hours=a["n_min"] / 60.0)
    people = sorted({it["participant"] for it in items.values()})
    out = dict(n_compared=len(cmp_keys), n_onset_before_min=len(early_keys), onset_before_min_sessions=[list(k) for k in early_keys],
               n_ineligible=len(inel), people=people)
    if len(people) < P["min_persons"]:
        out["skipped"] = f"chỉ {len(people)} người có phiên so sánh, cần >= {P['min_persons']}"
        return out, {}, []
    rows = {m: {p: [] for p in people} for m in METHODS}
    per_session, folds = {}, []
    for f, test_p in enumerate(people):
        train = [it for it in items.values() if it["participant"] != test_p]
        test_keys = [k for k, it in items.items() if it["participant"] == test_p]
        assert all(it["participant"] != test_p for it in train)
        haz = Hazard(P).fit(train)
        med = m1_reminder(train)
        folds.append(dict(test=test_p, n_train_sessions=len(train), n_train_events=sum(it["onset"] is not None for it in train),
                          m1_median_min=med, hazard_rows=haz.n_rows, hazard_events=haz.n_events,
                          hazard_constant=haz.const, hazard_coef=getattr(haz, "coef", None)))
        for k in test_keys:
            it = items[k]
            r2, risk2 = haz.reminder(it["feat"])
            rec = dict(participant=it["participant"], session_id=it["session_id"], onset=it["onset"], censor_min=it["censor_min"], hours=it["hours"])
            per = {"m0": (float(P["reference_reminder_min"]), 0.0), "m1": (None if med is None else float(med), 0.0), "m2": (r2, risk2)}
            for m, (r, risk) in per.items():
                rows[m][test_p].append(dict(rec, r=r, risk=risk))
            per_session[k] = {m: per[m][0] for m in METHODS}
        log(f"fold {f + 1}/{len(people)} test={test_p} train={len(train)} phiên, m1 trung vị={med}")
    pooled = {m: score_rows([x for p in people for x in rows[m][p]], P) for m in METHODS}
    ci, dci = bootstrap(rows, P["bootstrap"], P)
    out.update(pooled=pooled, ci95=ci, diff_vs_m0_ci95=dci, folds=folds, bootstrap=P["bootstrap"])
    return out, per_session, folds
