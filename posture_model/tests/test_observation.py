"""Freshness, latest-only reconnect and cross-repository state labels, no server/camera."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observation import ObservationBuffer, REASON
from engine import PostureEngine
from ui.tokens import labels
from iot_notifier import IotNotifier
from ui.controller import AppController


def main():
    fixture = json.loads((Path(__file__).resolve().parents[2] / 'api_handover/device-observation-v1.json').read_text(encoding='utf-8'))
    for item in fixture['states']:
        assert REASON[item['state']] == item['reason']
        assert labels()['state'][item['state']]['label'] == item['label']
    buffer, packets = ObservationBuffer(), []
    emit = lambda event, body: packets.append((event, body))
    with patch('observation.time.monotonic', return_value=0):
        buffer.put('device', 'session', 'CALIBRATING')
        assert buffer.send(emit)
        assert not buffer.send(emit)
        buffer.put('device', 'session', 'UNKNOWN')
        assert buffer.send(emit)
    with patch('observation.time.monotonic', return_value=4.9):
        buffer.put('device', 'session', 'UNKNOWN')
    with patch('observation.time.monotonic', return_value=5):
        assert buffer.send(emit)
    with patch('observation.time.monotonic', return_value=10):
        assert not buffer.send(emit, force=True), 'Reconnect must not replay an old frame'
        buffer.put('device', 'session', 'GOOD')
        assert buffer.send(emit, force=True)
    assert packets[-1][1]['sequence'] > packets[0][1]['sequence']
    assert all(event == 'device-state' for event, body in packets)
    engine = PostureEngine.__new__(PostureEngine)
    engine.pres = SimpleNamespace(away=False)
    engine.trackers = [SimpleNamespace(status='GOOD')]
    engine._neck_observed = False
    assert engine._posture_state(False) == 'UNKNOWN'
    assert engine._posture_state(True) == 'CALIBRATING'
    engine.pres.away = True
    assert engine._posture_state(False) == 'AWAY'
    engine.pres.away = False
    engine._neck_observed = True
    assert engine._posture_state(False) == 'GOOD'
    engine.trackers[0].status = 'BAD'
    assert engine._posture_state(False) == 'BAD'
    sent = []
    iot = SimpleNamespace(enabled=True, _clock=lambda: 100, _last_state=None, _last_state_t=0,
        cfg={'status_every_sec': 60}, _status_body=lambda state, minutes: {'state': state},
        _send=lambda method, path, body: sent.append(body))
    for state in ('UNKNOWN', 'CAMERA_LOST'):
        iot._last_state = None
        IotNotifier.on_state(iot, {'state': state})
    assert sent == [{'state': 'OFFLINE'}, {'state': 'OFFLINE'}]
    local = []
    controller = SimpleNamespace(mode='session', _leaving=False, engine=object(), _engine_error=None,
        _last_state_received=0, _state_stale=False, _clear_notices=lambda: None,
        window=SimpleNamespace(set_state=lambda value: local.append(value['state']), hint=SimpleNamespace(setText=lambda text: None)),
        tray=SimpleNamespace(set_state=lambda state: None))
    with patch('ui.controller.time.monotonic', return_value=4):
        AppController._check_state_freshness(controller)
    assert local == ['UNKNOWN'] and controller._state_stale
    controller.mode, controller._state_stale = 'login', False
    AppController._check_state_freshness(controller)
    assert local == ['UNKNOWN'], 'An old engine must not update the login screen'
    print('PASS: shared states/labels, heartbeat, no stale replay, unknown before known and AWAY precedence')


if __name__ == '__main__':
    main()
