"""Opt-in Socket.IO notifications trigger authoritative GETs; capture only consumes snapshots."""
import collections
import json
import threading
import urllib.request
import urllib.error
import time
import re
import copy
from datetime import datetime, timezone
from observation import ObservationBuffer
from notification_policy import validate as validate_policy, DEFAULT as DEFAULT_POLICY


def valid_snapshot(value):
    if not isinstance(value, dict):
        return False
    version = value.get('version')
    try:
        served = datetime.fromisoformat(value.get('servedAt', '').replace('Z', '+00:00'))
        return (type(version) is int and 0 <= version <= 2**53 - 1
                and isinstance(value.get('revision'), str) and re.fullmatch('[0-9a-f]{64}', value['revision']) is not None
                and isinstance(value.get('effective'), dict) and served.tzinfo is not None)
    except (ValueError, TypeError, AttributeError):
        return False


def config_status_text(info):
    if not info:
        return 'Chưa nhận cấu hình từ máy chủ.'
    received, applied, result = (info.get(k) for k in ('received', 'applied', 'result'))
    if received and received['version'] is None:
        text = 'Máy chủ cũ: chưa xác nhận được phiên bản.'
    elif result and result['state'] == 'REJECTED':
        text = f"Đã từ chối cấu hình v{result['version']}; giữ cấu hình hợp lệ trước đó."
    elif applied:
        text = f"Desktop đã nạp cấu hình v{applied['version']}."
        if received and any(received.get(k) != applied.get(k) for k in ('version', 'revision')):
            text += f" Đang chờ nạp v{received['version']}."
    elif received:
        text = 'Máy chủ cũ: chưa xác nhận được phiên bản.' if received['version'] is None else f"Đã nhận v{received['version']}, đang chờ nạp."
    else:
        text = 'Chưa nhận cấu hình từ máy chủ.'
    return text + (' Chưa kiểm tra được cấu hình mới.' if info.get('fetchError') else '')

class ConfigSync:
    def __init__(self, auth):
        import socketio
        self.auth = auth
        self.sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False, request_timeout=5,
                                  websocket_extra_options={"redirect_limit": 0})
        self.dirty = threading.Event()
        self.dirty.set()
        self.stopped = threading.Event()
        self.snapshots = collections.deque(maxlen=1)
        self.policies = collections.deque(maxlen=1)
        self.policy_error = False
        self.policy_legacy = False
        self.policy_version = 0
        self.observations = ObservationBuffer()
        self.lock = threading.Lock()
        self.received = self.applied = self.result = self.taken = None
        self.fetch_error = False
        self.next_poll = 0.0
        self.sio.on("config", lambda data: self.dirty.set())
        self.thread = threading.Thread(target=self._run, name="config-sync", daemon=True)

    def start(self):
        self.thread.start()

    def take(self):
        try:
            self.taken = self.snapshots.pop()
            return self.taken['effective']
        except IndexError:
            return None

    def complete(self, accepted):
        snapshot = self.taken
        self.taken = None
        if snapshot is None:
            return
        metadata = dict(version=snapshot['version'], revision=snapshot['revision'],
                        state='APPLIED' if accepted else 'REJECTED',
                        appliedAt=datetime.now(timezone.utc).isoformat() if accepted else None)
        with self.lock:
            self.result = metadata
            if accepted:
                self.applied = metadata if metadata['version'] is not None else None
        self.observations.set_config(metadata if metadata['version'] is not None else None)

    def take_policy(self):
        try:
            return self.policies.pop()
        except IndexError:
            return None

    def _fetch_policy(self):
        try:
            request = urllib.request.Request(self.auth.base_url + '/api/v1/config/me/notification-policy')
            legacy = False
            try:
                with self.auth.open(request, timeout=5) as response:
                    policy = json.loads(response.read(65536))
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                policy = dict(DEFAULT_POLICY)
                legacy = True
            validate_policy(policy)
            if policy['version'] < self.policy_version:
                raise ValueError('Policy version regressed')
            self.policies.append(policy)
            self.policy_version = policy['version']
            self.policy_legacy = legacy
            self.policy_error = False
        except Exception:
            self.policy_error = True  # Never log token-bearing request/response details.

    def status(self):
        with self.lock:
            return copy.deepcopy(dict(received=self.received, applied=self.applied, result=self.result, fetchError=self.fetch_error))

    def _fetch(self):
        try:
            request = urllib.request.Request(self.auth.base_url + '/api/v1/config/me/snapshot')
            with self.auth.open(request, timeout=5) as response:
                snapshot = json.loads(response.read(65536))
            if not valid_snapshot(snapshot):
                raise ValueError('Invalid versioned snapshot')
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            request = urllib.request.Request(self.auth.base_url + '/api/v1/config/me')
            with self.auth.open(request, timeout=5) as response:
                config = json.loads(response.read(65536))
            if not isinstance(config, dict):
                raise ValueError('Invalid legacy snapshot')
            snapshot = dict(version=None, revision=None, effective=config)
        with self.lock:
            previous = self.received
            if (previous and previous['version'] is not None and snapshot['version'] is not None
                    and snapshot['version'] < previous['version']):
                raise ValueError('Config version regressed')
            self.received = {k: snapshot[k] for k in ('version', 'revision')}
            self.fetch_error = False
        self.snapshots.append(snapshot)
        self.next_poll = time.monotonic() + 30
        self._fetch_policy()

    def _run(self):
        while not self.stopped.is_set():
            try:
                if self.sio.connected:
                    self.observations.send(self.sio.emit)
                if self.dirty.is_set() or time.monotonic() >= self.next_poll:
                    self.dirty.clear()
                    self._fetch()  # Fetch at startup even if the socket is unavailable.
                if not self.sio.connected:
                    token = self.auth.token()
                    self.sio.connect(self.auth.base_url, auth={"token": token}, transports=["websocket"],
                                     socketio_path="socket.io", wait_timeout=5)
                    self.dirty.set()  # Startup and every reconnect recover missed updates.
                    self.observations.send(self.sio.emit, force=True)
                self.observations.send(self.sio.emit)
                if self.dirty.wait(1):
                    self.dirty.clear()
                    self._fetch()  # Full authoritative snapshot; no stale push vs GET race.
            except Exception:
                with self.lock:
                    self.fetch_error = True
                # Libraries may include token-bearing packets/URLs in errors. Never log them.
                self.dirty.set()
                print("Config sync unavailable; keeping last valid configuration")
                self.stopped.wait(5)
        try:
            if self.sio.connected:
                self.observations.send(self.sio.emit, force=True)
        except Exception:
            pass
        self.sio.disconnect()

    def stop(self):
        self.stopped.set()
        self.dirty.set()
        if self.thread.is_alive():
            self.thread.join()  # Finish HTTP/connect before releasing the client.
