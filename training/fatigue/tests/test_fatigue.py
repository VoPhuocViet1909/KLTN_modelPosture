"""Test pipeline D1–D3 bằng ví dụ tính tay / dữ liệu tự sinh. Chạy: python -m pytest training/fatigue/tests -q"""
import copy
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as C        # noqa: E402
import blocks as BL       # noqa: E402
import d3 as D3           # noqa: E402
import evaluate as EV     # noqa: E402
import survival as SV     # noqa: E402
import trend as TR        # noqa: E402
import simulate as SIM    # noqa: E402  (forecast/simulate.py, nối vào sys.path ở common.py)

P = C.load_protocol()
Pf = C.forecast_protocol()
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone(timedelta(hours=7)))


def sess(rates, frac=None, who="P1", sid="S1", extra_minutes=0, away=None, alerts=None):
    """Session từ tỷ lệ BAD mỗi khối 10 phút (None = khối thiếu: chỉ 40% phân loại được). frac = tỷ lệ phân loại được mỗi khối."""
    n_blocks = len(rates)
    n = n_blocks * 10 + extra_minutes
    cls = np.zeros((n, 6))
    for k, r in enumerate(rates):
        cl = 60.0 * (0.4 if r is None else (1.0 if frac is None else frac[k]))
        bad = 0.0 if r is None else r * cl
        cls[k * 10:(k + 1) * 10, 0] = cl - bad
        cls[k * 10:(k + 1) * 10, 1] = bad
    cls[n_blocks * 10:, 0] = 60.0
    away = np.zeros(n) if away is None else np.array(away, float)
    presence = cls.sum(1)
    covered = presence + away
    return C.D.Session(participant=who, session_id=sid, started_at=T0, n=n, window_sec=60.0,
                       window_start=[T0 + timedelta(minutes=i) for i in range(n)], covered=covered, presence=presence, away=away,
                       unknown=60.0 - covered, cls=cls, alerts=np.zeros(n, int) if alerts is None else np.array(alerts, int),
                       model_version=["test"] * n)


def an(rates, **kw):
    return BL.analyse_session(sess(rates, **kw), P, Pf)


# ---------------------------------------------------------------- khối, khối thiếu, đủ điều kiện
def test_blocks_drop_remainder_and_bad_rate():
    s = sess([0.2, 0.4, 0.1, 0.3], extra_minutes=7)
    rows = BL.block_rows(s, P, Pf)
    assert len(rows) == 4 and [r["block_start_min"] for r in rows] == [0, 10, 20, 30]      # 7 phút dư bị bỏ
    assert [round(r["bad_rate"], 6) for r in rows] == [0.2, 0.4, 0.1, 0.3]
    assert all(r["classified_sec"] == 600 and not r["missing"] for r in rows)


def test_block_missing_boundary_exactly_half():
    ok = BL.block_rows(sess([0.1] * 6, frac=[0.5] * 6), P, Pf)                      # 300/600 s = đúng 50% -> không thiếu
    assert not any(r["missing"] for r in ok)
    low = BL.block_rows(sess([0.1] * 6, frac=[0.49] * 6), P, Pf)
    assert all(r["missing"] for r in low)
    assert BL.block_rows(sess([0.1, None, 0.1, 0.1, 0.1, 0.1]), P, Pf)[1]["missing"]


def test_eligibility_rules():
    assert an([0.1] * 6)["eligible"]
    assert an([0.1] * 5 + [None])["eligible"]                                              # 60 phút, 5 khối không thiếu >= 4
    assert an([0.1] * 5)["reason"] == "phiên ngắn hơn min_session_min"                    # 50 phút < 60
    a = an([0.1, 0.1, None, None, None, 0.1, None])                                         # 70 phút nhưng 3 khối không thiếu
    assert not a["eligible"] and a["reason"] == "ít khối không thiếu"
    a = an([None, None, 0.1, 0.1, 0.1, 0.1])                                                # không có mức đầu buổi
    assert not a["eligible"] and a["reason"] == "không có mức đầu buổi"


# ---------------------------------------------------------------- mức đầu buổi, onset, kiểm duyệt
def test_baseline_uses_first_two_valid_blocks_weighted():
    a = an([0.1, 0.3, 0.1, 0.1, 0.1, 0.1], frac=[1.0, 0.5, 1, 1, 1, 1])
    assert a["baseline"] == pytest.approx((0.1 * 600 + 0.3 * 300) / 900)               # trọng số theo phân loại được
    assert an([None, 0.2, 0.2, 0.2, 0.2, 0.2])["baseline"] == pytest.approx(0.2)         # khối đầu thiếu: chỉ dùng khối còn lại


def test_onset_and_censoring():
    a = an([0.1, 0.1, 0.2, 0.3, 0.3, 0.1])           # ngưỡng 0,25: khối 3 và 4 liên tiếp -> onset phút 30
    assert a["onset"] == 30 and not a["censored"] and a["eligible"]
    a = an([0.1, 0.1, 0.1, 0.3, 0.1, 0.3])           # hai khối cao không liên tiếp
    assert a["onset"] is None and a["censored"] and a["censor_min"] == 60
    a = an([0.1, 0.1, 0.1, 0.1, 0.1, 0.5])           # khối cuối cao nhưng không có khối sau -> kiểm duyệt
    assert a["onset"] is None and a["censored"]
    a = an([0.1, 0.1, 0.1, 0.3, None, 0.3, 0.3])     # khối thiếu làm đứt chuỗi; khối 5,6 cao -> onset phút 50
    assert a["onset"] == 50
    a = an([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert a["onset"] is None and a["censor_min"] == 70


def test_onset_threshold_is_inclusive_and_ignores_baseline_blocks():
    assert an([0.1, 0.1, 0.1, 0.25, 0.25, 0.1])["onset"] == 30                              # đúng baseline + 0,15 tính
    assert an([0.1, 0.1, 0.1, 0.2499, 0.2499, 0.1])["onset"] is None
    assert an([0.6, 0.6, 0.6, 0.6, 0.6, 0.6])["onset"] is None                              # mức đầu buổi đã cao, không vượt thêm Δ
    a = an([0.1, 0.1, 0.5, 0.5, 0.1, 0.1])
    assert a["onset"] == 20                                                                   # khối 2 là khối đầu sau baseline


# ---------------------------------------------------------------- D3: chỉ dùng phút < 30
def _rand_session(seed, n=80):
    r = np.random.default_rng(seed)
    bad = r.uniform(0, 30, n)
    s = sess([0.1] * 8)
    s.cls[:, 1], s.cls[:, 0] = bad, 60 - bad
    s.alerts = (r.random(n) < 0.1).astype(int)
    s.away = (r.random(n) < 0.05) * 40.0
    return s


def test_d3_features_use_only_first_30_minutes():
    s = _rand_session(3)
    f0 = D3.session_features(s, P, Pf)
    s2 = copy.deepcopy(s)
    r = np.random.default_rng(1)
    s2.cls[30:] = r.uniform(0, 30, s2.cls[30:].shape)                                # đổi mọi thứ từ phút 30 trở đi
    s2.away[30:], s2.alerts[30:] = 60.0, 4
    s2.window_start = s2.window_start[:30] + [w + timedelta(hours=7) for w in s2.window_start[30:]]
    assert np.array_equal(f0, D3.session_features(s2, P, Pf))
    s3 = copy.deepcopy(s)
    s3.cls[29, 1] += 5                                                                   # đổi phút 29 thì đặc trưng phải đổi
    assert not np.array_equal(f0, D3.session_features(s3, P, Pf))
    assert len(f0) == len(P["d3"]["features"]) and C.truncate(s, 30).n == 30 and s.n == 80


def test_d3_feature_values_hand_example():
    s = sess([0.1, 0.2, 0.4, 0.9, 0.9, 0.9, 0.9, 0.9])
    f = dict(zip(P["d3"]["features"], D3.session_features(s, P, Pf)))
    assert (f["bad_b0"], f["bad_b1"], f["bad_b2"]) == pytest.approx((0.1, 0.2, 0.4))
    assert f["bad_slope"] == pytest.approx(0.15)                                           # hồi quy theo chỉ số khối
    assert f["share_forward_head"] == pytest.approx(0.7 / 3) and f["share_good"] == pytest.approx(1 - 0.7 / 3)
    assert f["longest_sitting_min"] == 30 and f["alerts_total"] == 0 and f["missing_frac"] == 0
    assert f["hour_sin"] == pytest.approx(np.sin(2 * np.pi * 9 / 24))


def test_split_groups_report_early_onset_separately():
    A = {("p", "a"): an([0.1, 0.1, 0.5, 0.5, 0.5, 0.5]), ("p", "b"): an([0.1] * 6), ("p", "c"): an([0.1, 0.1, 0.1, 0.5, 0.5, 0.5]),
         ("p", "d"): an([0.1] * 3)}
    cmp_, early, inel = D3.split_groups(A, P)
    assert early == [("p", "a")] and sorted(cmp_) == [("p", "b"), ("p", "c")] and inel == [("p", "d")]


# ---------------------------------------------------------------- hazard với dữ liệu kiểm duyệt
def test_person_period_handles_censoring_exactly():
    F = len(P["d3"]["features"])
    items = [dict(feat=np.zeros(F), onset=50, censor_min=70), dict(feat=np.ones(F), onset=None, censor_min=80)]
    X, y = D3.person_period(items, P)
    assert y.tolist() == [0, 0, 1] + [0] * 5                         # onset ở khối 5: khối 3,4 -> 0, khối 5 -> 1; kiểm duyệt (80 phút): khối 3..7 đều 0
    assert X[:, -1].tolist() == [3, 4, 5] + [3, 4, 5, 6, 7]
    assert X[:3, :-1].sum() == 0 and X[3:, :-1].min() == 1


def test_hazard_const_rule_cumulative_probability_and_margin():
    h = D3.Hazard(P)
    h.const = 0.2
    r, risk = h.reminder(np.zeros(len(P["d3"]["features"])))
    assert r == 55.0                                                # F: 0,2; 0,36; 0,488; 0,590 -> khối 6 (phút 60) trừ lề 5
    assert risk == pytest.approx(0.2 * (P["d3"]["max_block_idx"] - 3 + 1))
    h.const = 0.0
    assert h.reminder(np.zeros(len(P["d3"]["features"])))[0] is None  # không bao giờ tới 0,5 -> không nhắc
    h.const = 0.99
    assert h.reminder(np.zeros(len(P["d3"]["features"])))[0] == P["d3"]["earliest_reminder_min"]   # khối 3 -> 25, kẹp xuống 30


def test_hazard_learns_a_deterministic_relation_with_censoring():
    r = np.random.default_rng(0)
    F = len(P["d3"]["features"])
    items = []
    for i in range(60):
        k_on = int(r.integers(3, 9))
        feat = np.zeros(F)
        feat[3] = (k_on - 6) / 3.0                                                         # đặc trưng xác định onset
        cens = r.random() < 0.3
        items.append(dict(feat=feat, onset=None if cens else k_on * 10, censor_min=(k_on + 1) * 10 if cens else k_on * 10 + 20))
    tr, te = items[:45], items[45:]
    hz = D3.Hazard(P).fit(tr)
    assert hz.n_events > 0
    err = []
    for it in te:
        if it["onset"] is not None:
            rem, _ = hz.reminder(it["feat"])
            err.append(abs(rem - it["onset"]))
    assert np.mean(err) < 15                                                                 # hazard bắt được quan hệ dù có kiểm duyệt
    # không có sự kiện nào -> hazard hằng 0 -> không nhắc
    none = D3.Hazard(P).fit([dict(feat=np.zeros(F), onset=None, censor_min=70)] * 5)
    assert none.const == 0.0 and none.reminder(np.zeros(F))[0] is None


def test_m1_reminder_is_km_median():
    items = [dict(onset=40, censor_min=80), dict(onset=60, censor_min=80), dict(onset=None, censor_min=80), dict(onset=50, censor_min=70)]
    assert D3.m1_reminder(items) == 50                                                     # S: 0,75 (40), 0,5 (50) -> trung vị 50
    assert D3.m1_reminder([dict(onset=None, censor_min=80)] * 3 + [dict(onset=40, censor_min=80)]) is None


# ---------------------------------------------------------------- chấm điểm, C-index, KM
def _row(onset, r, risk=0.0, censor=80, hours=1.0):
    return dict(onset=onset, censor_min=censor, r=r, risk=risk, hours=hours)


def test_timely_window_boundaries():
    rows = [_row(60, 45), _row(60, 44), _row(60, 60), _row(60, 61), _row(60, None)]
    m = D3.score_rows(rows, P)
    assert (m["timely"], m["early"], m["late"], m["none"]) == (2, 1, 1, 1)               # 45 và 60 đều đúng lúc (cửa sổ đóng)
    assert m["timely_rate"] == 0.4 and m["mae_min"] == pytest.approx((15 + 16 + 0 + 1) / 4)


def test_censored_sessions_count_reminders_per_hour_but_not_timeliness():
    m = D3.score_rows([_row(60, 50, hours=2), _row(None, 50, hours=2), _row(None, None, hours=1)], P)
    assert m["n_onset"] == 1 and m["reminders"] == 2 and m["reminders_per_hour"] == pytest.approx(2 / 5)


def test_c_index_hand_examples_and_censoring():
    assert SV.c_index([1, 2, 3], [1, 1, 0], [3, 2, 1]) == 1.0
    assert SV.c_index([1, 2, 3], [1, 1, 0], [1, 2, 3]) == 0.0
    assert SV.c_index([1, 2, 3], [1, 1, 0], [1, 1, 1]) == 0.5
    # i=0 (onset ở 3): j=1 bị kiểm duyệt sớm hơn (ở 2) -> không so sánh được; j=2 đồng thuận (risk 1 > 0), j=3 bất đồng (1 < 2) -> 0,5
    assert SV.c_index([3, 2, 4, 5], [1, 0, 0, 0], [1, 5, 0, 2]) == pytest.approx(0.5)
    assert SV.c_index([3, 2, 4], [1, 0, 0], [1, 5, 0]) == 1.0                           # chỉ còn cặp (0,2), đồng thuận
    assert np.isnan(SV.c_index([1, 2], [0, 0], [1, 2]))


def test_kaplan_meier_hand_example():
    km = SV.kaplan_meier([2, 3, 3, 5], [1, 1, 0, 1])
    assert [(t, round(s, 4), n, d) for t, s, n, d in km["steps"]] == [(2.0, 0.75, 4, 1), (3.0, 0.5, 3, 1), (5.0, 0.0, 1, 1)]
    assert km["median"] == 3.0 and km["n_events"] == 3
    assert SV.kaplan_meier([5, 6, 7], [0, 0, 0])["median"] is None


def test_onset_distribution_per_person():
    A = {("a", "1"): an([0.1, 0.1, 0.1, 0.5, 0.5, 0.5], who="a"), ("a", "2"): an([0.1, 0.1, 0.1, 0.1, 0.5, 0.5, 0.5], who="a", sid="2"),
         ("b", "1"): an([0.1] * 6, who="b")}
    d = SV.onset_distribution(A)
    assert d["n_eligible"] == 3 and d["n_onset"] == 2 and d["per_person"]["a"]["median"] == 35.0
    assert d["per_person"]["b"]["median"] is None and d["per_person"]["b"]["n_censored"] == 1


# ---------------------------------------------------------------- D1, curves, xáo khối
def _trend_analyses(slope_per_hour, n_people=6, noise=0.01, seed=0):
    r = np.random.default_rng(seed)
    out = {}
    for p in range(n_people):
        base = r.uniform(0.05, 0.2)
        for k in range(3):
            rates = [max(0.0, base + slope_per_hour * (b * 10 + 5) / 60 + r.normal(0, noise)) for b in range(10)]
            s = sess(rates, who=f"P{p}", sid=f"S{k}")
            out[(s.participant, s.session_id)] = BL.analyse_session(s, P, Pf)
    return out


def test_trend_recovers_known_slope_and_is_zero_when_flat():
    t, df = TR.run_trend(_trend_analyses(0.05), P)
    ax = t["time_axis"]
    assert ax["primary"] is not None and ax["mixedlm"]["slope_pp_per_hour"] == pytest.approx(5.0, abs=1.0)
    lo, hi = ax["mixedlm"]["ci95_pp_per_hour"]
    assert lo < 5.0 < hi
    flat = TR.run_trend(_trend_analyses(0.0, seed=2), P)[0]["time_axis"]
    prim = flat["mixedlm"] if flat["primary"] == "mixedlm" else flat["gee_weighted"]
    assert abs(prim["slope_pp_per_hour"]) < 1.5 and prim["ci95_pp_per_hour"][0] < 0 < prim["ci95_pp_per_hour"][1]


def test_curves_json_format_and_only_eligible_valid_blocks():
    A = {("a", "1"): an([0.1, 0.3, None, 0.5, 0.1, 0.1], who="a"), ("a", "2"): an([0.3, 0.1, 0.1, 0.1, 0.1, 0.1], who="a", sid="2"),
         ("b", "1"): an([0.2] * 3, who="b")}                                                     # b không đủ điều kiện
    c = TR.curves(A, P)
    assert c["version"] == 1 and c["block_min"] == 10 and set(c["participants"]) == {"a"}
    blocks = {b["block_idx"]: b for b in c["participants"]["a"]["blocks"]}
    assert 2 not in blocks or blocks[2]["n_sessions"] == 1                                       # khối thiếu của phiên 1 bị bỏ
    assert blocks[0]["mean_bad_rate"] == pytest.approx(0.2) and blocks[0]["n_sessions"] == 2
    assert set(blocks[0]) == {"block_idx", "start_min", "mean_bad_rate", "n_sessions", "classified_sec"}
    json.dumps(c)


def test_shuffle_blocks_keeps_block_contents_and_window_times():
    s = sess([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], extra_minutes=3)
    out = BL.shuffle_blocks({("P1", "S1"): s}, P, 0)[("P1", "S1")]
    before = sorted(round(r["bad_rate"], 6) for r in BL.block_rows(s, P, Pf))
    after = [round(r["bad_rate"], 6) for r in BL.block_rows(out, P, Pf)]
    assert sorted(after) == before and after != [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]                # cùng tập khối, khác thứ tự
    assert out.window_start == s.window_start and np.array_equal(out.cls[60:], s.cls[60:])        # phút dư và giờ thật giữ nguyên
    assert BL.shuffle_blocks({("P1", "S1"): s}, P, 0)[("P1", "S1")].cls.tolist() == out.cls.tolist()  # cố định theo seed


# ---------------------------------------------------------------- protocol, tái dùng forecast, LOSO, đầu-cuối
def test_protocol_locked_values_and_forecast_reuse():
    assert P["version"] == 2 and P["block"]["minutes"] == 10 and P["onset"]["delta"] == 0.15 and P["reference_reminder_min"] == 50
    assert P["eligible"] == {"_doc": P["eligible"]["_doc"], "min_session_min": 60, "min_valid_blocks": 4}
    assert C.FE.minute_table.__module__ == "features" and C.D.load.__module__ == "data"       # import từ forecast, không chép
    s = sess([0.1] * 6, away=[0] * 25 + [31] + [0] * 34)                                       # away 31 s >= away_reset_sec của forecast
    rows = BL.block_rows(s, P, Pf)
    assert Pf["features"]["away_reset_sec"] == 30 and rows[2]["sitting_end_min"] == 4 and rows[1]["sitting_end_min"] == 20


def test_loso_never_trains_on_the_test_person(tmp_path):
    SIM.write_dataset(tmp_path / "d", persons=5, sessions=3, seed=7, planted_fatigue=True)
    ss = C.D.load(tmp_path / "d")
    A = BL.analyse_all(ss, P, Pf)
    P2 = copy.deepcopy(P)
    P2["bootstrap"]["n"] = 20
    out, per_session, folds = D3.run_d3(ss, A, P2, Pf, log=lambda *_: None)
    cmp_, _, _ = D3.split_groups(A, P2)
    for f in folds:
        mine = sum(1 for k in cmp_ if A[k]["participant"] == f["test"])
        assert f["n_train_sessions"] == len(cmp_) - mine and mine > 0
    assert sorted(per_session) == sorted(cmp_)


def test_default_simulation_unchanged_by_planted_fatigue_flag(tmp_path):
    SIM.write_dataset(tmp_path / "a", persons=2, sessions=2, seed=9)
    SIM.write_dataset(tmp_path / "b", persons=2, sessions=2, seed=9, planted_fatigue=False)
    for f in ("minutes.jsonl", "sessions.jsonl", "simulate_meta.json"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()
    SIM.write_dataset(tmp_path / "c", persons=2, sessions=2, seed=9, planted_fatigue=True)
    assert (tmp_path / "a" / "minutes.jsonl").read_bytes() != (tmp_path / "c" / "minutes.jsonl").read_bytes()


def test_end_to_end_small(tmp_path):
    SIM.write_dataset(tmp_path / "d", persons=5, sessions=3, seed=21, planted_fatigue=True)
    res, meta = EV.run(tmp_path / "d", tmp_path / "out", boot_n=20, log=lambda *_: None)
    for f in ("blocks.csv", "curves.json", "sessions.csv", "metrics.json", "metrics.md", "curves.png", "km.png", "run_meta.json"):
        assert (tmp_path / "out" / f).exists()
    head = open(tmp_path / "out" / "sessions.csv", encoding="utf-8").readline().strip().split(",")
    assert head[:8] == ["participant", "session_id", "onset", "censored", "r_m0", "r_m1", "r_m2", "r_m3"]
    rows = list(csv.DictReader(open(tmp_path / "out" / "sessions.csv", encoding="utf-8")))
    assert all(r["r_m0"] == "50" for r in rows if r["group"] == "compared")
    assert meta["protocol_override"] == {"bootstrap_n": 20} and meta["protocol_version"] == 2
    assert {"data_sha256", "protocol_sha256", "forecast_protocol_sha256", "git"} <= set(meta)
    assert res["d1"]["time_axis"]["primary"] is not None
    md = (tmp_path / "out" / "metrics.md").read_text(encoding="utf-8")
    assert "m3: hazard gọn" in md and "(không nhắc " in md and "m3 − m0" in md          # MAE đi kèm tỷ lệ không nhắc


# ---------------------------------------------------------------- protocol v2: m3 và đối chứng xáo phút
def test_protocol_v2_m3_and_controls():
    assert P["version"] == 2 and "sửa trước khi có dữ liệu thật" in P["changelog"]
    assert P["d3"]["m3"]["features"] == ["bad_b0", "bad_b1", "bad_slope"]
    assert set(P["controls"]) == {"shuffle_blocks_seed", "shuffle_minutes_seed"} and D3.METHODS == ("m0", "m1", "m2", "m3")


def test_m3_uses_only_its_features_and_block_index():
    names = P["d3"]["m3"]["features"]
    F = len(P["d3"]["features"])
    cols = D3.feature_cols(P, names)
    assert cols == [0, 1, 3]
    items = [dict(feat=np.arange(F, dtype=float), onset=50, censor_min=70), dict(feat=np.ones(F), onset=None, censor_min=80)]
    X, y = D3.person_period(items, P, cols)
    assert X.shape == (8, 4) and X[:3, :-1].tolist() == [[0.0, 1.0, 3.0]] * 3 and X[:3, -1].tolist() == [3, 4, 5]
    r = np.random.default_rng(0)
    its = []
    for i in range(50):
        k = int(r.integers(3, 9))
        f = r.normal(size=F)
        f[3] = (k - 6) / 3.0
        its.append(dict(feat=f, onset=k * 10, censor_min=k * 10 + 20))
    hz = D3.Hazard(P, names).fit(its)
    assert set(hz.coef) == set(names) | {"block_idx"}
    f0 = its[0]["feat"].copy()
    f1 = f0.copy()
    f1[[i for i in range(F) if i not in cols]] = 99.0                              # đổi mọi đặc trưng ngoài tập của m3
    assert hz.reminder(f0) == hz.reminder(f1)
    assert D3.Hazard(P).fit(its).cols == list(range(F))                             # m2 vẫn dùng đủ 15


def test_shuffle_minutes_keeps_minutes_destroys_order_and_is_deterministic():
    s = sess([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], extra_minutes=3)
    s.cls[:, 1] += np.arange(s.n) * 0.1                                              # mỗi phút một giá trị riêng
    out = BL.shuffle_minutes({("P1", "S1"): s}, P, 0)[("P1", "S1")]
    assert sorted(out.cls[:, 1].tolist()) == sorted(s.cls[:, 1].tolist()) and out.cls[:, 1].tolist() != s.cls[:, 1].tolist()
    assert out.window_start == s.window_start
    assert BL.shuffle_minutes({("P1", "S1"): s}, P, 0)[("P1", "S1")].cls.tolist() == out.cls.tolist()
    assert BL.shuffle_minutes({("P1", "S1"): s}, P, 1)[("P1", "S1")].cls.tolist() != out.cls.tolist()


def test_shuffle_minutes_removes_a_known_trend():
    sessions = {}
    r = np.random.default_rng(3)
    for p in range(6):
        for k in range(3):
            rates = [0.1 + 0.05 * b + r.normal(0, 0.01) for b in range(10)]            # tăng 5 điểm % mỗi khối = 30 điểm %/giờ
            s = sess(rates, who=f"P{p}", sid=f"S{k}")
            sessions[(s.participant, s.session_id)] = s
    before = TR.run_trend(BL.analyse_all(sessions, P, Pf), P)[0]["time_axis"]
    after = TR.run_trend(BL.analyse_all(BL.shuffle_minutes(sessions, P, 0), P, Pf), P)[0]["time_axis"]

    def sl(ax):
        return (ax["mixedlm"] if ax["primary"] == "mixedlm" else ax["gee_weighted"])
    assert sl(before)["slope_pp_per_hour"] > 25 and sl(before)["ci95_pp_per_hour"][0] > 0
    lo, hi = sl(after)["ci95_pp_per_hour"]
    assert abs(sl(after)["slope_pp_per_hour"]) < 5 and lo < 0 < hi


def test_run_with_shuffle_minutes_control(tmp_path):
    SIM.write_dataset(tmp_path / "d", persons=5, sessions=3, seed=21)
    res, meta = EV.run(tmp_path / "d", tmp_path / "out", boot_n=20, log=lambda *_: None, shuffle_minutes=True)
    assert meta["shuffle_minutes"] is True and meta["shuffle_control"] is False and res["shuffle_minutes"] is True
    assert "PHÚT" in (tmp_path / "out" / "metrics.md").read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        EV.run(tmp_path / "d", tmp_path / "out2", boot_n=20, log=lambda *_: None, shuffle_control=True, shuffle_minutes=True)
