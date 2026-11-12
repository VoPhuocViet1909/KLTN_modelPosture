"""Read-only local command history; all reads use the dialog's authenticated owner/server."""
import sqlite3
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

STATE = {'pending': 'Chờ gửi', 'sent': 'Đã gửi', 'failed': 'Bị từ chối', 'cancelled': 'Đã bỏ sau đối soát'}
ACTION = {'START': 'Bắt đầu nghỉ', 'SNOOZE': 'Hoãn nghỉ', 'SKIP': 'Bỏ qua', 'COMPLETE': 'Hoàn thành nghỉ', 'CANCEL': 'Hủy nghỉ'}


class CommandHistory(QWidget):
    def __init__(self, queue, auth, export, retry, parent=None):
        super().__init__(parent)
        self.queue, self.auth, self.page, self.items = queue, auth, 0, []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel('Lịch sử nghỉ và phản hồi của tài khoản tại máy chủ này. Xuất toàn bộ kết quả theo bộ lọc, kể cả các trang khác. Thời gian của dữ liệu cũ có thể chưa được ghi nhận.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.setAccessibleName('Lọc trạng thái lịch sử')
        self.filter.addItem('Tất cả trạng thái', None)
        for value, label in STATE.items():
            self.filter.addItem(label, value)
        row.addWidget(QLabel('Trạng thái'))
        row.addWidget(self.filter, 1)
        layout.addLayout(row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Lưu trên máy lúc (giờ Việt Nam)', 'Thao tác', 'Trạng thái'])
        self.table.setAccessibleName('Lịch sử nghỉ và phản hồi trên máy')
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setMinimumHeight(180)
        self.table.setMaximumHeight(260)
        self.table.itemSelectionChanged.connect(self.selected)
        layout.addWidget(self.table)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        pages = QHBoxLayout()
        self.previous, self.next = QPushButton('Trang trước'), QPushButton('Trang sau')
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        pages.addWidget(self.previous)
        pages.addWidget(self.next)
        layout.addLayout(pages)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName('Chi tiết thao tác đã chọn')
        self.details.setMaximumHeight(140)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        reload = QPushButton('Tải lại lịch sử')
        reload.clicked.connect(self.refresh)
        self.retry = QPushButton('Thử gửi lệnh chờ')
        self.retry.clicked.connect(retry)
        self.export = QPushButton('Xuất lịch sử JSON')
        self.export.clicked.connect(lambda: export(self.filter.currentData()))
        for button in (reload, self.retry):
            actions.addWidget(button)
        layout.addLayout(actions)
        layout.addWidget(self.export)
        self.message = QLabel()
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        for control in (self.filter, self.previous, self.next, reload, self.retry, self.export):
            control.setMinimumHeight(44)
        self.filter.currentIndexChanged.connect(self.reset)
        self.refresh()

    def reset(self):
        self.page = 0
        self.refresh()

    def move(self, offset):
        self.page = max(0, self.page + offset)
        self.refresh()

    def refresh(self):
        try:
            data = self.queue.history(self.auth, self.filter.currentData(), self.page)
            if self.page and self.page * data['size'] >= data['total']:
                self.page = max(0, (data['total'] - 1) // data['size'])
                data = self.queue.history(self.auth, self.filter.currentData(), self.page)
            self.items = data['items']
            self.table.clearContents()
            self.table.setRowCount(len(self.items))
            self.details.clear()
            for index, item in enumerate(self.items):
                at = item['createdAt']
                when = datetime.fromisoformat(at).astimezone(timezone(timedelta(hours=7))).strftime('%d/%m/%Y %H:%M:%S') if at else 'Chưa rõ (dữ liệu cũ)'
                action = ACTION.get(item['body'].get('action'), 'Phản hồi cảnh báo' if item['resource'].startswith('feedback/') else 'Thao tác nghỉ')
                for column, value in enumerate((when, action, STATE[item['state']])):
                    self.table.setItem(index, column, QTableWidgetItem(value))
            self.summary.setText(f"Trang {self.page + 1} · {data['total']} thao tác." if data['total'] else 'Chưa có thao tác trong bộ lọc này. Ghi nhận nghỉ hoặc phản hồi để xem tại đây.')
            self.previous.setEnabled(self.page > 0)
            self.next.setEnabled((self.page + 1) * data['size'] < data['total'])
            self.retry.setEnabled(bool(self.queue.stats(self.auth).get('pending')))
        except (OSError, ValueError, sqlite3.Error):
            self.items = []
            self.table.setRowCount(0)
            self.details.clear()
            self.previous.setEnabled(False)
            self.next.setEnabled(False)
            self.summary.setText('Chưa đọc được lịch sử. Kiểm tra quyền ghi/đọc trên máy rồi thử tải lại.')

    def selected(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.items):
            item = self.items[index]
            body = item['body']
            ref = body.get('episodeRef', {})
            details = [f"Mã thao tác: {item['operationId']}", f"Thiết bị: {body.get('deviceId', ref.get('deviceId', ''))}"]
            if ref:
                details.extend([f"Cảnh báo: {ref.get('alertType', '')}", f"Cảnh báo bắt đầu: {ref.get('startedAt', '')}",
                                f"Ghi chú: {body.get('note') or 'Không có'}"])
            if item['error']:
                details.append('Máy chủ từ chối (HTTP ' + item['error'] + '). Xem lại trạng thái trước khi đối soát.')
            self.details.setPlainText('\n'.join(details))

    def exporting(self, busy, message=''):
        self.export.setEnabled(not busy)
        self.export.setText('Đang xuất…' if busy else 'Xuất lịch sử JSON')
        self.message.setText(message)
