"""Thiết lập cục bộ; ảnh kiểm tra chỉ ở RAM, không ghi hoặc gửi lên máy chủ."""
from urllib.parse import urlsplit

import cv2
from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ui.bridge import Task
from ui.camera_view import _qimage


def preferences():
    return QSettings("KLTN", "PostureMonitor")


def validate(side, front, server):
    def camera(value, optional=False):
        if optional and value == "-1":
            return
        if not value.isdecimal() or not 0 <= int(value) <= 99:
            raise ValueError("Chọn số camera từ 0 đến 99; camera trước có thể tắt.")
    camera(side)
    camera(front, True)
    if front != "-1" and int(side) == int(front):
        raise ValueError("Camera hông và camera trước phải là hai thiết bị khác nhau.")
    try:
        u = urlsplit(server)
        u.port  # Kiểm cổng sai khi đọc thuộc tính này.
        if (u.scheme not in ("http", "https") or not u.hostname or u.username or u.password
                or u.path not in ("", "/") or u.query or u.fragment or any(c.isspace() for c in server)):
            raise ValueError()
    except ValueError:
        raise ValueError("Nhập địa chỉ máy chủ như http://127.0.0.1:8080, không kèm tài khoản hay đường dẫn.") from None
    return side, front, server.rstrip("/")


def snapshots(side, front, capture=None):
    # ponytail: ảnh kiểm tra webcam; thêm preview liên tục/IP khi có yêu cầu camera mạng.
    capture = capture or cv2.VideoCapture
    images = []
    for source in (side, front):
        if source == "-1":
            images.append(None)
            continue
        cap = capture(int(source))
        try:
            ok, frame = cap.read() if cap.isOpened() else (False, None)
            if not ok or frame is None:
                raise ValueError(f"Không đọc được camera {source}. Kiểm tra kết nối, quyền camera hoặc thử số khác.")
            images.append(_qimage(frame))
        finally:
            cap.release()
    return images


class SetupDialog(QDialog):
    def __init__(self, side, front, server, parent=None, server_editable=True):
        super().__init__(parent)
        self.setWindowTitle("Thiết lập Posture Monitor")
        self.setMinimumWidth(580)
        self.resize(640, 680)
        self.task = None
        self.server_editable = server_editable
        self.result_values = None
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("root")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        title = QLabel("Thiết lập camera")
        title.setObjectName("pageTitle")
        lay.addWidget(title)
        note = QLabel("Chọn hai thiết bị khác nhau rồi bấm Kiểm tra hình. "
                      "Số camera phụ thuộc máy của bạn; nếu sai góc nhìn, thử đổi số thiết bị.")
        note.setObjectName("note")
        note.setWordWrap(True)
        lay.addWidget(note)
        form = QFormLayout()
        self.side, self.front = QComboBox(), QComboBox()
        for combo in (self.side, self.front):
            combo.setEditable(True)
            combo.addItems([str(i) for i in range(6)])
        self.front.addItem("Không dùng camera trước")
        self.side.setCurrentText(side)
        self.front.setCurrentText("Không dùng camera trước" if front == "-1" else front)
        self.side.setAccessibleName("Số camera hông")
        self.front.setAccessibleName("Camera trước, có thể chọn không dùng")
        form.addRow("Camera hông", self.side)
        form.addRow("Camera trước", self.front)
        self.server = QLineEdit(server or "http://127.0.0.1:8080")
        self.server.setAccessibleName("Địa chỉ máy chủ")
        self.server.setEnabled(server_editable)
        if not server_editable:
            self.server.setToolTip("Đăng xuất trước khi đổi máy chủ.")
        form.addRow("Máy chủ", self.server)
        lay.addLayout(form)
        previews = QHBoxLayout()
        self.images = []
        for text, hint in (("Camera hông", "Đặt ngang người khoảng 90°, thấy tai–vai–hông."),
                           ("Camera trước", "Nhìn thẳng mặt và hai vai. Có thể không dùng.")):
            card = QFrame()
            card.setObjectName("panel")
            card_layout = QVBoxLayout(card)
            heading = QLabel(text)
            heading.setObjectName("sectionTitle")
            card_layout.addWidget(heading)
            image = QLabel("Chưa có ảnh kiểm tra")
            image.setAccessibleName(text)
            image.setObjectName("preview")
            image.setMinimumSize(200, 144)
            image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            image.setAlignment(Qt.AlignCenter)
            image.setWordWrap(True)
            card_layout.addWidget(image, 1)
            guidance = QLabel(hint)
            guidance.setObjectName("note")
            guidance.setWordWrap(True)
            card_layout.addWidget(guidance)
            previews.addWidget(card, 1)
            self.images.append(image)
        lay.addLayout(previews)
        caption = QLabel("Ảnh chụp kiểm tra, không phải video trực tiếp. Không lưu hoặc gửi ảnh.")
        caption.setObjectName("note")
        caption.setWordWrap(True)
        lay.addWidget(caption)
        next_step = QLabel("Tiếp theo: ngồi thẳng, giữ yên để hiệu chỉnh. Nếu không dùng camera trước, "
                           "ứng dụng sẽ không đo lệch vai và khoảng cách mắt–màn hình.")
        next_step.setWordWrap(True)
        next_step.setObjectName("note")
        lay.addWidget(next_step)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        self.check = QPushButton("Kiểm tra hình")
        self.check.clicked.connect(self.preview)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Lưu và tiếp tục")
        self.buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(self.check)
        actions.addStretch(1)
        actions.addWidget(self.buttons)
        outer.addLayout(actions)
        for combo in (self.side, self.front):
            combo.currentTextChanged.connect(self.clear_images)

    def values(self):
        front = self.front.currentText().strip()
        return validate(self.side.currentText().strip(), "-1" if front == "Không dùng camera trước" else front,
                        self.server.text().strip())

    def clear_images(self):
        for image in self.images:
            image.setText("Chưa có ảnh kiểm tra")
        self.error.clear()

    def preview(self):
        if self.task is not None and self.task.isRunning():
            return
        try:
            side, front, _ = self.values()
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.clear_images()
        self.check.setText("Đang kiểm tra…")
        for w in (self.side, self.front, self.server, self.check, self.buttons):
            w.setEnabled(False)
        self.task = Task(lambda: snapshots(side, front), self)
        self.task.done.connect(self.show_images)
        self.task.failed.connect(self.show_error)
        self.task.finished.connect(self.preview_finished)
        self.task.start()

    @Slot(object)
    def show_images(self, images):
        for label, image in zip(self.images, images):
            if image is None:
                label.setText("Camera trước đã tắt")
            else:
                label.setPixmap(QPixmap.fromImage(image).scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @Slot(object)
    def show_error(self, error):
        self.error.setText(str(error))

    @Slot()
    def preview_finished(self):
        for w in (self.side, self.front, self.check, self.buttons):
            w.setEnabled(True)
        self.server.setEnabled(self.server_editable)
        self.check.setText("Kiểm tra hình")

    def save(self):
        try:
            values = self.values()
        except ValueError as e:
            self.error.setText(str(e))
            return
        settings = preferences()
        for key, value in zip(("side", "front", "server"), values):
            settings.setValue(key, value)
        settings.setValue("configured", True)
        settings.sync()
        if settings.status() != QSettings.NoError:
            self.error.setText("Không lưu được thiết lập. Kiểm tra quyền ghi của tài khoản Windows rồi thử lại.")
            return
        self.result_values = values
        self.accept()

    def reject(self):
        if self.task is None or not self.task.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.task is not None and self.task.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
