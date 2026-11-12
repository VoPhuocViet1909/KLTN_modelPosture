"""
Gửi cảnh báo từ Desktop App xuống thiết bị ESP32-S3 qua HTTP trong mạng LAN (hợp đồng API: TaiLieu/KeHoach_IoT_ThongBao.md mục 2).

  IotClient    luồng nền + hàng đợi: GET/POST tới thiết bị, timeout ngắn, không thử lại, heartbeat /ping.
  IotNotifier  đổi sự kiện / trạng thái của engine thành lệnh gửi (on_event, on_state, on_config, close).

Mọi hàm của IotNotifier chỉ xếp lệnh vào hàng đợi rồi trả về ngay và không bao giờ ném lỗi: thiết bị tắt hay mất mạng
không được làm chậm vòng lặp camera hoặc giao diện Qt. Chỉ dùng thư viện chuẩn.
"""
import csv
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import iot_config

LATENCY_CSV = os.path.join(iot_config.APP_DIR, "out", "iot_latency.csv")
ALERT_EVENTS = ("ALERT_STARTED", "ALERT_REPEATED", "REMINDER")
COUNTED_EVENTS = ("ALERT_STARTED", "REMINDER")          # tăng "cảnh báo hôm nay" trên thiết bị
_STOP = object()
# Bỏ qua proxy hệ thống: thiết bị nằm trong LAN, proxy công ty / VPN sẽ làm request thất bại.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(url, key, method, path, body=None, timeout=1.0):
    """Một request tới thiết bị. Trả về (http, data, ms); http = 0 khi không nối được. Không ném lỗi."""
    t0 = time.monotonic()
    status, raw = 0, b""
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if key:
            headers["X-Device-Key"] = key
        req = urllib.request.Request(url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                status, raw = r.status, r.read(65536)
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read(65536)
    except Exception:                                    # hết giờ, từ chối kết nối, tên không phân giải, URL sai...
        status = 0
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}, int((time.monotonic() - t0) * 1000)


class IotClient:
    QUEUE_MAX = 20
    ALERT_MAX_AGE = 3.0           # lệnh /alert nằm hàng đợi quá lâu thì bỏ: cảnh báo cũ không còn ý nghĩa

    def __init__(self, url, key="", timeout=1.0, heartbeat_sec=15.0, latency_path=LATENCY_CSV, on_connect=None):
        self.url, self.key, self.timeout, self.heartbeat_sec = url, key, timeout, heartbeat_sec
        self.latency_path = latency_path
        self.on_connect = on_connect
        self.connected = False
        self.info = {}                    # nội dung /ping gần nhất
        self.error = ""                   # "" | "BAD_KEY" | "UNREACHABLE"
        self._q = queue.Queue(maxsize=self.QUEUE_MAX)
        self._evt = threading.Event()
        self._evt.set()                   # chưa chạy
        self._thread = None
        self._lock = threading.Lock()
        self._csv_lock = threading.Lock()
        self._next_ping = 0.0

    # ---------------------------------------------------------------- điều khiển
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._evt.is_set()

    def start(self):
        """Chạy luồng nền nếu chưa chạy (gọi nhiều lần được). Mỗi lần chạy có hàng đợi riêng."""
        with self._lock:
            if self.running:
                return
            self._q, self._evt = queue.Queue(maxsize=self.QUEUE_MAX), threading.Event()
            self._next_ping = 0.0
            self._thread = threading.Thread(target=self._run, args=(self._q, self._evt), name="IotClient", daemon=True)
            self._thread.start()

    def stop(self, final=None, wait=None):
        """Bỏ lệnh còn chờ, gửi nốt `final` = (method, path, body) nếu có rồi dừng luồng.
        wait = số giây chờ luồng thoát (mặc định timeout + 1; 0 = không chờ, dùng được trong luồng giao diện)."""
        with self._lock:
            th, q, evt = self._thread, self._q, self._evt
            if not self.running:
                return
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
            if final is not None:
                q.put_nowait((time.monotonic(),) + tuple(final))
            evt.set()                     # luồng làm nốt `final` rồi thoát
            self.connected = False
        wait = self.timeout + 1.0 if wait is None else wait
        if wait > 0:
            th.join(wait)
            self.connected = False        # kết quả của request đang bay lúc dừng có thể vừa đặt lại True

    def configure(self, url, key, timeout, heartbeat_sec):
        """Đổi địa chỉ / khóa khi đang chạy; ping ngay để chấm trạng thái cập nhật sớm."""
        if (url, key) != (self.url, self.key):
            self.connected, self.info, self.error = False, {}, ""
        self.url, self.key, self.timeout, self.heartbeat_sec = url, key, timeout, heartbeat_sec
        self._next_ping = 0.0

    def send(self, method, path, body=None):
        """Xếp lệnh vào hàng đợi, trả về ngay. Hàng đợi đầy thì bỏ lệnh cũ nhất."""
        item, q = (time.monotonic(), method, path, body), self._q
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    # ---------------------------------------------------------------- luồng nền
    def _run(self, q, evt):
        while True:
            if not evt.is_set() and time.monotonic() >= self._next_ping:
                self._ping()
                self._next_ping = time.monotonic() + max(self.heartbeat_sec, 1.0)
            try:
                item = q.get(timeout=max(0.05, min(0.5, self._next_ping - time.monotonic())))
            except queue.Empty:
                if evt.is_set():
                    return
                continue
            t_enq, method, path, body = item
            if method == "POST" and path == "/alert" and time.monotonic() - t_enq > self.ALERT_MAX_AGE:
                continue
            self._request(method, path, body, live=not evt.is_set())

    def _ping(self):
        status, data, _ = self._request("GET", "/ping")
        if status == 200 and data.get("ok") is not False:
            self.info = data

    def _request(self, method, path, body=None, live=True):
        url, key = self.url, self.key
        status, data, ms = call(url, key, method, path, body, self.timeout)
        self._log(path, status, ms)
        if live and (url, key) == (self.url, self.key):          # bỏ kết quả khi đang dừng hoặc vừa đổi địa chỉ
            self._set_state(status, method == "GET" and path == "/ping")
        return status, data, ms

    def _set_state(self, status, is_ping):
        was = self.connected
        if status == 200:
            self.connected, self.error = True, ""
        elif status == 401:
            self.connected, self.error, self.info = False, "BAD_KEY", {}
        elif status == 0:
            self.connected, self.error, self.info = False, "UNREACHABLE", {}
        elif is_ping:
            self.connected = False
        if self.connected and not was and self.on_connect is not None:
            try:
                self.on_connect()
            except Exception:
                pass

    def _log(self, path, status, ms):
        if not self.latency_path:
            return
        try:
            with self._csv_lock:
                new = not os.path.exists(self.latency_path) or os.path.getsize(self.latency_path) == 0
                os.makedirs(os.path.dirname(os.path.abspath(self.latency_path)), exist_ok=True)
                with open(self.latency_path, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["ts", "path", "http", "ms"])
                    w.writerow([datetime.now(timezone.utc).isoformat(timespec="milliseconds"), path.split("?")[0],
                                status, ms])
        except OSError:
            pass


class IotNotifier:
    """Gắn vào engine: on_event (EventLog.listeners), on_state, on_config, close. Dùng lại được qua nhiều engine."""

    def __init__(self, cfg=None, app_cfg=None, latency_path=LATENCY_CSV, clock=time.time):
        self.cfg = iot_config.clean(cfg)
        self.app_cfg = app_cfg                    # AppConfig của app, để gửi soundOn khi thiết bị vừa nối lại
        self._clock = clock
        self.client = IotClient(self.cfg["url"], self.cfg["key"], self.cfg["timeout_sec"], self.cfg["heartbeat_sec"],
                                latency_path, on_connect=self._on_connect)
        self._lock = threading.Lock()
        self._day, self._alerts_today = None, 0
        self._last_state, self._last_state_t, self._last_status = None, 0.0, None

    # ---------------------------------------------------------------- trạng thái cho giao diện
    @property
    def enabled(self):
        return self.cfg["enabled"]

    @property
    def connected(self):
        return self.enabled and self.client.connected

    @property
    def info(self):
        return self.client.info if self.enabled else {}

    @property
    def mutes_pc_beep(self):
        """True khi máy tính không nên bíp: thiết bị đang kết nối và người dùng chọn tắt bíp trên máy."""
        return self.connected and self.cfg["mute_pc_beep"]

    def apply(self, cfg):
        """Áp cấu hình mới ngay (từ giao diện), không cần khởi động lại."""
        try:
            self.cfg = cfg = iot_config.clean(cfg)
            self.client.configure(cfg["url"], cfg["key"], cfg["timeout_sec"], cfg["heartbeat_sec"])
            if cfg["enabled"]:
                self.client.start()
            else:
                self.client.stop(wait=0)          # không chờ: có thể đang gọi từ luồng giao diện
        except Exception:
            pass

    # ---------------------------------------------------------------- engine gọi
    def on_event(self, ev):
        try:
            if not self.enabled:
                return
            kind, alert_type = ev.get("eventType"), ev.get("alertType")
            if kind in ALERT_EVENTS and ev.get("notify") and alert_type:
                body = dict(eventType=kind, alertType=alert_type, level=max(1, min(3, int(ev.get("level") or 1))))
                if ev.get("sittingMin") is not None:
                    body["sittingMin"] = ev["sittingMin"]
                dist = (ev.get("snapshot") or {}).get("distanceCm")
                if dist is not None:
                    body["distanceCm"] = dist
                if kind in COUNTED_EVENTS:
                    self._count_alert()
                self._send("POST", "/alert", body)
            elif kind == "ALERT_RESOLVED" and alert_type:
                self._send("POST", "/alert", dict(eventType=kind, alertType=alert_type))
            elif kind == "SESSION_END":
                self._send("POST", "/status", self._status_body("OFFLINE", 0))
        except Exception:
            pass

    def on_state(self, st):
        try:
            if not self.enabled:
                return
            state, now = st["state"], self._clock()
            if state in ('UNKNOWN', 'CAMERA_LOST'):
                state = 'OFFLINE'  # Existing ESP32 firmware has no observation-state extension.
            if state == self._last_state and now - self._last_state_t < self.cfg["status_every_sec"]:
                return
            self._last_state, self._last_state_t = state, now
            self._send("POST", "/status", self._status_body(state, int(st.get("sittingSec") or 0) // 60))
        except Exception:
            pass

    def on_config(self, changed, cfg):
        try:
            if self.enabled and "notify_sound" in changed:
                self._send("POST", "/config", dict(soundOn=bool(cfg["notify_sound"])))
        except Exception:
            pass

    def close(self):
        """Hết phiên: báo OFFLINE cho thiết bị rồi dừng luồng nền. Gọi lại on_event/on_state sẽ tự chạy lại luồng."""
        try:
            self._last_state = None
            if self.client.running:
                self.client.stop(final=("POST", "/status", self._status_body("OFFLINE", 0)))
        except Exception:
            pass

    # ---------------------------------------------------------------- nội bộ
    def _send(self, method, path, body):
        self.client.start()
        self.client.send(method, path, body)

    def _on_connect(self):
        """Chạy trong luồng nền khi thiết bị vừa nối (lại): gửi cấu hình tiếng và trạng thái gần nhất."""
        if self.app_cfg is not None:
            self.client.send("POST", "/config", dict(soundOn=bool(self.app_cfg["notify_sound"])))
        self._last_state = None                   # lần on_state kế tiếp gửi lại trạng thái

    def _count_alert(self):
        with self._lock:
            day = datetime.fromtimestamp(self._clock()).date()
            if day != self._day:
                self._day, self._alerts_today = day, 0
            self._alerts_today += 1

    def _status_body(self, state, sitting_min):
        with self._lock:
            n = self._alerts_today if self._day == datetime.fromtimestamp(self._clock()).date() else 0
        return dict(state=state, sittingMin=sitting_min, alertsToday=n)


def probe(url, key="", timeout=2.0, test=False):
    """Kiểm tra thiết bị một lần (giao diện gọi trong luồng nền): GET /ping, tùy chọn phát âm thử trước.
    Trả về dict(ok, tested, error, info). error = "" | "BAD_KEY" | "UNREACHABLE". Không ném lỗi."""
    tested = False
    if test:
        status, _, _ = call(url, key, "GET", "/alert?type=TEST", timeout=timeout)
        tested = status == 200
    status, data, _ = call(url, key, "GET", "/ping", timeout=timeout)
    if status == 200:
        return dict(ok=True, tested=tested, error="", info=data)
    return dict(ok=False, tested=False, error="BAD_KEY" if status == 401 else "UNREACHABLE", info={})
