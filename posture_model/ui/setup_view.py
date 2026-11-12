"""Thiết lập cục bộ; ảnh kiểm tra chỉ ở RAM, không ghi hoặc gửi lên máy chủ."""
from urllib.parse import urlsplit

import cv2
from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

import iot_config
from iot_notifier import probe
from live_stream import validate_rtsp_base
from ui.bridge import Task
from ui.camera_view import _qimage
from ui.tokens import labels
from ui.widgets import ConnectionDot


def preferences():
    return QSettings("KLTN", "PostureMonitor")


def media_rtsp_base(settings, server, fallback='rtsp://127.0.0.1:8554'):
    if settings.value('media_server') == str(server or '').strip().rstrip('/'):
        return str(settings.value('media_rtsp_base', fallback))
    return fallback


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
    def __init__(self, side, front, server, parent=None, server_editable=True, iot=None):
        super().__init__(parent)
        self.iot = iot                  # IotNotifier đang chạy trong app (None khi mở lần đầu): lưu xong áp dụng ngay
        self.iot_task = None
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
        self.media_rtsp = QLineEdit(media_rtsp_base(preferences(), self.server.text()))
        self.media_rtsp.setAccessibleName('Địa chỉ máy chủ video RTSP')
        self.media_rtsp.setMinimumHeight(44)
        form.addRow('Máy chủ video', self.media_rtsp)
        self.server.textEdited.connect(lambda: self.media_rtsp.setText(media_rtsp_base(preferences(), self.server.text())))
        lay.addLayout(form)
        media_note = QLabel('Chỉ dùng khi bật chia sẻ camera. Cùng máy: rtsp://127.0.0.1:8554. '
                            'Khác máy: điền địa chỉ máy chủ video đã được quản trị viên cấu hình.')
        media_note.setWordWrap(True)
        media_note.setObjectName('note')
        lay.addWidget(media_note)
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
        lay.addWidget(self._iot_panel())
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

    # ---------------------------------------------------------------- thiết bị IoT
    def _iot_panel(self):
        t = labels()["iot"]
        cfg = iot_config.load()
        card = QFrame()
        card.setObjectName("panel")
        lay = QVBoxLayout(card)
        heading = QLabel(t["title"])
        heading.setObjectName("sectionTitle")
        lay.addWidget(heading)
        note = QLabel(t["note"])
        note.setObjectName("note")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.iot_enabled = QCheckBox(t["enable"])
        self.iot_enabled.setChecked(cfg["enabled"])
        lay.addWidget(self.iot_enabled)
        form = QFormLayout()
        self.iot_url = QLineEdit(cfg["url"])
        self.iot_url.setAccessibleName(t["url"])
        self.iot_key = QLineEdit(cfg["key"])
        self.iot_key.setEchoMode(QLineEdit.Password)
        self.iot_key.setAccessibleName(t["key"])
        self.iot_key.setPlaceholderText(t["key_hint"])
        form.addRow(t["url"], self.iot_url)
        form.addRow(t["key"], self.iot_key)
        lay.addLayout(form)
        self.iot_mute = QCheckBox(t["mute_pc"])
        self.iot_mute.setChecked(cfg["mute_pc_beep"])
        lay.addWidget(self.iot_mute)
        row = QHBoxLayout()
        self.iot_test = QPushButton(t["test"])
        self.iot_test.clicked.connect(lambda: self.iot_probe(True))
        self.iot_dot = ConnectionDot()
        row.addWidget(self.iot_test)
        row.addWidget(self.iot_dot, 1)
        lay.addLayout(row)
        self.iot_dot.dot.setPixmap(ConnectionDot._dot("lost"))
        self.iot_dot.text.setText(t["idle"])
        self.iot_dot.text.setWordWrap(True)
        for w in (self.iot_url, self.iot_key):
            w.textChanged.connect(self.iot_reset_status)
        if cfg["enabled"]:
            self.iot_probe(False)
        return card

    def iot_values(self):
        url = self.iot_url.text().strip()
        norm = iot_config.normalize_url(url) if url else iot_config.DEFAULTS["url"]
        if norm is None:
            raise ValueError(labels()["iot"]["bad_url"])
        cfg = iot_config.load()                      # giữ timeout, chu kỳ... người dùng đã sửa tay trong file
        cfg.update(enabled=self.iot_enabled.isChecked(), url=norm, key=self.iot_key.text().strip(),
                   mute_pc_beep=self.iot_mute.isChecked())
        return cfg

    def iot_reset_status(self):
        if self.iot_task is None or not self.iot_task.isRunning():
            self.iot_dot.dot.setPixmap(ConnectionDot._dot("lost"))
            self.iot_dot.text.setText(labels()["iot"]["idle"])

    def iot_probe(self, test):
        """Kiểm tra thiết bị (và phát âm thử nếu test) ở luồng nền; kết quả chỉ hiện ở dòng trạng thái, không bật hộp thoại."""
        if self.iot_task is not None and self.iot_task.isRunning():
            return
        try:
            cfg = self.iot_values()
        except ValueError as e:
            self.iot_dot.text.setText(str(e))
            return
        self.iot_test.setEnabled(False)
        self.iot_test.setText(labels()["iot"]["testing"])
        self.iot_task = Task(lambda: probe(cfg["url"], cfg["key"], test=test), self)
        self.iot_task.done.connect(self.iot_show)
        self.iot_task.finished.connect(self.iot_probe_finished)
        self.iot_task.start()

    @Slot(object)
    def iot_show(self, r):
        t = labels()["iot"]
        if r["ok"]:
            info = r["info"]
            detail = t["info"].format(fw="v" + str(info.get("fw", "?")), rssi=info.get("rssi", "?"))
            text = f"{t['tested'] if r['tested'] else t['connected']} · {detail}"
        else:
            text = t["bad_key"] if r["error"] == "BAD_KEY" else t["unreachable"]
        self.iot_dot.dot.setPixmap(ConnectionDot._dot("ok" if r["ok"] else "lost"))
        self.iot_dot.text.setText(text)

    @Slot()
    def iot_probe_finished(self):
        self.iot_test.setEnabled(True)
        self.iot_test.setText(labels()["iot"]["test"])

    def _busy(self):
        return any(t is not None and t.isRunning() for t in (self.task, self.iot_task))

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
            rtsp = validate_rtsp_base(self.media_rtsp.text().strip())
        except ValueError as e:
            self.error.setText(str(e))
            return
        try:
            iot_cfg = self.iot_values()
        except ValueError as e:
            self.error.setText(str(e))
            return
        settings = preferences()
        for key, value in zip(("side", "front", "server"), values):
            settings.setValue(key, value)
        settings.setValue('media_server', values[2])
        settings.setValue('media_rtsp_base', rtsp)
        settings.setValue("configured", True)
        settings.sync()
        if settings.status() != QSettings.NoError:
            self.error.setText("Không lưu được thiết lập. Kiểm tra quyền ghi của tài khoản Windows rồi thử lại.")
            return
        if not iot_config.save(iot_cfg):
            self.error.setText(labels()["iot"]["save_failed"])
            return
        if self.iot is not None:
            self.iot.apply(iot_cfg)                  # áp dụng ngay, không cần khởi động lại
        self.result_values = values
        self.accept()

    def reject(self):
        if not self._busy():
            super().reject()

    def closeEvent(self, event):
        if self._busy():
            event.ignore()
        else:
            super().closeEvent(event)
