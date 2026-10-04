"""
Phát dữ liệu giả lập vào server theo đúng hợp đồng v1.0. Chỉ cần thư viện chuẩn.

1) seed – sinh LỊCH SỬ nhiều ngày cho nhiều máy, để làm Dashboard khi chưa có app thật:
   python replay.py seed --base http://127.0.0.1:8080 --email demo@kltn.local --password 123456 --devices 5 --days 7
   Mỗi ngày làm việc 08:30–17:30, nghỉ trưa 12:00–13:00; tư thế xấu dần về chiều; có cảnh báo, vắng mặt,
   nhắc nghỉ mắt, đầu / cuối phiên. 1 máy × 1 ngày ≈ 480 metrics + 60–120 sự kiện.

2) load – kiểm thử tải: N máy gửi đồng thời trong T giây:
   python replay.py load --base ... --token <JWT> --devices 500 --duration 120 --interval 5
   Mỗi máy gửi 1 lô mỗi --interval giây (mặc định 60 = nhịp thật; 5 = dồn tải gấp 12 lần),
   mỗi lô = 1 metrics (+ 30% kèm cặp cảnh báo). In throughput, độ trễ p50 / p95 / p99, lỗi theo mã.
   --out ket_qua.csv ghi từng request (dùng vẽ biểu đồ cho chương đánh giá).

Cờ chung: --email/--password (đăng nhập 1 lần, mọi máy dùng chung token) | --token | --no-auth
"""
import argparse
import csv
import heapq
import json
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from payloads import Device


def login(base, email, password):
    req = urllib.request.Request(base + "/api/v1/auth/login", method="POST",
                                 data=json.dumps({"email": email, "password": password,
                                                  "deviceId": "dev_replay", "deviceName": "replay.py"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["accessToken"]


def post(base, token, batch, timeout=10):
    """-> (status, accepted, rejected, giây)"""
    h = {"Content-Type": "application/json", "X-Device-Id": batch["deviceId"]}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + "/api/v1/telemetry/batch", data=json.dumps(batch).encode(), headers=h,
                                 method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read() or b"{}")
            return r.status, len(body.get("accepted", [])), len(body.get("rejected", [])), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, 0, 0, time.perf_counter() - t0
    except Exception:
        return 0, 0, 0, time.perf_counter() - t0          # 0 = lỗi mạng / timeout


def pct(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


# ====================================================================== seed
def day_history(dev, day, rng):
    """Sự kiện + metrics của 1 ngày làm việc (giờ Việt Nam, UTC+7)."""
    vn = timezone(timedelta(hours=7))
    start = datetime(day.year, day.month, day.day, 8, 30, tzinfo=vn) + timedelta(minutes=rng.randint(-15, 15))
    end = datetime(day.year, day.month, day.day, 17, 30, tzinfo=vn) + timedelta(minutes=rng.randint(-20, 30))
    lunch0 = datetime(day.year, day.month, day.day, 12, 0, tzinfo=vn)
    lunch1 = lunch0 + timedelta(minutes=rng.randint(50, 70))
    dev.session_id = "s_" + format(rng.getrandbits(48), "012x")
    events = [dev.session_start(start), dev.calibrated(start + timedelta(seconds=10))]
    metrics, t, last_eye = [], start.replace(second=0) + timedelta(minutes=1), start
    while t < end:
        if lunch0 <= t < lunch1:
            if t == lunch0:
                events += dev.away_back(lunch0, int((lunch1 - lunch0).total_seconds()))
            t += timedelta(minutes=1)
            continue
        hours = (t - start).total_seconds() / 3600
        fatigue = 0.05 * hours + (0.08 if t.hour in (14, 15, 16) else 0)
        good = min(1.0, max(0.0, rng.gauss(0.88 - fatigue, 0.12)))
        alerts = {}
        if good < 0.6 and rng.random() < 0.15:          # ~20–30 lần cảnh báo / ngày
            kind = rng.choice(["NECK_TRUNK", "NECK_TRUNK", "NECK_TRUNK", "SHOULDER_TILT", "TOO_CLOSE"])
            events += dev.alert_pair(t + timedelta(seconds=rng.randint(0, 20)), rng.randint(15, 90), kind)
            alerts = {kind: 1}
        metrics.append(dev.metric(t, bad_ratio=1 - good, alerts=alerts))
        if (t - last_eye).total_seconds() >= 1200:
            events.append(dev.reminder(t))
            last_eye = t
        t += timedelta(minutes=1)
    events.append(dev.session_end(end, round((end - start).total_seconds(), 1)))
    return events, metrics


def cmd_seed(a, token):
    rng = random.Random(a.seed)
    today = datetime.now(timezone(timedelta(hours=7))).date()
    days = [today - timedelta(days=i) for i in range(a.days, 0, -1)]
    days = [d for d in days if d.weekday() < 5 or a.weekends]
    sent = acc = rej = errs = 0
    t0 = time.time()
    for k in range(a.devices):
        dev = Device(seed=rng.random())
        for d in days:
            events, metrics = day_history(dev, d, rng)
            items = [("e", e) for e in events] + [("m", m) for m in metrics]
            for i in range(0, len(items), a.batch):
                chunk = items[i:i + a.batch]
                batch = dev.batch([x for t, x in chunk if t == "e"], [x for t, x in chunk if t == "m"])
                s, n_acc, n_rej, _ = post(a.base, token, batch)
                sent += len(chunk)
                acc += n_acc
                rej += n_rej
                errs += s != 200
                if s != 200 and errs <= 3:
                    print(f"  lỗi HTTP {s} (máy {dev.device_id}, ngày {d})")
        print(f"máy {k + 1}/{a.devices} ({dev.device_id}): {len(days)} ngày")
    print(f"\nĐã gửi {sent} mục trong {time.time() - t0:.1f} s: accepted {acc}, rejected {rej}, lô lỗi {errs}")


# ====================================================================== load
def cmd_load(a, token):
    rng = random.Random(a.seed)
    devs = [Device(seed=rng.random()) for _ in range(a.devices)]
    sim_minute = {d.device_id: 0 for d in devs}
    base_time = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    lock = threading.Lock()
    rows = []
    t_start = time.time()
    # lịch: mỗi máy bắt đầu lệch nhau ngẫu nhiên trong khoảng --ramp giây
    heap = [(t_start + rng.uniform(0, a.ramp), i) for i in range(len(devs))]
    heapq.heapify(heap)

    def send(i):
        dev = devs[i]
        with lock:
            m = sim_minute[dev.device_id]
            sim_minute[dev.device_id] += 1
        ts = base_time + timedelta(minutes=m)          # mỗi lô = 1 "phút" giả lập -> metricId không trùng
        events = [dev.session_start(ts), dev.calibrated(ts)] if m == 0 else []
        if rng.random() < 0.3:
            events += dev.alert_pair(ts, rng.randint(10, 60))
        batch = dev.batch(events, [dev.metric(ts)])
        s, n_acc, n_rej, dt = post(a.base, token, batch, a.timeout)
        with lock:
            rows.append((time.time() - t_start, dev.device_id, s, dt, len(events) + 1, n_acc, n_rej))

    print(f"{a.devices} máy, {a.duration} s, mỗi máy 1 lô / {a.interval} s "
          f"(≈ {a.devices / a.interval:.1f} request/s mục tiêu), {a.workers} luồng")
    last_print = t_start
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while time.time() - t_start < a.duration:
            now = time.time()
            while heap and heap[0][0] <= now:
                due, i = heapq.heappop(heap)
                pool.submit(send, i)
                heapq.heappush(heap, (due + a.interval, i))
            if now - last_print >= 10:
                last_print = now
                with lock:
                    recent = [r for r in rows if r[0] >= now - t_start - 10]
                lat = [r[3] for r in recent if r[2] == 200]
                print(f"  t={now - t_start:5.0f}s  {len(recent) / 10:6.1f} req/s  "
                      f"p95 {1000 * pct(lat, 95):6.0f} ms  lỗi {sum(r[2] != 200 for r in recent)}")
            time.sleep(0.005)
    elapsed = time.time() - t_start
    ok = [r for r in rows if r[2] == 200]
    lat = [r[3] for r in ok]
    codes = {}
    for r in rows:
        codes[r[2]] = codes.get(r[2], 0) + 1
    print("\n===== KẾT QUẢ =====")
    print(f"request: {len(rows)}  thành công: {len(ok)} ({100 * len(ok) / max(len(rows), 1):.1f}%)  mã: {codes}")
    print(f"throughput: {len(rows) / elapsed:.1f} request/s, {sum(r[5] for r in rows) / elapsed:.1f} mục/s")
    print(f"độ trễ (ms): p50 {1000 * pct(lat, 50):.0f}  p95 {1000 * pct(lat, 95):.0f}  "
          f"p99 {1000 * pct(lat, 99):.0f}  max {1000 * max(lat, default=float('nan')):.0f}")
    print(f"mục bị rejected: {sum(r[6] for r in rows)}")
    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_sec", "device_id", "status", "latency_ms", "items", "accepted", "rejected"])
            for r in rows:
                w.writerow([f"{r[0]:.3f}", r[1], r[2], f"{1000 * r[3]:.1f}", r[4], r[5], r[6]])
        print("->", a.out)


def main():
    ap = argparse.ArgumentParser(description="Phát dữ liệu giả lập vào server (hợp đồng v1.0)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("seed", "load"):
        p = sub.add_parser(name)
        p.add_argument("--base", default="http://127.0.0.1:8080")
        p.add_argument("--email")
        p.add_argument("--password")
        p.add_argument("--token")
        p.add_argument("--no-auth", action="store_true")
        p.add_argument("--devices", type=int, default=5)
        p.add_argument("--seed", type=int, default=42, help="hạt giống ngẫu nhiên (chạy lại ra cùng dữ liệu)")
        if name == "seed":
            p.add_argument("--days", type=int, default=7)
            p.add_argument("--weekends", action="store_true", help="sinh cả thứ 7, chủ nhật")
            p.add_argument("--batch", type=int, default=200, help="số mục / lô")
        else:
            p.add_argument("--duration", type=float, default=60)
            p.add_argument("--interval", type=float, default=60)
            p.add_argument("--ramp", type=float, default=10, help="giãn thời điểm bắt đầu các máy (giây)")
            p.add_argument("--workers", type=int, default=64)
            p.add_argument("--timeout", type=float, default=10)
            p.add_argument("--out")
    a = ap.parse_args()
    a.base = a.base.rstrip("/")
    token = a.token
    if a.email and a.password:
        token = login(a.base, a.email, a.password)
    elif not token and not a.no_auth:
        ap.error("cần --email + --password, hoặc --token, hoặc --no-auth")
    (cmd_seed if a.cmd == "seed" else cmd_load)(a, token)


if __name__ == "__main__":
    main()
