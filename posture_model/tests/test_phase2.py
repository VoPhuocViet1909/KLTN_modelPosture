"""Kiểm thử giai đoạn 2 (schema, outbox, sender + mất mạng, metrics):  python tests/test_phase2.py"""
import json
import os
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from alerts import AlertTracker, EventLog, PresenceTracker, Reminders  # noqa: E402
from metrics import MetricsAggregator, aggregate_log  # noqa: E402
from mock_server import serve  # noqa: E402
from outbox import Outbox  # noqa: E402
from schema import validate  # noqa: E402
from sender import Sender  # noqa: E402


def tmp():
    return tempfile.mkdtemp()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_events(log):
    """Sinh đủ các loại sự kiện thật từ alerts.py."""
    out = [log.emit(dict(eventType="SESSION_START", t=0.0, frontCam=False))]
    tr = AlertTracker("NECK_TRUNK", alert_sec=5, clear_sec=3, repeat_sec=10)
    t = 0.0
    for bad, sec in [(True, 17), (False, 4)]:
        for _ in range(int(sec * 10)):
            t += 0.1
            out += log.emit_all(tr.update(bad, round(t, 2)), snapshot={"pBad": 0.9, "neck": 25.0, "rulaB": 1})
    p = PresenceTracker(away_sec=5)
    for present, sec in [(False, 6), (True, 1)]:
        for _ in range(int(sec * 10)):
            t += 0.1
            out += log.emit_all(p.update(present, round(t, 2)))
    r = Reminders(sit_limit_min=1, eye_break_min=1)
    r.start(t)
    out += log.emit_all(r.update(t + 61))
    out.append(log.emit(dict(eventType="CONFIG_APPLIED", t=t, changedKeys=["alert_sec"])))
    out.append(log.emit(dict(eventType="SESSION_END", t=t, durationSec=round(t, 1), alertCount={"NECK_TRUNK": 1})))
    return out


# ------------------------------------------------------------------ schema
def test_schema_accepts_real_events():
    log = EventLog(None, "v3")
    evs = make_events(log)
    types = {e["eventType"] for e in evs}
    assert {"ALERT_STARTED", "ALERT_REPEATED", "ALERT_RESOLVED", "USER_AWAY", "USER_BACK", "REMINDER"} <= types
    for e in evs:
        e = {k: v for k, v in e.items() if k != "notify"}
        assert validate("event", e) == [], (e["eventType"], validate("event", e))


def test_schema_rejects_bad_events():
    log = EventLog(None, "v3")
    e = log.emit(dict(eventType="ALERT_RESOLVED", t=1.0, alertType="NECK_TRUNK", startedAt=0.0, endedAt=1.0,
                      reason="CORRECTED"))                     # thiếu durationSec
    assert any("durationSec" in x for x in validate("event", e))
    e2 = dict(e, durationSec=1.0, severity="CRITICAL")
    assert any("severity" in x for x in validate("event", e2))
    assert validate("event", dict(e2, severity="LOW", eventId="khong-phai-uuid"))
    assert validate("config", {"alert_sec": -1}) and validate("config", {"alert_sec": 5}) == []


# ------------------------------------------------------------------ outbox
def test_outbox_dedupe_order_backoff():
    ob = Outbox(os.path.join(tmp(), "o.db"))
    ob.put("event", "a", {"x": 1})
    ob.put("event", "a", {"x": 2})                            # trùng id -> bỏ qua
    ob.put("event", "b", {"x": 3}, urgent=True)
    ob.put("metric", "c", {"x": 4})
    assert [i for i, _, _ in ob.due()] == ["b", "a", "c"]     # khẩn trước, rồi cũ trước
    ob.mark_failed(["a"], "timeout")
    assert [i for i, _, _ in ob.due()] == ["b", "c"]          # 'a' đang chờ backoff
    ob.retry_now()
    assert len(ob.due()) == 3
    ob.mark_sent(["a", "b"])
    ob.mark_dead([("c", "sai schema")])
    assert ob.stats() == {"pending": 0, "sent": 2, "dead": 1}


# ------------------------------------------------------------------ sender + server giả
def wait_until(cond, sec=10):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_sender_delivery_outage_and_recovery():
    port, d = free_port(), tmp()
    srv, store = serve(port, token="tok", folder=os.path.join(d, "srv"), quiet=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    log = EventLog(None, "v3")
    ob = Outbox(os.path.join(d, "o.db"))
    snd = Sender(ob, f"http://127.0.0.1:{port}", "tok", log.device_id, interval=0.3)
    snd.probe_sec = 0.5
    snd.start()
    evs = make_events(log)
    for e in evs:
        snd.enqueue_event(e)
    agg = MetricsAggregator(snd.enqueue_metric, log.wall_t0, log.session_id, log.device_id)
    for i in range(700):                                      # 70 giây mẫu -> 1-2 bản metrics
        agg.add(i / 10, True, "GOOD", 0.1, {"neck": 3.0, "trunk": 1.0, "head_pitch": 0.0})
    agg.flush()
    assert wait_until(lambda: snd.q.empty() and ob.stats()["pending"] == 0
                      and sum(store.by_type.values()) == len(evs)), (ob.stats(), dict(store.by_type), len(evs))
    assert store.n_metrics >= 1 and ob.stats()["dead"] == 0
    assert snd.online is True

    # ---- mất mạng: server tắt, dữ liệu phải nằm lại trong outbox
    srv.shutdown()
    srv.server_close()
    more = [log.emit(dict(eventType="USER_AWAY", t=100.0, startedAt=70.0)),
            log.emit(dict(eventType="USER_BACK", t=130.0, awaySec=60.0))]
    for e in more:
        snd.enqueue_event(e)
    assert wait_until(lambda: snd.online is False)
    assert ob.stats()["pending"] == 2

    # ---- có mạng lại: probe /health rồi gửi bù, không trùng
    srv2, store2 = serve(port, token="tok", folder=os.path.join(d, "srv"), quiet=True)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    assert wait_until(lambda: ob.stats()["pending"] == 0, 15), ob.stats()
    assert store2.by_type["USER_AWAY"] == 1 and store2.by_type["USER_BACK"] == 1

    # ---- gửi lại đúng id cũ -> server bỏ trùng; sự kiện sai schema -> bị từ chối (dead)
    snd.check_schema = False
    snd.enqueue_event(dict(evs[0], eventId="11111111-1111-4111-8111-111111111111", severity="WRONG"))
    assert wait_until(lambda: ob.stats()["dead"] == 1)
    snd.stop()
    srv2.shutdown()
    srv2.server_close()


def test_sender_wrong_token_keeps_data():
    port, d = free_port(), tmp()
    srv, _ = serve(port, token="right", folder=os.path.join(d, "srv"), quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log = EventLog(None, "v3")
    ob = Outbox(os.path.join(d, "o.db"))
    snd = Sender(ob, f"http://127.0.0.1:{port}", "wrong", log.device_id, interval=0.3)
    snd.start()
    snd.enqueue_event(log.emit(dict(eventType="SESSION_START", t=0.0, frontCam=False)))
    assert wait_until(lambda: snd.last_error == "HTTP 401")
    assert ob.stats()["pending"] == 1 and ob.stats()["dead"] == 0      # 401 không làm mất dữ liệu
    snd.stop()
    srv.shutdown()
    srv.server_close()


# ------------------------------------------------------------------ metrics
def test_metrics_windows_and_score():
    out = []
    t0 = 1_789_999_980.0                                       # chia hết cho 60 -> cửa sổ bắt đầu đúng t=0
    agg = MetricsAggregator(out.append, t0, "s1", "d1")
    for i in range(1, 1501):                                   # 150 giây, 10 mẫu/giây
        t = i / 10
        neck = "GOOD" if (t % 60) < 45 else "CANH BAO"         # mỗi phút: 45 s đúng, 15 s sai
        present = not (120 <= t < 130)                         # vắng 10 s ở phút thứ 3
        agg.add(t, present, neck, 0.2, {"neck": 5.0, "trunk": 2.0, "head_pitch": 1.0},
                tilt_rel=1.0, tilt_status="GOOD", dist_cm=60.0, dist_status="GOOD")
        if abs(t - 46.0) < 1e-6:
            agg.on_event({"eventType": "ALERT_STARTED", "alertType": "NECK_TRUNK"})
    agg.flush()
    assert len(out) == 3 and out[0]["windowStart"].endswith(":00Z")
    m = out[0]
    assert abs(m["goodRatio"] - 0.75) < 0.01 and m["alertCount"] == {"NECK_TRUNK": 1}
    # 100 × (0.6·0.75 + 0.2·1 + 0.2·1) − 5 = 80
    assert m["postureScore"] == 80, m["postureScore"]
    assert abs(out[2]["presenceSec"] - 20) < 0.3 and out[2]["coveredSec"] < 31
    for x in out:
        assert validate("metrics", x) == [], validate("metrics", x)


def test_aggregate_log_csv():
    d = tmp()
    p = os.path.join(d, "log.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("time,posture,p_bad,neck,trunk,head_pitch,vis_ear,vis_shoulder,vis_hip,rula_b,shoulder,tilt_rel,"
                "distance_cm,distance\n")
        for i in range(1, 1200):                               # 0.1 .. 119.9 s -> đúng 2 cửa sổ
            t = i / 10
            st = "CANH BAO" if 30 <= t < 40 else "GOOD"
            f.write(f"{t:.2f},{st},0.1,4.0,2.0,0.0,1,1,1,0,GOOD,0.5,58.0,GOOD\n")
    ms = aggregate_log(p, 1_789_999_980.0)
    assert len(ms) == 2 and ms[0]["alertCount"] == {"NECK_TRUNK": 1}
    assert abs(ms[0]["goodRatio"] - 50 / 60) < 0.02


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        t = time.time()
        fn()
        print(f"OK  {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)}/{len(fns)} test đạt")
