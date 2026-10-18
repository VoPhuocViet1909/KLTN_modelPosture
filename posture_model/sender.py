"""
Thread Sender: vòng lặp camera chỉ bỏ dữ liệu vào hàng đợi (không chờ đĩa, không chờ mạng).

  vòng lặp camera --enqueue--> queue.Queue --> [thread Sender] --> Outbox SQLite --> POST theo lô --> server

- Gửi theo lô mỗi `interval` giây (mặc định 5), tối đa `batch_max` mục / lô.
- Sự kiện khẩn (ALERT_*, USER_AWAY/BACK) đánh thức thread để gửi ngay -> Dashboard thấy gần như tức thì.
- Lỗi mạng / 5xx / 429: giữ trong outbox, thử lại với backoff. Khi đang mất mạng, cứ 15 giây hỏi /health,
  có mạng lại là gửi bù ngay.
- 2xx: server trả {"accepted": [...], "rejected": [{"id", "reason"}]} -> mục bị từ chối đánh dấu dead.
- api_base_url = null: chỉ lưu outbox (chế độ offline), chưa gửi đi đâu.

API (giai đoạn 3 làm bằng Spring Boot, mock_server.py làm giả để thử):
  POST {base}/api/v1/telemetry/batch   Authorization: Bearer <token>   body = batch.schema.json
  GET  {base}/api/v1/health
"""
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from schema import validate
from api_session import AuthError, NoRedirect

URGENT = {"ALERT_STARTED", "ALERT_REPEATED", "ALERT_RESOLVED", "USER_AWAY", "USER_BACK"}
LOCAL_ONLY_KEYS = ("notify",)          # khoá chỉ dùng trong app, không gửi lên server
LOCAL_ONLY_EVENTS = {"CALIBRATION_FAILED"}   # sự kiện chỉ ghi ở máy (events.jsonl), không thuộc 10 loại của ingestion


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Sender(threading.Thread):
    def __init__(self, outbox, base_url=None, token=None, device_id="", interval=5.0, batch_max=100,
                 timeout=5.0, check_schema=True, auth=None):
        super().__init__(daemon=True, name="Sender")
        self.outbox = outbox
        self.base_url = (base_url or "").rstrip("/") or None
        self.token, self.device_id = token, device_id
        self.interval, self.batch_max, self.timeout = interval, batch_max, timeout
        self.check_schema = check_schema
        self.auth = auth
        self._opener = urllib.request.build_opener(NoRedirect)
        self.q = queue.Queue()
        self._wake = threading.Event()
        self._halt = threading.Event()
        self.online = None              # None = chưa thử, True / False
        self.last_error = None
        self.last_ok = None
        self.sent_total = 0
        self._last_probe = 0.0
        self.probe_sec = 15.0           # đang mất mạng: bao lâu hỏi /health một lần

    # ------------------------------------------------------------------ gọi từ vòng lặp camera
    def enqueue_event(self, ev):
        if ev.get("eventType") in LOCAL_ONLY_EVENTS:
            return
        ev = {k: v for k, v in ev.items() if k not in LOCAL_ONLY_KEYS}
        urgent = ev.get("eventType") in URGENT
        self.q.put(("event", ev["eventId"], ev, urgent))
        if urgent:
            self._wake.set()

    def enqueue_metric(self, m):
        self.q.put(("metric", m["metricId"], m, False))

    def configure(self, base_url=None, token=None, interval=None, batch_max=None):
        self.base_url = (base_url or "").rstrip("/") or None
        self.token = token
        if interval:
            self.interval = interval
        if batch_max:
            self.batch_max = batch_max
        self._wake.set()

    def status_text(self):
        st = self.outbox.stats()
        if not self.base_url:
            return f"offline mode, {st['pending']} cho gui"
        state = {True: "online", False: "MAT KET NOI", None: "..."}[self.online]
        return f"server {state}, {st['pending']} cho gui"

    # ------------------------------------------------------------------ thread
    def run(self):
        while not self._halt.is_set():
            self._wake.wait(self.interval)
            self._wake.clear()
            self._drain()
            if self.base_url and not self._halt.is_set():
                self._maybe_probe()
                self._flush()
        self._drain()
        if self.base_url:
            self._flush(final=True)

    def stop(self, timeout=5.0):
        self._halt.set()
        self._wake.set()
        self.join(timeout)

    def _drain(self):
        while True:
            try:
                kind, item_id, payload, urgent = self.q.get_nowait()
            except queue.Empty:
                return
            self.outbox.put(kind, item_id, payload, urgent)
            if self.check_schema:
                errs = validate("event" if kind == "event" else "metrics", payload)
                if errs:
                    print(f"[sender] {kind} {item_id} sai schema, không gửi:", errs[:3])
                    self.outbox.mark_dead([(item_id, "; ".join(errs[:5]))])

    def _maybe_probe(self):
        """Đang mất mạng: 15 giây hỏi /health một lần, có mạng lại thì bỏ thời gian chờ backoff."""
        if self.online is not False or time.time() - self._last_probe < self.probe_sec:
            return
        self._last_probe = time.time()
        try:
            req = urllib.request.Request(self.base_url + "/api/v1/health")
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                if 200 <= r.status < 300:
                    self.online = True
                    self.outbox.retry_now()
                    print("[sender] có mạng lại, gửi bù dữ liệu trong outbox")
        except Exception:
            pass

    def _flush(self, final=False):
        for _ in range(1 if final else 50):      # Thoát: chỉ thử một lô; phần còn lại đã ở SQLite.
            items = self.outbox.due(self.batch_max)
            if not items:
                return
            if not self._send(items):
                return
            if self._halt.is_set():
                return

    def _send(self, items):
        body = {"schemaVersion": "1.0", "deviceId": self.device_id, "sentAt": _now_iso(),
                "events": [p for _, k, p in items if k == "event"],
                "metrics": [p for _, k, p in items if k == "metric"]}
        ids = [i for i, _, _ in items]
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Device-Id": self.device_id}
        try:
            if self.auth and any(payload.get("userId") != self.auth.user_id for _, _, payload in items):
                raise AuthError("Outbox belongs to another user; use that account or a separate --outbox")
            if self.token and not self.auth:
                headers["Authorization"] = f"Bearer {self.token}"
            req = urllib.request.Request(self.base_url + "/api/v1/telemetry/batch", data=data, headers=headers,
                                         method="POST")
            with (self.auth.open(req, timeout=self.timeout) if self.auth else
                  self._opener.open(req, timeout=self.timeout)) as r:
                raw = r.read()
            res = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 413 and self.batch_max > 1:             # lô quá lớn -> chia nhỏ
                self.batch_max = max(1, self.batch_max // 2)
                return True
            self._fail(ids, f"HTTP {e.code}", offline=e.code >= 500 or e.code in (408, 429))
            return False
        except AuthError as e:
            self._fail(ids, str(e), offline=True)
            return False
        except Exception:                                       # Không ghi URL/token vào outbox/log.
            self._fail(ids, "Telemetry unavailable or invalid response", offline=True)
            return False
        rejected = {r["id"]: r.get("reason", "rejected") for r in res.get("rejected", []) if "id" in r}
        self.outbox.mark_dead(list(rejected.items()))
        ok = [i for i in ids if i not in rejected]
        self.outbox.mark_sent(ok)
        if self.online is not True:
            print("[sender] đã kết nối server")
        self.online, self.last_ok, self.last_error = True, time.time(), None
        self.sent_total += len(ok)
        return True

    def _fail(self, ids, err, offline):
        self.outbox.mark_failed(ids, err)
        if offline and self.online is not False:
            print("[sender] mất kết nối server, dữ liệu giữ trong outbox:", err)
        if offline:
            self.online = False
        self.last_error = err
