"""
Sinh dữ liệu đúng hợp đồng v1.0 (dùng chung cho contract_test.py và replay.py). Chỉ cần thư viện chuẩn.
Mỗi lần gọi tạo id mới, nên gửi nhiều lần không bị coi là trùng (trừ khi cố ý gửi lại).
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

APP_VERSION, MODEL_VERSION = "1.0.0", "v3"
CONFIG_SNAPSHOT = {"alertSec": 5, "clearSec": 3, "repeatSec": 240, "pBadThreshold": 0.5,
                   "shoulderTiltOn": 3.5, "distanceOnCm": 50}


def iso(dt, ms=True):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds" if ms else "seconds").replace("+00:00", "Z")


class Device:
    """Một Desktop App giả: giữ deviceId / sessionId, sinh sự kiện và metrics hợp lệ."""

    def __init__(self, device_id=None, user_id=None, seed=None):
        self.rng = random.Random(seed)
        self.device_id = device_id or "dev_" + uuid.uuid4().hex[:12]
        self.session_id = "s_" + uuid.uuid4().hex[:12]
        self.user_id = user_id

    def _base(self, event_type, ts):
        return {"eventId": str(uuid.uuid4()), "eventType": event_type, "userId": self.user_id,
                "deviceId": self.device_id, "sessionId": self.session_id, "ts": iso(ts),
                "modelVersion": MODEL_VERSION, "appVersion": APP_VERSION}

    def snapshot(self, bad):
        r = self.rng
        return {"pBad": round(r.uniform(0.7, 1.0) if bad else r.uniform(0.0, 0.3), 2),
                "neck": round(r.uniform(18, 35) if bad else r.uniform(-3, 8), 2),
                "trunk": round(r.uniform(8, 20) if bad else r.uniform(-3, 4), 2),
                "headPitch": round(r.uniform(5, 15) if bad else r.uniform(-3, 4), 2),
                "rulaB": 1 if bad else 0, "tiltRel": round(r.uniform(-2, 2), 2),
                "distanceCm": round(r.uniform(45, 70), 1)}

    # ---------------------------------------------------------------- từng loại sự kiện
    def session_start(self, ts):
        return dict(self._base("SESSION_START", ts), frontCam=True, distanceMethod="iris")

    def calibrated(self, ts):
        return dict(self._base("CALIBRATED", ts), side="left",
                    baseline={"neck": 24.6, "trunk": -5.8, "headPitch": -1.8},
                    shoulderTiltBase=-0.8, distanceCm=58.0, distanceMethod="iris", focalPx=612.0)

    def alert_pair(self, start, bad_sec, alert_type="NECK_TRUNK", repeat=False):
        """ALERT_STARTED (+ ALERT_REPEATED) + ALERT_RESOLVED khớp nhau."""
        started = dict(self._base("ALERT_STARTED", start + timedelta(seconds=5)), alertType=alert_type,
                       severity="LOW", level=1, startedAt=iso(start), snapshot=self.snapshot(True),
                       config=CONFIG_SNAPSHOT)
        out = [started]
        if repeat:
            out.append(dict(self._base("ALERT_REPEATED", start + timedelta(seconds=245)), alertType=alert_type,
                            severity="MEDIUM", level=2, startedAt=iso(start), durationSec=245.0,
                            snapshot=self.snapshot(True), config=CONFIG_SNAPSHOT))
        end = start + timedelta(seconds=bad_sec)
        out.append(dict(self._base("ALERT_RESOLVED", end + timedelta(seconds=3)), alertType=alert_type,
                        severity="LOW", level=1, startedAt=iso(start), endedAt=iso(end),
                        durationSec=round(float(bad_sec), 1), reason="CORRECTED",
                        snapshot=self.snapshot(False), config=CONFIG_SNAPSHOT))
        return out

    def away_back(self, ts, away_sec=60):
        return [dict(self._base("USER_AWAY", ts + timedelta(seconds=30)), startedAt=iso(ts)),
                dict(self._base("USER_BACK", ts + timedelta(seconds=away_sec)), awaySec=float(away_sec))]

    def reminder(self, ts, kind="EYE_BREAK"):
        e = dict(self._base("REMINDER", ts), alertType=kind, severity="LOW" if kind == "EYE_BREAK" else "MEDIUM",
                 level=1 if kind == "EYE_BREAK" else 2)
        if kind == "SIT_TOO_LONG":
            e["sittingMin"] = 50.0
        return e

    def config_applied(self, ts):
        return dict(self._base("CONFIG_APPLIED", ts), changedKeys=["alert_sec"])

    def session_end(self, ts, duration=3600.0):
        return dict(self._base("SESSION_END", ts), durationSec=duration, alertCount={"NECK_TRUNK": 1})

    def all_event_types(self, now=None):
        now = now or datetime.now(timezone.utc)
        t = lambda s: now - timedelta(seconds=600 - s)
        return ([self.session_start(t(0)), self.calibrated(t(10))] + self.alert_pair(t(60), 300, repeat=True)
                + self.away_back(t(400)) + [self.reminder(t(500)), self.reminder(t(510), "SIT_TOO_LONG"),
                                            self.config_applied(t(520)), self.session_end(t(590), 590.0)])

    # ---------------------------------------------------------------- metrics
    def metric(self, window_start, bad_ratio=None, alerts=None):
        """alerts: {alertType: số lần bật cảnh báo trong phút}; None = tự đoán theo goodRatio."""
        r = self.rng
        good = round(1 - (bad_ratio if bad_ratio is not None else r.uniform(0, 0.5)), 3)
        ws = window_start.replace(second=0, microsecond=0)
        if alerts is None:
            alerts = {"NECK_TRUNK": 1} if good < 0.7 else {}
        score = max(0, min(100, round(100 * (0.6 * good + 0.4) - 5 * sum(alerts.values()))))
        return {"metricId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.session_id}/{int(ws.timestamp())}")),
                "userId": self.user_id, "deviceId": self.device_id, "sessionId": self.session_id,
                "windowStart": iso(ws, ms=False), "windowSec": 60, "coveredSec": 60.0, "samples": 600,
                "presenceSec": 60.0, "goodRatio": good, "pBadMean": round(1 - good, 2),
                "neckMean": round(r.uniform(2, 20), 2), "neckMax": round(r.uniform(20, 35), 2),
                "trunkMean": round(r.uniform(0, 8), 2), "trunkMax": round(r.uniform(8, 18), 2),
                "headPitchMean": round(r.uniform(-2, 10), 2), "tiltRelMean": round(r.uniform(-2, 2), 2),
                "tiltAbsMax": round(r.uniform(2, 5), 2), "shoulderBadRatio": 0.0,
                "distanceMeanCm": round(r.uniform(50, 65), 1), "distanceMinCm": round(r.uniform(44, 50), 1),
                "tooCloseRatio": 0.0, "alertCount": alerts, "postureScore": score,
                "modelVersion": MODEL_VERSION, "appVersion": APP_VERSION}

    def batch(self, events=(), metrics=()):
        return {"schemaVersion": "1.0", "deviceId": self.device_id, "sentAt": iso(datetime.now(timezone.utc)),
                "events": list(events), "metrics": list(metrics)}
