"""Read-only, source-scoped history. Opening history never acknowledges or retries data."""
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone


class TelemetryHistory:
    def __init__(self, path):
        self.path = os.path.abspath(path)

    def _read(self, auth, state=None, page=0, size=25, all_rows=False):
        if state not in (None, 'pending', 'sent', 'failed') or page < 0 or not 1 <= size <= 100:
            raise ValueError('Invalid history filter')
        with closing(sqlite3.connect(Path(self.path).as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            context = db.execute('SELECT server,owner FROM outbox_context WHERE singleton=1').fetchone()
            if context != (auth.base_url.rstrip('/'), str(auth.user_id)):
                raise ValueError('History source mismatch')
            # Include the owner predicate even with a bound DB: never expose foreign/corrupt rows.
            clause = "json_extract(CASE WHEN json_valid(payload) THEN payload ELSE '{}' END,'$.userId')=?"
            clause += {None: '', 'pending': ' AND sent_at IS NULL AND dead=0', 'sent': ' AND sent_at IS NOT NULL',
                       'failed': ' AND sent_at IS NULL AND dead=1'}[state]
            total = db.execute('SELECT COUNT(*) FROM outbox WHERE ' + clause, (str(auth.user_id),)).fetchone()[0]
            sql = 'SELECT id,kind,payload,created_at,sent_at,dead,attempts FROM outbox WHERE ' + clause + ' ORDER BY created_at DESC,id'
            params = (str(auth.user_id),) if all_rows else (str(auth.user_id), size, page * size)
            rows = db.execute(sql + ('' if all_rows else ' LIMIT ? OFFSET ?'), params).fetchall()
        items = []
        for key, kind, payload, created, sent, dead, attempts in rows:
            # Export a summary only: arbitrary payload/last_error strings may contain secrets.
            items.append(dict(id=key, kind=kind, createdAt=datetime.fromtimestamp(created, timezone.utc).isoformat(),
                              sentAt=datetime.fromtimestamp(sent, timezone.utc).isoformat() if sent is not None else None,
                              state='sent' if sent is not None else 'failed' if dead else 'pending', attempts=attempts))
        return dict(items=items, total=total, page=page, size=size)

    def history(self, auth, state=None, page=0, size=25):
        return self._read(auth, state, page, size)

    def export_history(self, auth, target, state=None):
        target = os.path.abspath(target)
        forbidden = [self.path + suffix for suffix in ('', '-wal', '-shm', '-journal')]
        if any(os.path.normcase(os.path.realpath(target)) == os.path.normcase(os.path.realpath(source))
               or os.path.exists(target) and os.path.exists(source) and os.path.samefile(target, source) for source in forbidden):
            raise ValueError('Export would overwrite source database')
        data = self._read(auth, state, all_rows=True)
        fd, temporary = tempfile.mkstemp(prefix='.telemetry-', suffix='.json', dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(dict(exportedAt=datetime.now(timezone.utc).isoformat(), server=auth.base_url.rstrip('/'),
                               owner=str(auth.user_id), filter=state, **data), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return data['total']
