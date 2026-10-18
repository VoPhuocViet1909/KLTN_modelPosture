"""Màn đăng nhập: email, mật khẩu, "Ghi nhớ đăng nhập", "Dùng không đăng nhập". Lỗi nói rõ chuyện gì và cách xử lý."""
import urllib.parse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui.widgets import PlumbLine


class LoginView(QFrame):
    loginRequested = Signal(str, str, bool)      # email, mật khẩu, ghi nhớ
    localRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 20)
        lay.setSpacing(6)

        self.plumb = PlumbLine(84)
        self.plumb.set_state("GOOD")
        lay.addWidget(self.plumb, 0, Qt.AlignHCenter)
        title = QLabel("Đăng nhập")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        self.server = QLabel("")
        self.server.setObjectName("note")
        self.server.setAlignment(Qt.AlignCenter)
        self.server.setWordWrap(True)
        lay.addWidget(self.server)
        lay.addSpacing(10)

        lay.addWidget(self._label("Email"))
        self.email = QLineEdit()
        self.email.setPlaceholderText("ban@congty.vn")
        self.email.setAccessibleName("Email")
        lay.addWidget(self.email)
        lay.addSpacing(4)
        lay.addWidget(self._label("Mật khẩu"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setAccessibleName("Mật khẩu")
        lay.addWidget(self.password)
        lay.addSpacing(4)
        self.remember = QCheckBox("Ghi nhớ đăng nhập")
        self.remember.setChecked(True)
        lay.addWidget(self.remember)

        self.info = QLabel("")
        self.info.setObjectName("note")
        self.info.setWordWrap(True)
        self.info.hide()
        lay.addWidget(self.info)
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.setAccessibleName("Lỗi đăng nhập")
        self.error.hide()
        lay.addWidget(self.error)

        self.btn_login = QPushButton("Đăng nhập")
        self.btn_login.setObjectName("primary")
        self.btn_login.setDefault(True)
        self.btn_login.clicked.connect(self._submit)
        lay.addWidget(self.btn_login)
        self.btn_local = QPushButton("Dùng không đăng nhập")
        self.btn_local.setObjectName("link")
        self.btn_local.setToolTip("Chỉ nhắc tư thế tại chỗ, không gửi dữ liệu lên máy chủ")
        self.btn_local.clicked.connect(self.localRequested)
        lay.addWidget(self.btn_local, 0, Qt.AlignHCenter)
        lay.addStretch(1)

        self.email.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._submit)
        self.setTabOrder(self.email, self.password)
        self.setTabOrder(self.password, self.remember)
        self.setTabOrder(self.remember, self.btn_login)
        self.setTabOrder(self.btn_login, self.btn_local)

    @staticmethod
    def _label(text):
        lb = QLabel(text)
        lb.setObjectName("note")
        return lb

    def _submit(self):
        email, pw = self.email.text().strip(), self.password.text()
        self._mark_invalid(self.email, not email)
        self._mark_invalid(self.password, not pw)
        if not email or not pw:
            self.show_error("Nhập email và mật khẩu để đăng nhập.")
            (self.email if not email else self.password).setFocus()
            return
        self.show_error("")
        self.loginRequested.emit(email, pw, self.remember.isChecked())

    @staticmethod
    def _mark_invalid(edit, bad):
        edit.setProperty("invalid", bool(bad))
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    # ---------------------------------------------------------------- điều khiển từ controller
    def set_server(self, base_url):
        host = urllib.parse.urlsplit(base_url or "").netloc
        self.server.setText(f"Máy chủ: {host}" if host else "Chưa cấu hình địa chỉ máy chủ")

    def show_error(self, msg):
        self.error.setText(msg)
        self.error.setVisible(bool(msg))
        if msg:
            self.info.hide()

    def show_info(self, msg):
        """Thông báo trung tính (ví dụ 'Đã đăng xuất'), không tô màu lỗi."""
        self.info.setText(msg)
        self.info.setVisible(bool(msg))
        if msg:
            self.error.hide()

    def set_busy(self, busy, text="Đang đăng nhập…"):
        for w in (self.email, self.password, self.remember, self.btn_local):
            w.setEnabled(not busy)
        self.btn_login.setEnabled(not busy)
        self.btn_login.setText(text if busy else "Đăng nhập")

    def prefill(self, email):
        if email:
            self.email.setText(email)

    def reset(self):
        """Xóa mật khẩu khi quay về màn đăng nhập (không giữ mật khẩu trong widget)."""
        self.password.clear()
        self._mark_invalid(self.email, False)
        self._mark_invalid(self.password, False)
        self.set_busy(False)
        (self.password if self.email.text() else self.email).setFocus()
