"""Versioned fetch, explicit legacy fallback, rejection and reconnect without a server."""
import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_sync import ConfigSync, valid_snapshot, config_status_text


def main():
    state = dict(version=3, revision='a'*64, effective={'bad_hold_sec': 8}, servedAt='2026-11-13T00:00:00Z')
    calls = []
    def open_request(request, **kwargs):
        calls.append(request.full_url)
        if isinstance(state.get('error'), int) and request.full_url.endswith('/snapshot'):
            raise urllib.error.HTTPError(request.full_url, state['error'], '', {}, None)
        return io.BytesIO(json.dumps(state['effective'] if request.full_url.endswith('/me') else state).encode())
    sync = ConfigSync(SimpleNamespace(base_url='http://example.test', open=open_request))
    assert valid_snapshot(state)
    assert not valid_snapshot(dict(state, version=True))
    assert not valid_snapshot(dict(state, revision='invalid'))
    sync._fetch()
    assert sync.status()['applied'] is None
    assert sync.take() == state['effective']
    sync.complete(True)
    assert sync.status()['applied']['version'] == 3
    assert sync.observations.config['state'] == 'APPLIED'
    state['revision'] = 'b'*64  # Organization membership can change without a version increment.
    sync._fetch(); sync.take(); sync.complete(False)
    assert sync.status()['applied']['revision'] == 'a'*64
    assert sync.status()['result']['state'] == 'REJECTED'
    assert 'từ chối' in config_status_text(sync.status())
    state['version'] = 2
    try:
        sync._fetch()
        raise AssertionError('Regressed version accepted')
    except ValueError:
        pass
    state.update(version=4, revision='c'*64)
    sync._fetch(); sync.take(); sync.complete(True)
    assert sync.status()['applied']['version'] == 4
    state['error'] = 503
    before = len(calls)
    try:
        sync._fetch()
        raise AssertionError('503 incorrectly fell back')
    except urllib.error.HTTPError:
        pass
    assert len(calls) == before + 1
    state['error'] = 404
    sync._fetch(); sync.take(); sync.complete(True)
    assert sync.status()['received']['version'] is None
    assert sync.observations.config is None, 'Legacy config must not advertise a known version'
    assert calls[-1].endswith('/config/me')
    assert sync.status()['applied'] is None
    del state['error']
    # Drive the actual worker with a fake clock: no waiting, network or real socket.
    polling = ConfigSync(sync.auth)
    polling.sio = SimpleNamespace(connected=True, emit=lambda *args: None, disconnect=lambda: None)
    clock = [0.0]
    advances = iter([29, 30, 59, 60, 61])
    def advance(timeout):
        clock[0] = next(advances)
        if clock[0] == 61:
            polling.stopped.set()
        return False
    before = len(calls)
    with patch('config_sync.time.monotonic', side_effect=lambda: clock[0]), patch.object(polling.dirty, 'wait', side_effect=advance):
        polling._run()
    assert len(calls) == before + 3, 'Worker must fetch at startup, 30 and 60 seconds'
    reconnect = ConfigSync(sync.auth)
    socket = SimpleNamespace(connected=False, emit=lambda *args: None, disconnect=lambda: None)
    socket.connect = lambda *args, **kwargs: setattr(socket, 'connected', True)
    reconnect.sio = socket
    reconnect.auth.token = lambda: 'synthetic-token'
    def stop_after_connect(timeout):
        assert reconnect.dirty.is_set()
        reconnect.stopped.set()
        return True
    before = len(calls)
    with patch.object(reconnect.dirty, 'wait', side_effect=stop_after_connect):
        reconnect._run()
    assert len(calls) == before + 2, 'Reconnect must fetch again after connecting'
    print('PASS: versioned fetch, membership revision, apply/reject, regression and 404-only legacy fallback')


if __name__ == '__main__':
    main()
