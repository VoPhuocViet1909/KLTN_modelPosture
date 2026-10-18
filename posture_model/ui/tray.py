"""Icon khay hệ thống: 4 biến thể GOOD/BAD/AWAY/OFFLINE (thước dọi thu nhỏ + chấm màu trạng thái)."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ui.tokens import color, state_label, status_color, tokens

TRAY_STATES = ("GOOD", "BAD", "AWAY", "OFFLINE")


def make_icon(state, size=64):
    """Nền trắng bo góc (đọc được trên thanh tác vụ sáng lẫn tối), thước dọi + chấm màu trạng thái."""
    st = state if state in TRAY_STATES else "OFFLINE"
    col = QColor(status_color(st))
    tilt = tokens()["plumb"]["tilt-deg"][st]
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color("border")), size / 32))
    p.setBrush(QColor(color("background")))
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    p.save()
    p.scale(size / 100.0, size / 100.0)
    p.translate(46, 80)                              # chân thước dọi, hơi lệch trái để chừa chỗ cho chấm
    p.rotate(tilt)
    pen = QPen(col, 8, Qt.SolidLine, Qt.RoundCap)
    if st == "AWAY":
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([1.2, 1.2])
    p.setPen(pen)
    p.drawLine(QPointF(0, 0), QPointF(0, -42))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(0, -56), 11, 11)
    p.restore()
    p.setPen(QPen(QColor(color("foreground")), size / 24, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(size * 0.30, size * 0.80), QPointF(size * 0.62, size * 0.80))
    r = size * 0.15                                 # chấm trạng thái ở góc trên phải, viền trắng
    c = QPointF(size * 0.77, size * 0.27)
    p.setPen(QPen(QColor(color("background")), size / 22))
    p.setBrush(col)
    p.drawEllipse(c, r, r)
    p.end()
    return QIcon(px)


class TrayController(QSystemTrayIcon):
    openRequested = Signal()
    recalibrateRequested = Signal()
    quitRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icons = {s: make_icon(s) for s in TRAY_STATES}
        self.menu = QMenu()
        self.act_open = QAction("Mở", self.menu)
        self.act_recal = QAction("Hiệu chỉnh lại", self.menu)
        self.act_quit = QAction("Thoát", self.menu)
        self.act_open.triggered.connect(self.openRequested)
        self.act_recal.triggered.connect(self.recalibrateRequested)
        self.act_quit.triggered.connect(self.quitRequested)
        self.menu.addAction(self.act_open)
        self.menu.addAction(self.act_recal)
        self.menu.addSeparator()
        self.menu.addAction(self.act_quit)
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)
        self.set_state("OFFLINE")

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.openRequested.emit()

    def set_state(self, state):
        st = state if state in TRAY_STATES else "OFFLINE"
        label = state_label(state) if state in TRAY_STATES else "Đang hiệu chỉnh"
        self.setIcon(self._icons[st])
        self.setToolTip(f"Posture Monitor – {label}")
        self.state = state
