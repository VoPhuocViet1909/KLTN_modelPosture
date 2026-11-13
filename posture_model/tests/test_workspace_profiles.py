"""Scope isolation, calibration evidence and authenticated route limits without network/camera."""
import io
import json
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_profiles import WorkspaceProfiles, CAMERA_DEFAULTS, validate_current
from app_config import AppConfig
from alerts import machine_device_id
from api_session import ApiSession, AuthError
from config_sync import ConfigSync
from engine import PostureEngine


def rejected(fn):
    try: fn()
    except (ValueError, TypeError, KeyError): return
    raise AssertionError('Invalid profile accepted')


def main():
    auth = SimpleNamespace(base_url='http://one.invalid', user_id='owner')
    other = SimpleNamespace(base_url=auth.base_url, user_id='other')
    server = SimpleNamespace(base_url='http://two.invalid', user_id='owner')
    device = machine_device_id()
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory)/'profiles.db')
        profiles = WorkspaceProfiles(path)
        profiles.select(auth,device,'home','Home')
        profiles.save_cameras(auth,device,'home','1','0',dict(CAMERA_DEFAULTS,camera_focal_px=800))
        for identity, dev, workspace in [(other,device,'home'),(server,device,'home'),(auth,'other-device','home'),(auth,device,'office')]:
            assert profiles.cameras(identity,dev,workspace) is None
        assert profiles.selection(other,device)['workspaceId'] is None
        assert WorkspaceProfiles(path).cameras(auth,device,'home')['settings']['camera_focal_px'] == 800
        event = dict(eventType='CALIBRATED',ts='2026-11-13T00:00:00Z',baseline=dict(neck=20,trunk=0,headPitch=0), focalPx=800)
        engine = SimpleNamespace(o=SimpleNamespace(workspace_db=path,workspace_id='home'), auth=auth,elog=SimpleNamespace(device_id=device))
        PostureEngine._save_profile_calibration(engine,event)
        with closing(sqlite3.connect(path)) as db:
            recorded = json.loads(db.execute('SELECT calibration FROM profiles').fetchone()[0])
            assert recorded['baseline'] == event['baseline']
        assert 'baseline' not in profiles.cameras(auth,device,'home'), 'Measured angles must never be restored as camera settings'
        rejected(lambda: profiles.save_cameras(auth,device,'office','https://user:secret@camera','0'))
        rejected(lambda: profiles.save_cameras(auth,device,'office','1','0',dict(api_token='secret')))
        cfg = AppConfig(str(Path(directory)/'config.json'))
        cfg.values['camera_focal_px'] = 999
        cfg.apply_remote(dict(camera_focal_px=1200))
        cfg.apply_profile(CAMERA_DEFAULTS)
        assert cfg['camera_focal_px'] is None, 'A new profile must not inherit old local or remote calibration'
        cfg.apply_profile(profiles.cameras(auth,device,'home')['settings'])
        assert cfg['camera_focal_px'] == 800
        cfg.apply_profile(CAMERA_DEFAULTS)
        assert cfg['camera_focal_px'] is None
        assert 'profile' not in Path(cfg.path).read_text(encoding='utf-8')
    calls = []
    session = ApiSession.__new__(ApiSession)
    session.base_url = auth.base_url
    session.token = lambda **kwargs: 'synthetic-token'
    session._opener = SimpleNamespace(open=lambda req, **kwargs: calls.append(req.full_url) or io.BytesIO(b'{}'))
    key = '11111111-1111-4111-8111-111111111111'
    for path, method in [('workspaces?page=0&size=100','GET'),('devices/current?deviceId='+device,'GET'),('devices/'+key,'PUT'),('devices/'+key+'/heartbeat','POST')]:
        session.open(urllib.request.Request(auth.base_url+'/api/v1/config/me/'+path,method=method)).close()
    assert len(calls)==4
    for url, method in [('http://two.invalid/api/v1/config/me/workspaces','GET'),(auth.base_url+'/api/v1/config/me/devices/'+key+'/heartbeat?owner=other','POST'),(auth.base_url+'/api/v1/config/me/devices/current?deviceId=../other','GET'),(auth.base_url+'/api/v1/config/me/workspaces/'+key,'DELETE')]:
        rejected(lambda: session.open(urllib.request.Request(url,method=method)))
    assert len(calls)==4
    current = dict(device=dict(deviceKey=key,deviceId=device,name='PC',workspaceId=None,status='ACTIVE',version=1),workspace=None)
    validate_current(current,device)
    rejected(lambda: validate_current(current,'foreign-device'))
    network = []
    def fake_open(req, **kwargs):
        network.append(req)
        return io.BytesIO(json.dumps(current if req.get_method()=='GET' else dict(reportedAt='2026-11-13T00:00:00Z')).encode())
    sync = ConfigSync(SimpleNamespace(base_url=auth.base_url,open=fake_open))
    sync._fetch_workspace()
    assert not sync.workspace_error and sync.workspace_current==current
    assert network[-1].get_method()=='POST' and network[-1].data==b'{}'
    assert network[-1].full_url.endswith('/'+key+'/heartbeat')
    print('PASS: profile scope/restart, calibration evidence without restore, local camera precedence, strict API routes and heartbeat')


if __name__=='__main__': main()
