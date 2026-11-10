"""No Docker: replay, owner isolation and REST allowlist with a fake transport."""
import io
import json
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_session import ApiSession, AuthError
from command_outbox import CommandOutbox


class Auth:
    base_url = 'http://localhost:8080'
    def __init__(self, owner='one'):
        self.user_id = owner
        self.sent = []
        self.fail = None
    def open(self, request, timeout=5):
        if request.get_method() == 'GET':
            return io.BytesIO(b'{"items":[],"total":0}')
        body = json.loads(request.data)
        self.sent.append(body)
        if self.fail:
            raise self.fail
        result = dict(version=body['expectedVersion'] + 1)
        if 'breakId' in body:
            result['breakId'] = body['breakId']
        else:
            result['feedbackId'] = request.full_url.rsplit('/', 1)[1]
        return io.BytesIO(json.dumps(result).encode())


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'commands.db')
        queue = CommandOutbox(path)
        a, b = Auth(), Auth('two')
        queue.break_action(a, 'device', 'START')
        queue.break_action(a, 'device', 'COMPLETE')
        assert queue.stats(b) == {}
        queue.flush(b)
        assert not b.sent
        a.fail = OSError('offline')
        queue.flush(a)
        first = a.sent[0]
        assert queue.stats(a)['pending'] == 2
        a.fail = None
        queue = CommandOutbox(path)
        assert queue.flush(a)['sent'] == 2
        assert a.sent[1] == first
        assert a.sent[2]['expectedVersion'] == 1
        assert a.sent[1]['breakId'] == a.sent[2]['breakId']
        queue.break_action(a, 'device', 'START')
        queue.break_action(a, 'device', 'COMPLETE')
        a.fail = urllib.error.HTTPError(a.base_url, 409, 'conflict', {}, None)
        queue.flush(a)
        assert queue.stats(a)['failed'] == 1 and queue.stats(a)['pending'] == 1
        count = len(a.sent)
        queue.flush(a)
        assert len(a.sent) == count, 'A failed predecessor blocks its dependent command'
        a.fail = None
        queue.resolve_failed(a)
        assert queue.stats(a).get('failed', 0) == 0
        assert queue.stats(a)['cancelled'] == 2
        queue.break_action(a, 'device', 'START')
        ref = dict(deviceId='device', sessionId='session', alertType='NECK_TRUNK', startedAt='2026-11-10T01:00:00Z')
        queue.remember_episode(a, dict(eventType='ALERT_STARTED', **ref))
        queue.feedback(a, ref, 'UNSURE', 'NONE', '')
        assert queue.resources(b, 'episode/') == []
        other_server = Auth()
        other_server.base_url = 'http://localhost:8081'
        assert queue.stats(other_server) == {}

    auth = ApiSession.__new__(ApiSession)
    auth._init_common('http://localhost:8080')
    auth.token = lambda **kwargs: 'test-token'
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(b'{}')
    auth._opener = Opener()
    auth.open(urllib.request.Request(auth.base_url + '/api/v1/config/me/goals?from=2026-11-10&to=2026-11-11'))
    auth.open(urllib.request.Request(auth.base_url + '/api/v1/alerts/me/break-actions', data=b'{}', method='POST'))
    for url in ('http://localhost:8081/api/v1/alerts/me/break-actions', auth.base_url + '/api/v1/users', auth.base_url + '/api/v1/alerts/me/feedback/invalid'):
        try:
            auth.open(urllib.request.Request(url, data=b'{}', method='POST'))
            raise AssertionError('Out-of-scope request accepted')
        except AuthError:
            pass
    print('PASS: durable ordered retry, receipt validation, owner/server isolation, terminal conflict, request allowlist')


if __name__ == '__main__':
    main()
