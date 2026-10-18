"""Icon Lucide (SVG trong ui/icons) tô màu bằng token. Không dùng emoji làm icon."""
import functools
import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ui.tokens import UI_DIR

ICON_DIR = os.path.join(UI_DIR, "icons")


@functools.lru_cache(maxsize=None)
def _svg(name):
    with open(os.path.join(ICON_DIR, name + ".svg"), encoding="utf-8") as f:
        return f.read()


def pixmap(name, color, size=16, dpr=2.0):
    """Icon `name` tô nét bằng `color` (#rrggbb), vuông `size` px logic, nét sắc trên màn hình độ phân giải cao."""
    svg = _svg(name).replace("currentColor", color)
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return px


def icon(name, color, size=16):
    return QIcon(pixmap(name, color, size))
