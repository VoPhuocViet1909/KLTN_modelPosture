"""
Lịch sử cảnh báo (/alerts/*) và thống kê (/stats/*) cho mock_server.py, tính lại từ dữ liệu đã nhận.
Làm theo cùng quy tắc với alert-service và analytics-service của backend (xem openapi.yaml v1.5):
  - phiên không có SESSION_END đóng sau 3 phút không có dữ liệu (endReason TIMEOUT, endedAt = dữ liệu cuối);
  - cảnh báo không có ALERT_RESOLVED kết thúc cùng phiên (SESSION_END / SESSION_TIMEOUT);
  - điểm trung bình có trọng số theo presenceSec; ngày và heatmap tính theo giờ Việt Nam (UTC+7).
Chỉ dùng thư viện chuẩn.
"""
import re
from datetime import datetime, timedelta, timezone

VN = timezone(timedelta(hours=7))
SESSION_TIMEOUT = timedelta(minutes=3)
DEFAULT_RANGE, MAX_RANGE = timedelta(days=7), timedelta(days=92)
ALERT_TYPE = re.compile(r"[A-Z][A-Z0-9_]{0,39}")
ALERT_EVENTS = ("ALERT_STARTED", "ALERT_REPEATED", "ALERT_RESOLVED")


class QueryError(Exception):
    """Tham số sai -> 400 VALIDATION_FAILED, field = tên tham số."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def parse_time(text):
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt(dt):
    """Giống Instant của Java: ...Z, phần lẻ giây chỉ khi khác 0."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        spec = "seconds"
    elif dt.microsecond % 1000 == 0:
        spec = "milliseconds"
    else:
        spec = "microseconds"
    return dt.isoformat(timespec=spec).replace("+00:00", "Z")


# ---------------------------------------------------------------- tham số
def _one(q, name):
    v = q.get(name)
    return v[0] if v else None


def time_range(q, now):
    def parse(field):
        text = _one(q, field)
        if text is None:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is None or dt.tzinfo is None:
            raise QueryError(field, "must be an ISO-8601 timestamp with offset")
        return dt
    end = parse("to") or now
    start = parse("from") or end - DEFAULT_RANGE
    if not start < end or end - start > MAX_RANGE:
        raise QueryError("from", "range must be positive and at most 92 days")
    return start, end


def paging(q):
    def integer(field, default, low, high, message):
        text = _one(q, field)
        if text is None:
            return default
        try:
            v = int(text)
        except ValueError:
            raise QueryError(field, message)
        if not low <= v <= high:
            raise QueryError(field, f"must be between {low} and {high}")
        return v
    return (integer("page", 0, 0, 10_000, "must be an integer of at least 0"),
            integer("size", 20, 1, 100, "must be an integer between 1 and 100"))


def alert_type(q):
    v = _one(q, "alertType")
    if v is not None and not ALERT_TYPE.fullmatch(v):
        raise QueryError("alertType", "must be an alert type such as NECK_TRUNK")
    return v


def _page(items, page, size):
    return {"items": items[page * size:(page + 1) * size], "page": page, "size": size, "total": len(items)}


# ---------------------------------------------------------------- phiên và cảnh báo
def build_sessions(events, metrics, now):
    """events / metrics: các dict đã nhận, có thêm _receivedUserId. -> {(user, device, session): phiên}"""
    out = {}

    def touch(user, item, ts):
        key = (user, item["deviceId"], item["sessionId"])
        s = out.setdefault(key, {"startedAt": None, "endedAt": None, "lastSeen": ts})
        s["lastSeen"] = max(s["lastSeen"], ts)
        return s
    for e in events:
        ts = parse_time(e["ts"])
        s = touch(e.get("_receivedUserId"), e, ts)
        if e["eventType"] == "SESSION_START":
            s["startedAt"] = ts if s["startedAt"] is None else min(s["startedAt"], ts)
        elif e["eventType"] == "SESSION_END":
            s["endedAt"] = ts if s["endedAt"] is None else max(s["endedAt"], ts)
    for m in metrics:
        touch(m.get("_receivedUserId"), m, parse_time(m["windowStart"]))
    for s in out.values():
        if s["endedAt"] is not None:
            s["endReason"] = "SESSION_END"
        elif now - s["lastSeen"] > SESSION_TIMEOUT:
            s["endedAt"], s["endReason"] = s["lastSeen"], "TIMEOUT"
        else:
            s["endReason"] = None
    return out


def build_alerts(events, sessions):
    groups = {}
    for e in events:
        if e["eventType"] not in ALERT_EVENTS or not e.get("startedAt"):
            continue
        user = e.get("_receivedUserId")
        started = parse_time(e["startedAt"])
        key = (user, e["deviceId"], e["sessionId"], e["alertType"], started)
        a = groups.setdefault(key, {"severity": None, "severityAt": None, "endedAt": None, "reason": None,
                                    "repeatCount": 0})
        ts = parse_time(e["ts"])
        if e.get("severity") and (a["severityAt"] is None or ts >= a["severityAt"]):
            a["severity"], a["severityAt"] = e["severity"], ts
        if e["eventType"] == "ALERT_REPEATED":
            a["repeatCount"] += 1
        if e["eventType"] == "ALERT_RESOLVED":
            ended = parse_time(e["endedAt"])
            if a["endedAt"] is None or ended >= a["endedAt"]:
                a["endedAt"], a["reason"] = ended, e.get("reason")
    out = []
    for (user, device, session, kind, started), a in groups.items():
        s = sessions.get((user, device, session), {})
        ended, reason = a["endedAt"], a["reason"]
        if ended is None and s.get("endedAt") is not None:
            ended = max(started, s["endedAt"])
            reason = "SESSION_TIMEOUT" if s["endReason"] == "TIMEOUT" else "SESSION_END"
        out.append({"userId": user, "deviceId": device, "sessionId": session, "alertType": kind,
                    "severity": a["severity"], "startedAt": started, "endedAt": ended,
                    "durationSec": None if ended is None else int(ended.timestamp()) - int(started.timestamp()),
                    "endReason": reason, "repeatCount": a["repeatCount"], "open": ended is None})
    return out


def alerts_page(events, metrics, now, q, users):
    """users: tập userId trong phạm vi (người gọi, hoặc cả tổ chức)."""
    start, end = time_range(q, now)
    kind = alert_type(q)
    page, size = paging(q)
    items = [a for a in build_alerts(events, build_sessions(events, metrics, now))
             if a["userId"] in users and start <= a["startedAt"] < end and (kind is None or a["alertType"] == kind)]
    items.sort(key=lambda a: (a["deviceId"], a["sessionId"], a["alertType"]))
    items.sort(key=lambda a: a["startedAt"], reverse=True)
    return _page([_times(a, "startedAt", "endedAt") for a in items], page, size)


def sessions_page(events, metrics, now, q, user):
    start, end = time_range(q, now)
    page, size = paging(q)
    sessions = build_sessions(events, metrics, now)
    counts = {}
    for a in build_alerts(events, sessions):
        k = (a["userId"], a["deviceId"], a["sessionId"])
        counts[k] = counts.get(k, 0) + 1
    items = []
    for (u, device, session), s in sessions.items():
        first = s["startedAt"] or s["lastSeen"]
        if u == user and s["lastSeen"] >= start and first < end:
            items.append({"deviceId": device, "sessionId": session, "startedAt": s["startedAt"],
                          "endedAt": s["endedAt"], "endReason": s["endReason"], "lastSeenAt": s["lastSeen"],
                          "open": s["endedAt"] is None, "alertCount": counts.get((u, device, session), 0),
                          "_first": first})
    items.sort(key=lambda s: (s["deviceId"], s["sessionId"]))
    items.sort(key=lambda s: s["_first"], reverse=True)
    for s in items:
        s.pop("_first")
    return _page([_times(s, "startedAt", "endedAt", "lastSeenAt") for s in items], page, size)


def _times(row, *names):
    return {k: (fmt(v) if k in names and v is not None else v) for k, v in row.items()}


# ---------------------------------------------------------------- thống kê
def _measures(rows):
    scored = [m for m in rows if m.get("postureScore") is not None]
    weight = sum(m["presenceSec"] for m in scored)
    alerts = {}
    for m in rows:
        for k, v in (m.get("alertCount") or {}).items():
            alerts[k] = alerts.get(k, 0) + v
    return {"meanScore": sum(m["postureScore"] * m["presenceSec"] for m in scored) / weight if weight else None,
            "badMinutes": sum((1 - m["goodRatio"]) * m["presenceSec"] for m in rows
                              if m.get("goodRatio") is not None) / 60,
            "presenceMinutes": sum(m["presenceSec"] for m in rows) / 60,
            "alerts": dict(sorted(alerts.items()))}


def _in_range(metrics, users, start, end):
    return [m for m in metrics if m.get("_receivedUserId") in users and start <= parse_time(m["windowStart"]) < end]


def summary(metrics, now, q, users):
    start, end = time_range(q, now)
    return _measures(_in_range(metrics, users, start, end))


def timeseries(metrics, now, q, user):
    bucket = _one(q, "bucket") or "day"
    if bucket not in ("hour", "day"):
        raise QueryError("bucket", "must be hour or day")
    start, end = time_range(q, now)
    groups = {}
    for m in _in_range(metrics, {user}, start, end):
        ws = parse_time(m["windowStart"])
        if bucket == "hour":
            key = ws.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        else:
            key = ws.astimezone(VN).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        groups.setdefault(key, []).append(m)
    return [dict({"start": fmt(k)}, **_measures(v)) for k, v in sorted(groups.items())]


def heatmap(metrics, now, q, user):
    text = _one(q, "weeks") or "4"
    try:
        weeks = int(text)
    except ValueError:
        raise QueryError("weeks", "must be an integer between 1 and 12")
    if not 1 <= weeks <= 12:
        raise QueryError("weeks", "must be between 1 and 12")
    cells = {}
    for m in _in_range(metrics, {user}, now - timedelta(days=7 * weeks), now):
        if m.get("postureScore") is None:
            continue
        local = parse_time(m["windowStart"]).astimezone(VN)
        c = cells.setdefault((local.isoweekday(), local.hour), [0.0, 0.0])
        c[0] += m["postureScore"] * m["presenceSec"]
        c[1] += m["presenceSec"]
    return [{"weekday": d, "hour": h,
             "meanScore": (cells[(d, h)][0] / cells[(d, h)][1]) if cells.get((d, h)) and cells[(d, h)][1] else None}
            for d in range(1, 8) for h in range(24)]
