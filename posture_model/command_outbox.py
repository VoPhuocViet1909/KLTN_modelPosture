"""Owner-scoped REST commands, separate from telemetry and its frozen event types."""
import contextlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timezone, timedelta


def now():
    return datetime.now(timezone.utc).isoformat()


class CommandOutbox:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS commands (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT UNIQUE NOT NULL,
                  server TEXT NOT NULL, owner TEXT NOT NULL, resource TEXT NOT NULL,
                  method TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'pending', error TEXT, receipt TEXT);
                CREATE TABLE IF NOT EXISTS local_resources (
                  server TEXT NOT NULL, owner TEXT NOT NULL, resource TEXT NOT NULL,
                  body TEXT NOT NULL, PRIMARY KEY(server,owner,resource));
            ''')

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def identity(auth):
        if not auth or not auth.user_id or not auth.base_url:
            raise ValueError('Đăng nhập để ghi nhận nghỉ/phản hồi.')
        return auth.base_url.rstrip('/'), str(auth.user_id)

    def resources(self, auth, prefix):
        server, owner = self.identity(auth)
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM local_resources WHERE server=? AND owner=? AND resource LIKE ? ORDER BY rowid DESC', (server, owner, prefix + '%'))]

    def enqueue(self, auth, resource, method, path, body, local):
        server, owner = self.identity(auth)
        body = {**body, 'operationId': str(uuid.uuid4())}
        with self.db() as db:
            db.execute('INSERT INTO commands(operation,server,owner,resource,method,path,body) VALUES (?,?,?,?,?,?,?)',
                       (body['operationId'], server, owner, resource, method, path, json.dumps(body, allow_nan=False)))
            db.execute('INSERT INTO local_resources VALUES (?,?,?,?) ON CONFLICT(server,owner,resource) DO UPDATE SET body=excluded.body',
                       (server, owner, resource, json.dumps(local)))
        return body['operationId']

    def break_action(self, auth, device, action):
        server, owner = self.identity(auth)
        with self.db() as db:
            if db.execute("SELECT 1 FROM commands WHERE server=? AND owner=? AND resource LIKE 'break/%' AND state='failed' LIMIT 1", (server, owner)).fetchone():
                raise ValueError('Có thao tác nghỉ bị từ chối. Xử lý xung đột trên web trước khi ghi lần nghỉ mới.')
        active = next((b for b in self.resources(auth, 'break/') if b['deviceId'] == device and b['state'] in ('SNOOZED', 'IN_PROGRESS')), None)
        state = active['state'] if active else 'NONE'
        allowed = {'NONE': {'START': 'IN_PROGRESS', 'SNOOZE': 'SNOOZED', 'SKIP': 'SKIPPED'},
                   'SNOOZED': {'START': 'IN_PROGRESS', 'SNOOZE': 'SNOOZED', 'SKIP': 'SKIPPED'},
                   'IN_PROGRESS': {'COMPLETE': 'COMPLETED', 'CANCEL': 'CANCELLED'}}
        if action not in allowed.get(state, {}):
            raise ValueError('Thao tác không phù hợp với trạng thái nghỉ hiện tại.')
        record = dict(active) if active else dict(breakId=str(uuid.uuid4()), version=0, deviceId=device)
        at = now()
        body = dict(breakId=record['breakId'], expectedVersion=record['version'], deviceId=device, action=action, occurredAt=at, snoozeUntil=None, reminderEventId=None)
        if action == 'SNOOZE':
            body['snoozeUntil'] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        if action == 'START':
            record['startedAt'] = at
        if action == 'COMPLETE':
            started = datetime.fromisoformat(record['startedAt'])
            elapsed = (datetime.fromisoformat(at) - started).total_seconds()
            if not 0 < elapsed <= 14400:
                raise ValueError('Khoảng nghỉ phải lớn hơn 0 và không quá 4 giờ. Hủy lần nghỉ nếu thời gian không hợp lệ.')
        record.update(version=record['version'] + 1, state=allowed[state][action], occurredAt=at, snoozeUntil=body['snoozeUntil'])
        self.enqueue(auth, 'break/' + record['breakId'], 'POST', '/api/v1/alerts/me/break-actions', body, record)
        return record

    def remember_episode(self, auth, event):
        if event.get('eventType') != 'ALERT_STARTED' or not event.get('startedAt'):
            return
        ref = {k: event[k] for k in ('deviceId', 'sessionId', 'alertType', 'startedAt')}
        resource = 'episode/' + str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(ref, sort_keys=True)))
        server, owner = self.identity(auth)
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO local_resources VALUES (?,?,?,?)', (server, owner, resource, json.dumps(ref)))

    def feedback(self, auth, ref, rating, reason, note):
        existing = next((f for f in self.resources(auth, 'feedback/') if f['episodeRef'] == ref), None)
        record = dict(existing) if existing else dict(feedbackId=str(uuid.uuid4()), version=0, episodeRef=ref)
        body = dict(episodeRef=ref, rating=rating, reason=reason, note=note, expectedVersion=record['version'])
        record.update(version=record['version'] + 1, rating=rating, reason=reason, note=note)
        self.enqueue(auth, 'feedback/' + record['feedbackId'], 'PUT', '/api/v1/alerts/me/feedback/' + record['feedbackId'], body, record)

    def stats(self, auth):
        server, owner = self.identity(auth)
        with self.db() as db:
            return dict(db.execute('SELECT state,count(*) FROM commands WHERE server=? AND owner=? GROUP BY state', (server, owner)).fetchall())

    def flush(self, auth, stop=None):
        server, owner = self.identity(auth)
        with self.db() as db:
            rows = db.execute("SELECT * FROM commands WHERE server=? AND owner=? AND state IN ('pending','failed') ORDER BY seq", (server, owner)).fetchall()
        blocked = set()
        for row in rows:
            if stop is not None and stop.is_set():
                break
            if row['state'] == 'failed':
                blocked.add(row['resource'])
                continue
            if row['resource'] in blocked:
                continue
            request = urllib.request.Request(server + row['path'], data=row['body'].encode(), method=row['method'], headers={'Content-Type': 'application/json'})
            try:
                with auth.open(request, timeout=5) as response:
                    receipt = json.load(response)
                expected = json.loads(row['body'])['expectedVersion'] + 1
                if not isinstance(receipt, dict) or type(receipt.get('version')) is not int or receipt.get('version') != expected:
                    break  # Uncertain response: retain the same operation, never advance the chain.
                expected_key = 'breakId' if row['resource'].startswith('break/') else 'feedbackId'
                if receipt.get(expected_key) != row['resource'].split('/', 1)[1]:
                    break
                with self.db() as db:
                    db.execute("UPDATE commands SET state='sent',receipt=? WHERE operation=?", (json.dumps(receipt), row['operation']))
            except urllib.error.HTTPError as error:
                if error.code in (400, 404, 409):
                    with self.db() as db:
                        db.execute("UPDATE commands SET state='failed',error=? WHERE operation=?", (str(error.code), row['operation']))
                    blocked.add(row['resource'])
                else:
                    break
            except (OSError, ValueError):
                break
        return self.stats(auth)

    def resolve_failed(self, auth):
        """Explicit user recovery: only discard chains already rejected by the server."""
        server, owner = self.identity(auth)
        with self.db() as db:
            resources = [r[0] for r in db.execute("SELECT DISTINCT resource FROM commands WHERE server=? AND owner=? AND state='failed'", (server, owner))]
        for kind, path, key in [('break/', '/api/v1/alerts/me/breaks', 'breakId'), ('feedback/', '/api/v1/alerts/me/feedback', 'feedbackId')]:
            failed = [r for r in resources if r.startswith(kind)]
            if not failed:
                continue
            records = {}
            for page in range(100):
                query = urllib.parse.urlencode({'from': (datetime.now(timezone.utc)-timedelta(days=91)).isoformat(), 'to': now(), 'page': page, 'size': 100})
                with auth.open(urllib.request.Request(server + path + '?' + query), timeout=5) as response:
                    body = json.load(response)
                records.update({kind + r[key]: r for r in body['items']})
                if (page + 1) * 100 >= body['total']:
                    break
            else:
                raise ValueError('Dữ liệu quá nhiều để đối soát. Thu hẹp lịch sử trước khi thử lại.')
            with self.db() as db:
                for resource in failed:
                    db.execute("UPDATE commands SET state='cancelled' WHERE server=? AND owner=? AND resource=? AND state IN ('failed','pending')", (server, owner, resource))
                    if resource in records:
                        db.execute('UPDATE local_resources SET body=? WHERE server=? AND owner=? AND resource=?', (json.dumps(records[resource]), server, owner, resource))
                    else:
                        db.execute('DELETE FROM local_resources WHERE server=? AND owner=? AND resource=?', (server, owner, resource))
        return self.stats(auth)
