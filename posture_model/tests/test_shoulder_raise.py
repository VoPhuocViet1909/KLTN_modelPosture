"""Kiểm thử nhún vai (shoulder_raise) + cửa sổ cử động, không cần camera:  python tests/test_shoulder_raise.py"""
import json
import math
import os
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import engine as engine_mod  # noqa: E402
from engine import EngineListener, EngineOptions, PostureEngine  # noqa: E402
from fake_pose import (FakeFrontDetector, FakePoseDetector, front_landmarks, make_blank_video,  # noqa: E402
                       write_config)
from notifier import NotifierBase  # noqa: E402
from posture_features import shoulder_raise, shoulder_tilt  # noqa: E402


class Quiet(NotifierBase):
    def __call__(self, ev):
        pass


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
def _run(front_schedule, side_schedule=None, **cfg):
    side_sched = side_schedule or [(1e9, 0)]

    class Side(FakePoseDetector):
        schedule = side_sched

    class Front(FakeFrontDetector):
        schedule = front_schedule

    made = []

    def factory(task):
        det = Side(task) if not made else Front(task)
        made.append(det)
        return det
    engine_mod.PoseDetector = factory
    with tempfile.TemporaryDirectory() as d:
        video = os.path.join(d, "v.avi")
        make_blank_video(video, 30)
        conf = write_config(os.path.join(d, "cfg.json"), **cfg)
        opts = EngineOptions(side_video=video, front_video=video, no_face=True, config=conf,
                             events=os.path.join(d, "ev.jsonl"), metrics_out=os.path.join(d, "m.jsonl"),
                             outbox=os.path.join(d, "ob.db"), send=False, log=os.path.join(d, "log.csv"))
        eng = PostureEngine(opts, notifier=Quiet(), listener=EngineListener())
        assert eng.run() == "video_end"
        ev = [json.loads(l) for l in open(opts.events, encoding="utf-8")]
        log = open(opts.log, encoding="utf-8").read()
    return ev, log


def _kinds(ev, alert="SHOULDER_TILT"):
    return [e["eventType"] for e in ev if e.get("alertType") == alert]


SHRUG = [(6, 0.0, 0.0), (1e9, 0.0, 0.4)]            # sau giây 6: nhún cả hai vai, vai vẫn ngang (tilt = 0)
RAISE_CFG = dict(shoulder_raise_on=0.15, shoulder_raise_off=0.08)


def test_raise_null_giong_het_hanh_vi_cu():
    base_ev, base_log = _run([(1e9, 0.0, 0.0)])
    assert any(e["eventType"] == "CALIBRATED" for e in base_ev)
    ev, log = _run(SHRUG)                                              # nhún vai nhưng shoulder_raise_on = null
    seq = lambda e: [(x["eventType"], x.get("alertType")) for x in e if x["eventType"] not in ("SESSION_START", "SESSION_END")]
    assert seq(ev) == seq(base_ev) and "ALERT_STARTED" not in [x[0] for x in seq(ev)], seq(ev)
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


def test_cu_dong_manh_tracker_nhan_none():
    wave = lambda t: 6.0 if int(round(t * 10)) % 4 < 2 else -6.0      # đảo dấu ±6° mỗi 0,2 s (vươn vai, với đồ)
    sched = [(6, 0.0, 0.0), (1e9, wave, 0.0)]
    ev, _ = _run(sched, shoulder_motion_std=None)                      # tắt cửa sổ cử động: dao động làm lệch trung vị -> báo
    ev_moving, _ = _run(sched)                                         # mặc định 2,0°: coi là đang cử động -> không báo
    assert "ALERT_STARTED" not in _kinds(ev_moving), _kinds(ev_moving)
    assert "ALERT_STARTED" in _kinds(ev), "nếu không có cửa sổ cử động thì ca này phải báo (đối chứng)"


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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        t = time.time()
        fn()
        print(f"OK  {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)}/{len(fns)} test đạt")
