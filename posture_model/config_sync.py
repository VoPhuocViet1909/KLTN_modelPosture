"""Opt-in Socket.IO notifications trigger authoritative GETs; capture only consumes snapshots."""
import collections
import json
import threading
import urllib.request

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
        self.sio.on("config", lambda data: self.dirty.set())
        self.thread = threading.Thread(target=self._run, name="config-sync", daemon=True)

    def start(self):
        self.thread.start()

    def take(self):
        try:
            return self.snapshots.pop()
        except IndexError:
            return None

    def _fetch(self):
        request = urllib.request.Request(self.auth.base_url + "/api/v1/config/me")
        with self.auth.open(request, timeout=5) as response:
            config = json.loads(response.read(65536))
        if not isinstance(config, dict):
            raise ValueError("Invalid config snapshot")
        self.snapshots.append(config)

    def _run(self):
        while not self.stopped.is_set():
            try:
                if self.dirty.is_set():
                    self.dirty.clear()
                    self._fetch()  # Fetch at startup even if the socket is unavailable.
                if not self.sio.connected:
                    token = self.auth.token()
                    self.sio.connect(self.auth.base_url, auth={"token": token}, transports=["websocket"],
                                     socketio_path="socket.io", wait_timeout=5)
                    self.dirty.set()  # Startup and every reconnect recover missed updates.
                if self.dirty.wait(1):
                    self.dirty.clear()
                    self._fetch()  # Full authoritative snapshot; no stale push vs GET race.
            except Exception:
                # Libraries may include token-bearing packets/URLs in errors. Never log them.
                self.dirty.set()
                print("Config sync unavailable; keeping last valid configuration")
                self.stopped.wait(5)
        self.sio.disconnect()

    def stop(self):
        self.stopped.set()
        self.dirty.set()
        if self.thread.is_alive():
            self.thread.join()  # Finish HTTP/connect before releasing the client.
