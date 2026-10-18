"""Chụp màn hình bước hiệu chỉnh qua đường ống Qt đầy đủ (video trắng + landmark giả chạy đúng tốc độ thực):

    python ui/calib_e2e.py gu    <thư mục>   # gù lưng lúc hiệu chỉnh -> bị bắt làm lại -> ngồi thẳng -> đạt
    python ui/calib_e2e.py vai   <thư mục>   # cam laptop không thấy đủ hai vai -> "Bỏ qua camera laptop" -> chạy không đo lệch vai
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import engine as engine_mod
from engine import EngineOptions
from fake_pose import FakePoseDetector, make_blank_video, write_config
from ui.controller import AppController


class PacedFake(FakePoseDetector):
    pause = 0.1
    schedule = [(13, -8.8, 58), (1e9, 0, 0)]            # lưng gù 30 độ (đầu vẫn ~20 độ so với đứng) suốt lượt đầu (0-10 s) và thời gian chờ, thẳng từ giây 13

    def __call__(self, frame, ts):
        time.sleep(PacedFake.pause)                   # 10 mẫu/giây = đúng tốc độ thực
        return super().__call__(frame, ts)


def main(phase, out):
    os.makedirs(out, exist_ok=True)
    if phase == "vai":
        PacedFake.schedule = [(1e9, 0, 0)]
        PacedFake.pause = 0.05                       # cả hai camera cùng gọi detector
    engine_mod.PoseDetector = PacedFake
    d = tempfile.mkdtemp()
    video = os.path.join(d, "v.avi")
    make_blank_video(video, 60)
    cfg = write_config(os.path.join(d, "cfg.json"), calib_sec=10)
    opts = EngineOptions(side_video=video, front=("-1" if phase == "gu" else "0"),
                         front_video=video if phase == "vai" else None, no_face=True, config=cfg,
                         events=os.path.join(d, "ev.jsonl"), metrics_out=os.path.join(d, "m.jsonl"),
                         outbox=os.path.join(d, "ob.db"))
    app = QApplication(sys.argv[:1])
    ctl = AppController(app, opts, store=None)
    ctl.start()
    ctl.window.login.btn_local.click()
    shot = lambda n: ctl.window.grab().save(os.path.join(out, f"{phase}_{n}.png"))
    log = {}
    note = lambda k, v: (log.update({k: v}), print(f"[{phase}] {k}: {v}"))
    taken = set()

    def take(name, delay=300, then=None):
        if name not in taken:
            taken.add(name)
            QTimer.singleShot(delay, lambda: (shot(name), then() if then else None))

    def on_state(s):                                 # chụp theo SỰ KIỆN (không theo giờ, vì engine khởi động mất vài giây)
        c = s.get("calib") or {}
        checks = {x["code"]: x["ok"] for x in c.get("checks", [])}
        if phase == "gu":
            if s["state"] == "CALIBRATING" and c.get("stage") == "measuring" and checks.get("back") is False:
                take("1_dang_do_gu_lung_x")
            elif s["state"] == "CALIBRATING" and c.get("stage") == "failed":
                take("2_khong_dat_ly_do_dem_nguoc")
            elif "2_khong_dat_ly_do_dem_nguoc" in taken and s["state"] == "CALIBRATING" and c.get("stage") == "measuring"                     and checks and all(v is True for v in checks.values()):
                take("3_lam_lai_ngoi_thang_dat_het")
            elif "3_lam_lai_ngoi_thang_dat_het" in taken and s["state"] == "GOOD":
                take("4_dat_dang_theo_doi", 1500, app.quit)
        else:
            if c.get("stage") == "failed" and "1_thieu_vai_co_nut_bo_qua" not in taken:
                take("1_thieu_vai_co_nut_bo_qua", 300, ctl.window.calib_view.btn_skip.click)
            elif s["state"] == "CALIBRATING" and c.get("frontSkipped") and c.get("stage") == "measuring" and checks                     and all(v is True for v in checks.values()):
                take("2_sau_khi_bo_qua_dang_do")
            elif s["state"] == "GOOD" and s.get("frontSkipped"):
                take("3_dang_theo_doi_khong_do_lech_vai", 1500, app.quit)
    ctl.bridge.state.connect(on_state)
    QTimer.singleShot(90000, app.quit)
    app.exec()
    kinds = [json.loads(l) for l in open(os.path.join(d, "ev.jsonl"), encoding="utf-8")]
    note("su_kien", [(e["eventType"], [r["code"] for r in e.get("reasons", [])]) for e in kinds
                     if e["eventType"].startswith("CALIB")])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp()))
