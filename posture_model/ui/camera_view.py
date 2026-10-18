"""Cửa sổ 'Xem camera': khung hình + khung xương. Chỉ nhận khung khi cửa sổ đang mở (engine.want_frames).

Hai hình (camera hông + camera laptop) luôn được co vừa vùng hiển thị, giữ tỉ lệ, thấy TRỌN khung gốc; vùng đủ rộng thì xếp ngang,
hẹp thì xếp dọc (chọn cách xếp cho hình to hơn). Co lại ngay khi đổi kích thước cửa sổ, không cắt xén.
"""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from posture_features import IDX
from ui.tokens import color

GAP = 8


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


def frame_images(frame):
    """frame (dict từ engine.on_frame) -> [QImage hông (có khung xương), QImage laptop (nếu có)], kích thước gốc."""
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
    return parts


def layout_rects(sizes, box_w, box_h, gap=GAP):
    """Xếp các hình kích thước `sizes` [(w, h)] vào hộp box_w x box_h, giữ tỉ lệ, không cắt, không chồng nhau.
    Thử xếp ngang và xếp dọc, lấy cách cho hình to hơn. Trả [(x, y, w, h)] (float) căn giữa trong hộp."""
    n = len(sizes)
    if n == 0 or box_w <= 0 or box_h <= 0:
        return []

    def fit(horizontal):
        if horizontal:      # cùng chiều cao h: tổng bề rộng = h * sum(w/h) + gap
            ratios = sum(w / h for w, h in sizes)
            scale_h = min(box_h, (box_w - gap * (n - 1)) / ratios) if ratios else 0
            return scale_h, [(scale_h * w / h, scale_h) for w, h in sizes]
        # cùng bề rộng w: tổng chiều cao = w * sum(h/w) + gap
        ratios = sum(h / w for w, h in sizes)
        scale_w = min(box_w, (box_h - gap * (n - 1)) / ratios) if ratios else 0
        return scale_w, [(scale_w, scale_w * h / w) for w, h in sizes]

    # so sánh theo hệ số co thật (diện tích hình), không theo chiều cao/bề rộng riêng lẻ
    best = None
    for horizontal in ((True, False) if n > 1 else (True,)):
        _, dims = fit(horizontal)
        area = sum(w * h for w, h in dims)
        if best is None or area > best[0]:
            best = (area, horizontal, dims)
    _, horizontal, dims = best
    total_w = sum(w for w, _ in dims) + gap * (n - 1) if horizontal else max(w for w, _ in dims)
    total_h = max(h for _, h in dims) if horizontal else sum(h for _, h in dims) + gap * (n - 1)
    x0, y0 = (box_w - total_w) / 2, (box_h - total_h) / 2
    out, cx, cy = [], x0, y0
    for w, h in dims:
        if horizontal:
            out.append((cx, y0 + (total_h - h) / 2, w, h))
            cx += w + gap
        else:
            out.append((x0 + (total_w - w) / 2, cy, w, h))
            cy += h + gap
    return out


def render(images, size, background=None):
    """Vẽ `images` vào QPixmap `size` đúng như cửa sổ hiển thị (dùng cho test và chụp màn hình)."""
    px = QPixmap(size)
    px.fill(QColor(background or color("surface")))
    p = QPainter(px)
    paint_fit(p, images, size.width(), size.height())
    p.end()
    return px


def paint_fit(p, images, box_w, box_h):
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    rects = layout_rects([(i.width(), i.height()) for i in images], box_w, box_h)
    for img, (x, y, w, h) in zip(images, rects):
        p.drawImage(QRectF(x, y, w, h), img)
    return rects


class FitView(QWidget):
    """Vẽ các hình đã co vừa toàn bộ vùng widget (cập nhật khi đổi kích thước)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.images = []
        self.placeholder = "Đang chờ hình…"
        self.setMinimumSize(240, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAccessibleName("Hình camera")

    def set_images(self, images):
        self.images = images
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(color("surface")))
        if not self.images:
            p.setPen(QColor(color("muted-foreground")))
            p.drawText(self.rect(), Qt.AlignCenter, self.placeholder)
            return
        paint_fit(p, self.images, self.width(), self.height())


class CameraView(QWidget):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Camera – Posture Monitor")
        self.resize(960, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self.view = FitView()
        note = QLabel("Hình chỉ hiện trên máy này, không được lưu hay gửi đi.")
        note.setObjectName("note")
        lay.addWidget(self.view, 1)
        lay.addWidget(note)

    def show_frame(self, frame):
        self.view.set_images(frame_images(frame))

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()
