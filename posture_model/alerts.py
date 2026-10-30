"""
Cơ chế cảnh báo (giai đoạn 1 – Desktop App).

- AlertTracker   : state machine cho 1 nhánh (cổ/thân, lệch vai, quá gần màn hình)
                   -> ALERT_STARTED / ALERT_REPEATED / ALERT_RESOLVED (kèm thời lượng ngồi sai)
- PresenceTracker: USER_AWAY / USER_BACK khi mất / thấy lại người
- Reminders      : SIT_TOO_LONG (ngồi liên tục quá lâu), EYE_BREAK (quy tắc 20-20-20)
- EventLog       : gắn eventId, thời gian, phiên, thiết bị... rồi ghi JSONL (outbox cho giai đoạn 2)

Trạng thái dùng chung chuỗi với code cũ: "..." (chưa rõ), "GOOD", "BAD", "CANH BAO".
Mọi hàm update(...) nhận `now` = số giây kể từ lúc bắt đầu (đồng hồ của vòng lặp camera).
"""
import json
import os
import platform
import threading
import time
import uuid
from datetime import datetime, timezone

SEVERITY = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}


class AlertTracker:
    """
    bad = True / False / None (None = không chắc, ví dụ đang ở vùng trễ hysteresis -> giữ nguyên).

      "..." / GOOD --BAD liên tục >= alert_sec--> CANH BAO      => ALERT_STARTED  (level 1)
      CANH BAO     --vẫn BAD sau repeat_sec-----> CANH BAO      => ALERT_REPEATED (level +1, tối đa 3)
      CANH BAO     --GOOD liên tục >= clear_sec-> GOOD          => ALERT_RESOLVED (durationSec)

    durationSec = từ lúc BẮT ĐẦU ngồi sai (không phải lúc bật cảnh báo) tới lúc BẮT ĐẦU ngồi đúng lại.
    cooldown_sec: 2 lần ALERT_STARTED cùng loại gần nhau hơn cooldown thì sự kiện vẫn được ghi (để thống kê)
    nhưng notify=False (không bật thông báo cho đỡ phiền).
    """

    def __init__(self, alert_type, alert_sec=5, clear_sec=3, repeat_sec=240, cooldown_sec=60, max_level=3):
        self.alert_type = alert_type
        self.alert_sec, self.clear_sec = alert_sec, clear_sec
        self.repeat_sec, self.cooldown_sec, self.max_level = repeat_sec, cooldown_sec, max_level
        self.status = "..."
        self.bad_since = self.good_since = None
        self.alert_started = None      # thời điểm bắt đầu ngồi sai của đợt cảnh báo hiện tại
        self.last_notify = None
        self.last_start_notify = -1e9
        self.level = 0
        self.count = 0                 # số đợt cảnh báo trong phiên

    # ------------------------------------------------------------------
    def configure(self, **kw):
        for k, v in kw.items():
            if v is not None and hasattr(self, k):
                setattr(self, k, v)

    @property
    def alerting(self):
        return self.status == "CANH BAO"

    def _ev(self, kind, now, **extra):
        e = dict(eventType=kind, alertType=self.alert_type, t=now,
                 severity=SEVERITY.get(max(self.level, 1), "LOW"), level=max(self.level, 1))
        e.update(extra)
        return e

    def update(self, bad, now):
        """Trả về danh sách sự kiện (thường rỗng)."""
        events = []
        if bad is True:
            self.good_since = None
            if self.bad_since is None:
                self.bad_since = now
            if not self.alerting:
                if now - self.bad_since >= self.alert_sec:
                    self.status, self.level, self.alert_started = "CANH BAO", 1, self.bad_since
                    self.count += 1
                    notify = now - self.last_start_notify >= self.cooldown_sec
                    if notify:
                        self.last_start_notify = now
                    self.last_notify = now
                    events.append(self._ev("ALERT_STARTED", now, startedAt=self.alert_started, notify=notify))
                else:
                    self.status = "BAD"
            elif self.repeat_sec and now - self.last_notify >= self.repeat_sec:
                self.level = min(self.level + 1, self.max_level)
                self.last_notify = now
                events.append(self._ev("ALERT_REPEATED", now, startedAt=self.alert_started,
                                       durationSec=round(now - self.alert_started, 1), notify=True))
        elif bad is False:
            self.bad_since = None
            if self.good_since is None:
                self.good_since = now
            if now - self.good_since >= self.clear_sec:
                if self.alerting:
                    events.append(self._resolved(now, end=self.good_since, reason="CORRECTED"))
                self.status = "GOOD"
        return events

    def _resolved(self, now, end, reason):
        e = self._ev("ALERT_RESOLVED", now, startedAt=self.alert_started, endedAt=end,
                     durationSec=round(end - self.alert_started, 1), reason=reason, notify=False)
        self.alert_started, self.level, self.last_notify = None, 0, None
        return e

    def reset(self, now=None, reason="RESET"):
        """Hiệu chỉnh lại / người dùng rời đi: đóng đợt cảnh báo đang mở (nếu có) rồi về trạng thái '...'."""
        events = []
        if self.alerting and now is not None:
            events.append(self._resolved(now, end=now, reason=reason))
        self.status, self.bad_since, self.good_since = "...", None, None
        self.alert_started, self.level, self.last_notify = None, 0, None
        return events


class PresenceTracker:
    """Không thấy người liên tục >= away_sec -> USER_AWAY; thấy lại -> USER_BACK (kèm số giây vắng)."""

    def __init__(self, away_sec=30):
        self.away_sec = away_sec
        self.last_seen = None
        self.away = False
        self.away_from = None

    def update(self, present, now):
        events = []
        if present:
            if self.away:
                events.append(dict(eventType="USER_BACK", t=now, awaySec=round(now - self.away_from, 1)))
                self.away = False
            self.last_seen = now
        else:
            if self.last_seen is None:
                self.last_seen = now
            if not self.away and now - self.last_seen >= self.away_sec:
                self.away, self.away_from = True, self.last_seen
                events.append(dict(eventType="USER_AWAY", t=now, startedAt=self.last_seen))
        return events


# Mốc phút ngồi để tăng mức nhắc SIT_TOO_LONG: < 60 LOW/1, 60–89 MEDIUM/2, >= 90 HIGH/3 [S9][S10].
SIT_LEVEL_MIN = (60, 90)


class Reminders:
    """
    Nhắc theo thời gian ngồi (không cần AI):
      SIT_TOO_LONG: ngồi liên tục >= sit_limit_min phút, sau đó nhắc lại mỗi sit_repeat_min phút.
                    Mức tăng theo số phút đã ngồi (SIT_LEVEL_MIN): < 60 LOW/1, 60–89 MEDIUM/2, >= 90 HIGH/3.
      EYE_BREAK   : mỗi eye_break_min phút ngồi -> nhắc nhìn xa 20 giây.
    Rời ghế (USER_AWAY) thì cả hai đồng hồ đặt lại.
    """

    def __init__(self, sit_limit_min=30, sit_repeat_min=10, eye_break_min=20):
        self.sit_limit_min, self.sit_repeat_min, self.eye_break_min = sit_limit_min, sit_repeat_min, eye_break_min
        self.sit_start = None
        self.next_sit = None
        self.next_eye = None

    def configure(self, **kw):
        for k, v in kw.items():
            if v is not None and hasattr(self, k):
                setattr(self, k, v)
        if self.sit_start is not None:              # tính lại mốc theo cấu hình mới
            self.next_sit = self.sit_start + self.sit_limit_min * 60
            self.next_eye = self.sit_start + self.eye_break_min * 60

    def start(self, now):
        self.sit_start = now
        self.next_sit = now + self.sit_limit_min * 60 if self.sit_limit_min else None
        self.next_eye = now + self.eye_break_min * 60 if self.eye_break_min else None

    def stop(self):
        self.sit_start = self.next_sit = self.next_eye = None

    def sitting_sec(self, now):
        return 0.0 if self.sit_start is None else now - self.sit_start

    def update(self, now):
        events = []
        if self.sit_start is None:
            return events
        if self.next_sit is not None and now >= self.next_sit:
            mins = (now - self.sit_start) / 60
            level = 1 + sum(mins >= m for m in SIT_LEVEL_MIN)
            events.append(dict(eventType="REMINDER", alertType="SIT_TOO_LONG", t=now, sittingMin=round(mins, 1),
                               severity=("LOW", "MEDIUM", "HIGH")[level - 1], level=level, notify=True))
            self.next_sit = now + max(self.sit_repeat_min, 1) * 60
        if self.next_eye is not None and now >= self.next_eye:
            events.append(dict(eventType="REMINDER", alertType="EYE_BREAK", t=now, severity="LOW", level=1, notify=True))
            self.next_eye = now + self.eye_break_min * 60
        return events


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventLog:
    """
    Chuẩn hoá sự kiện theo schema trong kế hoạch rồi ghi 1 dòng JSON / sự kiện vào `path` (outbox).
    Giai đoạn 2, thread Sender sẽ đọc file / hàng đợi này để gửi lên server.

    wall_t0: thời điểm thật (epoch) ứng với now = 0 -> đổi `t` (giây trong phiên) sang ISO-8601 UTC.
    """

    APP_VERSION = "1.0.0"

    def __init__(self, path, model_version, wall_t0=None, user_id=None, device_id=None, listeners=()):
        self.path = path
        self.wall_t0 = time.time() if wall_t0 is None else wall_t0
        self.session_id = "s_" + uuid.uuid4().hex[:12]
        self.device_id = device_id or "dev_" + uuid.uuid5(uuid.NAMESPACE_DNS, platform.node() or "pc").hex[:12]
        self.user_id = user_id
        self.model_version = model_version
        self.listeners = list(listeners)
        self.recent = []                 # vài sự kiện gần nhất để vẽ lên màn hình
        self._lock = threading.Lock()
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._f = open(path, "a", encoding="utf-8")
        else:
            self._f = None

    def iso(self, t):
        return None if t is None else _iso(self.wall_t0 + t)

    def emit(self, ev, snapshot=None, config=None):
        e = dict(ev)
        t = e.pop("t", None)
        out = {
            "eventId": str(uuid.uuid4()),
            "eventType": e.pop("eventType"),
            "userId": self.user_id,
            "deviceId": self.device_id,
            "sessionId": self.session_id,
            "ts": self.iso(t),
        }
        for k in ("startedAt", "endedAt"):
            if k in e:
                e[k] = self.iso(e[k])
        out.update(e)
        if snapshot is not None and out["eventType"].startswith("ALERT"):
            out["snapshot"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in snapshot.items()}
        out["modelVersion"] = self.model_version
        out["appVersion"] = self.APP_VERSION
        if config is not None:
            out["config"] = config
        with self._lock:
            if self._f:
                self._f.write(json.dumps(out, ensure_ascii=False) + "\n")
                self._f.flush()
            self.recent = (self.recent + [out])[-20:]
        for fn in self.listeners:
            try:
                fn(out)
            except Exception as exc:                 # thông báo lỗi không được làm dừng vòng lặp camera
                print("listener lỗi:", exc)
        return out

    def emit_all(self, events, snapshot=None, config=None):
        return [self.emit(e, snapshot, config) for e in events]

    def close(self):
        if self._f:
            self._f.close()
            self._f = None
