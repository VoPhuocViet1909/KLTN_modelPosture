"""Test đơn vị pipeline A2/A3 bằng dữ liệu tự sinh (không cần video, model hay NPZ).

Chạy:  python -m pytest training/a2_eval/tests -q
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as C            # noqa: E402
import importlib.util         # noqa: E402

# posture_model cũng có metrics.py (của app): nạp metrics.py của A3 theo đường dẫn file để không đụng tên module
_spec = importlib.util.spec_from_file_location("a2_metrics", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metrics.py"))
M = importlib.util.module_from_spec(_spec)
sys.modules["a2_metrics"] = M
_spec.loader.exec_module(M)
import pipeline as P          # noqa: E402

CLASSES = C.load_model_cfg()["classes"]
PRM = P.app_filter_params(C.load_model_cfg())


# ---------------------------------------------------------------- landmark tự sinh (cam hông, người quay mặt sang phải)
def fake_lm(T, neck_deg, trunk_deg, vis=1.0):
    """Landmark pixel (T,33,3): chỉ có tai/mắt/vai/hông cả hai bên, góc cổ/thân đúng theo công thức của posture_features."""
    lm = np.full((T, 33, 3), np.nan, np.float32)
    sh, hip = np.array([300.0, 300.0]), None
    th = math.radians(trunk_deg)
    hip = sh - 100 * np.array([math.sin(th), -math.cos(th)])          # sh - hip = 100*(sin, -cos)
    ang = math.radians(trunk_deg + neck_deg)                           # góc tai-vai so với phương đứng
    ear = sh + 100 * np.array([math.sin(ang), -math.cos(ang)])
    eye = ear + np.array([15.0, 0.0])                                  # đường tai->mắt nằm ngang: head_pitch 0
    nose = ear + np.array([40.0, 5.0])
    for i in (7, 8):
        lm[:, i] = [*ear, vis]
    for i in (2, 5):
        lm[:, i] = [*eye, vis]
    for i in (11, 12):
        lm[:, i] = [*sh, vis]
    for i in (23, 24):
        lm[:, i] = [*hip, vis]
    lm[:, 0] = [*nose, vis]
    return lm


def fake_world(T):
    w = np.zeros((T, 33, 3), np.float32)
    w[:, [11, 23], 2] = -0.1      # trái gần camera hơn
    w[:, [12, 24], 2] = 0.1
    return w


# ---------------------------------------------------------------- tham số lấy từ app
def test_filter_params_from_app():
    assert PRM["threshold"] == C.load_model_cfg()["threshold"] == 0.5
    assert PRM["hysteresis"] == 0.1 and PRM["alert_sec"] == 5 and PRM["clear_sec"] == 3 and PRM["median"] == 5


def test_win_stats_order():
    x = np.random.default_rng(0).normal(size=(3, 20, 6))
    s = C.win_stats(x)
    assert s.shape == (3, 24)
    assert np.allclose(s[:, :6], x.mean(1)) and np.allclose(s[:, 6:12], x.std(1))
    assert np.allclose(s[:, 12:18], x.min(1)) and np.allclose(s[:, 18:], x.max(1))


# ---------------------------------------------------------------- góc, hiệu chỉnh, cửa sổ
def test_calibration_and_angles_roundtrip():
    T = 40
    side, f, base = P.calibrate(fake_lm(T, 8, 3), fake_world(T))
    assert side == 0 and f == 1.0
    assert base["neck"] == pytest.approx(8, abs=1e-3) and base["trunk"] == pytest.approx(3, abs=1e-3)
    cal, valid = P.calibrated_angles(fake_lm(T, 38, 3), side, f, base)
    assert valid.all()
    assert cal[0, C.FEATURES.index("neck")] == pytest.approx(30, abs=1e-3)
    assert cal[0, C.FEATURES.index("trunk")] == pytest.approx(0, abs=1e-3)


def test_calibration_needs_people():
    with pytest.raises(ValueError):
        P.calibrate(np.full((30, 33, 3), np.nan, np.float32), fake_world(30))


def test_windows_centers_and_validity():
    T = 25
    cal = np.zeros((T, 6))
    cal[:, 5] = 1.0                                   # vis_hip
    valid = np.ones(T, bool)
    valid[0:5] = False                                # 5/20 khung hỏng -> 75% < 80%: cửa sổ đầu không hợp lệ
    t = np.arange(T) / 10
    w = P.make_windows(cal, valid, t)
    assert len(w["end"]) == 6 and w["X"].shape == (6, 20, 6)
    assert w["t_end"][0] == pytest.approx(1.9) and w["t_center"][0] == pytest.approx(0.95)
    assert list(w["ok"]) == [False, True, True, True, True, True]          # 5 khung hỏng = 75% < 80%; 4 khung hỏng = 80% đủ
    assert (w["X"][0][:5] == 0).all()                 # khung hỏng = 0 như engine.py


def test_windows_too_short():
    w = P.make_windows(np.zeros((10, 6)), np.ones(10, bool), np.arange(10) / 10)
    assert len(w["end"]) == 0


# ---------------------------------------------------------------- luật góc
def test_rule_predictor_classes():
    T = 30
    cal = np.zeros((T, 6))
    cal[:, 5] = 1.0
    cal[10:, 0], cal[10:, 1] = 30.0, 40.0             # cổ 30°, thân 40°: gù lưng
    end = np.array([19, 29])
    p, pr = P.predict_rule(cal, end, CLASSES, C.load_model_cfg()["class_rule"])
    assert p[0] == pytest.approx(0.5)                                      # cửa sổ 0..19: 10/20 khung BAD
    assert p[1] == 1.0 and CLASSES[int(np.argmax(pr[1]))] == "SLOUCH"
    assert pr[1].sum() == pytest.approx(1.0)


def test_frame_class_priority():
    rule = C.load_model_cfg()["class_rule"]
    row = lambda n, t: np.array([n, t, 0.0, 1, 1, 1])
    assert CLASSES[C.frame_class(row(5, -20), 1, CLASSES, rule)] == "LEAN_BACKWARD"
    assert CLASSES[C.frame_class(row(25, 25), 1, CLASSES, rule)] == "SLOUCH"
    assert CLASSES[C.frame_class(row(5, 25), 1, CLASSES, rule)] == "LEAN_FORWARD"
    assert CLASSES[C.frame_class(row(25, 5), 1, CLASSES, rule)] == "FORWARD_HEAD"
    assert CLASSES[C.frame_class(row(-20, 0), 1, CLASSES, rule)] == "NECK_EXTENSION"
    assert C.frame_class(row(0, 0), 0, CLASSES, rule) == 0
    assert C.frame_class(row(0, 0), float("nan"), CLASSES, rule) == -1


# ---------------------------------------------------------------- bộ lọc của app
def _feed(p_seq, dt=0.1, cls_probs=None):
    N = len(p_seq)
    probs = np.tile(cls_probs if cls_probs is not None else np.eye(6)[3], (N, 1))
    t_end = np.arange(N) * dt + 1.9
    return P.run_filter(np.array(p_seq, float), probs, np.ones(N, bool), t_end, CLASSES, PRM)


def test_filter_alert_after_alert_sec_and_class():
    rows, ev = _feed([0.05] * 40 + [0.95] * 100)               # GOOD 4 s rồi BAD 10 s
    started = [e for e in ev if e["eventType"] == "ALERT_STARTED"]
    assert len(started) == 1
    on = started[0]
    bad_start = 1.9 + 4.0 + 0.2                                # median 5 trễ ~2 khung -> BAD thật từ ~khung 42
    assert on["startedAt"] == pytest.approx(bad_start, abs=0.31)
    assert on["t"] - on["startedAt"] >= PRM["alert_sec"] - 1e-6
    ar = P.alert_rows(ev, "transformer", "v.mp4", "P1")
    assert len(ar) == 1 and ar[0]["cls"] == "SLOUCH" and ar[0]["t_off"] >= ar[0]["t_on"]
    assert rows[-1]["bad_raw"] and rows[-1]["cls_raw"] == "SLOUCH" and rows[-1]["bad_f"] is True
    assert rows[0]["bad_raw"] is False and rows[0]["cls_raw"] == "GOOD"


def test_filter_hysteresis_holds_and_median_removes_spike():
    rows, ev = _feed([0.05] * 30 + [0.55] * 60)                # 0.55 nằm trong vùng trễ 0.4–0.6: không BAD sau lọc
    assert not [e for e in ev if e["eventType"] == "ALERT_STARTED"]
    assert rows[-1]["bad_raw"] is True and rows[-1]["bad_f"] is False
    rows, ev = _feed([0.05] * 30 + [0.95, 0.95] + [0.05] * 60)   # nhiễu 2 khung: median 5 loại bỏ
    assert all(r["bad_f"] is not True for r in rows)


def test_filter_invalid_windows_hold_state():
    N = 60
    p = np.full(N, 0.95)
    ok = np.ones(N, bool)
    ok[20:30] = False
    t_end = np.arange(N) * 0.1 + 1.9
    rows, ev = P.run_filter(p, np.tile(np.eye(6)[1], (N, 1)), ok, t_end, CLASSES, PRM)
    assert all(rows[i] is None for i in range(20, 30))
    assert rows[-1]["cls_f"] == "FORWARD_HEAD"
    assert [e["eventType"] for e in ev].count("ALERT_STARTED") == 1


def test_filter_closes_open_alert_at_end():
    rows, ev = _feed([0.95] * 80)
    ar = P.alert_rows(ev, "rf", "v.mp4", "P1")
    assert len(ar) == 1 and ar[0]["end_reason"] == "END"


# ---------------------------------------------------------------- quy về đoạn 2 giây
def test_segment_bounds_drop_remainder():
    assert P.segment_bounds(7.9) == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    assert P.segment_bounds(8.0)[-1] == (6.0, 8.0)
    assert P.segment_bounds(1.9) == []


def _row(bad_raw, cls_raw, bad_f=None):
    return dict(bad_raw=bad_raw, cls_raw=cls_raw, bad_f=bad_f, cls_f=cls_raw, p_med=0.5)


def test_aggregate_majority_and_class_plurality():
    rows = [_row(True, "SLOUCH")] * 4 + [_row(True, "FORWARD_HEAD")] * 3 + [_row(False, "GOOD")] * 3
    cls, bad, bad_f, cov = P.aggregate_segment(rows, list(range(10)), CLASSES)
    assert (cls, bad, cov) == ("SLOUCH", 1, 1.0) and bad_f == ""
    rows = [_row(True, "SLOUCH")] * 4 + [_row(False, "GOOD")] * 6                      # BAD 40% -> GOOD
    assert P.aggregate_segment(rows, list(range(10)), CLASSES)[:2] == ("GOOD", 0)
    rows = [_row(True, "SLOUCH")] * 5 + [_row(False, "GOOD")] * 5                      # đúng 50% -> BAD (như notebook y>=0.5)
    assert P.aggregate_segment(rows, list(range(10)), CLASSES)[:2] == ("SLOUCH", 1)
    rows = [_row(True, "SLOUCH")] * 2 + [_row(True, "FORWARD_HEAD")] * 2               # hòa: lớp đứng trước trong danh sách
    assert P.aggregate_segment(rows, list(range(4)), CLASSES)[0] == "FORWARD_HEAD"


def test_aggregate_filtered_and_no_pose():
    rows = [_row(True, "SLOUCH", True)] * 6 + [_row(True, "SLOUCH", False)] * 2 + [_row(True, "SLOUCH", None)] * 2
    assert P.aggregate_segment(rows, list(range(10)), CLASSES)[2] == 1
    rows = [None] * 6 + [_row(True, "SLOUCH", True)] * 4                                # 40% hợp lệ < 50%
    assert P.aggregate_segment(rows, list(range(10)), CLASSES)[0] == P.NO_POSE
    assert P.aggregate_segment([], [], CLASSES)[0] == P.NO_POSE


def test_segments_table_uses_window_center_and_labels():
    t_center = np.arange(0.95, 8.0, 0.1)                      # 8 s video, cửa sổ bước 0,1 s
    n = len(t_center)
    rows = [_row(bool(tc >= 4.0), "SLOUCH" if tc >= 4.0 else "GOOD") for tc in t_center]
    by = {m: rows for m in P.METHODS}
    seg = P.segments_table("v.mp4", "P1", 8.05, t_center, by, CLASSES)
    assert [s["t_start"] for s in seg] == [0.0, 2.0, 4.0, 6.0]
    assert [s["transformer"] for s in seg] == ["GOOD", "GOOD", "SLOUCH", "SLOUCH"]
    assert seg[0]["transformer_bad"] == 0 and seg[3]["rule_bad"] == 1 and seg[0]["coverage"] == 1.0
    P.attach_labels(seg, [dict(video="v.mp4", t_start=4.0, label="SLOUCH"), dict(video="x.mp4", t_start=0.0, label="GOOD")])
    assert [s["true_label"] for s in seg] == ["", "", "SLOUCH", ""]


# ---------------------------------------------------------------- chỉ số (ví dụ tính tay)
def _pred(video, ts, true, pred, person="P1", method="transformer"):
    r = dict(video=video, person=person, t_start=ts, t_end=ts + 2, true_label=true, coverage=1.0)
    for m in M.METHODS:
        r[m] = pred
        r[f"{m}_bad"] = "" if pred == "NO_POSE" else int(pred != "GOOD")
        r[f"{m}_bad_filtered"] = ""
    return r


def test_segment_metrics_hand_example():
    true = ["GOOD", "GOOD", "SLOUCH", "SLOUCH", "SLOUCH", "UNCLEAR", "GOOD", ""]
    pred = ["GOOD", "SLOUCH", "SLOUCH", "SLOUCH", "GOOD", "GOOD", "NO_POSE", "GOOD"]
    rows = [_pred("v", 2.0 * i, t, p) for i, (t, p) in enumerate(zip(true, pred))]
    s = M.person_stats(rows, [], "transformer", 5)
    assert s["drop"] == dict(total=8, unlabeled=1, unclear=1, no_pose=1, scored=5)
    r = M.finalize(M.combine([s]))
    assert r["accuracy"] == pytest.approx(3 / 5)
    assert r["f1_bad"] == pytest.approx(4 / 6)                            # tp2 fp1 fn1
    assert r["macro_f1"] == pytest.approx((0.5 + 4 / 6) / 2)              # GOOD 2/4, SLOUCH 4/6
    cm = s["cm"]
    assert cm[0, 0] == 1 and cm[0, 3] == 1 and cm[3, 3] == 2 and cm[3, 0] == 1 and cm.sum() == 5


def test_episodes_alerts_latency_false_alarms():
    # 0-2 GOOD | 2-8 BAD (3 đoạn = 6 s: đợt) | 8-10 GOOD | 10-14 BAD (2 đoạn = 4 s < 5 s: không phải đợt) | 14-20 GOOD
    labs = ["GOOD", "SLOUCH", "SLOUCH", "SLOUCH", "GOOD", "SLOUCH", "SLOUCH", "GOOD", "GOOD", "GOOD"]
    rows = [_pred("v", 2.0 * i, t, "GOOD") for i, t in enumerate(labs)]
    al = [dict(method="transformer", video="v", person="P1", t_on="7.0", t_off="9.0", **{"class": "SLOUCH"}),   # trong đợt: độ trễ 5
          dict(method="transformer", video="v", person="P1", t_on="16.5", t_off="18.0", **{"class": "SLOUCH"}),  # nhầm (GOOD)
          dict(method="transformer", video="v", person="P1", t_on="11.0", t_off="12.0", **{"class": "SLOUCH"}),  # trong BAD ngắn: đúng, không đợt
          dict(method="rf", video="v", person="P1", t_on="1.0", t_off="1.5", **{"class": "SLOUCH"})]
    s = M.person_stats(rows, al, "transformer", 5)
    assert (s["episodes"], s["detected"], s["latencies"]) == (1, 1, [5.0])
    assert s["false_alarms"] == 1 and s["true_alerts"] == 2 and s["n_alerts"] == 3
    assert s["hours"] == pytest.approx(10 * 2 / 3600)
    r = M.finalize(s)
    assert r["recall_episodes"] == 1.0 and r["latency_mean_sec"] == 5.0
    assert r["false_alarms_per_hour"] == pytest.approx(1 / (20 / 3600))
    s_rf = M.person_stats(rows, al, "rf", 5)                                   # rf chỉ có cảnh báo nhầm ở t=1 (GOOD), bỏ lỡ đợt
    assert (s_rf["false_alarms"], s_rf["episodes"], s_rf["detected"]) == (1, 1, 0)
    assert math.isnan(M.finalize(s_rf)["latency_mean_sec"])


def test_alert_already_on_at_episode_start_counts_zero_latency():
    labs = ["GOOD", "SLOUCH", "SLOUCH", "SLOUCH"]
    rows = [_pred("v", 2.0 * i, t, "GOOD") for i, t in enumerate(labs)]
    al = [dict(method="rule", video="v", person="P1", t_on="1.0", t_off="7.0", **{"class": "SLOUCH"})]
    s = M.person_stats(rows, al, "rule", 5)
    assert s["latencies"] == [0.0] and s["detected"] == 1


def test_unclear_breaks_episode():
    labs = ["SLOUCH", "SLOUCH", "UNCLEAR", "SLOUCH"]
    rows = [_pred("v", 2.0 * i, t, "SLOUCH") for i, t in enumerate(labs)]
    assert M.person_stats(rows, [], "rf", 5)["episodes"] == 0                  # 4 s + 2 s, đều < 5 s


# ---------------------------------------------------------------- bootstrap theo người
def _person_rows(person, correct, n=10):
    return [_pred(f"{person}.mp4", 2.0 * i, "SLOUCH", "SLOUCH" if correct else "GOOD", person=person) for i in range(n)]


def test_bootstrap_resamples_people_not_segments():
    rows = _person_rows("A", True) + _person_rows("B", False)
    res = M.compute(rows, [], 5, n_boot=400, seed=0)
    m = res["methods"]["transformer"]
    assert m["accuracy"] == pytest.approx(0.5)
    assert m["ci95"]["accuracy"] == [0.0, 1.0]            # nếu lấy mẫu theo đoạn, CI sẽ hẹp quanh 0,5
    assert res["persons"] == ["A", "B"]
    assert M.compute(rows, [], 5, n_boot=400, seed=0)["methods"]["rf"]["ci95"] == res["methods"]["rf"]["ci95"]   # cố định theo seed


def test_bootstrap_single_person_has_no_ci():
    res = M.compute(_person_rows("A", True), [], 5, n_boot=100)
    assert res["methods"]["transformer"]["ci95"]["accuracy"] is None


def test_markdown_renders():
    res = M.compute(_person_rows("A", True) + _person_rows("B", False), [], 5, n_boot=50)
    md = M.to_markdown(res)
    assert "Accuracy (đoạn)" in md and "Ma trận nhầm lẫn — rf" in md and "**SLOUCH**" in md
