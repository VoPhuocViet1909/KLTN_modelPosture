"""Local SQLite history: owner/server scope, legacy upgrade, paging and atomic export."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_outbox import CommandOutbox


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / 'commands.db'
        # A database created by M1, before history timestamps existed.
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE commands(seq INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT UNIQUE NOT NULL, server TEXT NOT NULL, owner TEXT NOT NULL, resource TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', error TEXT, receipt TEXT)")
            db.execute('INSERT INTO commands(operation,server,owner,resource,method,path,body) VALUES (?,?,?,?,?,?,?)',
                       ('old-operation', 'http://one', 'a', 'break/old', 'POST', '/old', '{}'))
        queue = CommandOutbox(str(path))
        a = SimpleNamespace(user_id='a', base_url='http://one', access_token='must-not-export')
        b = SimpleNamespace(user_id='b', base_url='http://one')
        other = SimpleNamespace(user_id='a', base_url='http://two')
        old = queue.history(a)['items'][0]
        assert old['createdAt'] is None and old['operationId'] == 'old-operation'
        CommandOutbox(str(path))  # The upgrade is idempotent.
        for i in range(31):
            queue.break_action(a, 'device-' + str(i), 'SKIP')
        queue.break_action(b, 'private-b', 'SKIP')
        queue.break_action(other, 'private-other-server', 'SKIP')
        with queue.db() as db:
            db.execute("UPDATE commands SET state='failed',error='409' WHERE operation='old-operation'")
        first = queue.history(a)
        second = queue.history(a, page=1)
        assert first['total'] == 32 and len(first['items']) == 25 and len(second['items']) == 7
        assert not ({i['operationId'] for i in first['items']} & {i['operationId'] for i in second['items']})
        assert all(i['createdAt'] for i in first['items'])
        assert queue.history(a, 'failed')['items'][0]['error'] == '409'
        assert queue.history(b)['total'] == queue.history(other)['total'] == 1
        for kwargs in (dict(state='invalid'), dict(page=-1), dict(size=101), dict(page=True)):
            try:
                queue.history(a, **kwargs)
                raise AssertionError('Invalid filter accepted')
            except ValueError:
                pass
        target = root / 'history.json'
        assert queue.export_history(a, target) == 32
        exported = json.loads(target.read_text(encoding='utf-8'))
        assert exported['owner'] == 'a' and exported['server'] == 'http://one'
        assert len(exported['commands']) == exported['total'] == 32
        assert 'private-b' not in target.read_text(encoding='utf-8')
        assert 'private-other-server' not in target.read_text(encoding='utf-8')
        assert 'must-not-export' not in target.read_text(encoding='utf-8')
        assert queue.export_history(a, target, 'failed') == 1
        assert json.loads(target.read_text(encoding='utf-8'))['commands'][0]['operationId'] == 'old-operation'
        saved = target.read_bytes()
        for method in ('command_outbox.os.replace', 'command_outbox.json.dump'):
            before = set(root.iterdir())
            with patch(method, side_effect=OSError('simulated disk failure')):
                try:
                    queue.export_history(a, target)
                    raise AssertionError('Failure not propagated')
                except OSError:
                    pass
            assert target.read_bytes() == saved and set(root.iterdir()) == before
        for protected in (path, Path(str(path) + '-wal')):
            try:
                queue.export_history(a, protected)
                raise AssertionError('Database destination accepted')
            except ValueError:
                pass
        with queue.db() as db:
            db.execute("CREATE TRIGGER reject_local BEFORE INSERT ON local_resources BEGIN SELECT RAISE(ABORT, 'simulated full disk'); END")
        before = queue.history(b)['total']
        try:
            queue.break_action(b, 'new', 'START')
            raise AssertionError('Write failure ignored')
        except sqlite3.Error:
            pass
        assert queue.history(b)['total'] == before
        assert not any(r['deviceId'] == 'new' for r in queue.resources(b, 'break/'))
    print('PASS: legacy upgrade, owner/server isolation, pagination, filtered full export, atomic failure and SQLite rollback')


if __name__ == '__main__':
    main()
