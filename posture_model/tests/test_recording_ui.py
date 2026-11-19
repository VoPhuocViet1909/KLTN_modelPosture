"""Kiểm giao diện công cụ quay, Qt offscreen, không camera. Tùy chọn: tham số 1 = thư mục lưu ảnh chụp.
Chạy:  PYTHONUTF8=1 python tests/test_recording_ui.py [thư_mục_ảnh]"""
import math
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import test_recording as tr  # noqa: E402
from recording.script import Phase, load_script  # noqa: E402
from recording.session import IDLE, RECORDING  # noqa: E402
from recording.ui import CmDialog, RecorderWindow  # noqa: E402
from ui.theme import apply_theme  # noqa: E402


def pump(app, win, sec):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < sec:
        app.processEvents()
        time.sleep(0.01)


def main():
    shots = sys.argv[1] if len(sys.argv) > 1 else None
    if shots:
        os.makedirs(shots, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    fam = apply_theme(app)
    assert fam == "Be Vietnam Pro", "phải nạp được font Be Vietnam Pro"
    out = tempfile.mkdtemp(prefix="recui_")
    sess = stop = win = None
    try:
        real = {c.id: c for c in load_script()}
        # clip thật (tên, hiệu lệnh, mức cần đạt tiếng Việt) nhưng rút ngắn để chạy nhanh
        a1 = tr.mk_clip("A1", "CALIBRATION", 7, [Phase(0, "", None)], "both", margin=1.0)
        a1.cue, a1.goal = real["A1"].cue, real["A1"].goal
        b1 = tr.mk_clip("B1", "FORWARD_HEAD_L1", 9, real["B1"].phases, "side", margin=1.0)
        b1.cue, b1.goal, b1.cam_text = real["B1"].cue, real["B1"].goal, "hông"
        e1 = tr.mk_clip("E1", "SHOULDER_TILT_L", 10, [Phase(0, "MỨC NHẸ", real["E1"].phases[0].check),
                                                       Phase(5, "MỨC RÕ HƠN", real["E1"].phases[1].check)], "front", margin=1.0)
        e1.cue, e1.goal, e1.cam_text = real["E1"].cue, real["E1"].goal, "laptop"
        e7 = tr.mk_clip("E7", "DISTANCE_STEPS", 6, [Phase(0, "70 cm", None), Phase(3, "60 cm", None)], "front", margin=1.0)
        e7.cue = real["E7"].cue
        dx = lambda d: 50.0 * math.tan(math.radians(d))
        side_fn = lambda t: dx(11.3 + 25) if sess and sess.current and sess.current.id == "B1" else 10.0
        front_fn = lambda t: 4.0 if sess and sess.current and sess.current.id == "E1" else 0.0
        sess, stop = tr.build(out, [a1, b1, e1, e7], side_fn, front_fn, ed=tr.FakeEd(), countdown=1.5)
        asked = []
        win = RecorderWindow(sess, ask_cm_fn=lambda parent: asked.append(1) or [70, 60, 50, 40])
        win.resize(1500, 900)
        win.show()
        pump(app, win, 1.0)
        assert "Hiệu lệnh thử" not in win.cue.text() and "Vỗ tay" in win.cue.text()       # tiếng Việt có dấu hiển thị đúng
        assert win.head.text().startswith("A1 · CALIBRATION") and "Bấm Space" in win.banner.text()
        if shots:
            win.grab().save(os.path.join(shots, "01_san_sang.png"))

        # ---- Space: đếm ngược 3-2-1 rồi ghi
        QTest.keyClick(win, Qt.Key_Space)
        assert sess.state == "COUNTDOWN"
        pump(app, win, 0.2)
        assert win.banner.text() in ("2", "1")
        if shots:
            win.grab().save(os.path.join(shots, "02_dem_nguoc.png"))
        pump(app, win, 1.9)
        assert sess.state == RECORDING and "NGỒI THẲNG" == win.banner.text()
        pump(app, win, 3.0)
        if shots:
            win.grab().save(os.path.join(shots, "03_hieu_chinh_A1.png"))
        while sess.state == RECORDING:
            pump(app, win, 0.1)
        pump(app, win, 0.3)
        assert sess.baseline is not None and "A1 ĐẠT" in win.message.text()
        assert win.head.text().startswith("B1 ·")

        # ---- B1: cổ lệch ~25° so với baseline -> chấm đạt (xanh), có số trực tiếp
        QTest.keyClick(win, Qt.Key_Space)
        pump(app, win, 1.6 + 3.0)
        assert sess.state == RECORDING
        assert win.badge.text().startswith("ĐẠT"), win.badge.text()
        assert "Cổ +" in win.numbers.text() and "Mức cần đạt: cổ 20–30°" == win.goal.text()
        assert tr.DAT == sess.live["status"]
        if shots:
            win.grab().save(os.path.join(shots, "04_dang_quay_DAT.png"))
        QTest.keyClick(win, Qt.Key_Escape)                 # hủy clip dở
        assert sess.state == IDLE and "Đã hủy" in win.message.text() and not os.path.exists(sess.file_path(b1, "side"))
        QTest.keyClick(win, Qt.Key_N)                      # N: sang E1
        assert sess.current is e1
        QTest.keyClick(win, Qt.Key_B)                      # B: về B1
        assert sess.current is b1
        QTest.keyClick(win, Qt.Key_C)                      # C: về A1
        assert sess.current is a1
        QTest.keyClick(win, Qt.Key_N)
        QTest.keyClick(win, Qt.Key_N)
        assert sess.current is e1

        # ---- E1: 2 mức, chữ MỨC RÕ HƠN ở mốc, lệch vai 4° đạt mức nhẹ, chưa đủ mức rõ hơn
        QTest.keyClick(win, Qt.Key_Space)
        pump(app, win, 1.6 + 2.0)
        assert win.badge.text().startswith("ĐẠT") and "MỨC NHẸ" in win.goal.text()
        pump(app, win, 3.2)
        assert win.banner.text() == "MỨC RÕ HƠN", win.banner.text()
        assert win.badge.text().startswith("CHƯA ĐỦ · đã đạt ") and win.badge.text().endswith("% thời gian"), win.badge.text()
        if shots:
            win.grab().save(os.path.join(shots, "05_muc_ro_hon_CHUA_DU.png"))
        while sess.state == RECORDING:
            pump(app, win, 0.1)
        pump(app, win, 0.2)
        assert "Xong SHOULDER_TILT_L" in win.message.text()

        # ---- E7 hỏi cm
        QTest.keyClick(win, Qt.Key_Space)
        while sess.state in ("COUNTDOWN", RECORDING):
            pump(app, win, 0.1)
        pump(app, win, 0.3)
        assert asked and sess.state == IDLE
        dlg = CmDialog()
        dlg.edits[1].setText("61,5")
        assert dlg.values() == ["", 61.5, "", ""]

        # ---- hết danh sách: màn hình xong buổi
        assert sess.finished and win.summary.isVisibleTo(win) and not win.badge.isVisibleTo(win)
        assert win.head.text() == "ĐÃ QUAY XONG BUỔI P01 S01" and "SHOULDER_TILT_L" in win.summary.text()
        QTest.keyClick(win, Qt.Key_Space)
        assert sess.state == IDLE and sess.finished
        if shots:
            win.grab().save(os.path.join(shots, "06_xong_buoi.png"))
        QTest.keyClick(win, Qt.Key_R)
        pump(app, win, 0.2)
        assert not sess.finished and sess.current is e7 and not win.summary.isVisibleTo(win) and win.badge.isVisibleTo(win)

        # ---- Q: thoát, lưu tiến độ
        QTest.keyClick(win, Qt.Key_Q)
        assert os.path.exists(sess.progress_path)
        print("ĐẠT  giao diện offscreen" + (f" (ảnh trong {shots})" if shots else ""))
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    main()
