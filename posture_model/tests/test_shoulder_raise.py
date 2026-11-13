"""Kiểm thử nhún vai (shoulder_raise) + cửa sổ cử động, không cần camera:  python tests/test_shoulder_raise.py"""
import json
import math  # noqa: F401
import os
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from alerts import AlertTracker  # noqa: E402
from fake_pose import front_landmarks  # noqa: E402
from posture_features import shoulder_raise, shoulder_tilt  # noqa: E402
from shoulder_scenarios import SCENARIOS, run as _run, signature, square  # noqa: E402


# ------------------------------------------------------------------ đặc trưng
def test_shoulder_raise_giam_khi_vai_nang():
    base = shoulder_raise(front_landmarks())
    assert abs(base - 0.5) < 1e-6                                   # 60 px / 120 px
    up = shoulder_raise(front_landmarks(raise_frac=0.4))
    assert abs(up - 0.3) < 1e-6 and up < base
    assert abs(shoulder_raise(front_landmarks(tilt_deg=5.0)) - 0.5) < 0.03   # nghiêng nhẹ: trung bình gần như không đổi
    assert math.isfinite(shoulder_tilt(front_landmarks(tilt_deg=5.0)))


def test_shoulder_raise_thieu_tai_va_vis_thap():
    one = shoulder_raise(front_landmarks(ears=(True, False)))
    assert abs(one - 0.5) < 1e-6                                    # thiếu một tai: dùng tai còn lại
    assert np.isnan(shoulder_raise(front_landmarks(ears=(False, False))))
    assert np.isnan(shoulder_raise(front_landmarks(vis=0.2)))      # vai bị che
    p = front_landmarks()
    p[12, 0] = p[11, 0] + 5                                         # hai vai gần như chồng nhau (xoay người)
    assert np.isnan(shoulder_raise(p))
    p = front_landmarks()
    p[7, 2] = p[8, 2] = 0.1                                         # cả hai tai không tin cậy
    assert np.isnan(shoulder_raise(p))


# ------------------------------------------------------------------ engine
def _kinds(ev, alert="SHOULDER_TILT"):
    return [e["eventType"] for e in ev if e.get("alertType") == alert]


def _starts(ev, alert="SHOULDER_TILT"):
    return [r[2] for r in signature(ev) if r[0] == "ALERT_STARTED" and r[1] == alert]


SHRUG = [(6, 0.0, 0.0), (1e9, 0.0, 0.4)]            # sau giây 6: nhún cả hai vai, vai vẫn ngang (tilt = 0)
RAISE_CFG = dict(shoulder_raise_on=0.15, shoulder_raise_off=0.08)
GOLDEN = os.path.join(HERE, "golden", "shoulder_pre_pr22.json")


def test_mac_dinh_giong_het_truoc_pr22():
    """Log vàng sinh từ commit TRƯỚC PR #22 bằng chính các kịch bản này (xem shoulder_scenarios.py). Mặc định
    shoulder_raise_on/off, shoulder_motion_std, shoulder_raise_motion_std = null -> sự kiện phải trùng từng cái."""
    golden = json.load(open(GOLDEN, encoding="utf-8"))
    assert set(golden) == set(SCENARIOS)
    for name, (front, side) in SCENARIOS.items():
        ev, _ = _run(front, side)
        assert signature(ev) == golden[name], (name, signature(ev), golden[name])
    assert any(r[0] == "ALERT_STARTED" and r[1] == "SHOULDER_TILT" for r in golden["wave"])   # dao động vẫn báo như cũ
    assert not any(r[1] == "SHOULDER_TILT" for r in golden["shrug"])                          # bản cũ không thấy nhún vai


def test_raise_null_khong_them_truong_vao_su_kien():
    ev, log = _run(SHRUG)
    cal = next(e for e in ev if e["eventType"] == "CALIBRATED")
    assert "shoulderRaiseBase" not in cal                              # không thêm trường vào sự kiện gửi backend
    assert "raise_rel" in log.splitlines()[0]
    tilt, _ = _run([(6, 0.0, 0.0), (1e9, 6.0, 0.0)])                   # lệch vai thật vẫn báo, không cần bật nhún vai
    assert "ALERT_STARTED" in _kinds(tilt)
    tilt2, _ = _run([(6, 0.0, 0.0), (1e9, 6.0, 0.0)], **RAISE_CFG)
    assert _kinds(tilt2) == _kinds(tilt)                               # bật nhún vai không làm đổi ca lệch vai


def test_nhun_hai_vai_tilt_bang_0_bi_bad_khi_bat_nguong():
    ev, log = _run(SHRUG, **RAISE_CFG)
    assert "ALERT_STARTED" in _kinds(ev), _kinds(ev)
    col = log.splitlines()[0].split(",").index("raise_rel")
    vals = [float(l.split(",")[col]) for l in log.splitlines()[1:] if l.split(",")[col] not in ("", "nan")]
    assert vals and max(vals) > 0.15


def test_cui_dau_khong_tinh_la_nhun_vai():
    # cam hông: cổ cúi 70 px từ giây 6 -> nhánh cổ BAD; cam laptop thấy tai gần vai (giống nhún) -> không được báo lệch vai
    ev, _ = _run(SHRUG, side_schedule=[(6, 0), (1e9, 70)], **RAISE_CFG)
    assert "ALERT_STARTED" in _kinds(ev, "NECK_TRUNK"), "nhánh cổ phải báo"
    assert "ALERT_STARTED" not in _kinds(ev), _kinds(ev)


def test_cu_dong_manh_tracker_khong_bao():
    sched = [(6, 0.0, 0.0), (1e9, square(6.0), 0.0)]                   # đảo dấu ±6° mỗi 0,2 s (vươn vai, với đồ)
    ev, _ = _run(sched)                                                # mặc định null: tắt cửa sổ cử động -> báo như cũ
    ev_moving, _ = _run(sched, shoulder_motion_std=2.0)                # bật 2,0°: coi là đang cử động -> không báo
    assert "ALERT_STARTED" in _kinds(ev), "đối chứng: không bật cửa sổ cử động thì ca này phải báo"
    assert "ALERT_STARTED" not in _kinds(ev_moving), _kinds(ev_moving)


def test_hold_reset_trong_tracker():
    tr = AlertTracker("SHOULDER_TILT", alert_sec=5, clear_sec=3)
    for t in (0, 1, 2, 3, 4):
        tr.update(True, t)
    assert tr.status == "BAD" and tr.bad_since == 0
    tr.hold_reset()                                                    # cử động: xóa mốc, đếm lại
    assert tr.bad_since is None and tr.status == "BAD"
    assert tr.update(True, 5) == [] and tr.update(True, 9) == []       # 4 s kể từ mốc mới (5) < 5 s
    assert [e["eventType"] for e in tr.update(True, 10)] == ["ALERT_STARTED"]
    tr.hold_reset()                                                    # đang CANH BAO: giữ nguyên
    assert tr.alerting and tr.alert_started == 5
    assert tr.update(None, 11) == [] and tr.alerting                   # update(None) vẫn không đổi gì
    tr2 = AlertTracker("X", alert_sec=5)
    tr2.update(True, 0)
    tr2.update(None, 3)
    assert tr2.bad_since == 0                                          # hành vi update(None) của nhánh khác không đổi


def test_lech_vai_cu_dong_8s_van_lech_canh_bao_sau_du_alert_sec():
    # lệch vai từ giây 6, vươn vai/cử động 7,5–15,5 s, sau đó vẫn lệch. Cửa sổ 10 s còn nhớ cử động tới ~24,7 s.
    # Không có hold_reset (đã thử tắt): mốc bad_since cũ (~6 s) còn nguyên nên cảnh báo bật NGAY khi hết cử động, 24,7 s.
    # Có hold_reset: phải BAD liên tục đủ alert_sec (3 s) kể từ lúc hết cử động -> bật ở 27,7 s.
    sched = [(6, 0.0, 0.0), (7.5, 6.0, 0.0), (15.5, square(6.0), 0.0), (1e9, 6.0, 0.0)]
    ev, _ = _run(sched, seconds=50, alert_sec=3, shoulder_motion_std=2.0)
    starts = _starts(ev)
    assert len(starts) == 1, signature(ev)
    assert starts[0] >= 27.0, f"bật quá sớm ({starts[0]} s): chưa đủ alert_sec sau cử động"
    assert starts[0] < 40


def test_script_thong_ke_demo_review_va_multiposture():
    import shoulder_threshold_stats as st
    assert st.cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0 and abs(st.cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1]) + 1) < 1e-9
    assert st.clip_kind("SHOULDER_SHRUG_BOTH") == "BAD" and st.clip_kind("FORWARD_HEAD_2") == "NOALERT"
    with tempfile.TemporaryDirectory() as d:
        rv = os.path.join(d, "review.csv")
        open(rv, "w", encoding="utf-8").write("clip,r1,r2\nP01_S01_GOOD_01,đạt,đạt\nP01_S01_TRANSIENT_1,đạt,không đạt\n"
                                              "P02_S01_GOOD_01,không đạt,không đạt\n")
        k, bad, n = st.read_review(rv)
        assert n == 3 and bad == {"P01_S01_TRANSIENT_1", "P02_S01_GOOD_01"} and abs(k - 0.4) < 1e-9, (k, bad)
        mp = os.path.join(d, "data.csv")
        open(mp, "w", encoding="utf-8").write("label,left_shoulder_x,left_shoulder_y,right_shoulder_x,right_shoulder_y\n"
                                              "TUP,0,0,10,0\nTUP,0,0,10,1\nBAD,0,0,10,5\n")
        p95, note = st.multiposture_p95(mp)
        assert p95 is not None and 0 < p95 < 6, note
        assert st.multiposture_p95(os.path.join(d, "none.csv"))[0] is None          # không có file: bỏ qua, không lỗi
        assert st.main(["--demo", "--out", d, "--multiposture", mp, "--review", rv]) == 0
        md = open(os.path.join(d, "shoulder_threshold_summary.md"), encoding="utf-8").read()
        assert "leave-one-person-out" in md and "Công thức" in md and os.path.exists(os.path.join(d, "shoulder_frames.csv"))
        assert "Đã áp dụng điều kiện cổ" in md and "KHÔNG điều kiện cổ" in md          # demo có cả cam hông
        from engine import PostureEngine
        assert st.NECK_GUARD_DEG == PostureEngine.SHRUG_NECK_GUARD_DEG                  # script và engine dùng cùng ngưỡng cổ
        nofa = lambda txt: int(next(l for l in txt.splitlines() if l.startswith("| Công thức")).split("|")[4].split("/")[0])
        assert st.main(["--demo", "--no-side", "--out", d]) == 0                         # thiếu _SIDE: chạy như cũ + cảnh báo
        md2 = open(os.path.join(d, "shoulder_threshold_summary.md"), encoding="utf-8").read()
        assert "chưa áp dụng điều kiện cổ" in md2 and "chưa có điều kiện cổ" in md2
        assert nofa(md) < nofa(md2), (nofa(md), nofa(md2))                               # điều kiện cổ giảm báo giả do cúi đầu


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        t = time.time()
        fn()
        print(f"OK  {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)}/{len(fns)} test đạt")
