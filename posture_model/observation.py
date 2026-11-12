"""Current camera/posture state, independent of delayed alert episodes."""
from datetime import datetime, timezone
import threading
import time

REASON = dict(GOOD='NONE', BAD='NONE', AWAY='NONE', CALIBRATING='CALIBRATING',
              UNKNOWN='INSUFFICIENT_DATA', CAMERA_LOST='CAMERA_READ_FAILED', OFFLINE='SESSION_STOPPED')


class ObservationBuffer:
    """Only the latest frame survives disconnect; never replay historical presence as live."""
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None
        self.sequence = 0
        self.sent_state = None
        self.sent_at = -1e9
        self.config = None

    def put(self, device, session, state):
        with self.lock:
            self.sequence += 1
            self.latest = (time.monotonic(), dict(version=1, deviceId=device, sessionId=session,
                sequence=self.sequence, state=state, reason=REASON[state], observedAt=datetime.now(timezone.utc).isoformat()))
            if self.config is not None:
                self.latest[1]['config'] = dict(self.config)

    def set_config(self, value):
        with self.lock:
            self.config = dict(value) if value else None
            self.sent_state = None

    def send(self, emit, force=False):
        now = time.monotonic()
        with self.lock:
            if self.latest is None or now - self.latest[0] > 3:
                return False
            payload = dict(self.latest[1])
            if not force and payload['state'] == self.sent_state and now - self.sent_at < 5:
                return False
        emit('device-state', payload)
        with self.lock:
            self.sent_state, self.sent_at = payload['state'], now
        return True
