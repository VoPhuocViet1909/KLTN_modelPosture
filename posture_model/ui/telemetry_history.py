"""Local telemetry summaries; no network calls and no payload editing."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
from datetime import datetime, timezone, timedelta
import sqlite3

STATE = {'pending': 'Chờ gửi', 'sent': 'Đã gửi', 'failed': 'Bị từ chối'}


class TelemetryHistoryDialog(QDialog):
    def __init__(self, history, auth, export, parent=None):
        super().__init__(parent)
        self.history, self.auth, self.page = history, auth, 0
        self.setWindowTitle('Dữ liệu trên máy')
        self.resize(740, 500)
        layout = QVBoxLayout(self)
        note = QLabel('Sự kiện và số liệu của tài khoản tại máy chủ này. Dữ liệu đã gửi có thể được dọn sau 7 ngày. File xuất chứa tóm tắt toàn bộ kết quả theo bộ lọc, không chứa nội dung gốc.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.filter = QComboBox()
        self.filter.setAccessibleName('Lọc trạng thái dữ liệu')
        self.filter.addItem('Tất cả trạng thái', None)
        for key, label in STATE.items():
            self.filter.addItem(label, key)
        layout.addWidget(self.filter)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Lưu lúc (giờ Việt Nam)', 'Loại', 'Trạng thái', 'Số lần thử lỗi'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.previous, self.next = QPushButton('Trang trước'), QPushButton('Trang sau')
        reload = QPushButton('Tải lại')
        self.export = QPushButton('Xuất tóm tắt JSON')
        for button in (self.previous, self.next, reload, self.export):
            button.setMinimumHeight(44)
            row.addWidget(button)
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        self.filter.currentIndexChanged.connect(self.reset)
        reload.clicked.connect(self.refresh)
        self.export.clicked.connect(lambda: export(self.filter.currentData()))
        self.refresh()

    def reset(self):
        self.page = 0
        self.refresh()

    def move(self, offset):
        self.page = max(0, self.page + offset)
        self.refresh()

    def refresh(self):
        try:
            data = self.history.history(self.auth, self.filter.currentData(), self.page)
            if self.page and self.page * data['size'] >= data['total']:
                self.page = max(0, (data['total'] - 1) // data['size'])
                data = self.history.history(self.auth, self.filter.currentData(), self.page)
            self.table.setRowCount(len(data['items']))
            for row, item in enumerate(data['items']):
                when = datetime.fromisoformat(item['createdAt']).astimezone(timezone(timedelta(hours=7))).strftime('%d/%m/%Y %H:%M:%S')
                for col, value in enumerate((when, 'Sự kiện' if item['kind'] == 'event' else 'Số liệu', STATE[item['state']], str(item['attempts']))):
                    cell = QTableWidgetItem(value)
                    cell.setToolTip('Mã dữ liệu: ' + item['id'])
                    self.table.setItem(row, col, cell)
            self.table.resizeColumnsToContents()
            self.summary.setText(f"Trang {self.page + 1} · {data['total']} mục." if data['total'] else 'Chưa có dữ liệu trong bộ lọc này.')
            self.previous.setEnabled(self.page > 0)
            self.next.setEnabled((self.page + 1) * data['size'] < data['total'])
        except (OSError, ValueError, sqlite3.Error):
            self.table.setRowCount(0)
            self.previous.setEnabled(False)
            self.next.setEnabled(False)
            self.summary.setText('Chưa đọc được dữ liệu của phiên này. Đợi phiên theo dõi khởi động rồi tải lại.')

    def exporting(self, busy, message):
        self.export.setEnabled(not busy)
        self.message.setText(message)
