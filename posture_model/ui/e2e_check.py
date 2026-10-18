"""Kiểm cả đường ống Qt (engine trong QThread -> signal -> cửa sổ) không cần camera/người:
video trắng + landmark giả chạy đúng tốc độ thực, chụp cửa sổ ở từng trạng thái, đo độ đơ của giao diện.

    python ui/e2e_check.py <thư mục ảnh ra>
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import engine as engine_mod
from engine import EngineOptions
from fake_pose import FakePoseDetector, make_blank_video, write_config
from ui.controller import AppController


class PacedFake(FakePoseDetector):
    schedule = [(5, 0), (14, 70), (1e9, 0)]       # thẳng -> cúi từ giây 5 -> thẳng lại từ giây 14

    def __call__(self, frame, ts):
        time.sleep(0.1)                             # 10 mẫu/giây = đúng tốc độ thực
        return super().__call__(frame, ts)


def main(out):
    os.makedirs(out, exist_ok=True)
    engine_mod.PoseDetector = PacedFake
    d = tempfile.mkdtemp()
    video = os.path.join(d, "v.avi")
    make_blank_video(video, 24)
    opts = EngineOptions(side_video=video, front="-1", config=write_config(os.path.join(d, "cfg.json")),
                         events=os.path.join(d, "ev.jsonl"), metrics_out=os.path.join(d, "m.jsonl"),
                         outbox=os.path.join(d, "ob.db"))
    app = QApplication(sys.argv[:1])
    ctl = AppController(app, opts, store=None)
    ctl.start()
    ctl.window.login.btn_local.click()               # "Dùng không đăng nhập": engine chạy local, không gửi
    seen, stalls = [], []
    ctl.bridge.state.connect(lambda s: seen.append(s["state"]) if not seen or seen[-1] != s["state"] else None)
    last = [time.monotonic()]

    def tick():                                     # giao diện đơ nếu hai nhịp 20 ms cách nhau quá xa
        now = time.monotonic()
        stalls.append(now - last[0])
        last[0] = now
    t = QTimer(interval=20)
    t.timeout.connect(tick)
    t.start()
    shot = lambda name: (lambda: ctl.window.grab().save(os.path.join(out, name)))
    QTimer.singleShot(1500, shot("e2e_1_hieu_chinh.png"))
    QTimer.singleShot(4500, shot("e2e_2_ngoi_dung.png"))
    QTimer.singleShot(5000, ctl.open_camera)
    QTimer.singleShot(9500, shot("e2e_3_ngoi_sai.png"))
    QTimer.singleShot(9700, lambda: ctl.camera.grab().save(os.path.join(out, "e2e_4_camera_khung_xuong.png")))
    QTimer.singleShot(19500, shot("e2e_5_ngoi_lai.png"))
    QTimer.singleShot(21000, ctl.camera.close)
    QTimer.singleShot(27000, app.quit)
    app.exec()
    print("trạng thái đã thấy:", seen)
    print(f"nhịp UI: tối đa {max(stalls) * 1000:.0f} ms, trung bình {sum(stalls) / len(stalls) * 1000:.1f} ms")
    ok = seen[:4] == ["CALIBRATING", "GOOD", "BAD", "GOOD"] and max(stalls) < 0.25
    print("ĐẠT" if ok else "KHÔNG ĐẠT")
    return 0 if ok else 1


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "e2e_screens"))
