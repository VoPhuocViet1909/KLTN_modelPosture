"""
Desktop App có giao diện (PySide6). Điểm vào mới; realtime_app.py vẫn là bản dòng lệnh (CLI).

  python app.py --side 1 --front 0
  python app.py --side-video hong.mp4 --front -1          # chạy thử trên video

Cửa sổ chính không hiện camera; nút "Xem camera" mở khung hình có vẽ khung xương. Đóng cửa sổ = thu xuống khay,
thoát bằng menu khay. Camera chọn tạm qua --side / --front (màn thiết lập sẽ thay ở giai đoạn sau).
"""
import argparse
import os
import sys

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from engine import APP_DIR, EngineOptions
from ui.controller import AppController


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="1", help="cam hông ~90°: số webcam hoặc link điện thoại")
    ap.add_argument("--front", default="0", help="cam laptop chính diện: số webcam hoặc link, -1 = tắt")
    ap.add_argument("--side-video", default=None)
    ap.add_argument("--front-video", default=None)
    ap.add_argument("--config", default=os.path.join(APP_DIR, "app_config.json"))
    ap.add_argument("--events", default=os.path.join(APP_DIR, "out", "events.jsonl"))
    ap.add_argument("--metrics-out", default=os.path.join(APP_DIR, "out", "metrics.jsonl"))
    ap.add_argument("--outbox", default=os.path.join(APP_DIR, "out", "outbox.db"))
    ap.add_argument("--no-face", action="store_true", help="không dùng Face Landmarker, đo bằng khoảng cách 2 mắt")
    ap.add_argument("--max-sec", type=float, default=None, help="dừng sau N giây (kiểm thử)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    opts = EngineOptions(side=a.side, front=a.front, side_video=a.side_video, front_video=a.front_video,
                         config=a.config, events=a.events, metrics_out=a.metrics_out, outbox=a.outbox,
                         no_face=a.no_face, max_sec=a.max_sec)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Posture Monitor")
    ctl = AppController(app, opts)
    ctl.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
