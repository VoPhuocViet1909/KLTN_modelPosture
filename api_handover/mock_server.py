"""
Server giả, làm đúng hợp đồng API v1.0 (xem api_handover/openapi.yaml), để:
  - phía Desktop App test gửi dữ liệu khi chưa có backend Spring Boot;
  - phía backend có một bản chạy được để đối chiếu (contract_test.py chạy vào mock phải đạt 100%).

  python mock_server.py                      # http://127.0.0.1:8080, không bắt buộc JWT
  python mock_server.py --token abc123       # bắt buộc JWT: token tĩnh abc123 HOẶC token lấy từ /auth/login
  python mock_server.py --require-login      # bắt buộc JWT lấy từ /auth/login
  python mock_server.py --fail-rate 0.3      # 30% request gửi dữ liệu trả 503 để thử gửi lại
  python mock_server.py --host 0.0.0.0       # cho máy khác trong mạng LAN gọi vào

Tài khoản demo: demo@kltn.local / 123456

Endpoint:
  GET  /api/v1/health                 -> {"status": "UP"}                       (không cần JWT)
  POST /api/v1/auth/login             -> {accessToken, refreshToken, expiresIn, user}
  POST /api/v1/auth/refresh           -> {accessToken, refreshToken, expiresIn}
  POST /api/v1/telemetry/batch        -> {accepted, rejected, duplicates}
  GET  /api/v1/config/me              -> cấu hình riêng của người dùng (chỉ các khoá khác mặc định)
  PUT  /api/v1/config/me              -> lưu cấu hình (kiểm tra theo config.schema.json)
  GET  /api/v1/stats                  -> (chỉ mock) đếm số sự kiện / metrics đã nhận
  GET  /live                          -> (chỉ mock) trang web xem trực tiếp dữ liệu nhận được
WebSocket /ws (STOMP) KHÔNG có trong mock.
Dữ liệu nhận được ghi vào mock_data/events.jsonl và mock_data/metrics.jsonl (đã bỏ trùng theo id).
"""
import argparse
import base64
import collections
import json
import os
import random
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from schema import validate

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_USERS = {"demo@kltn.local": {"password": "123456", "id": "u_demo", "name": "Demo User",
                                  "orgId": "org_demo", "role": "USER"}}
ACCESS_TTL = 3600
MAX_ITEMS = 500


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()


def make_jwt(sub, device_id, ttl=ACCESS_TTL):
    """JWT giả (không ký thật) chỉ để app có token đúng dạng header.payload.signature."""
    now = int(time.time())
    return ".".join([_b64({"alg": "none", "typ": "JWT"}),
                     _b64({"sub": sub, "deviceId": device_id, "iat": now, "exp": now + ttl}),
                     "mock-signature"])


class Store:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.seen = set()
        self.lock = threading.Lock()
        self.by_type = collections.Counter()
        self.n_metrics = 0
        self.tokens = {}        # accessToken -> (userId, exp)
        self.refresh = {}       # refreshToken -> userId
        self.configs = {}       # userId -> dict
        self.recent = collections.deque(maxlen=200)   # mục mới nhận, cho trang xem trực tiếp
        for name in ("events", "metrics"):           # nạp id cũ để chống trùng cả khi khởi động lại server
            p = os.path.join(folder, f"{name}.jsonl")
            if os.path.exists(p):
                for line in open(p, encoding="utf-8"):
                    try:
                        d = json.loads(line)
                        self.seen.add(d.get("eventId") or d.get("metricId"))
                    except ValueError:
                        pass

    def add(self, kind, item, user_id):
        key = item.get("eventId") if kind == "events" else item.get("metricId")
        with self.lock:
            if key in self.seen:
                return False
            self.seen.add(key)
            row = dict(item, _receivedUserId=user_id, _receivedAt=time.time())
            with open(os.path.join(self.folder, f"{kind}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if kind == "events":
                self.by_type[item.get("eventType")] += 1
            else:
                self.n_metrics += 1
            self.recent.append({"kind": kind, "receivedAt": time.time(), "item": item})
        return True

    def issue(self, user_id, device_id):
        access, refresh = make_jwt(user_id, device_id), secrets.token_urlsafe(24)
        with self.lock:
            self.tokens[access] = (user_id, time.time() + ACCESS_TTL)
            self.refresh[refresh] = (user_id, device_id)
        return access, refresh


LIVE_HTML = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Backend nhận được (mock)</title>
<style>
body{font:14px system-ui,Segoe UI,Arial;margin:0;background:#16181c;color:#e6e6e6}
header{padding:12px 16px;background:#22252b;position:sticky;top:0}
h1{font-size:16px;margin:0 0 6px} #st{color:#aab;font-size:13px}
table{border-collapse:collapse;width:100%} td,th{padding:5px 10px;border-bottom:1px solid #2c2f36;text-align:left;
white-space:nowrap} th{color:#99a;font-weight:600;font-size:12px} tr.new td{background:#2a3242}
.S{color:#ff6b6b}.R{color:#5fd38d}.P{color:#ffa94d}.M{color:#74c0fc}.o{color:#888}
td.j{white-space:normal;font:12px Consolas,monospace;color:#9aa;max-width:620px;overflow-wrap:anywhere}
</style></head><body><header><h1>Backend (server giả) nhận được – cập nhật mỗi giây</h1><div id="st">…</div></header>
<table><thead><tr><th>Nhận lúc</th><th>Loại</th><th>Chi tiết</th><th>Máy / phiên</th><th>JSON (bấm để mở)</th></tr></thead>
<tbody id="tb"></tbody></table>
<script>
let seen=new Set();
const t=s=>new Date(s).toLocaleTimeString('vi-VN');
function row(x){const i=x.item, e=x.kind==='events', ty=e?i.eventType:'METRICS';
 const c={ALERT_STARTED:'S',ALERT_REPEATED:'P',ALERT_RESOLVED:'R'}[ty]||(e?'o':'M');
 let d='';
 if(e){d=(i.alertType||'')+(i.durationSec!=null&&ty!=='SESSION_END'?' · '+i.durationSec+' s':'')
   +(i.snapshot?' · pBad '+i.snapshot.pBad+', cổ '+i.snapshot.neck+'°':'');}
 else{d='phút '+t(i.windowStart).slice(0,5)+' · điểm '+i.postureScore+' · đúng '+Math.round(100*i.goodRatio)+'% · cảnh báo '+JSON.stringify(i.alertCount);}
 const id=e?i.eventId:i.metricId, isNew=!seen.has(id); seen.add(id);
 return `<tr class="${isNew?'new':''}"><td>${t(x.receivedAt*1000)}</td><td class="${c}">${ty}</td><td>${d}</td>`+
 `<td class="o">${i.deviceId}<br>${i.sessionId}</td><td class="j"><details><summary>xem</summary>${JSON.stringify(i)}</details></td></tr>`;}
async function tick(){try{const r=await (await fetch('/api/v1/recent')).json();
 document.getElementById('st').textContent='Tổng: '+Object.entries(r.stats.events).map(([k,v])=>k+' '+v).join(' · ')+' · METRICS '+r.stats.metrics;
 const open=[...document.querySelectorAll('details[open]')].length; if(!open) document.getElementById('tb').innerHTML=r.items.map(row).join('');
}catch(e){document.getElementById('st').textContent='mất kết nối server giả';}}
tick(); setInterval(tick,1000);
</script></body></html>"""


def make_handler(store, static_token, require_auth, fail_rate, quiet):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw) if raw else {}

        def _user(self):
            """-> (userId | None, lỗi | None). userId lấy từ JWT, không lấy từ payload."""
            auth = self.headers.get("Authorization", "")
            tok = auth[7:] if auth.startswith("Bearer ") else None
            if tok and static_token and tok == static_token:
                return "u_static", None
            if tok and tok in store.tokens:
                uid, exp = store.tokens[tok]
                return (uid, None) if exp > time.time() else (None, "token hết hạn")
            if require_auth:
                return None, "thiếu hoặc sai JWT"
            return None, None

        # ------------------------------------------------------------------ GET
        def do_GET(self):
            if self.path == "/api/v1/health":
                return self._json(200, {"status": "UP"})
            if self.path in ("/", "/live"):
                body = LIVE_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/v1/recent":
                return self._json(200, {"stats": {"events": dict(store.by_type), "metrics": store.n_metrics},
                                        "items": list(store.recent)[-80:][::-1]})
            if self.path == "/api/v1/stats":
                return self._json(200, {"events": dict(store.by_type), "metrics": store.n_metrics})
            if self.path == "/api/v1/config/me":
                uid, err = self._user()
                if err or uid is None:
                    return self._json(401, {"error": err or "cần đăng nhập"})
                return self._json(200, store.configs.get(uid, {}))
            self._json(404, {"error": "not found"})

        # ------------------------------------------------------------------ PUT
        def do_PUT(self):
            if self.path != "/api/v1/config/me":
                return self._json(404, {"error": "not found"})
            try:
                cfg = self._body()                    # đọc hết body trước (giữ kết nối keep-alive sạch)
            except ValueError:
                return self._json(400, {"error": "bad json"})
            uid, err = self._user()
            if err or uid is None:
                return self._json(401, {"error": err or "cần đăng nhập"})
            errs = validate("config", cfg)
            if errs:
                return self._json(400, {"error": errs[:5]})
            store.configs[uid] = cfg
            self._json(200, cfg)

        # ------------------------------------------------------------------ POST
        def do_POST(self):
            try:
                body = self._body()
            except ValueError:
                return self._json(400, {"error": "bad json"})
            if self.path == "/api/v1/auth/login":
                u = DEMO_USERS.get(body.get("email"))
                if not u or u["password"] != body.get("password"):
                    return self._json(401, {"error": "sai email hoặc mật khẩu"})
                access, refresh = store.issue(u["id"], body.get("deviceId"))
                return self._json(200, {"accessToken": access, "refreshToken": refresh, "expiresIn": ACCESS_TTL,
                                        "user": {k: u[k] for k in ("id", "name", "orgId", "role")}})
            if self.path == "/api/v1/auth/refresh":
                rec = store.refresh.pop(body.get("refreshToken"), None)
                if not rec:
                    return self._json(401, {"error": "refresh token không hợp lệ"})
                access, refresh = store.issue(*rec)
                return self._json(200, {"accessToken": access, "refreshToken": refresh, "expiresIn": ACCESS_TTL})
            if self.path != "/api/v1/telemetry/batch":
                return self._json(404, {"error": "not found"})

            uid, err = self._user()
            if err:
                return self._json(401, {"error": err})
            if fail_rate and random.random() < fail_rate:
                return self._json(503, {"error": "simulated outage"})
            if not isinstance(body, dict):
                return self._json(400, {"error": "body phải là object"})
            events, metrics = body.get("events", []), body.get("metrics", [])
            if isinstance(events, list) and isinstance(metrics, list) and \
                    (len(events) > MAX_ITEMS or len(metrics) > MAX_ITEMS):
                return self._json(413, {"error": f"tối đa {MAX_ITEMS} sự kiện và {MAX_ITEMS} metrics / lô"})
            env_errs = validate("batch", {**body, "events": [], "metrics": []})
            if env_errs or not isinstance(events, list) or not isinstance(metrics, list):
                return self._json(400, {"error": env_errs or ["events / metrics phải là mảng"]})
            accepted, rejected, dup = [], [], 0
            for kind, schema_name, key, items in (("events", "event", "eventId", events),
                                                  ("metrics", "metrics", "metricId", metrics)):
                for item in items:
                    iid = item.get(key) if isinstance(item, dict) else None
                    errs = validate(schema_name, item)
                    if errs:
                        rejected.append({"id": iid, "reason": "; ".join(errs[:3])})
                        continue
                    if not store.add(kind, item, uid):
                        dup += 1
                    accepted.append(iid)
            if not quiet:
                types = collections.Counter(e.get("eventType") for e in events if isinstance(e, dict))
                print(f"batch từ {body.get('deviceId')}: {len(events)} sự kiện {dict(types)}, "
                      f"{len(metrics)} metrics, từ chối {len(rejected)}, trùng {dup}")
            self._json(200, {"accepted": accepted, "rejected": rejected, "duplicates": dup})
    return H


def serve(port=8080, token=None, fail_rate=0.0, folder=None, quiet=False, require_login=False, host="127.0.0.1"):
    store = Store(folder or os.path.join(HERE, "mock_data"))
    require_auth = bool(token) or require_login
    srv = ThreadingHTTPServer((host, port), make_handler(store, token, require_auth, fail_rate, quiet))
    srv.daemon_threads = True
    return srv, store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token", default=None, help="token tĩnh được chấp nhận (và bật bắt buộc JWT)")
    ap.add_argument("--require-login", action="store_true", help="bắt buộc JWT lấy từ /auth/login")
    ap.add_argument("--fail-rate", type=float, default=0.0)
    ap.add_argument("--data", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    srv, _ = serve(a.port, a.token, a.fail_rate, a.data, a.quiet, a.require_login, a.host)
    print(f"Mock server chạy tại http://{a.host}:{a.port}  (Ctrl+C để dừng)")
    print(f"Xem trực tiếp dữ liệu nhận được: mở trình duyệt http://127.0.0.1:{a.port}/live")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
