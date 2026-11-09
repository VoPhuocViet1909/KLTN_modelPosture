"""Offscreen controls, no network or cameras."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from command_outbox import CommandOutbox
from ui.progress_view import ProgressDialog


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        queue = CommandOutbox(str(Path(directory) / 'commands.db'))
        auth = SimpleNamespace(user_id='owner', base_url='http://localhost:8080')
        ref = dict(deviceId='device', sessionId='session', alertType='NECK_TRUNK', startedAt='2026-11-10T00:00:00Z')
        queue.remember_episode(auth, dict(eventType='ALERT_STARTED', **ref))
        synced = []
        dialog = ProgressDialog(queue, auth, 'device', lambda: synced.append(True))
        assert dialog.buttons['START'].isEnabled() and not dialog.buttons['COMPLETE'].isEnabled()
        dialog.act('START')
        assert dialog.buttons['COMPLETE'].isEnabled() and not dialog.buttons['START'].isEnabled()
        dialog.act('COMPLETE')
        dialog.reason.setCurrentIndex(dialog.reason.findData('OTHER'))
        dialog.feedback()
        assert queue.stats(auth)['pending'] == 2, 'OTHER requires a note before enqueue'
        dialog.note.setText('Camera moved')
        dialog.feedback()
        assert queue.stats(auth)['pending'] == 3 and len(synced) == 3
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print('PASS: rest states, durable enqueue, feedback validation and sync trigger (offscreen only)')


if __name__ == '__main__':
    main()
