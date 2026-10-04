"""
Kiểm tra một server có làm ĐÚNG hợp đồng API v1.0 không (chạy được vào mock_server.py hoặc backend Spring).
Chỉ cần Python 3.9+ (thư viện chuẩn).

  python contract_test.py --base http://127.0.0.1:8080 --email demo@kltn.local --password 123456
  python contract_test.py --base http://127.0.0.1:8080 --token <JWT>          # đã có sẵn token
  python contract_test.py --base ... --no-auth                                 # server chưa làm JWT
  python contract_test.py --base ... --only batch                              # chỉ chạy nhóm 'batch'
  python contract_test.py --base ... --report report.json                      # ghi kết quả JSON

Mã thoát 0 = đạt hết, 1 = có mục trượt. Mốc M2 trong kế hoạch: đạt 100%.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

from payloads import Device

RESULTS = []


class Client:
    def __init__(self, base, token=None, timeout=10):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def call(self, method, path, body=None, raw=None, auth=True, headers=None):
        """-> (status, json | text, giây)"""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = {"Content-Type": "application/json"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, text = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode("utf-8", "replace")
        dt = time.time() - t0
        try:
            return status, json.loads(text) if text else None, dt
        except ValueError:
            return status, text, dt


def check(group, name, ok, detail=""):
    RESULTS.append({"group": group, "name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        -> {str(detail)[:300]}"))
    return ok


def ids_of(batch):
    return [e["eventId"] for e in batch["events"]] + [m["metricId"] for m in batch["metrics"]]


# ====================================================================== nhóm kiểm tra
def t_health(c, a):
    s, b, _ = c.call("GET", "/api/v1/health", auth=False)
    check("health", "GET /health không cần JWT, trả 200", s == 200, (s, b))
    check("health", 'body có "status": "UP"', isinstance(b, dict) and b.get("status") == "UP", b)


def t_auth(c, a):
    if a.no_auth:
        print("  (bỏ qua: --no-auth)")
        return
    dev = Device()
    s, b, _ = c.call("POST", "/api/v1/telemetry/batch", dev.batch([dev.session_start(_now())]), auth=False)
    check("auth", "gửi lô KHÔNG có JWT -> 401", s == 401, (s, b))
    s, b, _ = c.call("POST", "/api/v1/telemetry/batch", dev.batch([dev.session_start(_now())]), auth=False,
                     headers={"Authorization": "Bearer khong-hop-le"})
    check("auth", "gửi lô với JWT sai -> 401", s == 401, (s, b))
    if a.email:
        s, b, _ = c.call("POST", "/api/v1/auth/login", {"email": a.email, "password": "sai-mat-khau"}, auth=False)
        check("auth", "login sai mật khẩu -> 401", s == 401, (s, b))
        s, b, _ = c.call("POST", "/api/v1/auth/login", {"email": a.email, "password": a.password,
                                                         "deviceId": "dev_contract_test", "deviceName": "contract"},
                         auth=False)
        ok = s == 200 and isinstance(b, dict) and all(k in b for k in ("accessToken", "refreshToken", "expiresIn"))
        check("auth", "login đúng -> 200 + accessToken, refreshToken, expiresIn", ok, (s, b))
        check("auth", "login trả user.id và user.role", ok and isinstance(b.get("user"), dict)
              and "id" in b["user"] and b["user"].get("role") in ("USER", "ORG_ADMIN", "SYS_ADMIN"), b)
        if ok:
            c.token = b["accessToken"]
            s2, b2, _ = c.call("POST", "/api/v1/auth/refresh", {"refreshToken": b["refreshToken"]}, auth=False)
            ok2 = s2 == 200 and isinstance(b2, dict) and "accessToken" in b2
            check("auth", "refresh -> 200 + accessToken mới", ok2, (s2, b2))
            if ok2:
                c.token = b2["accessToken"]
            s3, b3, _ = c.call("POST", "/api/v1/auth/refresh", {"refreshToken": "khong-hop-le"}, auth=False)
            check("auth", "refresh token sai -> 401", s3 == 401, (s3, b3))


def t_batch(c, a):
    dev = Device(seed=7)
    batch = dev.batch(dev.all_event_types(), [dev.metric(_now())])
    s, b, dt = c.call("POST", "/api/v1/telemetry/batch", batch)
    ok = s == 200 and isinstance(b, dict)
    check("batch", f"lô hợp lệ ({len(batch['events'])} sự kiện đủ 10 loại + 1 metrics) -> 200", ok, (s, b))
    if not ok:
        return
    acc = set(b.get("accepted") or [])
    miss = [i for i in ids_of(batch) if i not in acc]
    check("batch", "mọi id nằm trong accepted", not miss, f"thiếu {len(miss)}: {miss[:3]} | rejected={b.get('rejected')}")
    check("batch", "rejected rỗng", not b.get("rejected"), b.get("rejected"))

    # gửi lại y nguyên -> vẫn 200, vẫn accepted, không bị rejected
    s, b2, _ = c.call("POST", "/api/v1/telemetry/batch", batch)
    acc2 = set((b2 or {}).get("accepted") or []) if isinstance(b2, dict) else set()
    check("batch", "gửi lại đúng lô cũ -> 200, id cũ VẪN trong accepted (chống trùng)",
          s == 200 and all(i in acc2 for i in ids_of(batch)), (s, b2))
    if isinstance(b2, dict) and "duplicates" in b2:
        check("batch", "duplicates = số mục gửi lại", b2["duplicates"] == len(ids_of(batch)), b2.get("duplicates"))

    # một mục sai, một mục đúng -> chỉ mục sai bị từ chối
    good = dev.session_start(_now())
    bad = dict(dev.session_start(_now()), eventType="ALERT_STARTED", alertType="NECK_TRUNK",
               severity="CRITICAL", startedAt=good["ts"])
    s, b3, _ = c.call("POST", "/api/v1/telemetry/batch", dev.batch([good, bad]))
    rej = {r.get("id") for r in (b3 or {}).get("rejected", [])} if isinstance(b3, dict) else set()
    check("batch", "mục sai schema vào rejected, mục đúng vẫn accepted (200)",
          s == 200 and bad["eventId"] in rej and good["eventId"] in set(b3.get("accepted", [])), (s, b3))
    check("batch", "mỗi mục rejected có reason", all(r.get("reason") for r in (b3 or {}).get("rejected", [])), b3)

    # ALERT_RESOLVED thiếu durationSec phải bị từ chối
    pair = dev.alert_pair(_now(), 30)
    broken = dict(pair[-1])
    broken.pop("durationSec")
    s, b4, _ = c.call("POST", "/api/v1/telemetry/batch", dev.batch([broken]))
    check("batch", "ALERT_RESOLVED thiếu durationSec -> rejected",
          s == 200 and broken["eventId"] in {r.get("id") for r in (b4 or {}).get("rejected", [])}, (s, b4))

    # metrics null ở trường không đo được vẫn hợp lệ
    m = dev.metric(_now())
    for k in ("tiltRelMean", "tiltAbsMax", "shoulderBadRatio", "distanceMeanCm", "distanceMinCm", "tooCloseRatio"):
        m[k] = None
    s, b5, _ = c.call("POST", "/api/v1/telemetry/batch", dev.batch([], [m]))
    check("batch", "metrics có trường null (không có cam laptop) vẫn accepted",
          s == 200 and m["metricId"] in (b5 or {}).get("accepted", []), (s, b5))

    # lô rỗng hợp lệ
    s, b6, _ = c.call("POST", "/api/v1/telemetry/batch", dev.batch())
    check("batch", "lô rỗng -> 200", s == 200, (s, b6))


def t_errors(c, a):
    dev = Device()
    s, b, _ = c.call("POST", "/api/v1/telemetry/batch", raw=b"{khong phai json")
    check("errors", "body không phải JSON -> 400", s == 400, (s, b))
    body = dev.batch([dev.session_start(_now())])
    body.pop("deviceId")
    s, b, _ = c.call("POST", "/api/v1/telemetry/batch", body)
    check("errors", "thiếu deviceId -> 400", s == 400, (s, b))
    big = dev.batch([dev.session_start(_now()) for _ in range(501)])
    s, b, _ = c.call("POST", "/api/v1/telemetry/batch", big)
    check("errors", "501 sự kiện / lô -> 413", s == 413, (s, b if not isinstance(b, str) else b[:100]))


def t_perf(c, a):
    dev = Device()
    t0 = _now()
    evs = []
    for i in range(45):
        evs += dev.alert_pair(t0, 20 + i)
    batch = dev.batch(evs[:90], [dev.metric(t0)] + [Device().metric(t0) for _ in range(9)])
    s, b, dt = c.call("POST", "/api/v1/telemetry/batch", batch)
    check("perf", f"lô 100 mục trả lời < 5 giây (đo được {dt:.2f} s)", s == 200 and dt < 5, (s, dt))
    check("perf", "lô 100 mục: đủ 100 id trong accepted",
          s == 200 and len(set((b or {}).get("accepted", [])) & set(ids_of(batch))) == 100, b if s != 200 else "")


def t_config(c, a):
    if a.no_auth:
        print("  (bỏ qua: --no-auth)")
        return
    s, b, _ = c.call("GET", "/api/v1/config/me")
    check("config", "GET /config/me -> 200 + object", s == 200 and isinstance(b, dict), (s, b))
    new = {"alert_sec": 7, "distance_on_cm": 48, "notify_popup": False}
    s, b, _ = c.call("PUT", "/api/v1/config/me", new)
    check("config", "PUT /config/me hợp lệ -> 200", s == 200, (s, b))
    s, b, _ = c.call("GET", "/api/v1/config/me")
    check("config", "GET lại thấy giá trị vừa lưu", s == 200 and isinstance(b, dict)
          and all(b.get(k) == v for k, v in new.items()), b)
    s, b, _ = c.call("PUT", "/api/v1/config/me", {"alert_sec": -1})
    check("config", "PUT giá trị sai (alert_sec = -1) -> 400", s == 400, (s, b))
    s, b, _ = c.call("GET", "/api/v1/config/me", auth=False)
    check("config", "GET /config/me không JWT -> 401", s == 401, (s, b))


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


GROUPS = {"health": t_health, "auth": t_auth, "batch": t_batch, "errors": t_errors, "perf": t_perf, "config": t_config}


def main():
    ap = argparse.ArgumentParser(description="Kiểm tra hợp đồng API v1.0")
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--token", help="JWT có sẵn (thay cho --email/--password)")
    ap.add_argument("--no-auth", action="store_true", help="server chưa làm JWT: bỏ qua nhóm auth, config")
    ap.add_argument("--only", nargs="*", choices=list(GROUPS), help="chỉ chạy các nhóm này")
    ap.add_argument("--report", help="ghi kết quả ra file JSON")
    a = ap.parse_args()
    if not a.no_auth and not (a.token or (a.email and a.password)):
        ap.error("cần --email + --password, hoặc --token, hoặc --no-auth")

    c = Client(a.base, a.token)
    print(f"Kiểm tra hợp đồng API v1.0 tại {a.base}  (run {uuid.uuid4().hex[:6]})")
    for name, fn in GROUPS.items():
        if a.only and name not in a.only:
            continue
        print(f"\n[{name}]")
        try:
            fn(c, a)
        except urllib.error.URLError as e:
            check(name, "kết nối được server", False, e)
            break
    n_ok = sum(r["ok"] for r in RESULTS)
    print(f"\nKết quả: {n_ok}/{len(RESULTS)} đạt ({100 * n_ok / max(len(RESULTS), 1):.0f}%)")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump({"base": a.base, "passed": n_ok, "total": len(RESULTS), "results": RESULTS}, f,
                      ensure_ascii=False, indent=2)
    sys.exit(0 if n_ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
