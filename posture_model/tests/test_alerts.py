"""Kiểm thử logic cảnh báo (không cần camera):  python -m pytest tests -q   hoặc   python tests/test_alerts.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from alerts import AlertTracker, EventLog, PresenceTracker, Reminders  # noqa: E402
from app_config import AppConfig  # noqa: E402


def run(tr, seq, dt=0.1, t0=0.0):
    """seq: list (giá trị bad, số giây). Trả về list sự kiện và thời điểm kết thúc."""
    evs, t = [], t0
    for bad, sec in seq:
        for _ in range(int(round(sec / dt))):
            t += dt
            evs += tr.update(bad, round(t, 3))
    return evs, t


def kinds(evs):
    return [e["eventType"] for e in evs]


def test_short_bad_no_alert():
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3)
    evs, _ = run(tr, [(False, 4), (True, 4), (False, 4)])      # vươn vai 4 giây < 5 giây
    assert evs == [] and tr.status == "GOOD"


def test_started_then_resolved_with_duration():
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3, repeat_sec=0)
    evs, _ = run(tr, [(False, 4), (True, 20), (False, 5)])
    assert kinds(evs) == ["ALERT_STARTED", "ALERT_RESOLVED"]
    s, r = evs
    assert abs(s["startedAt"] - 4.1) < 1e-6 and abs(s["t"] - 9.1) < 1e-6
    assert abs(r["durationSec"] - 20.0) < 0.11                 # ngồi sai 20 giây
    assert r["reason"] == "CORRECTED" and tr.status == "GOOD"


def test_repeat_escalates_to_high():
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3, repeat_sec=60)
    evs, _ = run(tr, [(True, 5 + 60 * 3 + 1)])
    assert kinds(evs) == ["ALERT_STARTED", "ALERT_REPEATED", "ALERT_REPEATED", "ALERT_REPEATED"]
    assert [e["severity"] for e in evs] == ["LOW", "MEDIUM", "HIGH", "HIGH"]


def test_uncertain_keeps_state():
    tr = AlertTracker("SHOULDER_TILT", alert_sec=5, clear_sec=3, repeat_sec=0)
    evs, _ = run(tr, [(True, 6), (None, 30), (False, 1)])      # vùng trễ hysteresis -> giữ cảnh báo
    assert kinds(evs) == ["ALERT_STARTED"] and tr.alerting


def test_brief_good_does_not_resolve():
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3, repeat_sec=0)
    evs, _ = run(tr, [(True, 6), (False, 2), (True, 3)])       # thẳng lưng 2 giây rồi gù tiếp
    assert kinds(evs) == ["ALERT_STARTED"] and tr.alerting


def test_cooldown_records_but_does_not_notify():
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3, repeat_sec=0, cooldown_sec=60)
    evs, _ = run(tr, [(True, 6), (False, 4), (True, 6), (False, 4)])
    starts = [e for e in evs if e["eventType"] == "ALERT_STARTED"]
    assert len(starts) == 2 and starts[0]["notify"] and not starts[1]["notify"]
    assert tr.count == 2


def test_reset_closes_open_alert():
    tr = AlertTracker("TOO_CLOSE", alert_sec=5, clear_sec=3)
    evs, t = run(tr, [(True, 8)])
    evs += tr.reset(t, "AWAY")
    assert kinds(evs) == ["ALERT_STARTED", "ALERT_RESOLVED"] and evs[-1]["reason"] == "AWAY"
    assert tr.status == "..."


def test_presence():
    p = PresenceTracker(away_sec=30)
    evs = []
    t = 0.0
    for present, sec in [(True, 10), (False, 40), (True, 2)]:
        for _ in range(int(sec * 10)):
            t += 0.1
            evs += p.update(present, round(t, 3))
    assert kinds(evs) == ["USER_AWAY", "USER_BACK"]
    assert abs(evs[1]["awaySec"] - 40) < 0.2


def test_reminders():
    r = Reminders(sit_limit_min=50, sit_repeat_min=10, eye_break_min=20)
    r.start(0)
    evs = []
    for m in range(0, 71):
        evs += r.update(m * 60.0)
    types = [e["alertType"] for e in evs]
    assert types.count("EYE_BREAK") == 3                     # phút 20, 40, 60
    assert types.count("SIT_TOO_LONG") == 3                  # phút 50, 60, 70


def test_eventlog_schema_and_config_reload():
    d = tempfile.mkdtemp()
    log = EventLog(os.path.join(d, "ev.jsonl"), "v3", wall_t0=1_790_000_000.0)
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3)
    evs, _ = run(tr, [(True, 6)])
    out = log.emit_all(evs, snapshot={"pBad": 0.912345, "neck": 24.3}, config={"alertSec": 5})
    log.close()
    line = json.loads(open(os.path.join(d, "ev.jsonl"), encoding="utf-8").readline())
    for k in ("eventId", "eventType", "deviceId", "sessionId", "ts", "alertType", "severity", "startedAt",
              "snapshot", "modelVersion", "appVersion", "config"):
        assert k in line, k
    assert line["ts"].endswith("Z") and line["snapshot"]["pBad"] == 0.91 and out[0]["eventId"] == line["eventId"]

    path = os.path.join(d, "app_config.json")
    cfg = AppConfig(path, {"threshold": 0.5, "shoulder_tilt_on": 3.5, "shoulder_tilt_off": 2.5})
    assert cfg["p_bad_threshold"] == 0.5 and cfg["alert_sec"] == 5
    data = json.load(open(path, encoding="utf-8"))
    data["alert_sec"] = 10
    json.dump(data, open(path, "w", encoding="utf-8"))
    os.utime(path, (2_000_000_000, 2_000_000_000))
    assert cfg.reload() == {"alert_sec"} and cfg["alert_sec"] == 10


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK ", fn.__name__)
    print(f"{len(fns)}/{len(fns)} test đạt")
