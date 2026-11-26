"""Test pipeline dự báo C1–C4 bằng dữ liệu tự sinh / ví dụ tính tay. Chạy: python -m pytest training/forecast/tests -q"""
import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as D          # noqa: E402
import dataset as DS      # noqa: E402
import evaluate as EV     # noqa: E402
import features as FE     # noqa: E402
import labels as LB       # noqa: E402
import models as MD       # noqa: E402
import protocol as PR     # noqa: E402
import simulate as SIM    # noqa: E402

P = PR.load()
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone(timedelta(hours=7)))


def mk(good, bad, away=None, alerts=None, who="P1", sid="S1", window_sec=60.0):
    """Session từ danh sách giây GOOD / BAD mỗi phút. good[i] hoặc bad[i] = None -> phút mất tín hiệu (lớp NaN)."""
    n = len(good)
    cls = np.zeros((n, 6))
    miss = np.array([g is None or b is None for g, b in zip(good, bad)])
    cls[:, 0] = [0 if m else g for m, g in zip(miss, good)]
    cls[:, 1] = [0 if m else b for m, b in zip(miss, bad)]
    cls[miss] = np.nan
    away = np.zeros(n) if away is None else np.array(away, float)
    classified = np.nan_to_num(cls).sum(1)
    presence = classified.copy()
    covered = np.where(miss, 0.0, presence + away)
    return D.Session(participant=who, session_id=sid, started_at=T0, n=n, window_sec=window_sec,
                     window_start=[T0 + timedelta(minutes=i) for i in range(n)], covered=covered, presence=presence,
                     away=away, unknown=window_sec - covered, cls=cls,
                     alerts=np.zeros(n, int) if alerts is None else np.array(alerts, int))


def example():
    # 0: GOOD | 1–5: 50% BAD | 6–13: GOOD
    return mk([60] + [30] * 5 + [60] * 8, [0] + [30] * 5 + [0] * 8)


# ---------------------------------------------------------------- C1 nhãn
def test_labels_hand_example_and_end_of_session():
    s = example()
    anchors, drop = LB.build_anchors(s, P)
    assert [t for t, _ in anchors] == list(range(9))              # t = 9..13 không đủ 5 phút sau
    assert [y for _, y in anchors] == [1, 0, 0, 0, 0, 0, 0, 0, 0]  # t=0: 150/300 = đúng 50% -> 1; t=1: 120/300 -> 0
    assert drop == {"cuối phiên": 5}


def test_label_exact_50_percent_is_positive_and_49_is_not():
    s = example()
    assert LB.anchor_label(s, 0, P) == (1, None)
    s2 = mk([60] + [31] * 5 + [60] * 8, [0] + [29] * 5 + [0] * 8)     # 145/300 = 48,3%
    assert LB.anchor_label(s2, 0, P) == (0, None)


def test_anchor_requires_mostly_good_and_enough_data():
    s = mk([60, 20, 60, 60, 60, 60, 60, 60], [0, 40, 0, 0, 0, 0, 0, 0])        # phút 1: 33% GOOD
    assert LB.anchor_label(s, 1, P) == (None, "phút hiện tại không chủ yếu GOOD")
    s = mk([60, 20, 60, 60, 60, 60, 60, 60], [0, 0, 0, 0, 0, 0, 0, 0])         # phút 1: chỉ 20 s phân loại được
    assert LB.anchor_label(s, 1, P) == (None, "phút hiện tại ít dữ liệu")
    s = mk([60, 15, 60, 60, 60, 60, 60, 60], [0, 15, 0, 0, 0, 0, 0, 0])         # 30 s, 50% GOOD -> đạt cả hai
    assert LB.anchor_label(s, 1, P)[1] is None


def test_future_missing_fraction_boundary():
    # 5 phút sau của t=0 là phút 1..5. Thiếu 2/5 = 40% (<=50%) giữ lại; thiếu 3/5 = 60% bỏ.
    good = [60, 30, 30, 30, None, None, 60, 60, 60, 60]
    bad = [0, 30, 30, 30, None, None, 0, 0, 0, 0]
    assert LB.anchor_label(mk(good, bad), 0, P) == (1, None)                    # 90/180 = 50%
    good[3] = bad[3] = None
    assert LB.anchor_label(mk(good, bad), 0, P) == (None, "tương lai thiếu dữ liệu")
    # phút thiếu một phần: 5 phút sau chỉ có 30 s phân loại được mỗi phút -> thiếu đúng 50% (không > 50%): giữ lại
    assert LB.anchor_label(mk([60] + [30] * 5 + [60] * 4, [0] * 10), 0, P) == (0, None)
    # 29 s mỗi phút -> thiếu 51,7% > 50%: bỏ
    assert LB.anchor_label(mk([60] + [29] * 5 + [60] * 4, [0] * 10), 0, P) == (None, "tương lai thiếu dữ liệu")


def test_labels_do_not_cross_sessions():
    a, b = mk([60] * 8, [0] * 8, sid="A"), mk([60] * 8, [60] * 8, sid="B")
    ya = [y for _, y in LB.build_anchors(a, P)[0]]
    assert ya == [0, 0, 0]                                                       # phiên A không nhìn sang phiên B


def test_first_bad_minute_offset():
    s = mk([60, 60, 60, 20, 10, 60, 60, 60], [0, 0, 0, 40, 50, 0, 0, 0])
    assert LB.first_bad_minute_offset(s, 2, P) == 1
    assert LB.first_bad_minute_offset(s, 0, P) == 3
    assert LB.first_bad_minute_offset(s, 4, P) is None


# ---------------------------------------------------------------- C2 đặc trưng, rò rỉ tương lai
def _rand_session(seed, n=40):
    r = np.random.default_rng(seed)
    bad = r.uniform(0, 40, n)
    good = 60 - bad - r.uniform(0, 5, n)
    return mk(list(good), list(bad), away=list((r.random(n) < 0.1) * 40.0), alerts=list((r.random(n) < 0.1).astype(int)))


def test_features_do_not_change_when_future_changes():
    s = _rand_session(1)
    t = 20
    tab = FE.minute_table(s, P)
    f0, q0 = FE.flat_features(tab, t, P), FE.seq_features(tab, t, P)
    s2 = copy.deepcopy(s)
    r = np.random.default_rng(9)
    s2.cls[t + 1:, :] = r.uniform(0, 30, s2.cls[t + 1:, :].shape)           # sửa mọi thứ sau t
    s2.away[t + 1:] = 60
    s2.alerts[t + 1:] = 3
    s2.window_start = s2.window_start[:t + 1] + [w + timedelta(hours=5) for w in s2.window_start[t + 1:]]
    tab2 = FE.minute_table(s2, P)
    assert np.array_equal(f0, FE.flat_features(tab2, t, P))
    assert np.array_equal(q0, FE.seq_features(tab2, t, P))
    assert FE.state_of_minute(tab, t, P["baseline_b"]["state_edges"]) == FE.state_of_minute(tab2, t, P["baseline_b"]["state_edges"])
    # đối chứng: sửa phút <= t thì đặc trưng phải đổi
    s3 = copy.deepcopy(s)
    s3.cls[t - 1, 1] += 10
    assert not np.array_equal(f0, FE.flat_features(FE.minute_table(s3, P), t, P))


def test_sitting_resets_on_away_and_since_alert():
    s = mk([60] * 12, [0] * 12, away=[0, 0, 0, 40, 0, 0, 29, 0, 0, 0, 0, 0], alerts=[0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0])
    tab = FE.minute_table(s, P)
    assert list(tab["sitting"]) == [1, 2, 3, 0, 1, 2, 3, 4, 5, 6, 7, 8]     # away 40 >= 30 reset; away 29 không reset
    assert list(tab["since"][:3]) == [60, 0, 1] and tab["since"][8] == 0 and tab["since"][11] == 3


def test_history_start_of_session_is_flagged_not_filled():
    s = mk([60] * 12, [0] * 12)
    tab = FE.minute_table(s, P)
    f = FE.flat_features(tab, 2, P)
    assert f[FE.FLAT_NAMES.index("missing_frac")] == pytest.approx(0.7)        # chỉ có 3/10 phút
    q = FE.seq_features(tab, 2, P)
    assert q.shape == (10, len(FE.SEQ_NAMES)) and (q[:7] == 0).all()
    assert q[7:, FE.SEQ_NAMES.index("observed")].tolist() == [1, 1, 1]


def test_slope_and_shares():
    bad = [0, 6, 12, 18, 24, 30, 36, 42, 48, 54]
    s = mk([60 - b for b in bad], bad)
    f = FE.flat_features(FE.minute_table(s, P), 9, P)
    assert f[FE.FLAT_NAMES.index("bad_slope")] == pytest.approx(0.1)           # +6 s/phút = +0,1 tỷ lệ/phút
    assert f[FE.FLAT_NAMES.index("share_good")] == pytest.approx(330 / 600)      # tổng BAD = 6*(0+...+9) = 270 s
    assert f[FE.FLAT_NAMES.index("share_forward_head")] == pytest.approx(270 / 600)


# ---------------------------------------------------------------- đọc dữ liệu
def test_simulated_and_missing_classes_stay_nan(tmp_path):
    SIM.write_dataset(tmp_path / "d", persons=4, sessions=2, seed=5)
    ss = D.load(tmp_path / "d")
    assert any(np.isnan(s.cls).all(axis=1).any() for s in ss.values())          # phút mất tín hiệu = NaN, không phải 0
    for s in ss.values():
        nan_rows = np.isnan(s.cls).all(axis=1)
        assert ((s.unknown[nan_rows] == 60) | (s.presence[nan_rows] == 0)).all()    # mất tín hiệu hoặc rời ghế
        assert (np.abs(s.away + s.unknown + s.presence - 60) <= 1).all()


def test_loader_rejects_contract_violations(tmp_path):
    SIM.write_dataset(tmp_path / "ok", persons=1, sessions=1, seed=3)
    rows = [json.loads(x) for x in open(tmp_path / "ok" / "minutes.jsonl", encoding="utf-8")]

    def write(name, rs, drop=None):
        d = tmp_path / name
        d.mkdir()
        (d / "sessions.jsonl").write_text(open(tmp_path / "ok" / "sessions.jsonl", encoding="utf-8").read(), encoding="utf-8")
        with open(d / "minutes.jsonl", "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r) + "\n")
        return d
    bad = copy.deepcopy(rows)
    bad[10]["unknown_sec"] = 30.0
    with pytest.raises(D.DataError, match="window_sec"):
        D.load(write("coverage", bad))
    with pytest.raises(D.DataError, match="thiếu dòng phút"):
        D.load(write("gap", rows[:5] + rows[6:]))
    bad = copy.deepcopy(rows)
    bad[3]["window_start"] = bad[4]["window_start"]
    with pytest.raises(D.DataError, match="window_start"):
        D.load(write("time", bad))
    bad = copy.deepcopy(rows)
    k = next(i for i, r in enumerate(bad) if r["good_sec"] is not None)
    bad[k]["good_sec"] = bad[k]["presence_sec"] + 5
    with pytest.raises(D.DataError):
        D.load(write("classes", bad))


# ---------------------------------------------------------------- C3 mô hình
def test_markov_deterministic_chain():
    P2 = copy.deepcopy(P)
    P2["baseline_b"]["laplace"] = 0.0
    m = MD.MarkovB(P2)
    top = m.K - 2                                              # nhóm BAD cao nhất
    st = np.array([top] * 20)
    ds = dict(session_states={("p", "s"): st}, minute_rates={top: [("p", 0.9)] * 20})
    # các nhóm khác không có dữ liệu: laplace 0 -> chia 0; chỉ kiểm hàng của `top`
    m.lap = 0.0
    T = np.zeros((m.K, m.K))
    T[top, top] = 1.0
    m.T, m.rate = T, np.zeros(m.K)
    m.rate[top] = 0.9
    assert m._prob(top) == pytest.approx(1.0)
    m.rate[top] = 0.1
    assert m._prob(top) == pytest.approx(0.0)


def test_baseline_a_frequencies():
    ds = dict(bad_rate=np.array([0.05, 0.05, 0.25, 0.25, 0.25]), y=np.array([0, 1, 1, 1, 0]))
    a = MD.BaselineA(P).fit(ds)
    assert list(a.predict(ds)) == pytest.approx([0.5, 0.5, 2 / 3, 2 / 3, 2 / 3])


# ---------------------------------------------------------------- C4 nhắc, chỉ số, bootstrap
def _ds(minutes, y, hours=1.0, lead=None):
    n = len(minutes)
    return dict(participant=np.array(["P"] * n, dtype=object), session_id=np.array(["S"] * n, dtype=object),
                minute=np.array(minutes), y=np.array(y), lead=np.array(lead if lead is not None else [-1] * n),
                hours={"P": hours})


def test_reminder_silence_and_false_alert_rate():
    ds = _ds(list(range(10)), [0, 0, 1, 1, 0, 0, 0, 1, 1, 0], hours=2.0)
    p = np.ones(10)
    assert EV.reminder_minutes(ds["minute"], p, 0.5, 4) == [0, 4, 8]            # im ít nhất 4 phút
    fph, n = EV.false_per_hour(ds, p, 0.5, 4)
    assert n == 3 and fph == pytest.approx(2 / 2.0)                            # nhắc tại 0 (y=0), 4 (y=0), 8 (y=1) -> 2 nhầm / 2 giờ
    p2 = np.array([0, 0, 0.9, 0, 0, 0, 0, 0.9, 0, 0])
    assert EV.false_per_hour(ds, p2, 0.5, 4)[0] == 0.0


def test_lead_time_and_agg():
    ds = _ds([0, 1, 2], [1, 1, 0], hours=0.5, lead=[3, 1, -1])
    ag = EV.person_agg(ds, np.array([0.9, 0.2, 0.9]), 0.5, dict(P, reminder=dict(P["reminder"], silence_min=1)))
    assert ag["true"] == 1 and ag["false"] == 1 and ag["leads"] == [3] and ag["n_alerts"] == 2


def test_pick_threshold_meets_target_or_never_alerts():
    ds = _ds(list(range(0, 100, 10)), [0, 1, 0, 1, 0, 1, 0, 1, 0, 1], hours=10.0)
    p = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.4, 0.6, 0.5, 0.95])
    thr = EV.pick_threshold(ds, p, P)
    assert EV.false_per_hour(ds, p, thr, P["reminder"]["silence_min"])[0] <= P["reminder"]["target_false_per_hour"]
    assert thr < 0.5                                                              # 5 nhầm / 10 giờ = 0,5/giờ <= 2 -> ngưỡng thấp nhất
    ds2 = _ds(list(range(0, 100, 10)), [0] * 10, hours=0.1)     # 1 nhắc nhầm / 0,1 giờ = 10/giờ > 2
    assert EV.pick_threshold(ds2, np.linspace(0.1, 0.9, 10), P) > 1.0              # luôn nhầm: không nhắc


def test_pooled_metrics_hand_example():
    ag = dict(y=np.array([0, 0, 1, 1]), p=np.array([0.1, 0.6, 0.4, 0.9]), thr=0.5, hours=2.0, false=1, true=1, leads=[2], n_alerts=2)
    m = EV.pooled([ag])
    assert m["pr_auc"] == pytest.approx((1 + 2 / 3) / 2)
    assert m["brier"] == pytest.approx(0.185)
    assert m["sensitivity"] == pytest.approx(0.5) and m["false_per_hour"] == pytest.approx(0.5) and m["lead_mean"] == 2


def test_bootstrap_resamples_people_not_rows():
    def agg(correct):
        y = np.array([0, 1] * 10)
        p = y.astype(float) if correct else 1 - y.astype(float)
        return dict(y=y, p=p, thr=0.5, hours=1.0, false=0, true=0, leads=[], n_alerts=0)
    per = {"a": {"A": agg(True), "B": agg(False)}, "c": {"A": agg(True), "B": agg(True)}}
    ci, dci = EV.bootstrap(per, dict(n=300, ci=0.95, seed=0), ["a", "c"])
    # theo người: mẫu chỉ có {A,A}, {A,B}, {B,B} -> Brier của (a) thuộc {0, 0.5, 1}; CI phải rộng tới 0 và 1
    assert ci["a"]["brier"][0] == pytest.approx(0.0) and ci["a"]["brier"][1] == pytest.approx(1.0)
    assert ci["c"]["brier"] == [0.0, 0.0]
    assert dci["c"]["brier"][1] <= 0.0


def test_loso_never_shares_a_person_between_train_val_test():
    people = [f"P{i}" for i in range(8)]
    for f in range(8):
        val, fit = EV.split_val([p for i, p in enumerate(people) if i != f], P, f)
        assert people[f] not in val + fit and not set(val) & set(fit) and len(val) >= 1
        assert sorted(val + fit) == sorted(p for p in people if p != people[f])


def test_shuffle_control_keeps_counts_per_person(tmp_path):
    SIM.write_dataset(tmp_path / "d", persons=3, sessions=2, seed=11)
    ss = D.load(tmp_path / "d")
    a, b = DS.build_dataset(ss, P), DS.build_dataset(ss, P, shuffle_within_person_seed=0)
    for p in ["SIM01", "SIM02", "SIM03"]:
        assert a["y"][a["participant"] == p].sum() == b["y"][b["participant"] == p].sum()
    assert not np.array_equal(a["y"], b["y"])


def test_protocol_hash_ignores_line_endings(tmp_path):
    raw = PR.PROTOCOL_PATH.read_bytes()
    f1, f2 = tmp_path / "a.json", tmp_path / "b.json"
    f1.write_bytes(raw.replace(b"\r\n", b"\n"))
    f2.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert PR.protocol_hash(f1) == PR.protocol_hash(f2)


def test_labels_follow_protocol_not_constants():
    P2 = copy.deepcopy(P)
    P2["label"]["bad_fraction"] = 0.6
    assert LB.anchor_label(example(), 0, P)[0] == 1 and LB.anchor_label(example(), 0, P2)[0] == 0


def test_end_to_end_small(tmp_path):
    SIM.write_dataset(tmp_path / "d", persons=4, sessions=2, seed=21)
    P2 = copy.deepcopy(P)
    P2["gru"]["max_epochs"] = 3
    res, meta = EV.run(tmp_path / "d", tmp_path / "out", P=P2, boot_n=30, log=lambda *_: None)
    for f in ("predictions.csv", "metrics.json", "metrics.md", "pr_curve.png", "calibration.png", "run_meta.json"):
        assert (tmp_path / "out" / f).exists()
    head = open(tmp_path / "out" / "predictions.csv", encoding="utf-8").readline().strip()
    assert head == "participant,session_id,minute_idx,y,p_a,p_b,p_c,p_d"
    assert meta["protocol_override"] == {"bootstrap_n": 30} and "data_sha256" in meta and "protocol_sha256" in meta
    for fold in res["folds"]:
        assert fold["test"] not in fold["fit"] + fold["val"]
