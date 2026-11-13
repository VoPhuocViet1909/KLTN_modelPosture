"""Local camera choices/calibration evidence partitioned by server/user/device/workspace."""
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import closing

CAMERA_DEFAULTS = dict(calib_distance_cm=None, camera_focal_px=None, camera_hfov_deg=63, calib_sec=10)


def camera_value(side, front, settings=None):
    from schema import validate
    if settings is not None and (not isinstance(settings, dict) or set(settings) - set(CAMERA_DEFAULTS)):
        raise ValueError('Invalid profile settings')
    settings = {**CAMERA_DEFAULTS, **(settings or {})}
    if validate('config', settings):
        raise ValueError('Invalid camera calibration settings')
    value = dict(side=str(side), front=str(front), settings=settings)
    if any(len(value[key]) > 32 or not (value[key].lstrip('-').isdigit() or value[key].lower() in ('off','none')) for key in ('side','front')):
        raise ValueError('Profile camera source must be a local device index')
    return value


class WorkspaceProfiles:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS profiles(server TEXT,owner TEXT,device TEXT,workspace TEXT,cameras TEXT,calibration TEXT,updated REAL,PRIMARY KEY(server,owner,device,workspace))')
            db.execute('CREATE TABLE IF NOT EXISTS selected(server TEXT,owner TEXT,device TEXT,workspace TEXT,name TEXT,PRIMARY KEY(server,owner,device))')

    @staticmethod
    def identity(auth, device):
        if not auth.base_url or not auth.user_id or not device:
            raise ValueError('Missing profile identity')
        return auth.base_url.rstrip('/'), str(auth.user_id), device

    def selection(self, auth, device):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT workspace,name FROM selected WHERE server=? AND owner=? AND device=?', self.identity(auth, device)).fetchone()
        return dict(workspaceId=row[0] or None, name=row[1]) if row else dict(workspaceId=None, name='Chưa gán vị trí')

    def select(self, auth, device, workspace, name):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO selected VALUES(?,?,?,?,?) ON CONFLICT(server,owner,device) DO UPDATE SET workspace=excluded.workspace,name=excluded.name', (*self.identity(auth, device), workspace or '', name))

    def cameras(self, auth, device, workspace):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT cameras FROM profiles WHERE server=? AND owner=? AND device=? AND workspace=?', (*self.identity(auth, device), workspace or '')).fetchone()
        if not row or not row[0]:
            return None
        value = json.loads(row[0])
        if not isinstance(value, dict) or set(value) != {'side','front','settings'}:
            raise ValueError('Invalid stored camera profile')
        return camera_value(value['side'], value['front'], value['settings'])

    def save_cameras(self, auth, device, workspace, side, front, settings=None):
        value = camera_value(side, front, settings)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO profiles(server,owner,device,workspace,cameras,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(server,owner,device,workspace) DO UPDATE SET cameras=excluded.cameras,calibration=NULL,updated=excluded.updated', (*self.identity(auth, device), workspace or '', json.dumps(value), time.time()))

    def save_calibration(self, auth, device, workspace, event):
        # Evidence only: engine always measures again instead of restoring these angles.
        value = {key: event.get(key) for key in ('ts','baseline','shoulderTiltBase','distanceCm','distanceMethod','focalPx','modelVersion','appVersion')}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO profiles(server,owner,device,workspace,calibration,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(server,owner,device,workspace) DO UPDATE SET calibration=excluded.calibration,updated=excluded.updated', (*self.identity(auth, device), workspace or '', json.dumps(value, allow_nan=False), time.time()))


def request(auth, path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(auth.base_url + '/api/v1/config/me/' + path, data=data, headers={'Content-Type':'application/json'}, method=method or ('PUT' if body is not None else 'GET'))
    with auth.open(req, timeout=5) as response:
        return json.loads(response.read(262144))


def choices(auth, device):
    workspaces = []
    for page in range(100):
        result = request(auth, f'workspaces?page={page}&size=100')
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise ValueError('Invalid workspace response')
        workspaces += result['items']
        if len(workspaces) >= result['total']:
            break
    else:
        raise ValueError('Too many workspace profiles')
    current = request(auth, 'devices/current?' + urllib.parse.urlencode({'deviceId':device}))
    validate_current(current, device)
    for workspace in workspaces:
        if not isinstance(workspace, dict) or not isinstance(workspace.get('name'), str) or workspace.get('status') not in ('ACTIVE','ARCHIVED'):
            raise ValueError('Invalid workspace choices')
        uuid.UUID(workspace['workspaceId'])
    return dict(workspaces=workspaces, **current)


def validate_current(current, device_id):
    if not isinstance(current, dict) or set(current) != {'device','workspace'}:
        raise ValueError('Invalid device profile')
    device, workspace = current['device'], current['workspace']
    if device is None:
        if workspace is not None:
            raise ValueError('Workspace without registered device')
        return
    if not isinstance(device, dict) or device.get('deviceId') != device_id or device.get('status') not in ('ACTIVE','ARCHIVED'):
        raise ValueError('Device profile mismatch')
    uuid.UUID(device['deviceKey'])
    if type(device.get('version')) is not int or not 1 <= device['version'] <= 2**53-1 or not isinstance(device.get('name'), str):
        raise ValueError('Invalid device revision')
    if device.get('workspaceId') is not None:
        uuid.UUID(device['workspaceId'])
        if not isinstance(workspace, dict) or workspace.get('workspaceId') != device['workspaceId'] or workspace.get('status') not in ('ACTIVE','ARCHIVED') or not isinstance(workspace.get('name'), str):
            raise ValueError('Workspace profile mismatch')
    elif workspace is not None:
        raise ValueError('Unexpected workspace')
