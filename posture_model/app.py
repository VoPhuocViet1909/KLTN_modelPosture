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
from ui.setup_view import SetupDialog, preferences
from ui.theme import apply_theme


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default=None, help="cam hông ~90°: số webcam hoặc link điện thoại")
    ap.add_argument("--front", default=None, help="cam laptop chính diện: số webcam hoặc link, -1 = tắt")
    ap.add_argument("--side-video", default=None)
    ap.add_argument("--front-video", default=None)
    ap.add_argument("--config", default=os.path.join(APP_DIR, "app_config.json"))
    ap.add_argument("--events", default=os.path.join(APP_DIR, "out", "events.jsonl"))
    ap.add_argument("--metrics-out", default=os.path.join(APP_DIR, "out", "metrics.jsonl"))
    ap.add_argument("--outbox", default=os.path.join(APP_DIR, "out", "outbox.db"))
    ap.add_argument("--no-face", action="store_true", help="không dùng Face Landmarker, đo bằng khoảng cách 2 mắt")
    ap.add_argument("--max-sec", type=float, default=None, help="dừng sau N giây (kiểm thử)")
    ap.add_argument("--api-base-url", default=None,
                    help="địa chỉ backend (ưu tiên hơn api_base_url trong app_config.json), vd http://localhost:8080")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Posture Monitor")
    app.setQuitOnLastWindowClosed(False)
    settings = preferences()
    side = a.side if a.side is not None else str(settings.value("side", "1"))
    front = a.front if a.front is not None else str(settings.value("front", "0"))
    server = a.api_base_url or settings.value("server")
    if not settings.value("configured", False, type=bool) and a.side is None and not a.side_video:
        apply_theme(app)
        setup = SetupDialog(side, front, server)
        if setup.exec() != SetupDialog.Accepted:
            return 0
        side, front, server = setup.result_values
    opts = EngineOptions(side=side, front=front, side_video=a.side_video, front_video=a.front_video,
                         config=a.config, events=a.events, metrics_out=a.metrics_out, outbox=a.outbox,
                         no_face=a.no_face, max_sec=a.max_sec)
    ctl = AppController(app, opts, base_url=server)
    ctl.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
