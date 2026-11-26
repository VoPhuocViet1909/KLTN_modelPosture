"""Ghép nhãn (C1) + đặc trưng (C2) của mọi phiên thành một bảng mốc."""
from collections import Counter, defaultdict

import numpy as np

import features as FE
import labels as LB

ARRAY_KEYS = ("participant", "session_id", "minute", "y", "F", "S", "state", "bad_rate", "lead")


def build_dataset(sessions, P, shuffle_within_person_seed=None):
    """-> dict:
      participant/session_id/minute (N,), y (N,), F (N,D), S (N,T,C), state (N,), bad_rate (N,), lead (N,) (-1 = không có),
      session_states: {(participant, session_id): trạng thái từng phút}, minute_rates: {state: [(participant, tỷ lệ BAD)]},
      hours: {participant: giờ có mặt}, session_hours: {(participant, session_id): giờ có mặt},
      drops: Counter lý do bỏ, drops_by_person, n_candidates.
    shuffle_within_person_seed != None: xáo nhãn y TRONG từng người (đối chứng, mong đợi PR-AUC ~ tỷ lệ dương)."""
    edges = P["baseline_b"]["state_edges"]
    rows = defaultdict(list)
    drops, drops_by = Counter(), defaultdict(Counter)
    session_states, minute_rates = {}, defaultdict(list)
    hours, session_hours = defaultdict(float), {}
    cand = 0
    for key in sorted(sessions):
        s = sessions[key]
        tab = FE.minute_table(s, P)
        states = np.array([FE.state_of_minute(tab, t, edges) for t in range(s.n)])
        session_states[key] = states
        for t in range(s.n):
            if tab["obs"][t]:
                minute_rates[int(states[t])].append((s.participant, float(tab["bad_rate"][t])))
        session_hours[key] = float(s.presence.sum() / 3600.0)
        hours[s.participant] += session_hours[key]
        anchors, drop = LB.build_anchors(s, P)
        cand += s.n
        drops.update(drop)
        drops_by[s.participant].update(drop)
        for t, y in anchors:
            k = LB.first_bad_minute_offset(s, t, P)
            rows["participant"].append(s.participant)
            rows["session_id"].append(s.session_id)
            rows["minute"].append(t)
            rows["y"].append(y)
            rows["F"].append(FE.flat_features(tab, t, P))
            rows["S"].append(FE.seq_features(tab, t, P))
            rows["state"].append(int(states[t]))
            rows["bad_rate"].append(float(tab["bad_rate"][t]))
            rows["lead"].append(-1 if k is None else k)
    if not rows["y"]:
        raise ValueError("Không có mốc hợp lệ nào")
    ds = {k: np.array(v) for k, v in rows.items()}
    ds.update(session_states=session_states, minute_rates=dict(minute_rates), hours=dict(hours),
              session_hours=session_hours, drops=drops, drops_by_person={p: dict(c) for p, c in drops_by.items()},
              n_candidates=cand)
    if shuffle_within_person_seed is not None:
        rng = np.random.default_rng(shuffle_within_person_seed)
        y = ds["y"].copy()
        for p in np.unique(ds["participant"]):
            idx = np.where(ds["participant"] == p)[0]
            y[idx] = rng.permutation(y[idx])
        ds["y"] = y
    return ds


def subset(ds, people):
    """Phần của ds thuộc các người trong `people` (mảng mốc, trạng thái phút, tỷ lệ phút, giờ có mặt)."""
    people = set(people)
    mask = np.isin(ds["participant"], list(people))
    out = {k: ds[k][mask] for k in ARRAY_KEYS}
    out["session_states"] = {k: v for k, v in ds["session_states"].items() if k[0] in people}
    out["minute_rates"] = {s: [(p, r) for p, r in v if p in people] for s, v in ds["minute_rates"].items()}
    out["hours"] = {p: h for p, h in ds["hours"].items() if p in people}
    out["session_hours"] = {k: h for k, h in ds["session_hours"].items() if k[0] in people}
    return out


def stats(ds):
    """Thống kê in ra: số mốc, tỷ lệ dương theo người, số mốc bỏ theo lý do."""
    people = sorted(set(ds["participant"]))
    per = {p: dict(n=int((ds["participant"] == p).sum()), positive_rate=float(ds["y"][ds["participant"] == p].mean()),
                   dropped=ds["drops_by_person"].get(p, {})) for p in people}
    return dict(n_anchors=int(len(ds["y"])), n_minutes=int(ds["n_candidates"]), positive_rate=float(ds["y"].mean()),
                dropped=dict(ds["drops"]), per_person=per)
