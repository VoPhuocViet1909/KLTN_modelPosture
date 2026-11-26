"""Lõi của pipeline đánh giá A2: hàm thuần (không đọc video), test được bằng dữ liệu tự sinh.

Luồng cho một video (cam hông 90°):
  góc thô -> hiệu chỉnh -> cửa sổ 20 khung bước 1 (như engine.py) -> 3 bộ dự đoán cùng cửa sổ
  (Transformer ONNX, RF, luật góc) -> CÙNG bộ lọc của app (median 5 + hysteresis + AlertTracker)
  -> trạng thái thô và sau lọc -> quy về đoạn 2 giây khớp công cụ chấm A1.

Mỗi bộ dự đoán quy về cùng một dạng: p_bad (N,) và probs 6 lớp (N,6) cho từng cửa sổ, nên bộ lọc và cách chọn lớp
giống hệt nhau (posture_class.pick_posture_class trên trung bình 5 cửa sổ như engine.py).
"""
import collections
from collections import Counter

import numpy as np

import common as C
from common import APP_DEFAULTS, angles_ok, ANGLE_KEYS, pf
from alerts import AlertTracker   # của app
import posture_class              # của app

METHODS = ("transformer", "rf", "rule")
NO_POSE = "NO_POSE"
MIN_COVERAGE = 0.5      # đoạn có < 50% cửa sổ hợp lệ -> NO_POSE


# ---------------------------------------------------------------- góc, hiệu chỉnh, cửa sổ
def calibrate(cal_lm, cal_world):
    """Landmark của đoạn hiệu chỉnh -> (side, facing, baseline) đúng như engine.py khi hiệu chỉnh xong."""
    ok = np.isfinite(cal_lm).any(axis=(1, 2))
    if ok.sum() < 5:
        raise ValueError("Đoạn hiệu chỉnh có < 5 khung thấy người")
    lm, w = cal_lm[ok], cal_world[ok]
    side = pf.choose_side(lm, w)
    f = pf.facing_sign(lm, side)
    base = pf.calibration_baseline(pf.sequence_angles(lm, side, f))
    if not all(np.isfinite(v) for v in base.values()):
        raise ValueError(f"Baseline không hữu hạn: {base}")
    return side, f, base


def calibrated_angles(lm, side, f, base):
    """-> (cal (T,F) góc đã hiệu chỉnh, valid (T,) khung dùng được). Khung không hợp lệ giống engine.py: góc phi lý
    (angles_ok) hoặc thiếu cổ/thân -> coi như không thấy người."""
    cal = pf.apply_calibration(pf.sequence_angles(lm, side, f), base)
    iN, iT = C.FEATURES.index("neck"), C.FEATURES.index("trunk")
    valid = np.isfinite(cal[:, [iN, iT]]).all(1)
    for i in np.where(valid)[0]:
        if not angles_ok({k: float(cal[i, C.FEATURES.index(k)]) for k in ANGLE_KEYS}):
            valid[i] = False
    return cal, valid


def make_windows(cal, valid, t, win=C.WIN):
    """Cửa sổ trượt bước 1 khung (như engine.py). Trả dict: end (N,), t_end, t_center, ok (N,) cửa sổ đủ điều kiện dự đoán,
    X (N,win,F) đầu vào model (khung không hợp lệ = 0 như engine.py)."""
    T = len(cal)
    xin = pf.to_model_input(cal)
    xin[~valid] = 0.0
    if T < win:
        return dict(end=np.zeros(0, int), t_end=np.zeros(0), t_center=np.zeros(0), ok=np.zeros(0, bool),
                    X=np.zeros((0, win, len(C.FEATURES)), np.float32), valid=valid, cal=cal)
    ends = np.arange(win - 1, T)
    X = np.stack([xin[e - win + 1:e + 1] for e in ends])
    iV = C.FEATURES.index("vis_hip")
    ok = np.array([valid[e - win + 1:e + 1].mean() >= C.MIN_VALID and np.nanmean(cal[e - win + 1:e + 1, iV]) >= C.MIN_VIS_HIP
                   for e in ends])
    t = np.asarray(t, float)
    return dict(end=ends, t_end=t[ends], t_center=(t[ends] + t[ends - win + 1]) / 2, ok=ok, X=X, valid=valid, cal=cal)


# ---------------------------------------------------------------- ba bộ dự đoán: -> p_bad (N,), probs (N,K)
def _expand_probs(proba, fitted_classes, K):
    out = np.zeros((len(proba), K))
    for j, c in enumerate(fitted_classes):
        out[:, int(c)] = proba[:, j]
    return out


def predict_transformer(sess, X):
    outs = sess.run(None, {"x": X.astype(np.float32)})
    names = [o.name for o in sess.get_outputs()]
    pi = posture_class.find_posture_output(names)
    if pi is None:
        raise RuntimeError("ONNX không có output posture_logits (model cũ): không dựng được 6 lớp")
    p = 1 / (1 + np.exp(-np.asarray(outs[0], float).reshape(len(X))))
    z = np.asarray(outs[pi], float)
    z = np.exp(z - z.max(1, keepdims=True))
    return p, z / z.sum(1, keepdims=True)


def predict_rf(bundle, X, K):
    S = C.win_stats(X)
    rf_bad, rf_cls = bundle["rf_bad"], bundle["rf_cls"]
    pb = rf_bad.predict_proba(S)[:, list(rf_bad.classes_).index(1)]
    return pb, _expand_probs(rf_cls.predict_proba(S), rf_cls.classes_, K)


def predict_rule(cal, win_end, classes, rule_cfg, win=C.WIN):
    """Luật teacher theo cửa sổ: p_bad = tỉ lệ khung BAD (rula_frame_label), probs = tần suất lớp phụ của các khung BAD
    (GOOD = khung GOOD). Cửa sổ nhãn lẫn vẫn có đáp án (khác lúc train, nơi bị loại)."""
    lab, _, cls = C.teacher_frames(cal, classes, rule_cfg)
    K = len(classes)
    p = np.full(len(win_end), np.nan)
    pr = np.zeros((len(win_end), K))
    for n, e in enumerate(win_end):
        sl = slice(e - win + 1, e + 1)
        ok = np.isfinite(lab[sl])
        if not ok.any():
            continue
        p[n] = np.mean(lab[sl][ok])
        c = cls[sl][(cls[sl] >= 0) & ok]
        if len(c):
            pr[n] = np.bincount(c, minlength=K) / len(c)
        else:
            pr[n, 0] = 1.0 if p[n] < 0.5 else 0.0
    return p, pr


# ---------------------------------------------------------------- bộ lọc của app
def app_filter_params(model_cfg):
    """Tham số lọc/cảnh báo đúng nguồn của app: app_config.DEFAULTS + posture_config.threshold."""
    d = APP_DEFAULTS
    thr = d["p_bad_threshold"] if d["p_bad_threshold"] is not None else model_cfg["threshold"]
    return dict(threshold=thr, hysteresis=d["p_bad_hysteresis"], alert_sec=d["alert_sec"], clear_sec=d["clear_sec"],
                repeat_sec=d["repeat_sec"], cooldown_sec=d["cooldown_sec"], median=5)


def run_filter(p, probs, ok, t_end, classes, prm, t_stop=None):
    """Chạy một chuỗi dự đoán qua bộ lọc của app (median 5 + hysteresis + AlertTracker), từng cửa sổ.
    Trả (rows, events): rows[n] = dict(bad_raw, cls_raw, bad_f, cls_f, p_med) hoặc None khi cửa sổ không hợp lệ."""
    ph, ch = collections.deque(maxlen=prm["median"]), collections.deque(maxlen=prm["median"])
    tr = AlertTracker("POSTURE", alert_sec=prm["alert_sec"], clear_sec=prm["clear_sec"],
                      repeat_sec=prm["repeat_sec"], cooldown_sec=prm["cooldown_sec"])
    rows, events, thr, hy = [], [], prm["threshold"], prm["hysteresis"]
    last_cls = None
    for n in range(len(p)):
        now = float(t_end[n])
        if not ok[n] or not np.isfinite(p[n]):
            rows.append(None)
            events += [dict(e, t_class=last_cls) for e in tr.update(None, now)]
            continue
        ph.append(p[n])
        ch.append(probs[n])
        p_med = float(np.median(ph))
        mp = posture_class.mean_probs(ch)
        bad_raw = bool(p[n] >= thr)
        cls_raw = posture_class.pick_posture_class(mp, classes, "BAD" if bad_raw else "GOOD")
        bad = True if p_med >= thr + hy else False if p_med <= thr - hy else None
        evs = tr.update(bad, now)
        state = "BAD" if tr.status in ("BAD", "CANH BAO") else "GOOD" if tr.status == "GOOD" else None
        cls_f = posture_class.pick_posture_class(mp, classes, state)
        last_cls = cls_f if cls_f not in (None, "GOOD") else last_cls
        events += [dict(e, t_class=cls_f if cls_f not in (None, "GOOD") else last_cls) for e in evs]
        rows.append(dict(bad_raw=bad_raw, cls_raw=cls_raw, bad_f=None if state is None else state == "BAD",
                         cls_f=cls_f, p_med=p_med))
    stop = float(t_end[-1]) if t_stop is None and len(t_end) else t_stop
    if stop is not None:
        events += [dict(e, t_class=last_cls) for e in tr.reset(stop, "END")]
    return rows, events


def alert_rows(events, method, video, person):
    """ALERT_STARTED/RESOLVED -> các đợt (t_on, t_off). notify=False khi trong cooldown (vẫn tính, ghi cột notify)."""
    out, cur = [], None
    for e in events:
        if e["eventType"] == "ALERT_STARTED":
            cur = dict(method=method, video=video, person=person, t_on=round(e["t"], 3),
                       started_at=round(e["startedAt"], 3), cls=e.get("t_class") or "", notify=bool(e.get("notify", True)))
        elif e["eventType"] == "ALERT_RESOLVED" and cur is not None:
            cur["t_off"] = round(float(e.get("endedAt", e["t"])), 3)
            cur["end_reason"] = e.get("reason", "")
            out.append(cur)
            cur = None
    return out


# ---------------------------------------------------------------- quy về đoạn 2 giây
def segment_bounds(duration, segment_sec=C.SEGMENT_SEC):
    """Giống labeling.session.segments_for: t_start = 0, 2, 4, ...; bỏ phần dư < 2 s."""
    from labeling.session import segments_for
    return segments_for(duration, segment_sec)


def _plurality(items, order):
    cnt = Counter(items)
    return max(cnt, key=lambda c: (cnt[c], -order.index(c))) if cnt else None


def aggregate_segment(rows, idx, classes):
    """Gộp các cửa sổ (chỉ số idx, có tâm trong đoạn) của một bộ dự đoán thành nhãn đoạn.
    Quy tắc: BAD thô = ≥ 50% cửa sổ hợp lệ BAD; lớp = GOOD nếu không BAD, ngược lại lớp xấu nhiều cửa sổ nhất trong số cửa sổ BAD
    (hòa -> lớp đứng trước trong `classes`). BAD sau lọc = ≥ 50% cửa sổ có trạng thái rõ là BAD ('' nếu không cửa sổ nào rõ).
    Trả (cls, bad, bad_f, coverage); cls = NO_POSE khi coverage < MIN_COVERAGE."""
    valid = [rows[i] for i in idx if rows[i] is not None]
    cov = len(valid) / len(idx) if len(idx) else 0.0
    if not valid or cov < MIN_COVERAGE:
        return NO_POSE, "", "", cov
    bad = sum(r["bad_raw"] for r in valid) / len(valid) >= 0.5
    cls = _plurality([r["cls_raw"] for r in valid if r["bad_raw"] and r["cls_raw"]], classes) if bad else posture_class.GOOD
    cls = cls or posture_class.GOOD
    known = [r["bad_f"] for r in valid if r["bad_f"] is not None]
    bad_f = "" if not known else int(sum(known) / len(known) >= 0.5)
    return cls, int(bad), bad_f, cov


def segments_table(video, person, duration, t_center, rows_by_method, classes):
    """-> list dict một dòng cho mỗi đoạn 2 s. Cửa sổ thuộc đoạn khi t_center nằm trong [t_start, t_end)."""
    out = []
    for t0, t1 in segment_bounds(duration):
        idx = np.where((t_center >= t0) & (t_center < t1))[0]
        row = dict(video=video, person=person, t_start=t0, t_end=t1, true_label="")
        covs = []
        for m in METHODS:
            cls, bad, bad_f, cov = aggregate_segment(rows_by_method[m], idx, classes)
            row[m], row[f"{m}_bad"], row[f"{m}_bad_filtered"] = cls, bad, bad_f
            covs.append(cov)
        row["coverage"] = round(min(covs), 3)
        out.append(row)
    return out


def attach_labels(rows, label_rows):
    """Ghép nhãn tay theo (video, t_start). label_rows: list dict(video, t_start, label)."""
    lab = {(r["video"], round(float(r["t_start"]), 3)): r["label"] for r in label_rows}
    for r in rows:
        r["true_label"] = lab.get((r["video"], round(float(r["t_start"]), 3)), "")
    return rows
