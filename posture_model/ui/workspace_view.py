"""Choose a server workspace explicitly before restarting camera calibration."""
import json
import platform
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class WorkspaceDialog(QDialog):
    def __init__(self, device_id, selected, apply, reload, parent=None):
        super().__init__(parent)
        self.device_id, self.current, self.loaded, self.pending = device_id, None, False, None
        self.new_key = str(uuid.uuid4())
        self.setWindowTitle('Vị trí làm việc')
        self.resize(500, 360)
        layout = QVBoxLayout(self)
        label = QLabel('Máy này: ' + device_id + '\nVị trí đang dùng: ' + selected['name'])
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        note = QLabel('Chọn hồ sơ đã tạo trên web. Áp dụng sẽ dừng phiên/chia sẻ camera hiện tại, giữ dữ liệu chờ gửi và mở phiên mới để hiệu chỉnh lại. Baseline cũ chỉ lưu đối chiếu, không tự dùng lại.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.choice = QComboBox()
        self.choice.setAccessibleName('Vị trí của máy này')
        self.choice.setMinimumHeight(44)
        layout.addWidget(self.choice)
        self.message = QLabel('Đang lấy hồ sơ trên server…')
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.reload = QPushButton('Tải lại hồ sơ')
        self.apply = QPushButton('Áp dụng và hiệu chỉnh lại')
        self.reload.clicked.connect(reload)
        self.apply.clicked.connect(apply)
        self.apply.setEnabled(False)
        for button in (self.reload, self.apply):
            button.setMinimumHeight(44)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.choice.currentIndexChanged.connect(lambda: setattr(self, 'pending', None))

    def set_data(self, data):
        self.current = data['device']
        self.choice.clear()
        self.choice.addItem('Chưa gán vị trí', None)
        for workspace in data['workspaces']:
            if workspace.get('status') == 'ACTIVE':
                self.choice.addItem(workspace['name'], workspace['workspaceId'])
        selected = self.current.get('workspaceId') if self.current else None
        index = self.choice.findData(selected)
        self.choice.setCurrentIndex(max(0, index))
        self.loaded = True
        archived = self.current is not None and self.current.get('status') != 'ACTIVE'
        self.apply.setEnabled(not archived)
        self.reload.setEnabled(True)
        self.message.setText('Thiết bị đã lưu trữ; mở web để kích hoạt lại.' if archived else 'Chưa đăng ký máy này; Áp dụng sẽ đăng ký đúng mã máy ở trên.' if self.current is None else 'Hồ sơ server đã tải. Nhấn Áp dụng để xác nhận và đo lại.')
        self.pending = None

    def payload(self):
        if not self.loaded:
            raise ValueError('Workspace choices unavailable')
        current = self.current or {}
        body = dict(expectedVersion=current.get('version', 0), deviceId=self.device_id,
                    name=current.get('name', (platform.node() or 'Máy tính')[:80]), workspaceId=self.choice.currentData(), status='ACTIVE')
        signature = json.dumps(body, sort_keys=True)
        if self.pending is None or self.pending[0] != signature:
            self.pending = signature, str(uuid.uuid4())
        return current.get('deviceKey', self.new_key), dict(body, operationId=self.pending[1])

    def working(self, busy, message):
        self.choice.setEnabled(not busy)
        self.reload.setEnabled(not busy)
        self.apply.setEnabled(not busy and self.loaded and (self.current is None or self.current.get('status') == 'ACTIVE'))
        self.message.setText(message)
