"""Versioned PC delivery rules. No event queue and no changes to detection or telemetry."""
import copy
import threading
import time
from datetime import datetime, timedelta, timezone

VIETNAM = timezone(timedelta(hours=7))
DEFAULT = dict(version=0, updatedAt=None, quietEnabled=False, quietStartMinute=1320, quietEndMinute=420,
               focusUntil=None, minimumGapSec=0, toast=True, sound=True, popup=True)


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Invalid timestamp type')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp needs an offset')
    return parsed


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError('Invalid notification policy fields')
    for key in ('quietEnabled', 'toast', 'sound', 'popup'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid notification channel')
    for key, maximum in [('version', 2**53-1), ('quietStartMinute', 1439), ('quietEndMinute', 1439), ('minimumGapSec', 900)]:
        if type(value[key]) is not int or not 0 <= value[key] <= maximum:
            raise ValueError('Invalid notification time')
    if value['quietEnabled'] and value['quietStartMinute'] == value['quietEndMinute']:
        raise ValueError('Quiet interval must have two distinct boundaries')
    for key in ('focusUntil', 'updatedAt'):
        if value[key] is not None:
            instant(value[key])


class NotificationPolicy:
    def __init__(self, wall_clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
        self.lock = threading.Lock()
        self.wall_clock, self.monotonic = wall_clock, monotonic
        self.reset()

    def reset(self):
        with self.lock:
            self.value = copy.deepcopy(DEFAULT)
            self.last_interrupt = -float('inf')
            self.synced = False

    def apply(self, value):
        validate(value)
        with self.lock:
            if value['version'] < self.value['version']:
                raise ValueError('Policy version regressed')
            if self.synced and value['version'] == self.value['version'] and value != self.value:
                raise ValueError('Policy content changed without a new version')
            self.value = copy.deepcopy(value)
            self.synced = True

    def _reason(self, now):
        value = self.value
        if value['focusUntil'] and instant(value['focusUntil']) > now:
            return 'Tập trung đến ' + instant(value['focusUntil']).astimezone(VIETNAM).strftime('%H:%M %d/%m')
        minute = now.astimezone(VIETNAM).hour * 60 + now.astimezone(VIETNAM).minute
        start, end = value['quietStartMinute'], value['quietEndMinute']
        quiet = start <= minute < end if start < end else minute >= start or minute < end
        if value['quietEnabled'] and quiet:
            return f'Giờ yên lặng đến {end//60:02d}:{end%60:02d} (giờ Việt Nam)'
        return ''

    def decide(self):
        with self.lock:
            reason = self._reason(self.wall_clock())
            now = self.monotonic()
            if not reason and now - self.last_interrupt < self.value['minimumGapSec']:
                reason = 'Đang giãn cách thông báo; sự kiện vẫn được ghi nhận'
            result = {key: self.value[key] and not reason for key in ('toast', 'sound', 'popup')}
            if any(result.values()):
                self.last_interrupt = now
            return dict(result, reason=reason)

    def status(self):
        with self.lock:
            prefix = f"Chính sách nhắc đã nạp v{self.value['version']}." if self.synced else 'Chưa nhận chính sách nhắc từ server; dùng mặc định.'
            reason = self._reason(self.wall_clock())
            return prefix + (' ' + reason + '.' if reason else '')
