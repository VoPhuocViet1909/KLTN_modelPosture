"""Kiểm thử gửi cảnh báo xuống ESP32 bằng thiết bị giả (http.server trong luồng):  python -m pytest tests/test_iot_notifier.py"""
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import iot_config  # noqa: E402
import iot_notifier  # noqa: E402
from iot_notifier import IotClient, IotNotifier  # noqa: E402
from notifier import Notifier  # noqa: E402


class FakeDevice:
    """ESP32 giả: ghi lại (method, path, body, headers) mọi request."""

    def __init__(self, key=""):
        self.key, self.requests, self.delay = key, [], 0.0
        dev = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                dev.requests.append((self.command, self.path, json.loads(raw) if raw else None, dict(self.headers)))
                if dev.delay:
                    time.sleep(dev.delay)
                if dev.key and self.headers.get("X-Device-Key") != dev.key:
                    code, out = 401, {"ok": False, "error": "BAD_KEY"}
                elif self.path == "/ping":
                    code, out = 200, {"ok": True, "fw": "1.1.1", "rssi": -55}
                else:
                    code, out = 200, {"ok": True}
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def posted(self, path):
        return [r for r in self.requests if r[0] == "POST" and r[1] == path]


def wait_for(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def closed_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def make(url, tmp_path, clock=time.time, key="", app_cfg=None, **over):
    cfg = dict(enabled=True, url=url, key=key, timeout_sec=1.0, heartbeat_sec=15, status_every_sec=60)
    cfg.update(over)
    return IotNotifier(cfg, app_cfg=app_cfg, latency_path=str(tmp_path / "lat.csv"), clock=clock)


def ev(kind, alert="NECK_TRUNK", **kw):
    return dict(dict(eventType=kind, alertType=alert, level=1, notify=True), **kw)


# ---------------------------------------------------------------- bảng ánh xạ sự kiện -> request
def test_event_mapping(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path)
    try:
        n.on_event(ev("ALERT_STARTED", "TOO_CLOSE", snapshot=dict(distanceCm=38.5, neck=1.0)))
        n.on_event(ev("ALERT_REPEATED", level=2))
        n.on_event(ev("REMINDER", "SIT_TOO_LONG", sittingMin=61.5, level=2))
        n.on_event(dict(eventType="ALERT_RESOLVED", alertType="NECK_TRUNK", level=2, notify=False))
        n.on_event(dict(eventType="SESSION_END"))
        assert wait_for(lambda: len(dev.posted("/alert")) == 4 and len(dev.posted("/status")) == 1)
        bodies = [r[2] for r in dev.posted("/alert")]
        assert bodies[0] == dict(eventType="ALERT_STARTED", alertType="TOO_CLOSE", level=1, distanceCm=38.5)
        assert bodies[1] == dict(eventType="ALERT_REPEATED", alertType="NECK_TRUNK", level=2)
        assert bodies[2] == dict(eventType="REMINDER", alertType="SIT_TOO_LONG", level=2, sittingMin=61.5)
        assert bodies[3] == dict(eventType="ALERT_RESOLVED", alertType="NECK_TRUNK")
        assert dev.posted("/status")[0][2]["state"] == "OFFLINE"
    finally:
        n.close()
        dev.close()


def test_events_without_notify_or_other_types_are_not_sent(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path)
    try:
        n.on_event(ev("ALERT_STARTED", notify=False))
        n.on_event(dict(eventType="USER_AWAY"))
        n.on_event(dict(eventType="CONFIG_APPLIED"))
        n.on_event({})
        time.sleep(0.3)
        assert not dev.posted("/alert") and not dev.posted("/status")
    finally:
        n.close()
        dev.close()


def test_device_key_header(tmp_path):
    dev = FakeDevice(key="s3cret")
    n = make(dev.url, tmp_path, key="s3cret")
    try:
        n.on_event(ev("ALERT_STARTED"))
        assert wait_for(lambda: dev.posted("/alert") and n.connected)
        assert all(r[3].get("X-Device-Key") == "s3cret" for r in dev.requests)
    finally:
        n.close()
        dev.close()


def test_wrong_key_is_not_connected(tmp_path):
    dev = FakeDevice(key="s3cret")
    n = make(dev.url, tmp_path, key="sai")
    try:
        n.on_event(ev("ALERT_STARTED"))
        assert wait_for(lambda: n.client.error == "BAD_KEY")
        assert not n.connected
    finally:
        n.close()
        dev.close()


def test_no_key_header_when_key_empty(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path)
    try:
        n.on_event(ev("ALERT_STARTED"))
        assert wait_for(lambda: dev.posted("/alert"))
        assert all("X-Device-Key" not in r[3] for r in dev.requests)
    finally:
        n.close()
        dev.close()


# ---------------------------------------------------------------- thiết bị tắt
def test_closed_port_never_blocks_or_raises(tmp_path):
    n = make(closed_url(), tmp_path)
    try:
        t0 = time.perf_counter()
        for _ in range(30):
            n.on_event(ev("ALERT_STARTED"))
            n.on_state(dict(state="BAD", sittingSec=10))
            n.on_config({"notify_sound"}, {"notify_sound": True})
        assert time.perf_counter() - t0 < 0.05 * 3
        assert wait_for(lambda: n.client.error == "UNREACHABLE")
        assert n.connected is False
    finally:
        n.close()


def test_hung_device_does_not_block_caller(tmp_path):
    dev = FakeDevice()
    dev.delay = 2.0
    n = make(dev.url, tmp_path, timeout_sec=0.2)
    try:
        t0 = time.perf_counter()
        n.on_event(ev("ALERT_STARTED"))
        assert time.perf_counter() - t0 < 0.05
        assert wait_for(lambda: n.client.error == "UNREACHABLE", 3)
    finally:
        n.close()
        dev.close()


def test_disabled_does_nothing(tmp_path):
    dev = FakeDevice()
    n = IotNotifier(dict(enabled=False, url=dev.url), latency_path=str(tmp_path / "l.csv"))
    n.on_event(ev("ALERT_STARTED"))
    n.on_state(dict(state="GOOD", sittingSec=0))
    n.close()
    time.sleep(0.2)
    assert dev.requests == [] and not n.connected
    dev.close()


# ---------------------------------------------------------------- hàng đợi
def test_stale_alert_is_dropped(tmp_path):
    dev = FakeDevice()
    c = IotClient(dev.url, latency_path=None, heartbeat_sec=3600)
    try:
        c.start()
        assert wait_for(lambda: c.connected)
        old = time.monotonic() - (IotClient.ALERT_MAX_AGE + 2)
        c._q.put((old, "POST", "/alert", dict(eventType="ALERT_STARTED", alertType="OLD", level=1)))
        c._q.put((old, "POST", "/status", dict(state="GOOD")))             # chỉ /alert bị bỏ vì cũ
        c.send("POST", "/alert", dict(eventType="ALERT_STARTED", alertType="NEW", level=1))
        assert wait_for(lambda: dev.posted("/alert") and dev.posted("/status"))
        assert [r[2]["alertType"] for r in dev.posted("/alert")] == ["NEW"]
    finally:
        c.stop()
        dev.close()


def test_queue_drops_oldest_when_full():
    c = IotClient("http://127.0.0.1:9", latency_path=None)               # chưa start: lệnh nằm lại trong hàng đợi
    for i in range(IotClient.QUEUE_MAX + 5):
        c.send("POST", "/status", dict(i=i))
    assert c._q.qsize() == IotClient.QUEUE_MAX
    assert c._q.get_nowait()[3] == dict(i=5)


# ---------------------------------------------------------------- on_state / on_config / alertsToday
def test_on_state_only_when_changed_or_period_elapsed(tmp_path):
    dev = FakeDevice()
    now = [1000.0]
    n = make(dev.url, tmp_path, clock=lambda: now[0], status_every_sec=60)
    n.cfg["status_every_sec"] = 60
    try:
        n.on_state(dict(state="GOOD", sittingSec=125))
        n.on_state(dict(state="GOOD", sittingSec=130))
        now[0] += 30
        n.on_state(dict(state="GOOD", sittingSec=160))
        assert wait_for(lambda: len(dev.posted("/status")) == 1)
        time.sleep(0.2)
        assert len(dev.posted("/status")) == 1
        n.on_state(dict(state="BAD", sittingSec=170))              # đổi trạng thái
        now[0] += 61
        n.on_state(dict(state="BAD", sittingSec=240))              # đủ chu kỳ
        assert wait_for(lambda: len(dev.posted("/status")) == 3)
        bodies = [r[2] for r in dev.posted("/status")]
        assert bodies[0] == dict(state="GOOD", sittingMin=2, alertsToday=0)
        assert bodies[1]["state"] == "BAD" and bodies[2]["sittingMin"] == 4
    finally:
        n.close()
        dev.close()


def test_alerts_today_counts_only_notified_started_and_reminder(tmp_path):
    dev = FakeDevice()
    now = [datetime(2026, 11, 1, 10, 0).timestamp()]
    n = make(dev.url, tmp_path, clock=lambda: now[0])
    try:
        n.on_event(ev("ALERT_STARTED"))
        n.on_event(ev("ALERT_STARTED", notify=False))
        n.on_event(ev("ALERT_REPEATED"))
        n.on_event(ev("REMINDER", "EYE_BREAK"))
        n.on_event(dict(eventType="ALERT_RESOLVED", alertType="NECK_TRUNK", notify=False))
        n.on_state(dict(state="GOOD", sittingSec=0))
        assert wait_for(lambda: dev.posted("/status"))
        assert dev.posted("/status")[0][2]["alertsToday"] == 2
        now[0] = datetime(2026, 11, 2, 0, 5).timestamp()            # qua nửa đêm: đếm lại từ 0
        n.on_state(dict(state="BAD", sittingSec=0))
        assert wait_for(lambda: len(dev.posted("/status")) == 2)
        assert dev.posted("/status")[1][2]["alertsToday"] == 0
    finally:
        n.close()
        dev.close()


def test_on_config_sends_sound_only_for_notify_sound(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path)
    try:
        n.on_config({"alert_sec"}, {"notify_sound": True})
        n.on_config({"notify_sound", "alert_sec"}, {"notify_sound": False})
        assert wait_for(lambda: dev.posted("/config"))
        time.sleep(0.2)
        assert [r[2] for r in dev.posted("/config")] == [dict(soundOn=False)]
    finally:
        n.close()
        dev.close()


def test_sound_config_sent_when_device_connects(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path, app_cfg={"notify_sound": True})
    try:
        n.on_event(ev("ALERT_STARTED"))                              # khởi động luồng, ping đầu tiên nối được
        assert wait_for(lambda: dev.posted("/config"))
        assert dev.posted("/config")[0][2] == dict(soundOn=True)
    finally:
        n.close()
        dev.close()


def test_close_sends_offline_and_stops_thread(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path)
    n.on_state(dict(state="GOOD", sittingSec=0))
    assert wait_for(lambda: n.connected)
    n.close()
    assert dev.posted("/status")[-1][2]["state"] == "OFFLINE"
    assert not n.client.running and not n.connected
    n.on_state(dict(state="GOOD", sittingSec=0))                     # dùng lại sau close (engine mới) thì chạy lại
    assert wait_for(lambda: n.client.running and len(dev.posted("/status")) >= 3)
    n.close()
    dev.close()


def test_apply_live_changes_target_and_enabled(tmp_path):
    a, b = FakeDevice(), FakeDevice()
    n = make(a.url, tmp_path)
    try:
        n.on_event(ev("ALERT_STARTED"))
        assert wait_for(lambda: a.posted("/alert"))
        n.apply(dict(enabled=True, url=b.url))
        n.on_event(ev("ALERT_STARTED"))
        assert wait_for(lambda: b.posted("/alert"))
        n.apply(dict(enabled=False, url=b.url))
        assert not n.enabled and not n.connected
    finally:
        n.close()
        a.close()
        b.close()


def test_latency_csv(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path)
    try:
        n.on_event(ev("ALERT_STARTED"))
        assert wait_for(lambda: dev.posted("/alert"))
        time.sleep(0.1)
        lines = (tmp_path / "lat.csv").read_text(encoding="utf-8").splitlines()
        assert lines[0] == "ts,path,http,ms"
        rows = [l.split(",") for l in lines[1:]]
        assert any(r[1] == "/alert" and r[2] == "200" and r[3].isdigit() for r in rows)
        assert any(r[1] == "/ping" for r in rows)
    finally:
        n.close()
        dev.close()


# ---------------------------------------------------------------- tắt bíp trên máy
def test_pc_beep_muted_only_when_connected_and_option_on(tmp_path):
    dev = FakeDevice()
    n = make(dev.url, tmp_path, mute_pc_beep=True)
    try:
        assert not n.mutes_pc_beep                                    # chưa nối
        n.on_state(dict(state="GOOD", sittingSec=0))
        assert wait_for(lambda: n.mutes_pc_beep)
        n.apply(dict(enabled=True, url=dev.url, mute_pc_beep=False))
        assert wait_for(lambda: n.connected) and not n.mutes_pc_beep
    finally:
        n.close()
        dev.close()


class _Cfg(dict):
    pass


def test_notifier_skips_beep_when_iot_mutes():
    cfg = _Cfg(notify_toast=False, notify_sound=True, notify_popup=False, distance_on_cm=50)

    class Iot:
        mutes_pc_beep = True

    beeps = []
    for iot, expect in ((Iot(), 0), (None, 1)):
        n = Notifier(cfg, iot)
        n._run = lambda fn, *a: beeps.append(fn.__name__)
        n(dict(eventType="ALERT_STARTED", alertType="NECK_TRUNK", severity="MEDIUM", notify=True))
        assert beeps.count("_beep") == expect
        beeps.clear()


# ---------------------------------------------------------------- iot_config
def test_config_defaults_and_cleaning(tmp_path):
    p = str(tmp_path / "iot_config.json")
    d = iot_config.load(p)                                           # thiếu file
    assert d["enabled"] is False and d["url"] == "http://192.168.1.20" and d["key"] == ""
    assert d["mute_pc_beep"] is True and d["timeout_sec"] == 1.0
    (tmp_path / "iot_config.json").write_text("{hỏng", encoding="utf-8")
    assert iot_config.load(p) == d                                   # file hỏng
    c = iot_config.clean(dict(enabled="yes", url="posture-esp32.local/", key=" k ", timeout_sec=-3, lạ=1))
    assert c["enabled"] is False and c["url"] == "http://posture-esp32.local" and c["key"] == "k"
    assert c["timeout_sec"] == 1.0 and "lạ" not in c
    assert iot_config.clean(dict(url="ftp://x"))["url"] == "http://192.168.1.20"


def test_config_save_roundtrip(tmp_path):
    p = str(tmp_path / "iot_config.json")
    assert iot_config.save(dict(enabled=True, url="http://10.0.0.5", key="abc"), p)
    c = iot_config.load(p)
    assert c["enabled"] is True and c["url"] == "http://10.0.0.5" and c["key"] == "abc"
    assert not iot_config.save({}, str(tmp_path / "không" / "có" / "iot.json"))


def test_example_file_matches_defaults():
    with open(os.path.join(os.path.dirname(HERE), "iot_config.example.json"), encoding="utf-8") as f:
        assert json.load(f) == iot_config.DEFAULTS
