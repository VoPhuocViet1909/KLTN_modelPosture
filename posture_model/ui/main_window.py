"""Cửa sổ chính ~420x560. Hai trang: Đăng nhập (LoginView) và Trạng thái (thước dọi, nhãn trạng thái, thời gian ngồi,
khoảng cách mắt–màn hình, kết nối). Không hiện camera mặc định; nút 'Xem camera' mở cửa sổ riêng."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ui import icons
from ui.calibration_view import CalibrationView
from ui.login_view import LoginView
from ui.tokens import color
from ui.widgets import Banner, ConnectionDot, PlumbLine, StateBadge, tabular


def fmt_duration(sec):
    sec = int(max(sec, 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class MainWindow(QMainWindow):
    cameraRequested = Signal()
    loginClicked = Signal()                      # link "Đăng nhập" ở chế độ không đăng nhập
    recalibrateRequested = Signal()
    skipFrontRequested = Signal()

    PAGE_LOGIN, PAGE_STATUS = 0, 1

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Posture Monitor")
        self.setFixedSize(420, 560)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.login = LoginView()
        self.stack.addWidget(self.login)
        self.stack.addWidget(self._build_status_page())
        self.show_login()
        self.set_state(dict(state="OFFLINE"))

    def _build_status_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self.banner = Banner()
        outer.addWidget(self.banner)

        panel = QFrame()
        panel.setObjectName("panel")
        outer_pl = QVBoxLayout(panel)
        outer_pl.setContentsMargins(24, 20, 24, 20)
        self.panel_stack = QStackedWidget()
        outer_pl.addWidget(self.panel_stack)
        self.calib_view = CalibrationView()
        self.calib_view.recalibrateRequested.connect(self.recalibrateRequested)
        self.calib_view.skipFrontRequested.connect(self.skipFrontRequested)
        run_page = QWidget()
        pl = QVBoxLayout(run_page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.plumb = PlumbLine(190)
        pl.addWidget(self.plumb, 0, Qt.AlignHCenter)
        self.badge = StateBadge()
        pl.addWidget(self.badge)
        self.hint = QLabel("")
        self.hint.setObjectName("note")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(34)
        pl.addWidget(self.hint)
        self.btn_recal = QPushButton("Hiệu chỉnh lại")
        self.btn_recal.setObjectName("link")
        self.btn_recal.setToolTip("Ngồi thẳng và đo lại tư thế chuẩn")
        self.btn_recal.clicked.connect(self.recalibrateRequested)
        pl.addWidget(self.btn_recal, 0, Qt.AlignHCenter)
        pl.addStretch(1)

        stats = QGridLayout()
        stats.setHorizontalSpacing(16)
        stats.setVerticalSpacing(2)
        cap1, cap2 = QLabel("Thời gian ngồi"), QLabel("Khoảng cách mắt – màn hình")
        for c in (cap1, cap2):
            c.setObjectName("note")
            c.setWordWrap(True)
        self.sit = QLabel("00:00")
        self.sit.setObjectName("bigNumber")
        self.sit.setFont(tabular(self.sit.font()))
        self.dist = QLabel("Chưa đo")
        self.dist.setObjectName("pageTitle")
        self.dist.setFont(tabular(self.dist.font()))
        stats.addWidget(cap1, 0, 0)
        stats.addWidget(cap2, 0, 1)
        stats.addWidget(self.sit, 1, 0)
        stats.addWidget(self.dist, 1, 1, Qt.AlignBottom)
        stats.setColumnStretch(0, 5)
        stats.setColumnStretch(1, 4)
        pl.addLayout(stats)
        self.panel_stack.addWidget(run_page)           # 0: đang theo dõi
        self.panel_stack.addWidget(self.calib_view)    # 1: hiệu chỉnh
        outer.addWidget(panel, 1)

        bottom = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        self.conn = ConnectionDot()
        left.addWidget(self.conn)
        self.account = QLabel("")
        self.account.setObjectName("note")
        self.account.setIndent(20)
        left.addWidget(self.account)
        self.btn_login = QPushButton("Đăng nhập")
        self.btn_login.setObjectName("link")
        self.btn_login.setToolTip("Đăng nhập để gửi dữ liệu lên máy chủ và xem trên web")
        self.btn_login.clicked.connect(self.loginClicked)
        left.addWidget(self.btn_login, 0, Qt.AlignLeft)
        bottom.addLayout(left, 1)
        self.btn_cam = QPushButton("Xem camera")
        self.btn_cam.setIcon(icons.icon("video", color("foreground"), 16))
        self.btn_cam.setCursor(Qt.PointingHandCursor)
        self.btn_cam.clicked.connect(self.cameraRequested)
        bottom.addWidget(self.btn_cam, 0, Qt.AlignBottom)
        outer.addLayout(bottom)
        self.set_account(None)
        return page

    def closeEvent(self, e):
        """Đóng cửa sổ = thu xuống khay; chỉ thoát bằng menu khay."""
        e.ignore()
        self.hide()

    # ---------------------------------------------------------------- chuyển trang
    def show_login(self):
        self.stack.setCurrentIndex(self.PAGE_LOGIN)

    def show_status(self):
        self.stack.setCurrentIndex(self.PAGE_STATUS)

    def on_login_page(self):
        return self.stack.currentIndex() == self.PAGE_LOGIN

    def set_account(self, email):
        """email = tài khoản đang dùng; None = chế độ không đăng nhập (hiện link 'Đăng nhập')."""
        self.account.setVisible(bool(email))
        self.account.setText(email or "")
        self.btn_login.setVisible(not email)

    # ---------------------------------------------------------------- cập nhật từ engine
    def set_state(self, s):
        st = s.get("state", "OFFLINE")
        self.plumb.set_state(st if st in ("GOOD", "BAD", "AWAY", "OFFLINE") else None)
        self.badge.set_state(st)
        calibrating = st == "CALIBRATING"
        self.panel_stack.setCurrentIndex(1 if calibrating else 0)
        if calibrating:
            self.calib_view.update_view(s.get("calib"), s.get("calibLeft", 0), self._calib_seconds(s))
        skipped = bool(s.get("frontSkipped"))
        if st == "AWAY":
            self.hint.setText("Không thấy bạn trước camera.")
        elif st == "OFFLINE":
            self.hint.setText("Camera chưa hoạt động.")
        elif skipped:
            self.hint.setText("Đang chạy không đo lệch vai và khoảng cách (đã bỏ qua camera laptop).")
        else:
            self.hint.setText("")
        self.btn_recal.setVisible(st in ("GOOD", "BAD", "AWAY"))
        self.sit.setText(fmt_duration(s.get("sittingSec", 0)) if st not in ("OFFLINE",) else "00:00")
        d = s.get("distanceCm")
        self.dist.setText("Chưa đo" if d is None or st in ("OFFLINE", "CALIBRATING") else f"{d:.0f} cm")

    @staticmethod
    def _calib_seconds(s):
        return (s.get("calib") or {}).get("seconds") or s.get("calibLeft") or 10

    def set_sync(self, info):
        self.conn.set_info(info)

    def show_notice(self, alert_type, title, body):
        self.banner.show_alert(alert_type, title, body)
