"""Kiểm thử kiểm hợp lệ hiệu chỉnh (calibration.py) và việc engine không lưu baseline khi không đạt.
Không cần camera:  python tests/test_calibration.py"""
import json
import os
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import calibration  # noqa: E402
import engine as engine_mod  # noqa: E402
from engine import EngineListener, EngineOptions, PostureEngine  # noqa: E402
from fake_pose import FakePoseDetector, make_blank_video, side_landmarks, write_config  # noqa: E402
from notifier import NotifierBase  # noqa: E402
from sender import Sender  # noqa: E402

CFG = {"calib_visible_ratio": 0.8, "calib_max_neck_deg": 30.0, "calib_min_neck_deg": 0.0, "calib_max_trunk_deg": 20.0,
       "calib_min_trunk_deg": -20.0, "calib_still_deg": 5.0, "calib_front_ratio": 0.5,
       "distance_on_cm": 50, "distance_off_cm": 55}


class FakeEd:
    """Thay EyeDistance: kích thước trên ảnh px -> cm = 6000 / px."""

    def to_cm(self, px, kind, width):
        return 6000.0 / px


def dx(head=20.0, trunk=0.0):
    """Đổi (góc ĐẦU so với phương thẳng đứng, góc thân) sang tọa độ landmark giả: neck tương đối = đầu - thân."""
    return 50.0 * np.tan(np.radians(head - trunk)), 100.0 * np.tan(np.radians(trunk))


def samples(n=100, head=20.0, trunk=0.0, jitter=0.0, visible=1.0, front=None, dist_px=None, seed=1):
    """head/trunk: độ. front: None = không có cam laptop; số 0..1 = tỉ lệ khung thấy đủ 2 vai. dist_px: kích thước mống mắt (px).
    Mặc định đầu 20 độ so với đứng: ngồi thẳng thật có tai nằm trước vai ~15-27 độ."""
    rng = np.random.default_rng(seed)
    cal = calibration.new_samples()
    ear, tr = dx(head, trunk)
    for _ in range(n):
        cal["n_s"] += 1
        if rng.random() < visible:
            L, W = side_landmarks(ear + rng.normal(0, jitter), tr + rng.normal(0, jitter))
            cal["L"].append(L)
            cal["W"].append(W)
        if front is not None:
            cal["n_f"] += 1
            cal["tilt"].append(1.0 if rng.random() < front else np.nan)
            if dist_px:
                cal["dpx"].append(dist_px)
                cal["dkind"].append("iris")
    return cal


def run(cal, front=False):
    return calibration.evaluate(cal, CFG, front_enabled=front, ed=FakeEd() if front else None)


def codes(res):
    return [r["code"] for r in res["reasons"]]


def check(res, code):
    return next(c for c in res["checks"] if c["code"] == code)


def test_ngoi_thang_dat():
    res = run(samples())
    assert res["ok"] and res["reasons"] == []
    assert [c["ok"] for c in res["checks"]] == [True] * 4          # thấy người, lưng, cổ, ngồi yên
    res = run(samples(front=1.0, dist_px=100), front=True)         # cam laptop thấy vai, cách 60 cm (>= 50)
    assert res["ok"] and len(res["checks"]) == 6 and all(c["ok"] for c in res["checks"])


def test_ngoi_thang_tua_lung_tai_truoc_vai_phai_dat():
    # ca người thật báo lỗi: tựa lưng nhẹ 10-15 độ, tai trước vai ~20 độ. neck thô = đầu - thân = 20 + 12 = 32 độ
    # (> 20 độ: kiểm cũ báo NECK_NOT_STRAIGHT sai), nhưng đầu so với phương thẳng đứng chỉ 20 độ.
    for trunk in (-10.0, -12.0, -15.0):
        res = run(samples(head=20.0, trunk=trunk))
        assert res["ok"], (trunk, res["reasons"])
        assert abs(check(res, "neck")["value"] - 20.0) < 0.2 and abs(check(res, "back")["value"] - trunk) < 0.2
    # đúng số liệu chủ dự án đã gặp: neck thô 26,8, thân +0,9 -> đầu 27,7 vẫn đạt (p95 GOOD 31,2)
    assert run(samples(head=27.7, trunk=0.9))["ok"]
    # baseline thật của dataset P01_S02: neck 23,0 thân -7,3 (đầu 15,7); P01_S01 720p: neck 37,0 thân -15,6 (đầu 21,4)
    assert run(samples(head=15.7, trunk=-7.3))["ok"] and run(samples(head=21.4, trunk=-15.6))["ok"]


def test_cui_co_ro():
    res = run(samples(head=45.0))                                   # đầu nghiêng trước 45 độ = ngưỡng 30 + 15
    assert not res["ok"] and codes(res) == ["NECK_NOT_STRAIGHT"], codes(res)
    assert "+45°" in res["reasons"][0]["message"]
    assert codes(run(samples(head=36.0))) == ["NECK_NOT_STRAIGHT"]  # vượt ngưỡng 30 là bị bắt
    assert run(samples(head=29.0))["ok"]


def test_gu_lung():
    res = run(samples(head=20.0, trunk=30.0))                       # thân nghiêng 30 độ (> 20), đầu vẫn 20 độ
    assert not res["ok"] and codes(res) == ["BACK_NOT_STRAIGHT"], codes(res)
    assert "gù" in res["reasons"][0]["message"] and "+30°" in res["reasons"][0]["message"]
    assert run(samples(head=20.0, trunk=19.0))["ok"] is True        # dưới 20 độ vẫn chấp nhận được


def test_nga_sau_va_ngua_dau():
    res = run(samples(head=20.0, trunk=-25.0))                      # ngả sau 25 độ (< -20)
    assert codes(res) == ["BACK_NOT_STRAIGHT"] and "ngả ra sau" in res["reasons"][0]["message"]
    assert run(samples(head=20.0, trunk=-18.0))["ok"]               # tựa lưng 18 độ: ngưỡng -20 theo dữ liệu, -15 cũ loại nhầm
    res = run(samples(head=-10.0))                                  # đầu ngửa ra sau vai
    assert codes(res) == ["NECK_NOT_STRAIGHT"] and "ngửa" in res["reasons"][0]["message"]


def test_cu_dong_nhieu():
    res = run(samples(jitter=15.0))
    assert not res["ok"] and "MOVING_TOO_MUCH" in codes(res), codes(res)
    assert "Ngồi yên" in [m["message"] for m in res["reasons"] if m["code"] == "MOVING_TOO_MUCH"][0]


def test_khong_thay_nguoi_hong():
    res = run(samples(visible=0.5))
    assert not res["ok"] and codes(res) == ["SIDE_NOT_VISIBLE"]    # chưa thấy đủ thì không phán xét lưng/cổ
    assert [c["ok"] for c in res["checks"]] == [False, None, None, None]
    assert run(samples(n=0))["ok"] is False


def test_thieu_vai_cam_laptop():
    res = run(samples(front=0.3, dist_px=100), front=True)
    assert not res["ok"] and codes(res) == ["SHOULDERS_NOT_VISIBLE"]
    assert "Bỏ qua camera laptop" in res["reasons"][0]["message"]
    assert run(samples(front=0.3, dist_px=100), front=False)["ok"] is True      # đã bỏ qua cam laptop -> không xét vai


def test_qua_gan_man_hinh():
    res = run(samples(front=1.0, dist_px=150), front=True)          # 6000/150 = 40 cm < 50
    assert not res["ok"] and codes(res) == ["TOO_CLOSE"] and "40 cm" in res["reasons"][0]["message"]
    assert run(samples(front=1.0, dist_px=None), front=True)["ok"] is True       # không đo được khoảng cách thì không chặn


def test_xem_truc_tiep_chua_du_du_lieu():
    res = calibration.evaluate(samples(n=3), CFG, final=False)
    assert res["reasons"] == [] and all(c["ok"] is None for c in res["checks"])
    res = calibration.evaluate(samples(n=30, head=45.0), CFG, final=False)
    assert codes(res) == ["NECK_NOT_STRAIGHT"]


def test_nguong_tu_cau_hinh_va_gia_tri_sai():
    t = calibration.thresholds({"calib_still_deg": 12, "calib_visible_ratio": "x", "calib_max_neck_deg": True,
                                "calib_max_score": 3})                 # khóa cũ calib_max_score bị bỏ qua
    assert t["calib_still_deg"] == 12.0 and t["calib_visible_ratio"] == 0.8 and t["calib_max_neck_deg"] == 30.0
    assert "calib_max_score" not in t
    assert calibration.evaluate(samples(jitter=15.0), dict(CFG, calib_still_deg=30.0))["ok"] is True
    assert codes(run(samples(head=40.0))) == ["NECK_NOT_STRAIGHT"]
    assert calibration.evaluate(samples(head=40.0), dict(CFG, calib_max_neck_deg=45.0))["ok"] is True
    assert calibration.evaluate(samples(trunk=25.0), dict(CFG, calib_max_trunk_deg=30.0))["ok"] is True
    assert calibration.evaluate(samples(trunk=-25.0), dict(CFG, calib_min_trunk_deg=-30.0))["ok"] is True


def test_chan_doan_co_so_do_va_nguong():
    res = run(samples(head=45.0, trunk=25.0))
    lines = calibration.describe(res)
    assert len(lines) == 4
    neck_line = next(l for l in lines if "Cổ thẳng" in l)
    assert "KHÔNG ĐẠT" in neck_line and "+45.0°" in neck_line and "+0° … +30°" in neck_line, neck_line
    back_line = next(l for l in lines if "Lưng thẳng" in l)
    assert "+25.0°" in back_line and "-20° … +20°" in back_line, back_line
    assert all(c["detail"] for c in res["checks"])
    res = run(samples(front=1.0, dist_px=150), front=True)
    assert "40 cm" in check(res, "distance")["detail"] and "≥ 50 cm" in check(res, "distance")["detail"]


def test_su_kien_failed_khong_gui_len_may_chu():
    s = Sender(None)
    s.enqueue_event({"eventType": "CALIBRATION_FAILED", "eventId": "x"})
    assert s.q.empty()
    s.enqueue_event({"eventType": "CALIBRATED", "eventId": "y"})
    assert not s.q.empty()


# ------------------------------------------------------------------ engine
class Rec(EngineListener):
    def __init__(self):
        self.states, self.finished = [], None

    def on_state(self, s): self.states.append(s)
    def on_finished(self, reason, stats): self.finished = reason


class Quiet(NotifierBase):
    def __call__(self, ev):
        pass


def _opts(d, **kw):
    video = os.path.join(d, "v.avi")
    make_blank_video(video, 40)
    cfg = write_config(os.path.join(d, "cfg.json"))
    return EngineOptions(side_video=video, config=cfg, events=os.path.join(d, "ev.jsonl"),
                         metrics_out=os.path.join(d, "m.jsonl"), outbox=os.path.join(d, "ob.db"), send=False, **kw)


def _events(d):
    return [json.loads(l) for l in open(os.path.join(d, "ev.jsonl"), encoding="utf-8")]


def test_engine_gu_luc_hieu_chinh_bi_bat_lam_lai_roi_dat():
    class Fake(FakePoseDetector):
        schedule = [(6, 50), (1e9, 0)]            # cúi đầu 45 độ trong lượt hiệu chỉnh đầu (0-3 s), ngồi thẳng từ giây 6
    engine_mod.PoseDetector = Fake
    with tempfile.TemporaryDirectory() as d:
        rec = Rec()
        eng = PostureEngine(_opts(d, front="-1"), notifier=Quiet(), listener=rec)
        assert eng.run() == "video_end"
        ev = _events(d)
        kinds = [e["eventType"] for e in ev]
        assert kinds.index("CALIBRATION_FAILED") < kinds.index("CALIBRATED"), kinds
        assert kinds.count("CALIBRATED") == 1 and kinds.count("CALIBRATION_FAILED") == 1
        failed = next(e for e in ev if e["eventType"] == "CALIBRATION_FAILED")
        assert [r["code"] for r in failed["reasons"]] == ["NECK_NOT_STRAIGHT"] and failed["reasons"][0]["message"]
        ok = next(e for e in ev if e["eventType"] == "CALIBRATED")
        assert abs(ok["baseline"]["neck"]) < 1.0 and abs(ok["baseline"]["trunk"]) < 1.0   # chuẩn lấy từ lượt thẳng, không phải lượt cúi
        stages = [s["calib"]["stage"] for s in rec.states if s["calib"]]
        assert "measuring" in stages and "failed" in stages
        fs = next(s for s in rec.states if s["calib"] and s["calib"]["stage"] == "failed")
        assert fs["calib"]["reasons"][0]["code"] == "NECK_NOT_STRAIGHT" and fs["calib"]["retryLeft"] > 0
        live = [s for s in rec.states if s["calib"] and s["calib"]["stage"] == "measuring" and s["calib"]["checks"]]
        assert live and {c["code"] for c in live[-1]["calib"]["checks"]} == {"side_visible", "back", "neck", "still"}


def test_engine_khong_luu_baseline_neu_khong_bao_gio_dat():
    class Fake(FakePoseDetector):
        schedule = [(1e9, 50)]                    # cúi đầu suốt
    engine_mod.PoseDetector = Fake
    with tempfile.TemporaryDirectory() as d:
        PostureEngine(_opts(d, front="-1"), notifier=Quiet(), listener=Rec()).run()
        kinds = [e["eventType"] for e in _events(d)]
        assert "CALIBRATED" not in kinds and kinds.count("CALIBRATION_FAILED") >= 3, kinds
        assert "ALERT_STARTED" not in kinds       # chưa có baseline thì không theo dõi/cảnh báo
        details = next(e for e in _events(d) if e["eventType"] == "CALIBRATION_FAILED")["details"]
        assert "+45" in details["neck"] and "30" in details["neck"]      # chẩn đoán: số đo + ngưỡng nằm trong sự kiện


def test_engine_thieu_vai_cam_laptop_roi_bo_qua():
    class Fake(FakePoseDetector):
        schedule = [(1e9, 0)]

        def __call__(self, frame, ts):
            time.sleep(0.02)
            return super().__call__(frame, ts)
    engine_mod.PoseDetector = Fake
    with tempfile.TemporaryDirectory() as d:
        opts = _opts(d, front="-1", no_face=True, front_video=os.path.join(d, "v.avi"))
        rec = Rec()
        eng = PostureEngine(opts, notifier=Quiet(), listener=rec)
        eng.start()
        for _ in range(600):                      # lượt đầu không đạt vì cam laptop (fake chỉ có vai trái rõ)
            if any(s["calib"] and s["calib"]["stage"] == "failed" for s in list(rec.states)):
                break
            time.sleep(0.05)
        failed = next(s for s in list(rec.states) if s["calib"] and s["calib"]["stage"] == "failed")
        assert [r["code"] for r in failed["calib"]["reasons"]] == ["SHOULDERS_NOT_VISIBLE"]
        assert failed["calib"]["frontAvailable"] is True and failed["calib"]["frontSkipped"] is False
        eng.request_skip_front()
        for _ in range(900):
            if any(e["eventType"] == "CALIBRATED" for e in _events(d)):
                break
            time.sleep(0.05)
        eng.stop()
        eng.join(30)
        assert eng.front_skipped and any(e["eventType"] == "CALIBRATED" for e in _events(d))
        assert rec.states[-1]["frontSkipped"] is True
        ok = next(e for e in _events(d) if e["eventType"] == "CALIBRATED")
        assert ok["shoulderTiltBase"] is None


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        t = time.time()
        fn()
        print(f"OK  {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)}/{len(fns)} test đạt")
