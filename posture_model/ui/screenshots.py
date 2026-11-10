"""Chụp ảnh cửa sổ chính ở từng trạng thái (công cụ phát triển, không chạy camera):
    python ui/screenshots.py <thư mục ra>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.theme import apply_theme
from ui.tray import make_icon


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


CASES = [
    ("01_hieu_chinh", dict(state="CALIBRATING", calibLeft=6.0, sittingSec=0), None),
    ("02_ngoi_dung", dict(state="GOOD", sittingSec=754, distanceCm=62.0),
     dict(hasServer=True, online=True, pending=0)),
    ("03_ngoi_sai", dict(state="BAD", sittingSec=1210, distanceCm=47.0),
     dict(hasServer=True, online=True, pending=0)),
    ("04_vang_mat", dict(state="AWAY", sittingSec=0), dict(hasServer=True, online=True, pending=0)),
    ("05_mat_ket_noi", dict(state="GOOD", sittingSec=3725, distanceCm=58.0),
     dict(hasServer=True, online=False, pending=14)),
    ("06_khong_ket_noi", dict(state="OFFLINE"), None),
]


def main(out):
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv[:1])
    apply_theme(app)
    w = MainWindow()
    w.show()
    for name, st, sync in CASES:
        w.set_state(st)
        w.set_sync(sync)
        wait(900)                                   # chờ thước dọi xoay xong (600 ms)
        w.grab().save(os.path.join(out, name + ".png"))
        print("đã lưu", name)
    w.set_state(CASES[2][1])
    w.show_notice("NECK_TRUNK", "Cúi cổ, gù lưng", "Bạn đang cúi hoặc gù lưng. Ngồi thẳng, kéo vai ra sau nhé.")
    wait(900)
    w.grab().save(os.path.join(out, "07_banner_canh_bao.png"))
    w.show_notice("SIT_TOO_LONG", "Ngồi quá lâu", "Bạn đã ngồi liên tục 30 phút. Đứng dậy đi lại khoảng 2 phút nhé.")
    w.set_state(CASES[1][1])
    wait(900)
    w.grab().save(os.path.join(out, "08_banner_nghi_ngoi.png"))
    for s in ("GOOD", "BAD", "AWAY", "OFFLINE"):
        make_icon(s, 128).pixmap(128, 128).save(os.path.join(out, f"tray_{s}.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "screenshots"))
