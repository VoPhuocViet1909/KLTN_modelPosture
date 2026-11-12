"""Source isolation, legacy recovery, queue retention and atomic history export."""
import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from outbox import Outbox, scoped_path
from telemetry_history import TelemetryHistory
from sender import Sender
from ui.controller import AppController
from PySide6.QtWidgets import QMessageBox


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('Expected scope rejection')


def main():
    with tempfile.TemporaryDirectory() as directory:
        auth = SimpleNamespace(base_url='https://a.test', user_id='owner')
        other = SimpleNamespace(base_url='https://b.test', user_id='owner')
        path = str(Path(directory)/'legacy.db')
        box = Outbox(path)
        for index in range(31):
            box.put('event', str(index), dict(userId='owner', eventType='SESSION_STARTED', api_token='NEVER_EXPORT'))
        rejects(lambda: box.bind(auth.base_url, auth.user_id))
        assert box.db.execute('SELECT COUNT(*) FROM outbox_context').fetchone()[0] == 0
        box.bind(auth.base_url, auth.user_id, allow_legacy=True)
        rejects(lambda: box.bind(other.base_url, other.user_id, allow_legacy=True))
        rejects(lambda: box.put('event', 'foreign', dict(userId='other')))
        assert scoped_path(directory, auth.base_url, auth.user_id) != scoped_path(directory, other.base_url, other.user_id)
        box.mark_sent(['0']); box.mark_dead([('1', 'NEVER_EXPORT')]); box.mark_failed(['2'], 'NEVER_EXPORT')
        history = TelemetryHistory(path)
        assert history.history(auth)['total'] == 31
        assert len(history.history(auth)['items']) == 25
        assert len(history.history(auth, page=1)['items']) == 6
        assert history.history(auth, 'pending')['total'] == 29
        assert history.history(auth, 'failed')['total'] == 1
        rejects(lambda: history.history(other))
        rejects(lambda: history.history(SimpleNamespace(base_url=auth.base_url, user_id='other')))
        target = str(Path(directory)/'history.json')
        assert history.export_history(auth, target) == 31
        text = Path(target).read_text(encoding='utf-8')
        assert 'NEVER_EXPORT' not in text
        assert {x['id'] for x in json.loads(text)['items']} == {str(i) for i in range(31)}
        rejects(lambda: history.export_history(auth, path))
        rejects(lambda: history.export_history(auth, path+'-wal'))
        original = Path(target).read_bytes()
        with patch('telemetry_history.os.replace', side_effect=OSError('full disk')):
            try:
                history.export_history(auth, target)
                raise AssertionError('Write failure ignored')
            except OSError:
                pass
        assert Path(target).read_bytes() == original
        assert not list(Path(directory).glob('.telemetry-*'))
        assert box.stats() == dict(pending=29, sent=1, dead=1)
        requests = []
        auth.open = lambda *args, **kwargs: requests.append(args)
        sender = Sender(box, auth.base_url, auth=auth, check_schema=False)
        auth.base_url = other.base_url
        assert not sender._send(box.due(now=10**15)[:1])
        assert not requests, 'Changing the server must never upload a bound queue elsewhere'
        auth.base_url = 'https://a.test'
        box.close()
        box = Outbox(path); box.bind(auth.base_url, auth.user_id)
        assert {i for i,k,p in box.due(now=10**15)} == {str(i) for i in range(2,31)}
        box.close()
        mixed = Outbox(str(Path(directory)/'mixed.db'))
        mixed.put('event', 'x', dict(userId='other'))
        rejects(lambda: mixed.bind(auth.base_url, auth.user_id, allow_legacy=True))
        assert mixed.db.execute('SELECT COUNT(*) FROM outbox_context').fetchone()[0] == 0
        mixed.close()
        # Test the GUI migration decision without displaying a blocking dialog.
        default = str(Path(directory)/'outbox.db')
        legacy = str(Path(directory)/'outbox-owner.db')
        old = Outbox(legacy)
        old.put('event', 'legacy-id', dict(userId='owner')); old.close()
        controller = SimpleNamespace(opts=SimpleNamespace(outbox=default), default_outbox=default, window=None)
        with patch('ui.controller.QMessageBox.question', return_value=QMessageBox.No):
            assert AppController._user_outbox(controller, auth) == scoped_path(directory, auth.base_url, auth.user_id)
        old = Outbox(legacy)
        assert old.db.execute('SELECT COUNT(*) FROM outbox_context').fetchone()[0] == 0
        old.close()
        with patch('ui.controller.QMessageBox.question', return_value=QMessageBox.Yes):
            assert AppController._user_outbox(controller, auth) == legacy
        old = Outbox(legacy); old.assert_context(auth.base_url, auth.user_id)
        assert old.due()[0][0] == 'legacy-id'; old.close()
        with patch('ui.controller.QMessageBox.question', side_effect=AssertionError('Wrong server must not be offered the old queue')):
            assert AppController._user_outbox(controller, other) == scoped_path(directory, other.base_url, other.user_id)
    print('PASS: owner/server isolation, explicit legacy binding, pagination, retention and atomic safe export')


if __name__ == '__main__':
    main()
