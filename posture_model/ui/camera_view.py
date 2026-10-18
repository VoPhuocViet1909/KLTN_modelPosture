"""Cửa sổ 'Xem camera': khung hình + khung xương. Chỉ nhận khung khi cửa sổ đang mở (engine.want_frames)."""
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from posture_features import IDX
from ui.tokens import color


def _qimage(bgr):
    h, w = bgr.shape[:2]
    return QImage(np.ascontiguousarray(bgr).data, w, h, 3 * w, QImage.Format_BGR888).copy()


def draw_skeleton(img, L, pairs, ids):
    """Vẽ lên QImage: nối `pairs` (chỉ số landmark) bằng nét trắng, chấm primary ở các khớp `ids`."""
    if L is None:
        return
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#ffffff"), 3, Qt.SolidLine, Qt.RoundCap))
    for a, b in pairs:
        p.drawLine(QPointF(*L[a, :2]), QPointF(*L[b, :2]))
    p.setPen(QPen(QColor("#ffffff"), 2))
    p.setBrush(QColor(color("chart-1")))
    for i in ids:
        p.drawEllipse(QPointF(*L[i, :2]), 6, 6)
    p.end()


def compose(frame, height=300):
    """frame (dict từ engine.on_frame) -> QPixmap: camera hông (có khung xương) cạnh camera trước (nếu có)."""
    parts = []
    side = _qimage(frame["side"])
    sd = frame.get("side_idx")
    if frame.get("Ls") is not None and sd is not None:
        e, s, h, ey = IDX["ear"][sd], IDX["shoulder"][sd], IDX["hip"][sd], IDX["eye"][sd]
        draw_skeleton(side, frame["Ls"], [(e, s), (s, h), (e, ey)], [e, s, h, ey])
    parts.append(side)
    if frame.get("front") is not None:
        front = _qimage(frame["front"])
        draw_skeleton(front, frame.get("Lf"), [(11, 12)], [11, 12])
        parts.append(front)
    scaled = [i.scaledToHeight(height, Qt.SmoothTransformation) for i in parts]
    out = QImage(sum(i.width() for i in scaled) + 8 * (len(scaled) - 1), height, QImage.Format_RGB32)
    out.fill(QColor(color("surface")))
    p = QPainter(out)
    x = 0
    for i in scaled:
        p.drawImage(x, 0, i)
        x += i.width() + 8
    p.end()
    return QPixmap.fromImage(out)


class CameraView(QWidget):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Camera – Posture Monitor")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self.image = QLabel("Đang chờ hình…")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(480, 300)
        note = QLabel("Hình chỉ hiện trên máy này, không được lưu hay gửi đi.")
        note.setObjectName("note")
        lay.addWidget(self.image)
        lay.addWidget(note)

    def show_frame(self, frame):
        self.image.setPixmap(compose(frame))

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()
