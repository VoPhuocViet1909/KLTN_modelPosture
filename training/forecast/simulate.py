"""Sinh dữ liệu GIẢ đúng hợp đồng 3.1–3.2 (minutes.jsonl + sessions.jsonl) để kiểm pipeline dự báo. Seed cố định.

Mô hình sinh (KHÔNG phải mô hình về người thật, chỉ để có tín hiệu dự báo được):
- Mỗi người có tham số riêng (hazard nền, độ tăng theo thời gian ngồi, tốc độ hồi phục, thói quen rời ghế, phân bố lớp xấu).
- Chế độ GOOD/BAD theo phút kiểu Markov: xác suất GOOD->BAD tăng dần theo thời gian ngồi liên tục (và nhẹ theo giờ chiều);
  BAD->GOOD tăng sau khi có cảnh báo. Rời ghế (xác suất tăng khi ngồi lâu) làm reset đồng hồ ngồi và đưa về GOOD.
- Có phút rời ghế (một phần/cả phút), mất tín hiệu (unknown_sec = 60, lớp null), phút đầu/cuối phiên phủ một phần, cảnh báo
  phát sinh khi BAD kéo dài (alerts_total), `model_version` ghi `synthetic-sim`.
Kết quả chạy trên bộ này là KIỂM CODE, không phải kết quả nghiên cứu.

  python simulate.py OUT_DIR [--persons 10] [--sessions 4] [--seed 20261126]
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import data as D

TZ = timezone(timedelta(hours=7))


def person_params(rng, planted=False, planted_fatigue=False):
    """planted=True CHỈ cho bộ đối chứng công suất: BAD bắt đầu đúng khi ngồi liên tục đạt ngưỡng riêng và kéo dài 6 phút.
    Bộ chính (planted=False) giữ nguyên thứ tự rút số ngẫu nhiên."""
    p = dict(h0=rng.uniform(0.01, 0.04), h1=rng.uniform(0.03, 0.09), rec=rng.uniform(0.15, 0.35),
                leave0=rng.uniform(0.002, 0.008), leave_sit=rng.uniform(0.01, 0.03), leave_after=rng.uniform(35, 55),
                loss=rng.uniform(0.004, 0.015), cls_prior=rng.dirichlet(np.ones(5) * 1.5),
                alert_p=rng.uniform(0.5, 0.9))
    p["planted_T"] = int(rng.integers(18, 34)) if planted else None
    # chỉ rút thêm số ngẫu nhiên khi bật cờ -> đầu ra mặc định không đổi
    p["fatigue_m"] = float(rng.uniform(0.3, 1.2)) if planted_fatigue else None
    return p


def _classes(rng, present, bad_share, prior, f_classified):
    """Giây 6 lớp (làm tròn 0,1 s) cho một phút có người."""
    classified = present * f_classified
    bad = classified * bad_share
    parts = rng.multinomial(20, prior) / 20.0 * bad
    vals = [classified - bad, *parts]
    vals = [round(float(v), 1) for v in vals]
    while round(sum(vals), 1) > present:    # tổng lớp không vượt presence sau làm tròn
        vals[0] = round(max(vals[0] - 0.1, 0.0), 1)
    return vals


def simulate_session(rng, pr, start, duration_min, fatigue_v=None):
    """-> list dict phút (chưa có participant/session_id)."""
    end = start + timedelta(minutes=duration_min)
    floor = start.replace(second=0, microsecond=0)
    n = int(np.ceil((end - floor).total_seconds() / 60))
    off = start.second
    out = []
    mode, sit, bad_run, away_left, loss_left, planted_left = 0, 0, 0, 0, 0, 0
    last_alert_run = 0
    for m in range(n):
        w = floor + timedelta(minutes=m)
        win = 60.0
        covered_cap = win
        if m == 0:
            covered_cap = win - off
        if m == n - 1 and (end - w).total_seconds() < 60:
            covered_cap = (end - w).total_seconds()
        row = dict(minute_idx=m, window_start=w.isoformat())
        if loss_left > 0 or (m > 0 and rng.random() < pr["loss"]):
            if loss_left == 0:
                loss_left = int(rng.integers(1, 5))
            loss_left -= 1
            row.update(covered_sec=0.0, presence_sec=0.0, away_sec=0.0, unknown_sec=60.0, unclassified_sec=0.0, alerts_total=0,
                       model_version=None, app_version=None, **{f: None for f in D.CLASS_FIELDS})
            out.append(row)
            continue
        hour = w.hour + w.minute / 60
        away_sec = 0.0
        if away_left > 0:
            away_left -= 1
            away_sec = covered_cap if away_left > 0 else float(rng.uniform(10, 40))
            if away_left == 0:
                sit, mode, bad_run, last_alert_run = 0, 0, 0, 0
        elif m > 0 and rng.random() < pr["leave0"] + pr["leave_sit"] * max(0.0, sit - pr["leave_after"]) / 30:
            away_left = int(rng.integers(2, 9))
            away_sec = float(rng.uniform(10, 50))
            mode, bad_run = 0, 0
            sit = 0
        covered = round(covered_cap - (0.1 if m > 0 and rng.random() < 0.5 else 0.0), 1) if m > 0 else round(covered_cap, 1)
        covered = max(min(covered, covered_cap), 0.0)
        away_sec = min(away_sec, covered)
        present = round(covered - away_sec, 1)
        if present < 1.0:
            sit_inc = 0
        else:
            sit_inc = 1
        # chuyển chế độ (dựa trên thời gian ngồi và giờ), chỉ khi có người
        prev_mode = mode
        if present >= 1.0:
            haz = min(0.35, (pr["h0"] + pr["h1"] * sit / 30.0) * (1 + 0.3 * max(0.0, (hour - 13) / 5)))
            rec = min(0.9, pr["rec"] + (0.15 if bad_run >= 2 else 0.0))
            if fatigue_v is not None:                            # đối chứng công suất cho D (xuống sức): onset rõ, đoán được từ độ dốc đầu buổi
                fat_share = float(np.clip(min(0.85, 0.05 + 0.006 * fatigue_v * m) + rng.normal(0, 0.03), 0.0, 0.95))
                mode = 1 if fat_share > 0.5 else 0
            elif pr["planted_T"] is not None:                    # đối chứng công suất: khởi phát xác định
                if mode == 0 and sit == pr["planted_T"]:
                    mode, planted_left = 1, 6
                elif mode == 1:
                    planted_left -= 1
                    mode = 1 if planted_left > 0 else 0
            elif mode == 0 and rng.random() < haz:
                mode = 1
            elif mode == 1 and rng.random() < rec:
                mode = 0
            sit += sit_inc
        bad_run = bad_run + 1 if mode == 1 else 0
        alerts = 0
        if present >= 1.0:
            if mode == 1 and prev_mode == 0 and rng.random() < pr["alert_p"]:
                alerts, last_alert_run = 1, 0
            elif mode == 1 and bad_run - last_alert_run >= 4:
                alerts, last_alert_run = 1, bad_run
        vals = [None] * 6
        if present >= 1.0:
            if fatigue_v is not None:
                share = fat_share
            elif mode == 1:
                share = rng.uniform(0.3, 0.9) if prev_mode == 0 else float(rng.beta(8, 2))
            else:
                share = rng.uniform(0.1, 0.6) if prev_mode == 1 else float(rng.beta(1, 12))
            vals = _classes(rng, present, share, pr["cls_prior"], float(rng.uniform(0.9, 1.0)))
            unc = round(present - sum(vals), 1)
        else:
            unc = present
            if present > 0 or away_sec > 0:
                vals = [None] * 6
        row.update(covered_sec=covered, presence_sec=present, away_sec=round(away_sec, 1),
                   unknown_sec=round(win - covered, 1), unclassified_sec=unc, alerts_total=alerts,
                   model_version="synthetic-sim", app_version="synthetic",
                   **dict(zip(D.CLASS_FIELDS, vals)))
        out.append(row)
    return out, n


def _fix_row(row):
    """Giữ đúng quy tắc 3.1 sau làm tròn: lớp null thì unclassified = presence; away + presence = covered."""
    cov, pre = row["covered_sec"], row["presence_sec"]
    row["away_sec"] = round(cov - pre, 1)
    if all(row[f] is None for f in D.CLASS_FIELDS):
        row["unclassified_sec"] = pre
        if pre > 0 and row["model_version"] is None:
            row["model_version"] = "synthetic-sim"
    return row


def write_dataset(directory, persons=10, sessions=4, seed=20261126, planted=False, planted_fatigue=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    root = np.random.SeedSequence(seed)
    seeds = root.spawn(persons)
    origin = datetime(2026, 3, 2, 8, 0, tzinfo=TZ)
    srows, mrows = [], []
    for p in range(persons):
        rng = np.random.default_rng(seeds[p])
        pr = person_params(rng, planted, planted_fatigue)
        code = f"SIM{p + 1:02d}"
        for k in range(sessions):
            dur = int(rng.integers(90, 151))
            start = origin + timedelta(days=k + 7 * (p % 3), hours=int(rng.integers(0, 6)), minutes=int(rng.integers(0, 60)),
                                       seconds=int(rng.integers(5, 55)))
            sid = f"{code}-S{k + 1}"
            v = pr["fatigue_m"] * float(np.exp(rng.normal(0, 0.15))) if planted_fatigue else None
            rows, n = simulate_session(rng, pr, start, dur, v)
            end = start + timedelta(minutes=dur)
            srows.append(dict(participant=code, session_id=sid, started_at=start.isoformat(), ended_at=end.isoformat(),
                              duration_min=dur, camera_setup="side90+laptop", study_opt_in=True, ended_early=False,
                              note="Dữ liệu giả lập simulate.py"))
            for r in rows:
                mrows.append(dict(participant=code, session_id=sid, **_fix_row(r)))
    with open(directory / "sessions.jsonl", "w", encoding="utf-8") as f:
        for r in srows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(directory / "minutes.jsonl", "w", encoding="utf-8") as f:
        for r in mrows:
            r = {k: r[k] for k in ["participant", "session_id", "minute_idx", "window_start", "covered_sec", "presence_sec",
                                   "away_sec", "unknown_sec", "unclassified_sec", "alerts_total", "model_version", "app_version",
                                   *D.CLASS_FIELDS]}
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (directory / "simulate_meta.json").write_text(
        json.dumps(dict(persons=persons, sessions=sessions, seed=seed, planted=planted, **({"planted_fatigue": True} if planted_fatigue else {})),
                   indent=2), encoding="utf-8")
    D.load(directory)          # kiểm theo quy tắc 3.1; ném DataError nếu sai
    return directory


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--persons", type=int, default=10)
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261126)
    ap.add_argument("--planted", action="store_true",
                    help="bộ đối chứng công suất: BAD khởi phát xác định theo thời gian ngồi (KHÔNG thực tế)")
    ap.add_argument("--planted-fatigue", action="store_true",
                    help="bộ đối chứng công suất cho D (xuống sức): BAD tăng dần theo phút với độ dốc riêng từng phiên rồi vọt lên ở onset (KHÔNG thực tế)")
    a = ap.parse_args()
    d = write_dataset(a.out, a.persons, a.sessions, a.seed, a.planted, a.planted_fatigue)
    print("đã ghi", d, "|", D.summary(D.load(d)))


if __name__ == "__main__":
    main()
