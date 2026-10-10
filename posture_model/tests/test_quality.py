"""Kiểm thử lọc giá trị phi lý (quality.py + metrics.py):  python tests/test_quality.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from metrics import MetricsAggregator  # noqa: E402
from quality import angle_ok, angles_ok, dist_ok  # noqa: E402
from schema import validate  # noqa: E402

T0 = 1_789_999_980.0                                           # chia hết cho 60


def test_limits():
    assert angle_ok(45.0) and angle_ok(-90.0) and not angle_ok(188.07) and not angle_ok(-152.4)
    assert not angle_ok(None) and not angle_ok(float("nan"))
    assert angles_ok({"neck": 10.0, "trunk": -5.0, "head_pitch": 3.0})
    assert not angles_ok({"neck": 10.0, "trunk": 105.96, "head_pitch": 3.0})
    assert angles_ok({"neck": float("nan"), "trunk": float("nan"), "head_pitch": float("nan")})
    assert dist_ok(46.6) and dist_ok(20.0) and dist_ok(150.0)
    assert not dist_ok(1055.5) and not dist_ok(15.0) and not dist_ok(float("nan")) and not dist_ok(None)


def test_metrics_drop_implausible_values():
    out = []
    agg = MetricsAggregator(out.append, T0, "s1", "d1")
    for i in range(1, 601):                                    # 60 giây, 10 mẫu/giây
        t = i / 10
        spike = i % 50 == 0                                    # 12 mẫu lỗi xen kẽ
        ang = {"neck": 188.0 if spike else 5.0, "trunk": 106.0 if spike else 2.0,
               "head_pitch": -152.0 if spike else 1.0}
        agg.add(t, True, "GOOD", 0.2, ang, tilt_rel=1.0, tilt_status="GOOD",
                dist_cm=1055.5 if spike else 60.0, dist_status="GOOD")
    agg.flush()
    m = out[0]
    assert m["neckMax"] == 5.0 and m["trunkMax"] == 2.0 and m["headPitchMean"] == 1.0, m
    assert m["distanceMeanCm"] == 60.0 and m["distanceMinCm"] == 60.0, m
    assert validate("metrics", m) == []


def test_short_window_skipped_unless_alert():
    out = []
    agg = MetricsAggregator(out.append, T0, "s1", "d1")
    for i in range(1, 31):                                     # 3 giây rồi kết thúc phiên
        agg.add(i / 10, True, "GOOD", 0.2, {"neck": 5.0, "trunk": 2.0, "head_pitch": 1.0})
    assert agg.flush() is None and out == []
    agg = MetricsAggregator(out.append, T0, "s2", "d1")
    for i in range(1, 31):
        agg.add(i / 10, True, "CANH BAO", 0.9, {"neck": 30.0, "trunk": 2.0, "head_pitch": 1.0})
    agg.on_event({"eventType": "ALERT_STARTED", "alertType": "NECK_TRUNK"})
    agg.flush()
    assert len(out) == 1 and out[0]["alertCount"] == {"NECK_TRUNK": 1}   # có cảnh báo -> vẫn gửi


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        t = time.time()
        fn()
        print(f"OK  {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)}/{len(fns)} test đạt")
