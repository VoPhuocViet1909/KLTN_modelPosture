"""Quiet/focus/gap boundaries and telemetry retention with no real clock/network."""
import io
import json
import sys
import tempfile
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notification_policy import NotificationPolicy, DEFAULT
from notifier import Notifier, explanation
from alerts import EventLog, AlertTracker
from config_sync import ConfigSync


def main():
    wall = [datetime.fromisoformat('2026-11-13T15:00:00+00:00')]  # 22:00 VN
    tick = [0.0]
    policy = NotificationPolicy(lambda: wall[0], lambda: tick[0])
    policy.apply(dict(DEFAULT, version=1, quietEnabled=True))
    assert not policy.decide()['sound']
    wall[0] = datetime.fromisoformat('2026-11-13T23:59:00+07:00')
    assert not policy.decide()['toast']
    wall[0] = datetime.fromisoformat('2026-11-14T06:59:59+07:00')
    assert not policy.decide()['popup']
    wall[0] = datetime.fromisoformat('2026-11-14T07:00:00+07:00')
    assert policy.decide()['sound']
    policy.apply(dict(DEFAULT, version=2, focusUntil='2026-11-14T07:15:00+07:00', minimumGapSec=60))
    assert not policy.decide()['sound']
    wall[0] = datetime.fromisoformat('2026-11-14T07:15:00+07:00')
    tick[0] = 900
    assert policy.decide()['sound']
    tick[0] = 959.99
    assert not policy.decide()['sound']
    tick[0] = 960
    assert policy.decide()['sound']
    # Polling the same version must not reset the gap and cause another notification.
    policy.apply(dict(DEFAULT, version=2, focusUntil='2026-11-14T07:15:00+07:00', minimumGapSec=60))
    assert not policy.decide()['sound']
    for invalid in [dict(DEFAULT, version=1), dict(DEFAULT, version=2, sound=False), dict(DEFAULT, version=True), dict(DEFAULT, focusUntil=12)]:
        try:
            policy.apply(invalid)
            raise AssertionError('Invalid/regressed policy accepted')
        except ValueError:
            pass
    policy.reset()
    assert policy.value == DEFAULT and not policy.synced and policy.decide()['sound']

    with tempfile.TemporaryDirectory() as directory:
        cfg = {'notify_toast': True, 'notify_sound': True, 'notify_popup': True, 'distance_on_cm': 50}
        notifier = Notifier(cfg)
        notifier.policy.apply(dict(DEFAULT, version=1, focusUntil='2099-01-01T00:00:00Z'))
        interruptions = []
        notifier._run = lambda *args: interruptions.append(args)
        retained = []
        path = str(Path(directory)/'events.jsonl')
        log = EventLog(path, 'v3', wall_t0=1_790_000_000, listeners=[notifier, retained.append])
        tracker = AlertTracker('NECK_TRUNK', alert_sec=1, repeat_sec=2)
        for second in range(8):
            log.emit_all(tracker.update(True, second), snapshot={'pBad': .8})
        log.close()
        assert retained and len(Path(path).read_text(encoding='utf-8').splitlines()) == len(retained)
        assert not interruptions and notifier.active_banner(), 'Quiet delivery must retain events and visible banner'
        assert all(event['notify'] is True for event in retained), 'Do not alter recorded notify semantics'
        assert 'chưa phân loại nguyên nhân' in explanation(retained[0])
        assert 'nan' not in explanation(dict(alertType='TOO_CLOSE', snapshot={'distanceCm': float('nan')}))
    response = [dict(DEFAULT, version=4)]
    def open_request(request, **kwargs):
        value = response[0]
        if type(value) is int:
            raise urllib.error.HTTPError(request.full_url, value, '', {}, None)
        return io.BytesIO(json.dumps(value).encode())
    sync = ConfigSync(SimpleNamespace(base_url='http://test.invalid', open=open_request))
    sync._fetch_policy(); assert sync.take_policy()['version'] == 4
    response[0] = 503
    sync._fetch_policy(); assert sync.policy_error and sync.take_policy() is None
    response[0] = 404
    sync._fetch_policy(); assert sync.policy_error and sync.take_policy() is None, 'Do not downgrade active policy'
    fresh = ConfigSync(sync.auth)
    fresh._fetch_policy(); assert fresh.take_policy() == DEFAULT and fresh.policy_legacy
    from ui.controller import AppController
    banner, toast = [], []
    focused = NotificationPolicy()
    focused.apply(dict(DEFAULT, version=1, focusUntil='2099-01-01T00:00:00Z'))
    controller = SimpleNamespace(_leaving=False, mode='session', _engine_error=None, auth=None, _dialog=None,
        cfg=cfg, notifier=SimpleNamespace(policy=focused), iot=SimpleNamespace(mutes_pc_beep=False),
        window=SimpleNamespace(show_notice=lambda *args: banner.append(args)),
        tray=SimpleNamespace(isVisible=lambda: True, showMessage=lambda *args: toast.append(args)))
    with patch('ui.controller.threading.Thread') as sound, patch('ui.controller.AlertDialog') as popup:
        AppController._on_notice(controller, 'Title', 'Body', 'HIGH', 'NECK_TRUNK', 'ALERT_STARTED')
        assert banner and not toast and not sound.called and not popup.called
    print('PASS: quiet/focus/gap boundaries, no replay, retained events, invalid versions and worker fallback/errors')


if __name__ == '__main__':
    main()
