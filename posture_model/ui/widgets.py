"""Thành phần giao diện dùng chung, vẽ theo design system của web (PlumbLine, StateBadge, Banner, ConnectionDot)."""
import sys

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui import icons
from ui.tokens import alert_info, color, labels, state_label, status_color, tokens


def reduced_motion():
    """Windows: 'Hiệu ứng hoạt hình' tắt (SPI_GETCLIENTAREAANIMATION) = người dùng muốn giảm chuyển động."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        flag = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)
        return bool(ok) and flag.value == 0
    except Exception:
        return False


def tabular(font: QFont) -> QFont:
    """Chữ số đều nhau (tabular-nums) nếu font hỗ trợ."""
    try:
        font.setFeature("tnum", 1)
    except Exception:
        pass
    return font


def plumb_state(state):
    """Trạng thái của engine -> (màu, độ nghiêng, nét đứt). CALIBRATING/None = chưa có dữ liệu: nét đứt xám."""
    tilt = tokens()["plumb"]["tilt-deg"]
    if state in ("GOOD", "BAD", "AWAY", "OFFLINE"):
        return status_color(state), tilt[state], state == "AWAY"
    return status_color("OFFLINE"), 0, True


class PlumbLine(QWidget):
    """Thước dọi: thẳng = GOOD, nghiêng 14° = BAD, nét đứt = AWAY, xám = OFFLINE; xoay 600 ms khi đổi trạng thái."""

    ROTATE_MS = tokens()["motion"]["plumb-rotate-ms"]
    COLOR_MS = tokens()["motion"]["color-ms"]

    def __init__(self, size=200, parent=None):
        super().__init__(parent)
        self._h = size
        self.setFixedSize(int(size * 0.6), size)
        self._state = None
        col, tilt, dashed = plumb_state(None)
        self._angle, self._color, self._dashed = float(tilt), QColor(col), dashed
        self._rot = QVariantAnimation(self, duration=self.ROTATE_MS)
        curve = QEasingCurve(QEasingCurve.BezierSpline)
        curve.addCubicBezierSegment(QPointF(0.2, 0.8), QPointF(0.2, 1.0), QPointF(1.0, 1.0))
        self._rot.setEasingCurve(curve)
        self._rot.valueChanged.connect(self._on_angle)
        self._col = QVariantAnimation(self, duration=self.COLOR_MS)
        self._col.valueChanged.connect(self._on_color)

    def state(self):
        return self._state

    def angle(self):
        return self._angle

    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        col, tilt, dashed = plumb_state(state)
        self._dashed = dashed
        self._rot.stop()
        self._col.stop()
        if reduced_motion():
            self._angle, self._color = float(tilt), QColor(col)
        else:
            self._rot.setStartValue(float(self._angle))
            self._rot.setEndValue(float(tilt))
            self._rot.start()
            self._col.setStartValue(QColor(self._color))
            self._col.setEndValue(QColor(col))
            self._col.start()
        self.setAccessibleName(state_label(state) if state in ("GOOD", "BAD", "AWAY", "OFFLINE") else "Chưa có dữ liệu")
        self.update()

    def _on_angle(self, v):
        self._angle = float(v)
        self.update()

    def _on_color(self, v):
        self._color = QColor(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.height() / 100.0                 # viewBox 60x100 như PlumbLine.tsx
        p.scale(s, s)
        guide = QPen(QColor(color("border")), 2, Qt.CustomDashLine, Qt.FlatCap)
        guide.setDashPattern([1, 2])
        p.setPen(guide)
        p.drawLine(QPointF(30, 6), QPointF(30, 94))
        p.save()
        p.translate(30, 92)
        p.rotate(self._angle)
        p.translate(-30, -92)
        pen = QPen(self._color, 4, Qt.SolidLine, Qt.RoundCap)
        if self._dashed:
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([1.5, 1.5])
        p.setPen(pen)
        p.drawLine(QPointF(30, 26), QPointF(30, 92))
        if self._dashed:
            pen.setDashPattern([1.5, 1.25])
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(30, 16), 9, 9)
        p.restore()
        p.setPen(QPen(QColor(color("foreground")), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(16, 94), QPointF(44, 94))


class StateBadge(QWidget):
    """Icon (màu trạng thái) + chữ (luôn màu foreground)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.text = QLabel()
        self.text.setObjectName("stateText")
        lay.addStretch(1)
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        lay.addStretch(1)
        self.set_state("OFFLINE")

    def set_state(self, state):
        meta = labels()["state"][state]
        col = status_color(state) if state in ("GOOD", "BAD", "AWAY", "OFFLINE") else status_color("OFFLINE")
        self.icon.setPixmap(icons.pixmap(meta["icon"], col, 20))
        self.text.setText(meta["label"])


class ConnectionDot(QWidget):
    """Chấm + chữ trạng thái đồng bộ. Chấm màu primary (không dùng xanh lục để khỏi nhầm với GOOD)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.text = QLabel()
        self.text.setObjectName("note")
        lay.addWidget(self.dot)
        lay.addWidget(self.text, 1)
        self.set_info(None)

    def set_info(self, info, logged_in=True):
        """info = dict từ engine.on_sync hoặc None."""
        ui = labels()["ui"]
        if info is None or not info.get("hasServer"):
            kind, text = "local", ui["sync_local"]
        elif info.get("online") is False:
            kind, text = "lost", ui["sync_lost"].format(n=info.get("pending", 0))
        else:
            kind, text = "ok", ui["sync_ok"]
        self.kind = kind
        self.text.setText(text)
        self.dot.setPixmap(self._dot(kind))

    @staticmethod
    def _dot(kind):
        from PySide6.QtGui import QPixmap
        d = 2.0
        px = QPixmap(int(12 * d), int(12 * d))
        px.setDevicePixelRatio(d)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        if kind == "ok":
            p.setBrush(QColor(color("primary")))
            p.setPen(Qt.NoPen)
        else:                                       # mất kết nối / chưa đăng nhập: vòng rỗng xám
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(status_color("OFFLINE")), 2))
        p.drawEllipse(QRectF(1.5, 1.5, 9, 9))
        p.end()
        return px


class Banner(QFrame):
    """Banner cảnh báo trong cửa sổ, tự ẩn sau 6 giây. Icon + tiêu đề (tên ngắn) + lời nhắc; không tô màu theo mức."""

    HIDE_MS = 6000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setObjectName("note")
        col.addWidget(self.title)
        col.addWidget(self.body)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addLayout(col, 1)
        self._timer = QTimer(self, singleShot=True, interval=self.HIDE_MS)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_alert(self, alert_type, title, body):
        info = alert_info(alert_type)
        col = color("primary") if info["group"] == "rest" else status_color("BAD")
        self.icon.setPixmap(icons.pixmap(info["icon"], col, 20))
        self.title.setText(title)
        self.body.setText(body)
        self.show()
        self._timer.start()
        self.setAccessibleName(f"{title}. {body}")
