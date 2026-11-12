"""Offscreen history controls and export owner guards; no network/cameras."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
from command_outbox import CommandOutbox
from ui.controller import AppController
from ui.progress_view import ProgressDialog
from ui.theme import apply_theme


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        queue = CommandOutbox(str(root / 'commands.db'))
        a = SimpleNamespace(user_id='a', base_url='http://one')
        b = SimpleNamespace(user_id='b', base_url='http://one')
        for i in range(27):
            queue.break_action(a, 'device-' + str(i), 'SKIP')
        queue.break_action(b, 'private-b', 'SKIP')
        syncs = []
        dialog = ProgressDialog(queue, a, 'device', lambda: syncs.append(True), export=lambda state: None)
        dialog.resize(420, 420)
        dialog.show()
        next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Xem lịch sử trên máy').click()
        app.processEvents()
        history = dialog.history
        assert history.isVisible() and history.table.rowCount() == 25
        assert not history.previous.isEnabled() and history.next.isEnabled()
        history.next.click()
        assert history.table.rowCount() == 2 and history.previous.isEnabled()
        history.table.selectRow(0)
        assert 'Mã thao tác:' in history.details.toPlainText() and 'private-b' not in history.details.toPlainText()
        history.filter.setCurrentIndex(history.filter.findData('failed'))
        assert history.table.rowCount() == 0 and 'Chưa có thao tác' in history.summary.text()
        assert history.page == 0 and not history.next.isEnabled()
        history.filter.setCurrentIndex(0)
        history.retry.click()
        assert syncs == [True]
        app.processEvents()
        assert dialog.findChild(QScrollArea).verticalScrollBar().maximum() > 0, 'Small window must scroll'
        assert dialog.width() <= 420
        if len(sys.argv) > 1:
            output = Path(sys.argv[1])
            output.mkdir(parents=True, exist_ok=True)
            for width, height in ((680, 780), (420, 420)):
                dialog.resize(width, height)
                dialog.findChild(QScrollArea).ensureWidgetVisible(history.table)
                app.processEvents()
                assert dialog.grab().save(str(output / f'history-{width}.png'))

        tasks = []
        controller = SimpleNamespace(auth=a, mode='session', _leaving=False, _progress_dialog=dialog,
                                     _progress_queue=lambda: queue, _track=lambda *args: tasks.append(args))
        target = root / 'history.json'
        with patch('ui.controller.QFileDialog.getSaveFileName', return_value=(str(target), 'JSON')):
            AppController._export_command_history(controller, a, None)
        assert len(tasks) == 1 and not history.export.isEnabled()
        task, done, failed = tasks.pop()
        done(task.fn())
        assert history.export.isEnabled() and '27 thao tác' in history.message.text()
        assert json.loads(target.read_text(encoding='utf-8'))['total'] == 27
        with patch('ui.controller.QFileDialog.getSaveFileName', return_value=(str(target), 'JSON')):
            AppController._export_command_history(controller, a, None)
        task, done, failed = tasks.pop()
        controller.auth = b
        history.message.setText('Phiên đã thay đổi')
        done(task.fn())
        assert history.message.text() == 'Phiên đã thay đổi'
        assert json.loads(target.read_text(encoding='utf-8'))['owner'] == 'a'
        controller.auth = a
        history.exporting(False)

        # A nested file chooser can dispatch logout/login before returning a path.
        def switch_owner(*args):
            controller.auth = b
            return str(root / 'should-not-exist.json'), 'JSON'
        with patch('ui.controller.QFileDialog.getSaveFileName', side_effect=switch_owner):
            AppController._export_command_history(controller, a, None)
        assert not tasks and not (root / 'should-not-exist.json').exists()
        controller.auth = a
        with patch('ui.controller.QFileDialog.getSaveFileName', return_value=('', 'JSON')):
            AppController._export_command_history(controller, a, None)
        assert not tasks
        with patch.object(queue, 'break_action', side_effect=sqlite3.OperationalError('simulated full disk')):
            dialog.act('START')
        assert 'Chưa lưu được thao tác' in dialog.status.text() and syncs == [True]
        with patch.object(queue, 'history', side_effect=sqlite3.OperationalError('locked')):
            history.refresh()
        assert history.table.rowCount() == 0 and 'Chưa đọc được' in history.summary.text()
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.shutdown()
    print('PASS: history pagination/filter/empty/details, narrow layout, retry, atomic export UI and logout guards')


if __name__ == '__main__':
    main()
