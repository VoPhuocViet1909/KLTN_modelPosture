"""B2: bản ghi 60 giây khi rời ghế, camera đứng/mất khung, app tắt giữa phút, phiên bắt đầu giữa phút.
Không cần camera/server:  python tests/test_metrics_window.py  (hoặc pytest)"""
import os
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from frame_guard import FREEZE_SEC, FrozenFrameGuard  # noqa: E402
from metrics import POSTURE_CLASSES, MetricsAggregator, class_seconds  # noqa: E402
from schema import validate  # noqa: E402

T0 = datetime(2026, 11, 24, 10, 0, 0).timestamp()          # đầu một phút tròn


def new_agg(t0=T0, out=None):
    out = [] if out is None else out
    return MetricsAggregator(out.append, t0, "s1", "d1", "u1"), out


def feed(agg, a, b, present=True, cls="GOOD", step=0.1):
    t = a
    while t < b - 1e-9:
        agg.add(round(t, 2), present, ("GOOD" if cls == "GOOD" else "BAD") if present else None,
                posture_class=cls if present else None)
        t += step


def first(out):
    assert out, "không có bản ghi"
    return out[0]


# ---------------------------------------------------------------- (a) rời ghế 20 giây
def test_away_lowers_presence_keeps_covered():
    agg, out = new_agg()
    feed(agg, 0, 20)
    feed(agg, 20, 40, present=False)
    feed(agg, 40, 60)
    feed(agg, 60, 61)
    m = first(out)
    assert m["coveredSec"] >= 59.0, m["coveredSec"]                    # app vẫn đo suốt phút
    assert 38.5 <= m["presenceSec"] <= 40.5, m["presenceSec"]          # ~20 giây không có người
    secs = m["postureClassSeconds"]
    assert sum(secs.values()) <= m["presenceSec"] + 1e-9
    assert validate("metrics", m) == []


# ---------------------------------------------------------------- (b) camera mất khung / đứng khung
def test_lost_frames_lower_covered_and_do_not_extend_class():
    """read() lỗi: engine không gọi add() -> không có mẫu."""
    agg, out = new_agg()
    feed(agg, 0, 20)
    feed(agg, 40, 60)
    feed(agg, 60, 61)
    m = first(out)
    assert 39.5 <= m["coveredSec"] <= 42.0, m["coveredSec"]            # ~40 giây có mẫu (+≤1 giây của mẫu đầu sau khoảng trống)
    assert 39.5 <= m["presenceSec"] <= 42.0
    assert sum(m["postureClassSeconds"].values()) <= m["presenceSec"] + 1e-9


def frames(rng, n, noisy=True, base=None):
    base = rng.integers(40, 200, (48, 64, 3), dtype=np.uint8) if base is None else base
    for _ in range(n):
        if noisy:
            yield np.clip(base.astype(np.int16) + rng.integers(-2, 3, base.shape), 0, 255).astype(np.uint8)
        else:
            yield base.copy()


def run_engine_like(frozen_from, frozen_to, step=0.1, total=61, noise=True):
    """Lặp như engine: mỗi mẫu cập nhật guard; khung đứng liên tục ≥ 2 giây thì bỏ mẫu (không gọi add)."""
    rng = np.random.default_rng(1)
    agg, out = new_agg()
    guard = FrozenFrameGuard()
    still = rng.integers(40, 200, (48, 64, 3), dtype=np.uint8)
    stale = still.copy()
    n = int(total / step)
    for i in range(n):
        t = round(i * step, 2)
        if frozen_from <= t < frozen_to:
            frame = stale                                              # driver trả mãi khung cũ (ok = True)
        else:
            frame = (np.clip(still.astype(np.int16) + rng.integers(-2, 3, still.shape), 0, 255).astype(np.uint8)
                     if noise else still.copy())
            stale = frame
        if guard.update(frame, t):
            continue
        agg.add(t, True, "GOOD", posture_class="GOOD")                 # landmark gần như không đổi: vẫn GOOD
    agg.flush()
    return out


def test_identical_frames_for_20s_lower_covered_and_no_class():
    out = run_engine_like(20, 40)
    m = first(out)
    # 20 giây khung y hệt: 2 giây đầu vẫn tính (chưa đủ ngưỡng), 18 giây còn lại bị loại
    assert 39.5 <= m["coveredSec"] <= 44.0, m["coveredSec"]
    assert m["presenceSec"] <= m["coveredSec"] + 1e-9
    assert sum(m["postureClassSeconds"].values()) <= m["presenceSec"] + 1e-9
    assert m["postureClassSeconds"]["GOOD"] <= 44.0                    # không kéo dài nhãn GOOD qua đoạn đứng


def test_still_person_with_sensor_noise_counts_normally():
    out = run_engine_like(1e9, 1e9, noise=True, total=61)              # người ngồi yên, khung nào cũng có nhiễu nhỏ
    m = first(out)
    assert m["coveredSec"] >= 59.0 and m["presenceSec"] >= 59.0, m
    assert m["postureClassSeconds"]["GOOD"] >= 59.0


def test_guard_threshold_and_reset():
    rng = np.random.default_rng(2)
    f = next(frames(rng, 1))
    g = FrozenFrameGuard()
    assert not g.update(f, 0.0)
    assert not g.update(f.copy(), FREEZE_SEC - 0.1)                    # chưa đủ 2 giây
    assert g.update(f.copy(), FREEZE_SEC + 0.1)                        # đủ -> mất tín hiệu
    g2 = next(frames(rng, 1))
    assert not g.update(g2, FREEZE_SEC + 0.2)                          # khung mới -> hồi phục ngay
    # chênh 1 mức xám ở một pixel vẫn là khung sống
    h = FrozenFrameGuard()
    a = f.copy()
    b = f.copy()
    b[0, 0, 0] = np.uint8((int(b[0, 0, 0]) + 1) % 256)
    h.update(a, 0.0)
    h.update(b, 1.0)
    assert not h.update(a, 5.0)


# ---------------------------------------------------------------- (c) app tắt giữa phút
def test_app_closed_mid_minute_still_flushes_partial_window():
    agg, out = new_agg()
    feed(agg, 0, 30)
    m = agg.flush()
    assert m is not None and 29.0 <= m["coveredSec"] <= 30.0
    assert m["windowSec"] == 60 and validate("metrics", m) == []       # unknown = 60 − covered ở bước xuất


# ---------------------------------------------------------------- (d) phiên bắt đầu / kết thúc giữa phút
def test_session_starting_and_ending_mid_minute():
    agg, out = new_agg(t0=T0 + 30)                                     # bắt đầu 10:00:30
    feed(agg, 0, 150)                                                  # tới 10:03:00
    agg.flush()
    starts = [m["windowStart"] for m in out]
    assert starts[0].endswith("03:00:00Z") or starts[0] < "2026-11-24T03:00:30Z"   # cửa sổ đầu bắt đầu TRƯỚC lúc bắt đầu phiên
    assert abs(out[0]["coveredSec"] - 29.9) < 0.2                      # chỉ phủ nửa phút
    assert out[1]["coveredSec"] >= 59.5                                # phút giữa: đầy đủ
    for m in out:
        assert m["coveredSec"] <= m["windowSec"] and validate("metrics", m) == []
    # minute_idx theo hợp đồng: làm tròn xuống phút của session_start -> 0, 1, 2
    t_start = int(T0 + 30) // 60 * 60
    idx = [int((datetime.fromisoformat(m["windowStart"].replace("Z", "+00:00")).timestamp() - t_start) // 60) for m in out]
    assert idx == list(range(len(out)))


# ---------------------------------------------------------------- tổng 6 lớp ≤ presenceSec
def test_class_seconds_scaled_before_rounding_and_ratio_kept():
    cls = {"GOOD": 30.0, "SLOUCH": 20.0, "LEAN_FORWARD": 10.0}         # tổng 60, presence 45
    out = class_seconds(cls, 45.0)
    assert sum(out.values()) <= 45.0 + 1e-9
    assert abs(out["GOOD"] / out["SLOUCH"] - 1.5) < 0.05 and abs(out["SLOUCH"] / out["LEAN_FORWARD"] - 2.0) < 0.2


def test_class_seconds_rounding_never_exceeds_presence():
    rng = np.random.default_rng(3)
    for _ in range(2000):
        n = int(rng.integers(1, 7))
        vals = rng.uniform(0, 12, n)
        cls = dict(zip(POSTURE_CLASSES[:n], vals))
        presence = float(vals.sum() * rng.uniform(0.5, 1.0)) if rng.random() < 0.5 else float(vals.sum())
        out = class_seconds(cls, presence)
        assert sum(out.values()) <= round(presence, 1) + 1e-9, (cls, presence, out)
        assert all(v > 0 for v in out.values())


def test_class_seconds_in_real_window_not_above_presence():
    agg, out = new_agg()
    t = 0.0
    while t < 59.76:
        agg.add(round(t, 2), True, "GOOD", posture_class=POSTURE_CLASSES[int(t // 9.96) % 6])
        t += 0.1
    feed(agg, 60, 61)
    m = first(out)
    assert sum(m["postureClassSeconds"].values()) <= m["presenceSec"] + 1e-9
    assert validate("metrics", m) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
