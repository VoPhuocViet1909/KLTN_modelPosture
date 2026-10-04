"""
Gộp metrics theo cửa sổ thời gian (mặc định 60 giây, căn theo phút đồng hồ) từ CÙNG các mẫu ghi vào log.csv.

Chạy trong app: realtime_app.py gọi add(...) mỗi lần lấy mẫu (~10 lần/giây), hết phút -> 1 bản metrics.
Chạy riêng trên file log.csv có sẵn (để làm dataset / báo cáo):

  python metrics.py out/log.csv --start 2026-10-03T14:00:00+07:00 --out out/metrics_from_log.csv

Mọi tỉ lệ tính theo THỜI GIAN (mỗi mẫu nặng bằng khoảng cách tới mẫu trước, tối đa 1 giây), chỉ tính lúc có người.

postureScore (0..100), tính khi có người >= 10% cửa sổ:
    score = 100 × trung bình có trọng số của các nhánh đang có dữ liệu
              cổ/thân : goodRatio              (trọng số 0.6)
              lệch vai: 1 − shoulderBadRatio   (0.2)
              khoảng cách: 1 − tooCloseRatio   (0.2)
            − 5 × số lần bật cảnh báo tư thế (ALERT_STARTED) trong cửa sổ, kẹp trong [0, 100]
"""
import argparse
import csv
import json
import math
import time
import uuid
from datetime import datetime, timezone

BAD_STATES = ("BAD", "CANH BAO")
KNOWN_STATES = ("GOOD", "BAD", "CANH BAO")
WEIGHTS = {"neck": 0.6, "shoulder": 0.2, "distance": 0.2}
POSTURE_ALERTS = ("NECK_TRUNK", "SHOULDER_TILT", "TOO_CLOSE")


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mean(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


class _Window:
    def __init__(self, start):
        self.start = start
        self.covered = self.presence = 0.0
        self.samples = 0
        self.t = {"neck_known": 0.0, "neck_good": 0.0, "sh_known": 0.0, "sh_bad": 0.0, "d_known": 0.0, "d_bad": 0.0}
        self.v = {k: [] for k in ("pbad", "neck", "trunk", "head", "tilt", "dist")}
        self.alerts = {}


class MetricsAggregator:
    def __init__(self, on_metric, wall_t0, session_id, device_id, user_id=None, window_sec=60,
                 model_version=None, app_version="1.0.0"):
        self.on_metric = on_metric
        self.wall_t0, self.window = wall_t0, int(window_sec)
        self.session_id, self.device_id, self.user_id = session_id, device_id, user_id
        self.model_version, self.app_version = model_version, app_version
        self.cur = None
        self.last_now = None

    def add(self, now, present, neck_status=None, p_bad=None, ang=None, tilt_rel=None, tilt_status=None,
            dist_cm=None, dist_status=None):
        wall = self.wall_t0 + now
        wstart = math.floor(wall / self.window) * self.window
        if self.cur is None:
            self.cur = _Window(wstart)
        elif wstart != self.cur.start:
            self.flush()
            self.cur = _Window(wstart)
        dt = 0.0 if self.last_now is None else min(max(now - self.last_now, 0.0), 1.0)
        self.last_now = now
        w = self.cur
        w.covered += dt
        w.samples += 1
        if not present:
            return
        w.presence += dt
        if neck_status in KNOWN_STATES:
            w.t["neck_known"] += dt
            w.t["neck_good"] += dt if neck_status == "GOOD" else 0.0
        if tilt_status in KNOWN_STATES:
            w.t["sh_known"] += dt
            w.t["sh_bad"] += dt if tilt_status in BAD_STATES else 0.0
        if dist_status in KNOWN_STATES:
            w.t["d_known"] += dt
            w.t["d_bad"] += dt if dist_status in BAD_STATES else 0.0
        if p_bad is not None and math.isfinite(p_bad):
            w.v["pbad"].append(p_bad)
        if ang:
            for k, key in (("neck", "neck"), ("trunk", "trunk"), ("head", "head_pitch")):
                x = ang.get(key)
                if x is not None and math.isfinite(x):
                    w.v[k].append(x)
        if tilt_rel is not None and math.isfinite(tilt_rel):
            w.v["tilt"].append(tilt_rel)
        if dist_cm is not None and math.isfinite(dist_cm):
            w.v["dist"].append(dist_cm)

    def on_event(self, ev):
        """Listener của EventLog: đếm số lần bật cảnh báo / nhắc nhở trong cửa sổ hiện tại."""
        if self.cur is not None and ev.get("eventType") in ("ALERT_STARTED", "REMINDER") and ev.get("alertType"):
            a = ev["alertType"]
            self.cur.alerts[a] = self.cur.alerts.get(a, 0) + 1

    def flush(self):
        w = self.cur
        if w is None or w.samples == 0:
            return None
        self.cur = None
        ratio = lambda num, den: round(num / den, 3) if den > 0 else None
        good = ratio(w.t["neck_good"], w.t["neck_known"])
        sh_bad = ratio(w.t["sh_bad"], w.t["sh_known"])
        close = ratio(w.t["d_bad"], w.t["d_known"])
        m = {
            "metricId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.session_id}/{w.start}")),
            "userId": self.user_id, "deviceId": self.device_id, "sessionId": self.session_id,
            "windowStart": _iso(w.start), "windowSec": self.window,
            "coveredSec": round(w.covered, 1), "samples": w.samples, "presenceSec": round(w.presence, 1),
            "goodRatio": good, "pBadMean": _mean(w.v["pbad"]),
            "neckMean": _mean(w.v["neck"]), "neckMax": max(w.v["neck"], default=None),
            "trunkMean": _mean(w.v["trunk"]), "trunkMax": max(w.v["trunk"], default=None),
            "headPitchMean": _mean(w.v["head"]),
            "tiltRelMean": _mean(w.v["tilt"]), "tiltAbsMax": max((abs(x) for x in w.v["tilt"]), default=None),
            "shoulderBadRatio": sh_bad,
            "distanceMeanCm": _mean(w.v["dist"]), "distanceMinCm": min(w.v["dist"], default=None),
            "tooCloseRatio": close,
            "alertCount": dict(w.alerts),
            "postureScore": self.score(w, good, sh_bad, close),
            "modelVersion": self.model_version, "appVersion": self.app_version,
        }
        for k in ("neckMax", "trunkMax", "tiltAbsMax", "distanceMinCm"):
            if m[k] is not None:
                m[k] = round(m[k], 2)
        if self.on_metric:
            self.on_metric(m)
        return m

    @staticmethod
    def score(w, good, sh_bad, close):
        if w.covered <= 0 or w.presence < 0.1 * w.covered:
            return None
        parts = []
        if good is not None:
            parts.append((WEIGHTS["neck"], good))
        if sh_bad is not None:
            parts.append((WEIGHTS["shoulder"], 1 - sh_bad))
        if close is not None:
            parts.append((WEIGHTS["distance"], 1 - close))
        if not parts:
            return None
        base = 100 * sum(wt * v for wt, v in parts) / sum(wt for wt, _ in parts)
        penalty = 5 * sum(n for a, n in w.alerts.items() if a in POSTURE_ALERTS)
        return int(round(min(100, max(0, base - penalty))))


# ---------------------------------------------------------------- chạy riêng trên log.csv
def _f(row, k):
    try:
        x = float(row.get(k) or "nan")
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def aggregate_log(path, start_wall, window=60, session_id="offline", device_id="offline"):
    out = []
    agg = MetricsAggregator(out.append, start_wall, session_id, device_id, window_sec=window)
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    prev = None
    for r in rows:
        now = _f(r, "time")
        if now is None:
            continue
        neck = _f(r, "neck")
        present = neck is not None and r.get("posture") not in ("", "...")
        ang = {"neck": neck, "trunk": _f(r, "trunk"), "head_pitch": _f(r, "head_pitch")}
        agg.add(now, present, r.get("posture"), _f(r, "p_bad"), ang, _f(r, "tilt_rel"), r.get("shoulder"),
                _f(r, "distance_cm"), r.get("distance"))
        # đếm lần bật cảnh báo từ cột trạng thái (log.csv không có sự kiện)
        if prev is not None:
            for col, a in (("posture", "NECK_TRUNK"), ("shoulder", "SHOULDER_TILT"), ("distance", "TOO_CLOSE")):
                if r.get(col) == "CANH BAO" and prev.get(col) != "CANH BAO":
                    agg.on_event({"eventType": "ALERT_STARTED", "alertType": a})
        prev = r
    agg.flush()
    return out


def main():
    ap = argparse.ArgumentParser(description="Gộp log.csv thành metrics theo cửa sổ")
    ap.add_argument("log")
    ap.add_argument("--start", default=None, help="thời điểm thật ứng với time=0, ISO-8601 (mặc định: bây giờ)")
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--out", default=None, help=".csv hoặc .jsonl (mặc định in ra màn hình)")
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start).timestamp() if a.start else time.time()
    ms = aggregate_log(a.log, start, a.window)
    if not a.out:
        for m in ms:
            print(m["windowStart"], "score", m["postureScore"], "good", m["goodRatio"], "alerts", m["alertCount"])
        return
    if a.out.endswith(".jsonl"):
        with open(a.out, "w", encoding="utf-8") as f:
            for m in ms:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
    else:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(ms[0]) if ms else ["metricId"])
            wr.writeheader()
            for m in ms:
                wr.writerow({k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in m.items()})
    print(f"{len(ms)} cửa sổ -> {a.out}")


if __name__ == "__main__":
    main()
