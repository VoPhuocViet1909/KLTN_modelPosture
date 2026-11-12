"""Personal rest/feedback controls. Disk enqueue happens before any network work."""
import sqlite3
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QMessageBox, QScrollArea, QWidget
from PySide6.QtCore import Qt


class ProgressDialog(QDialog):
    def __init__(self, queue, auth, device, sync, parent=None, resolve=None, export=None):
        super().__init__(parent)
        self.queue, self.auth, self.device, self.sync = queue, auth, device, sync
        self.setWindowTitle('Nghỉ và phản hồi')
        self.setMinimumWidth(400)
        self.resize(680, 780)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        device_label = QLabel('Thiết bị: ' + device)
        device_label.setTextFormat(Qt.PlainText)
        device_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        device_label.setWordWrap(True)
        layout.addWidget(device_label)
        self.goals = QLabel('Mục tiêu: đang lấy từ máy chủ…')
        self.goals.setWordWrap(True)
        layout.addWidget(self.goals)
        note = QLabel('Nghỉ do bạn tự xác nhận. Khi mất mạng, thao tác được giữ trên máy và gửi bù khi đăng nhập cùng tài khoản.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.buttons = {}
        for actions in [[('START', 'Bắt đầu nghỉ'), ('SNOOZE', 'Hoãn 5 phút'), ('SKIP', 'Bỏ qua')], [('COMPLETE', 'Hoàn thành nghỉ'), ('CANCEL', 'Hủy lần nghỉ')]]:
            row = QHBoxLayout()
            for action, text in actions:
                button = QPushButton(text)
                button.setMinimumHeight(44)
                button.clicked.connect(lambda checked=False, a=action: self.act(a))
                self.buttons[action] = button
                row.addWidget(button)
            layout.addLayout(row)
        form = QFormLayout()
        self.episode = QComboBox()
        self.episode.setAccessibleName('Cảnh báo cần phản hồi')
        episodes = queue.resources(auth, 'episode/')[:100]
        for ref in episodes:
            self.episode.addItem(f"{ref['alertType']} · {ref['startedAt']}", ref)
        self.rating = QComboBox()
        for text, code in [('Phù hợp', 'CORRECT'), ('Chưa phù hợp', 'NOT_APPROPRIATE'), ('Chưa chắc', 'UNSURE')]:
            self.rating.addItem(text, code)
        self.reason = QComboBox()
        for text, code in [('Không có', 'NONE'), ('Camera dịch chuyển', 'CAMERA_MOVED'), ('Đang với lấy đồ', 'REACHING'), ('Không có người', 'NO_PERSON'), ('Khác', 'OTHER')]:
            self.reason.addItem(text, code)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        for label, widget in [('Cảnh báo', self.episode), ('Đánh giá', self.rating), ('Lý do', self.reason), ('Ghi chú', self.note)]:
            widget.setMinimumHeight(44)
            form.addRow(label, widget)
        layout.addLayout(form)
        feedback = QPushButton('Lưu phản hồi')
        feedback.setMinimumHeight(44)
        feedback.setEnabled(bool(episodes))
        feedback.clicked.connect(self.feedback)
        layout.addWidget(feedback)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.recover = QPushButton('Bỏ thao tác bị từ chối và tải lại')
        self.recover.clicked.connect(lambda: resolve() if resolve and QMessageBox.question(self, 'Xử lý xung đột', 'Bỏ các thao tác chưa gửi thuộc chuỗi đã bị từ chối và lấy lại trạng thái từ máy chủ? Các thao tác đã được máy chủ nhận vẫn giữ nguyên.') == QMessageBox.Yes else None)
        layout.addWidget(self.recover)
        history_button = QPushButton('Xem lịch sử trên máy')
        history_button.setCheckable(True)
        history_button.setMinimumHeight(44)
        layout.addWidget(history_button)
        from ui.command_history import CommandHistory
        self.history = CommandHistory(queue, auth, export or (lambda state: None), sync, content)
        self.history.export.setEnabled(export is not None)
        self.history.setVisible(False)
        history_button.toggled.connect(self.history.setVisible)
        history_button.toggled.connect(lambda shown: self.history.refresh() if shown else None)
        layout.addWidget(self.history)
        close = QPushButton('Đóng')
        close.clicked.connect(self.close)
        close.setMinimumHeight(44)
        outer.addWidget(close)
        self.refresh()

    def refresh(self):
        active = next((b for b in self.queue.resources(self.auth, 'break/') if b['deviceId'] == self.device and b['state'] in ('SNOOZED', 'IN_PROGRESS')), None)
        state = active['state'] if active else 'NONE'
        self.state.setText({'NONE': 'Chưa có lần nghỉ đang diễn ra.', 'SNOOZED': 'Đã hoãn nhắc nghỉ 5 phút.', 'IN_PROGRESS': 'Bạn đang nghỉ. Bấm hoàn thành khi quay lại.'}[state])
        for action, button in self.buttons.items():
            button.setEnabled(action in (('COMPLETE', 'CANCEL') if state == 'IN_PROGRESS' else ('START', 'SNOOZE', 'SKIP')))
        counts = self.queue.stats(self.auth)
        self.recover.setEnabled(bool(counts.get('failed')))
        self.status.setText(f"Chờ gửi: {counts.get('pending', 0)} · Đã gửi: {counts.get('sent', 0)} · Cần xử lý: {counts.get('failed', 0)}" + ('\nCó thao tác bị từ chối; xem lại lịch sử trên web trước khi thao tác tiếp.' if counts.get('failed', 0) else ''))
        if self.history.isVisible():
            self.history.refresh()

    def act(self, action):
        try:
            self.queue.break_action(self.auth, self.device, action)
            self.refresh()
            self.sync()
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
        except sqlite3.Error:
            self.status.setText('Chưa lưu được thao tác. Kiểm tra dung lượng trống và quyền ghi rồi thử lại.')

    def feedback(self):
        if self.reason.currentData() == 'OTHER' and not self.note.text().strip():
            self.status.setText('Nhập ghi chú khi chọn lý do Khác.')
            return
        try:
            self.queue.feedback(self.auth, self.episode.currentData(), self.rating.currentData(), self.reason.currentData(), self.note.text())
            self.refresh()
            self.sync()
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
        except sqlite3.Error:
            self.status.setText('Chưa lưu được phản hồi. Kiểm tra dung lượng trống và quyền ghi rồi thử lại.')
