"""
Công cụ chấm tay nhãn 6 lớp theo đoạn 2 giây (A1).

  python -m labeling.app --rater A --video nguoi01.mp4 nguoi02.mp4            # chạy trong posture_model/
  python -m labeling.app --rater A --video nguoi01.mp4 --out out/labels_A.csv

Mỗi đoạn 2 giây phát lặp. Phím: 1 GOOD · 2 FORWARD_HEAD · 3 LEAN_FORWARD · 4 SLOUCH · 5 LEAN_BACKWARD ·
6 NECK_EXTENSION · 0 UNCLEAR (không rõ) · Space phát lại · ← → đoạn trước/sau (không đổi nhãn) · Backspace bỏ nhãn đoạn
này · N tới đoạn chưa chấm kế tiếp. Chấm xong một đoạn là tự ghi CSV; mở lại cùng lệnh để chấm tiếp.
Chấm mù: không hiện dự đoán của model.
"""
import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from labeling.session import KEYS, LabelFileError, LabelSession
from labeling.video import VideoError, probe, read_segment

HELP = "  ".join(f"{k} {v}" for k, v in sorted(KEYS.items()) if k != "0") + "  0 UNCLEAR"


def to_qimage(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class LabelWindow(QWidget):
    def __init__(self, session, paths):
        super().__init__()
        self.s, self.paths = session, paths                  # paths: tên video -> đường dẫn
        self.frames, self.fps, self.pos = [], 30.0, 0
        self.setWindowTitle(f"Chấm nhãn tư thế ({session.rater})")
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setMinimumSize(640, 400)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setStyleSheet("background:#111")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.current_label = QLabel()
        help_ = QLabel(HELP + "\nSpace phát lại · ←/→ đoạn trước/sau · Backspace bỏ nhãn · N đoạn chưa chấm kế tiếp")
        help_.setWordWrap(True)
        for w in (self.view, self.status, self.current_label, help_):
            lay.addWidget(w)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.load_segment()

    def load_segment(self):
        name, t0, t1 = self.s.current()
        self.error = None
        try:
            self.frames, self.fps = read_segment(self.paths[name], t0, t1)
        except VideoError as e:
            self.frames, self.error = [], str(e)
        self.pos = 0
        self.timer.start(max(10, int(1000 / (self.fps or 30.0))))
        self.refresh()

    def refresh(self):
        name, t0, t1 = self.s.current()
        done, total = self.s.progress()
        text = (f"{name}  ·  {t0:g}–{t1:g} s  ·  đã chấm {done}/{total}"
                + ("  ·  XONG TẤT CẢ" if self.s.done else ""))
        self.status.setText(text + (f"\n{self.error}" if self.error else ""))
        lab = self.s.label_of()
        self.current_label.setText(f"Nhãn đoạn này: {lab}" if lab else "Nhãn đoạn này: (chưa chấm)")

    def tick(self):
        if not self.frames:
            return
        self.view.setPixmap(QPixmap.fromImage(to_qimage(self.frames[self.pos])).scaled(
            self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.pos = (self.pos + 1) % len(self.frames)

    def keyPressEvent(self, e):
        k, text = e.key(), e.text()
        if text in KEYS:
            self.s.assign(KEYS[text])
            self.load_segment()
        elif k == Qt.Key_Space:
            self.pos = 0
        elif k == Qt.Key_Left:
            self.s.step(-1)
            self.load_segment()
        elif k == Qt.Key_Right:
            self.s.step(1)
            self.load_segment()
        elif k == Qt.Key_Backspace:
            self.s.clear()
            self.refresh()
        elif text.lower() == "n":
            self.s.goto_next_unlabeled()
            self.load_segment()
        else:
            super().keyPressEvent(e)


def build_session(videos, rater, out):
    infos = []
    for v in videos:
        _, dur = probe(v)
        infos.append((os.path.basename(v), dur))
    return LabelSession(infos, rater, out), {os.path.basename(v): v for v in videos}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chấm tay nhãn 6 lớp theo đoạn 2 giây")
    ap.add_argument("--video", nargs="+", required=True)
    ap.add_argument("--rater", required=True, help="tên/mã người chấm, mỗi người một file CSV")
    ap.add_argument("--out", default=None, help="CSV đầu ra (mặc định out/labels_<rater>.csv)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join("out", f"labels_{a.rater}.csv")
    app = QApplication.instance() or QApplication([])
    try:
        session, paths = build_session(a.video, a.rater, out)
    except (VideoError, LabelFileError, ValueError) as e:
        print("Lỗi:", e, file=sys.stderr)
        return 2
    win = LabelWindow(session, paths)
    win.resize(900, 640)
    win.show()
    print(f"Chấm tiếp từ đoạn {session.index + 1}/{len(session.segments)}, ghi vào {out}")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
