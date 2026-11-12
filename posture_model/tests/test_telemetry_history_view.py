"""Offscreen history/filter/export and session callback isolation."""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from outbox import Outbox
from telemetry_history import TelemetryHistory
from ui.telemetry_history import TelemetryHistoryDialog
from ui.controller import AppController
from ui.theme import apply_theme


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    with tempfile.TemporaryDirectory() as directory:
        auth = SimpleNamespace(base_url='http://one', user_id='owner')
        box = Outbox(str(Path(directory)/'box.db'))
        box.bind(auth.base_url, auth.user_id)
        for i in range(27):
            box.put('metric', str(i), dict(userId='owner'))
        box.mark_dead([('0', 'bad')])
        exports = []
        dialog = TelemetryHistoryDialog(TelemetryHistory(box.path), auth, lambda state: exports.append(state))
        dialog.show(); app.processEvents()
        assert dialog.table.rowCount() == 25 and dialog.next.isEnabled()
        dialog.next.click()
        assert dialog.table.rowCount() == 2 and dialog.previous.isEnabled()
        dialog.filter.setCurrentIndex(dialog.filter.findData('failed'))
        assert dialog.table.rowCount() == 1 and dialog.page == 0
        dialog.export.click()
        assert exports == ['failed']
        tasks = []
        controller = SimpleNamespace(auth=auth, _leaving=False, _telemetry_dialog=dialog, _track=lambda *args: tasks.append(args))
        target = str(Path(directory)/'export.json')
        with patch('ui.controller.QFileDialog.getSaveFileName', return_value=(target, 'JSON')):
            AppController._export_telemetry(controller, auth, 'failed')
        task, done, failed = tasks.pop()
        assert not dialog.export.isEnabled()
        done(task.fn())
        assert dialog.export.isEnabled() and '1 mục' in dialog.message.text()
        assert json.loads(Path(target).read_text(encoding='utf-8'))['total'] == 1
        controller.auth = object()
        dialog.message.setText('Phiên mới')
        failed(ValueError())
        assert dialog.message.text() == 'Phiên mới'
        if len(sys.argv) > 1:
            destination = Path(sys.argv[1]); destination.mkdir(exist_ok=True, parents=True)
            app.processEvents()
            assert dialog.grab().save(str(destination/'telemetry-history.png'))
        dialog.close()
        box.close()
    print('PASS: local telemetry pages, filters, export and session callback isolation')


if __name__ == '__main__':
    main()
