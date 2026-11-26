"""Chỉ số A3 từ kết quả `evaluate.py` + nhãn tay của công cụ A1.

Mức đoạn (mỗi cách: transformer, rf, rule): accuracy, macro-F1 6 lớp, ma trận nhầm lẫn, F1 lớp BAD. Bỏ đoạn UNCLEAR, đoạn
NO_POSE và đoạn chưa có nhãn; in số đoạn bỏ. Macro-F1 lấy trung bình F1 của các lớp có mặt trong nhãn tay (như notebook v4);
BAD thật = nhãn tay khác GOOD, BAD dự đoán = cột `<cách>_bad` (trạng thái thô).

Mức cảnh báo (trạng thái SAU LỌC, đọc alerts.csv):
  - cảnh báo nhầm/giờ: số ALERT_STARTED có t_on rơi vào đoạn nhãn tay GOOD, chia số giờ đã chấm (đoạn có nhãn, không
    UNCLEAR, không NO_POSE). Cảnh báo bật trong đoạn UNCLEAR/NO_POSE/chưa chấm không tính nhầm cũng không tính đúng.
  - đợt ngồi sai = chuỗi đoạn nhãn tay BAD (khác GOOD) liên tiếp, dài >= `alert_sec` của app (đọc từ run_meta.json, mặc
    định app_config.DEFAULTS). GOOD / UNCLEAR / NO_POSE / thiếu nhãn cắt đợt.
  - recall = tỉ lệ đợt có cảnh báo: cảnh báo bật trong [đầu đợt, cuối đợt], hoặc đang bật từ trước và còn bật ở đầu đợt.
  - độ trễ = t_on - đầu đợt (0 nếu cảnh báo đã bật sẵn), tính trên các đợt phát hiện được.

Khoảng tin cậy 95%: bootstrap percentile theo NGƯỜI (đơn vị lấy mẫu = người, gộp lại rồi tính lại chỉ số), số lần và seed cố định,
không phụ thuộc dữ liệu.

  python metrics.py --run out/lan1 [--labels labels_A.csv --rater A] [--boot 2000]
Đầu ra: <run>/metrics.json, <run>/metrics.md
"""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

import common as C
from common import APP_DEFAULTS

CLASSES = list(C.load_model_cfg()["classes"])
UNCLEAR, NO_POSE = "UNCLEAR", "NO_POSE"
METHODS = ("transformer", "rf", "rule")
SEG = C.SEGMENT_SEC


# ---------------------------------------------------------------- đọc
def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _truthy(v):
    return v not in ("", None)


# ---------------------------------------------------------------- chỉ số từ ma trận nhầm lẫn
def f1_macro(cm):
    """Trung bình F1 các lớp có mặt trong nhãn thật (hàng tổng > 0)."""
    cm = np.asarray(cm, float)
    f = []
    for k in range(len(cm)):
        if cm[k].sum() == 0:
            continue
        tp, fp, fn = cm[k, k], cm[:, k].sum() - cm[k, k], cm[k].sum() - cm[k, k]
        f.append(2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0)
    return float(np.mean(f)) if f else float("nan")


def f1_bad(bc):
    tp, fp, fn = bc["tp"], bc["fp"], bc["fn"]
    return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else float("nan")


# ---------------------------------------------------------------- thống kê theo người và cách
def _episodes(segs, min_sec):
    """segs: list dict (video, t_start, t_end, y) với y = 'BAD' / khác; trả list (video, start, end) các đợt BAD liên tiếp."""
    out, cur = [], None
    for s in sorted(segs, key=lambda r: (r["video"], r["t_start"])):
        isb = s["y"] == "BAD"
        if isb and cur and cur[0] == s["video"] and abs(cur[2] - s["t_start"]) < 1e-6:
            cur[2] = s["t_end"]
        else:
            if cur and cur[2] - cur[1] >= min_sec - 1e-9:
                out.append(tuple(cur))
            cur = [s["video"], s["t_start"], s["t_end"]] if isb else None
    if cur and cur[2] - cur[1] >= min_sec - 1e-9:
        out.append(tuple(cur))
    return out


def person_stats(rows, alerts, method, alert_sec):
    """rows: dòng predictions.csv của MỘT người; alerts: dòng alerts.csv của người đó (mọi cách). -> dict cộng gộp được."""
    K = len(CLASSES)
    cm = np.zeros((K, K), int)
    bc = dict(tp=0, fp=0, fn=0, tn=0)
    drop = dict(total=len(rows), unlabeled=0, unclear=0, no_pose=0, scored=0)
    scored_segs, lab_by_seg = [], {}
    for r in rows:
        t, pred = r["true_label"], r[method]
        if not t:
            drop["unlabeled"] += 1
            continue
        if t == UNCLEAR:
            drop["unclear"] += 1
            continue
        if pred == NO_POSE:
            drop["no_pose"] += 1
            continue
        drop["scored"] += 1
        cm[CLASSES.index(t), CLASSES.index(pred)] += 1
        yb, pb = t != "GOOD", r[f"{method}_bad"] in (1, "1", True, "True")
        bc["tp" if yb and pb else "fn" if yb else "fp" if pb else "tn"] += 1
        key = (r["video"], round(float(r["t_start"]), 3))
        lab_by_seg[key] = "BAD" if yb else "GOOD"
        scored_segs.append(dict(video=r["video"], t_start=float(r["t_start"]), t_end=float(r["t_end"]), y="BAD" if yb else "GOOD"))
    hours = drop["scored"] * SEG / 3600.0
    mine = [a for a in alerts if a["method"] == method]
    false_alarms = true_alerts = 0
    for a in mine:
        seg = (a["video"], round(math.floor(float(a["t_on"]) / SEG + 1e-9) * SEG, 3))
        y = lab_by_seg.get(seg)
        if y == "GOOD":
            false_alarms += 1
        elif y == "BAD":
            true_alerts += 1
    eps = _episodes(scored_segs, alert_sec)
    lat, detected = [], 0
    for v, s, e in eps:
        hit = None
        for a in sorted((a for a in mine if a["video"] == v), key=lambda a: float(a["t_on"])):
            on, off = float(a["t_on"]), float(a["t_off"])
            if s - 1e-9 <= on <= e + 1e-9:
                hit = max(0.0, on - s)
                break
            if on < s and off >= s:
                hit = 0.0
                break
        if hit is not None:
            detected += 1
            lat.append(hit)
    return dict(cm=cm, bad=bc, drop=drop, hours=hours, false_alarms=false_alarms, true_alerts=true_alerts,
                n_alerts=len(mine), episodes=len(eps), detected=detected, latencies=lat)


def combine(stats):
    out = dict(cm=sum((s["cm"] for s in stats), np.zeros((len(CLASSES),) * 2, int)),
               bad={k: sum(s["bad"][k] for s in stats) for k in ("tp", "fp", "fn", "tn")},
               drop={k: sum(s["drop"][k] for s in stats) for k in ("total", "unlabeled", "unclear", "no_pose", "scored")},
               hours=sum(s["hours"] for s in stats), false_alarms=sum(s["false_alarms"] for s in stats),
               true_alerts=sum(s["true_alerts"] for s in stats), n_alerts=sum(s["n_alerts"] for s in stats),
               episodes=sum(s["episodes"] for s in stats), detected=sum(s["detected"] for s in stats),
               latencies=[x for s in stats for x in s["latencies"]])
    return out


def finalize(s):
    n = int(s["cm"].sum())
    nan = float("nan")
    return dict(
        accuracy=float(np.trace(s["cm"]) / n) if n else nan, macro_f1=f1_macro(s["cm"]), f1_bad=f1_bad(s["bad"]),
        false_alarms_per_hour=s["false_alarms"] / s["hours"] if s["hours"] > 0 else nan,
        recall_episodes=s["detected"] / s["episodes"] if s["episodes"] else nan,
        latency_mean_sec=float(np.mean(s["latencies"])) if s["latencies"] else nan,
        latency_median_sec=float(np.median(s["latencies"])) if s["latencies"] else nan)


METRIC_KEYS = ("accuracy", "macro_f1", "f1_bad", "false_alarms_per_hour", "recall_episodes", "latency_mean_sec")


def bootstrap(per_person, n_boot=2000, seed=0):
    """per_person: dict person -> stats. Lấy mẫu NGƯỜI có hoàn lại, gộp lại, tính lại chỉ số. -> dict key -> (lo, hi) hoặc None."""
    persons = sorted(per_person)
    if len(persons) < 2:
        return {k: None for k in METRIC_KEYS}
    rng = np.random.default_rng(seed)
    vals = {k: [] for k in METRIC_KEYS}
    for _ in range(n_boot):
        pick = rng.integers(0, len(persons), len(persons))
        m = finalize(combine([per_person[persons[i]] for i in pick]))
        for k in METRIC_KEYS:
            vals[k].append(m[k])
    out = {}
    for k, v in vals.items():
        v = np.array(v, float)
        v = v[np.isfinite(v)]
        out[k] = None if len(v) < max(10, n_boot // 10) else [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return out


def compute(pred_rows, alert_rows, alert_sec, n_boot=2000, seed=0):
    persons = sorted({r["person"] for r in pred_rows})
    res = dict(persons=persons, alert_sec=alert_sec, bootstrap=dict(n=n_boot, seed=seed, unit="person"), methods={})
    for m in METHODS:
        per = {p: person_stats([r for r in pred_rows if r["person"] == p],
                               [a for a in alert_rows if a["person"] == p], m, alert_sec) for p in persons}
        tot = combine(list(per.values()))
        ci = bootstrap(per, n_boot, seed)
        res["methods"][m] = dict(
            **finalize(tot), ci95=ci, n_segments_scored=tot["drop"]["scored"], dropped=tot["drop"],
            hours_scored=tot["hours"], false_alarms=tot["false_alarms"], n_alerts=tot["n_alerts"],
            episodes=tot["episodes"], episodes_detected=tot["detected"],
            confusion=dict(labels=CLASSES, rows="nhãn tay", cols="dự đoán", matrix=tot["cm"].tolist()),
            per_person={p: dict(**finalize(s), n_segments_scored=s["drop"]["scored"]) for p, s in per.items()})
    return res


# ---------------------------------------------------------------- Markdown
def _f(v, nd=3):
    return "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.{nd}f}"


def _ci(c, nd=3):
    return "—" if not c else f"[{c[0]:.{nd}f}; {c[1]:.{nd}f}]"


def to_markdown(res):
    L = [f"Người: {', '.join(res['persons'])} (bootstrap {res['bootstrap']['n']} lần theo người, seed {res['bootstrap']['seed']}). "
         f"Đợt ngồi sai dài ≥ {res['alert_sec']} s.", ""]
    L += ["| Chỉ số | Transformer | Random Forest | Luật góc |", "|---|---|---|---|"]
    names = dict(accuracy="Accuracy (đoạn)", macro_f1="Macro-F1 6 lớp", f1_bad="F1 lớp BAD",
                 false_alarms_per_hour="Cảnh báo nhầm / giờ", recall_episodes="Recall đợt ngồi sai",
                 latency_mean_sec="Độ trễ TB (s)")
    for k in METRIC_KEYS:
        nd = 1 if k in ("false_alarms_per_hour", "latency_mean_sec") else 3
        L.append(f"| {names[k]} | " + " | ".join(f"{_f(res['methods'][m][k], nd)} {_ci(res['methods'][m]['ci95'][k], nd)}"
                                                 for m in METHODS) + " |")
    L += ["", "| Số liệu | Transformer | Random Forest | Luật góc |", "|---|---|---|---|"]
    rows = [("Đoạn đã chấm điểm", lambda d: d["n_segments_scored"]),
            ("Bỏ: UNCLEAR", lambda d: d["dropped"]["unclear"]), ("Bỏ: NO_POSE", lambda d: d["dropped"]["no_pose"]),
            ("Bỏ: chưa có nhãn", lambda d: d["dropped"]["unlabeled"]),
            ("Giờ đã chấm", lambda d: f"{d['hours_scored']:.3f}"), ("Cảnh báo (tổng)", lambda d: d["n_alerts"]),
            ("Cảnh báo nhầm", lambda d: d["false_alarms"]),
            ("Đợt ngồi sai / phát hiện", lambda d: f"{d['episodes']} / {d['episodes_detected']}")]
    for name, fn in rows:
        L.append(f"| {name} | " + " | ".join(str(fn(res["methods"][m])) for m in METHODS) + " |")
    for m in METHODS:
        cmx = res["methods"][m]["confusion"]
        L += ["", f"Ma trận nhầm lẫn — {m} (hàng = nhãn tay, cột = dự đoán)", "",
              "| | " + " | ".join(cmx["labels"]) + " |", "|---|" + "---|" * len(cmx["labels"])]
        L += [f"| **{lab}** | " + " | ".join(str(v) for v in row) + " |" for lab, row in zip(cmx["labels"], cmx["matrix"])]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="thư mục out/<run> của evaluate.py")
    ap.add_argument("--labels", nargs="*", default=[], help="CSV nhãn A1; bỏ qua nếu predictions.csv đã có true_label")
    ap.add_argument("--rater", default=None)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    run = Path(a.run)
    pred = read_csv(run / "predictions.csv")
    alerts = read_csv(run / "alerts.csv")
    if a.labels:
        from evaluate import load_labels
        import pipeline as P
        P.attach_labels(pred, load_labels(a.labels, a.rater))
    alert_sec = APP_DEFAULTS["alert_sec"]
    mp = run / "run_meta.json"
    if mp.exists():
        alert_sec = json.loads(mp.read_text(encoding="utf-8"))["params"]["filter"]["alert_sec"]
    res = compute(pred, alerts, alert_sec, a.boot, a.seed)
    (run / "metrics.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    md = to_markdown(res)
    (run / "metrics.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
