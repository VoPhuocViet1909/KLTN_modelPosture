"""Chọn ngưỡng cho nhánh vai (lệch vai + nhún vai) từ video đã tách theo kịch bản.

  python shoulder_threshold_stats.py --videos D:\\KLTN\\video_tach          # dữ liệu thật
  python shoulder_threshold_stats.py --demo                               # dữ liệu giả (tests/fake_pose.py) để kiểm logic

Đầu vào: thư mục chứa P##_S##_<CLIP>_FRONT.mp4 (cam laptop; _SIDE.mp4 chưa dùng ở script này).
  - Baseline mỗi người/buổi = trung vị trên clip CALIBRATION (bỏ 3 s đầu/cuối).
  - GOOD = GOOD_01, GOOD_02.  BAD vai = SHOULDER_TILT_L/R, SHOULDER_RAISE_L/R, SHOULDER_SHRUG_BOTH (chỉ NỬA SAU clip = mức rõ).
  - Phải-KHÔNG-báo = HEAD_TILT_SIDE_*, FORWARD_HEAD_*, TRANSIENT_* (đếm báo giả).
Đầu ra (posture_model/out/ hoặc --out): shoulder_frames.csv, shoulder_threshold_summary.md.

Đặc trưng: tiltRel = shoulder_tilt − baseline (độ); raiseRel = (raise_base − raise)/raise_base (phân số, dương = vai nâng).
Công thức + ngưỡng đánh giá trên cửa sổ 2 s (trung vị); thí nghiệm phụ "Estrada 2023" trên cửa sổ 10 s (mean/median/std của
khoảng cách DỌC mũi→vai trái/phải chia độ rộng vai) + Decision Tree / Random Forest, leave-one-person-out.
Khác bài gốc: bài gốc dùng cam hông + 3 chuyên gia gán nhãn; ở đây là cam trước + nhãn theo kịch bản (và 2 người chấm nếu có review.csv).
"""
import argparse
import csv
import glob
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
from posture_features import shoulder_raise, shoulder_tilt  # noqa: E402

CLIP_RE = re.compile(r"^(P\d+)_(S\d+)_(.+)_FRONT\.mp4$", re.I)
CAL_TRIM_SEC = 3.0
WIN_SEC, ESTRADA_WIN_SEC = 2.0, 10.0
DEFAULT_MULTI = r"D:\KLTN\datasets\multiposture\data.csv"


# ------------------------------------------------------------------ nhãn theo tên clip
def clip_kind(clip):
    """-> 'CAL' | 'GOOD' | 'BAD' | 'NOALERT' | None (không dùng)."""
    c = clip.upper()
    if c.startswith("CALIBRATION"):
        return "CAL"
    if c.startswith("GOOD"):
        return "GOOD"
    if c.startswith(("SHOULDER_TILT", "SHOULDER_RAISE", "SHOULDER_SHRUG")):
        return "BAD"
    if c.startswith(("HEAD_TILT_SIDE", "FORWARD_HEAD", "TRANSIENT")):
        return "NOALERT"
    return None


def frame_features(L):
    """L: (33,3) pixel x,y,vis -> (tilt, raise, dL, dR); dL/dR = khoảng cách dọc mũi→vai / độ rộng vai (kiểu Estrada)."""
    if L is None:
        return (np.nan,) * 4
    tilt, rz = shoulder_tilt(L), shoulder_raise(L)
    w = abs(float(L[12, 0] - L[11, 0]))
    nose = L[0]
    if w < 20 or not np.isfinite(nose).all() or nose[2] < 0.5 or not np.isfinite(tilt):
        return tilt, rz, np.nan, np.nan
    return tilt, rz, float((L[11, 1] - nose[1]) / w), float((L[12, 1] - nose[1]) / w)


# ------------------------------------------------------------------ nguồn dữ liệu
def video_source(folder, fps):
    """Mỗi clip -> (person, session, clip, t[], bảng đặc trưng (n,4))."""
    import cv2
    from realtime_posture import PoseDetector
    det = PoseDetector(os.path.join(HERE, "pose_landmarker_full.task"))
    for path in sorted(glob.glob(os.path.join(folder, "*_FRONT.mp4"))):
        m = CLIP_RE.match(os.path.basename(path))
        if not m or clip_kind(m.group(3)) is None:
            continue
        cap = cv2.VideoCapture(path)
        vfps = cap.get(cv2.CAP_PROP_FPS) or 30
        step = max(int(round(vfps / fps)), 1)
        ts, feats, i = [], [], 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if i % step == 0:
                ts.append(i / vfps)
                feats.append(frame_features(det(fr, int(i / vfps * 1000))[0]))
            i += 1
        cap.release()
        yield m.group(1), m.group(2), m.group(3), np.array(ts), np.array(feats, float).reshape(-1, 4)


def demo_source(fps, seed=0):
    """Dữ liệu giả: 6 người, mỗi người đủ loại clip 20 s. Chỉ để kiểm logic, KHÔNG có ý nghĩa thống kê thật."""
    from fake_pose import front_landmarks
    rng = np.random.default_rng(seed)
    n = int(20 * fps)
    t = np.arange(n) / fps
    plan = {"CALIBRATION": (0, 0), "GOOD_01": (0, 0), "GOOD_02": (0, 0), "SHOULDER_TILT_L": (-6, 0), "SHOULDER_TILT_R": (6, 0),
            "SHOULDER_RAISE_L": (-4, 0.25), "SHOULDER_SHRUG_BOTH": (0, 0.35), "HEAD_TILT_SIDE_L": (1.5, 0.0),
            "FORWARD_HEAD_1": (0, 0.1), "TRANSIENT_1": (0, 0)}
    for pi in range(6):
        base_t, base_r = rng.normal(0, 1.0), rng.normal(0, 0.03)
        for clip, (tilt, rise) in plan.items():
            rows = []
            for k in range(n):
                second_half = t[k] >= 10
                on = second_half and clip_kind(clip) in ("BAD", "NOALERT") and not clip.startswith("TRANSIENT")
                tt = base_t + (tilt if on else 0) + rng.normal(0, 0.8)
                rr = base_r + (rise if on else 0) + rng.normal(0, 0.015)
                L = front_landmarks(tt, rr)
                L[:, :2] += rng.normal(0, 0.4, (33, 2)).astype(np.float32)
                L[0, 1] = (L[7, 1] + L[8, 1]) / 2 + 30        # mũi đi theo tai
                rows.append(frame_features(L))
            yield f"P{pi + 1:02d}", "S01", clip, t, np.array(rows, float)


# ------------------------------------------------------------------ thống kê
def cohen_kappa(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if len(a) == 0:
        return float("nan")
    po = float(np.mean(a == b))
    pe = sum(float(np.mean(a == v)) * float(np.mean(b == v)) for v in np.unique(np.concatenate([a, b])))
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def pct(x):
    if len(x) == 0:
        return "n=0"
    return "n=%d p50=%.3f p90=%.3f p95=%.3f p99=%.3f" % (len(x), *np.percentile(x, [50, 90, 95, 99]))


def youden(good, bad):
    """Ngưỡng tối ưu Youden J = TPR − FPR cho điểm số 'lớn hơn = xấu'. Trả (ngưỡng, J, đường ROC [(fpr, tpr)])."""
    good, bad = np.asarray(good, float), np.asarray(bad, float)
    if len(good) == 0 or len(bad) == 0:
        return float("nan"), float("nan"), []
    cand = np.unique(np.concatenate([good, bad]))
    roc = [(float(np.mean(good > c)), float(np.mean(bad > c))) for c in cand]
    j = [t - f for f, t in roc]
    i = int(np.argmax(j))
    return float(cand[i]), float(j[i]), roc


def read_review(path):
    """review.csv: clip,rater1,rater2 (đạt / không đạt, hoặc 1/0, pass/fail). -> (kappa, tập clip bị loại, n)."""
    ok_words = {"đạt", "dat", "1", "pass", "ok", "yes", "true"}
    r1, r2, bad = [], [], set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3 or row[0].strip().lower() in ("clip", "tên clip", "ten clip"):
                continue
            a, b = (row[1].strip().lower() in ok_words), (row[2].strip().lower() in ok_words)
            r1.append(a), r2.append(b)
            if not (a and b):
                bad.add(os.path.splitext(row[0].strip())[0].replace("_FRONT", "").replace("_SIDE", ""))
    return cohen_kappa(r1, r2), bad, len(r1)


def multiposture_p95(path):
    """Góc đường nối 2 vai trên khung ngồi thẳng (nhãn TUP) của MultiPosture. Đọc header để tìm cột; không khớp thì bỏ qua."""
    if not os.path.exists(path):
        return None, "không có file, bỏ qua"
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames or []
        low = {c: c.lower().replace(" ", "_") for c in cols}

        def find(side, axis):
            for c, l in low.items():
                if "shoulder" in l and side in l and re.search(rf"(^|[_\W]){axis}($|[_\W])", l):
                    return c
            return None
        cx = [find(s, a) for s in ("left", "right") for a in ("x", "y")]
        lab = next((c for c in cols if low[c] in ("label", "class", "posture", "target", "y")), None)
        if None in cx or lab is None:
            return None, f"không nhận ra cột vai/nhãn trong header: {cols[:12]}..."
        ang = []
        for r in rd:
            if str(r[lab]).strip().upper() != "TUP":
                continue
            try:
                lx, ly, rx, ry = (float(r[c]) for c in cx)
            except ValueError:
                continue
            dx, dy = rx - lx, ry - ly
            if dx < 0:
                dx, dy = -dx, -dy
            if dx > 1e-6:
                ang.append(abs(np.degrees(np.arctan2(dy, dx))))
    if not ang:
        return None, "không có khung TUP"
    return float(np.percentile(ang, 95)), f"n={len(ang)} khung TUP, p95 |góc 2 vai| = {np.percentile(ang, 95):.2f}° (đơn vị tọa độ có thể chuẩn hóa: góc vẫn đúng nếu x, y cùng tỉ lệ)"


# ------------------------------------------------------------------ dựng bảng khung + cửa sổ
def build_frames(source, bad_clips=()):
    """-> list dict mỗi khung (đã trừ baseline). Bỏ khung nan, bỏ nửa đầu clip BAD (chưa rõ), bỏ clip bị người chấm loại."""
    raw = list(source)
    base = {}
    for p, s, clip, t, F in raw:
        if clip_kind(clip) == "CAL":
            keep = (t >= CAL_TRIM_SEC) & (t <= t[-1] - CAL_TRIM_SEC) if len(t) else np.array([], bool)
            F = F[keep]
            if np.isfinite(F[:, 0]).sum() >= 5 and np.isfinite(F[:, 1]).sum() >= 5:
                base[(p, s)] = (float(np.nanmedian(F[:, 0])), float(np.nanmedian(F[:, 1])))
    rows = []
    for p, s, clip, t, F in raw:
        kind = clip_kind(clip)
        if kind in (None, "CAL") or (p, s) not in base or f"{p}_{s}_{clip}" in bad_clips:
            continue
        tb, rb = base[(p, s)]
        half = (t[-1] / 2) if len(t) else 0
        for k in range(len(t)):
            if not np.isfinite(F[k, 0]):
                continue
            if kind == "BAD" and t[k] < half:
                continue
            rr = (rb - F[k, 1]) / rb if np.isfinite(F[k, 1]) and rb > 0 else np.nan
            rows.append(dict(person=p, session=s, clip=clip, kind=kind, t=float(t[k]), tilt_rel=F[k, 0] - tb,
                             raise_rel=rr, dL=F[k, 2], dR=F[k, 3], label=1 if kind == "BAD" else 0))
    return rows


def windows(rows, sec, fps):
    """Cửa sổ không chồng nhau theo (người, buổi, clip). Giá trị = trung vị (và mean/std cho Estrada)."""
    n = max(int(sec * fps), 2)
    out, groups = [], {}
    for r in rows:
        groups.setdefault((r["person"], r["session"], r["clip"]), []).append(r)
    for (p, s, clip), g in groups.items():
        for i in range(0, len(g) - n + 1, n):
            w = g[i:i + n]
            col = lambda k: np.array([x[k] for x in w], float)
            d = dict(person=p, clip=clip, kind=w[0]["kind"], label=w[0]["label"])
            d["abs_tilt"] = float(np.nanmedian(np.abs(col("tilt_rel"))))
            d["raise"] = float(np.nanmedian(col("raise_rel"))) if np.isfinite(col("raise_rel")).any() else np.nan
            est = []
            for k in ("dL", "dR"):
                c = col(k)
                c = c[np.isfinite(c)]
                est += [float(np.mean(c)), float(np.median(c)), float(np.std(c))] if len(c) else [np.nan] * 3
            d["est"] = est
            out.append(d)
    return out


def fit_rule(train):
    """Ngưỡng Youden cho |tilt| và raise trên cửa sổ huấn luyện. Raise chỉ dùng khi đủ dữ liệu."""
    good = [w for w in train if w["kind"] == "GOOD"]
    bad = [w for w in train if w["kind"] == "BAD"]
    t_thr, _, _ = youden([w["abs_tilt"] for w in good], [w["abs_tilt"] for w in bad])
    gr = [w["raise"] for w in good if np.isfinite(w["raise"])]
    br = [w["raise"] for w in bad if np.isfinite(w["raise"])]
    r_thr, _, _ = youden(gr, br)
    return t_thr, r_thr


def rule_pred(w, t_thr, r_thr):
    return int(w["abs_tilt"] > t_thr or (np.isfinite(w["raise"]) and np.isfinite(r_thr) and w["raise"] > r_thr))


def loso(wins, predict_fn):
    """leave-one-person-out. predict_fn(train, test) -> list dự đoán cho test. Trả (acc, kappa, báo giả NOALERT, n NOALERT)."""
    persons = sorted({w["person"] for w in wins})
    yt, yp, fa, nfa = [], [], 0, 0
    for p in persons:
        train = [w for w in wins if w["person"] != p]
        test = [w for w in wins if w["person"] == p]
        if not train or not test:
            continue
        pred = predict_fn(train, test)
        for w, y in zip(test, pred):
            if w["kind"] in ("GOOD", "BAD"):
                yt.append(w["label"])
                yp.append(int(y))
            else:
                nfa += 1
                fa += int(y)
    acc = float(np.mean(np.array(yt) == np.array(yp))) if yt else float("nan")
    return acc, cohen_kappa(yt, yp), fa, nfa, len(yt)


def estrada_pred(model_cls, **kw):
    def fn(train, test):
        tr = [w for w in train if w["kind"] in ("GOOD", "BAD") and np.isfinite(w["est"]).all()]
        if len({w["label"] for w in tr}) < 2:
            return [0] * len(test)
        m = model_cls(random_state=0, **kw).fit([w["est"] for w in tr], [w["label"] for w in tr])
        X = np.nan_to_num(np.array([w["est"] for w in test], float))
        return m.predict(X)
    return fn


# ------------------------------------------------------------------ chương trình chính
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", help="thư mục chứa P##_S##_<CLIP>_FRONT.mp4")
    ap.add_argument("--demo", action="store_true", help="dùng dữ liệu giả để kiểm logic")
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--review", help="review.csv: clip,người chấm 1,người chấm 2 (đạt / không đạt yêu cầu kịch bản)")
    ap.add_argument("--multiposture", default=DEFAULT_MULTI)
    a = ap.parse_args(argv)
    if not a.demo and not a.videos:
        ap.error("cần --videos <thư mục> hoặc --demo")
    os.makedirs(a.out, exist_ok=True)
    md = ["# Chọn ngưỡng nhánh vai" + (" (DỮ LIỆU GIẢ --demo, không dùng làm số liệu thật)" if a.demo else ""), ""]

    bad_clips, kappa_note = set(), "không có review.csv: chưa kiểm độ đồng thuận nhãn."
    if a.review:
        k, bad_clips, n = read_review(a.review)
        kappa_note = f"Cohen's kappa giữa 2 người chấm trên {n} clip = {k:.3f}; loại {len(bad_clips)} clip không đạt: {sorted(bad_clips)}"
    md += ["## Độ đồng thuận nhãn", kappa_note, ""]

    rows = build_frames(demo_source(a.fps) if a.demo else video_source(a.videos, a.fps), bad_clips)
    if not rows:
        print("Không có khung hợp lệ (thiếu clip CALIBRATION hoặc tên clip sai quy ước).")
        return 1
    fcsv = os.path.join(a.out, "shoulder_frames.csv")
    with open(fcsv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    good = [r for r in rows if r["kind"] == "GOOD"]
    bad = [r for r in rows if r["kind"] == "BAD"]
    ga = np.abs([r["tilt_rel"] for r in good])
    gr = np.array([r["raise_rel"] for r in good], float)
    gr = gr[np.isfinite(gr)]
    md += ["## Phân bố khung GOOD (ngưỡng ON phải nằm trên p95–p99)",
           f"- |tiltRel| (độ): {pct(ga)}", f"- raiseRel (phân số): {pct(gr)}", ""]
    t_thr, t_j, t_roc = youden(ga, np.abs([r["tilt_rel"] for r in bad]))
    br = np.array([r["raise_rel"] for r in bad], float)
    br = br[np.isfinite(br)]
    r_thr, r_j, r_roc = youden(gr, br)
    md += ["## ROC / Youden (GOOD vs BAD vai, mức khung)",
           f"- |tiltRel|: ngưỡng Youden = {t_thr:.2f}°, J = {t_j:.3f} (ngưỡng đang dùng 3,5°; MDC SAPO 3,6°)",
           f"- raiseRel: ngưỡng Youden = {r_thr:.3f}, J = {r_j:.3f} (chưa có ngưỡng trong cấu hình: shoulder_raise_on = null)",
           f"- Điểm ROC |tiltRel| (FPR, TPR) mẫu: {[(round(f, 2), round(t, 2)) for f, t in t_roc[::max(len(t_roc) // 8, 1)]]}",
           f"- Điểm ROC raiseRel (FPR, TPR) mẫu: {[(round(f, 2), round(t, 2)) for f, t in r_roc[::max(len(r_roc) // 8, 1)]]}", ""]

    w2 = windows(rows, WIN_SEC, a.fps)
    acc, kap, fa, nfa, n = loso(w2, lambda tr, te: [rule_pred(w, *fit_rule(tr)) for w in te])
    cur = [rule_pred(w, 3.5, np.nan) for w in w2]
    cur_fa = sum(c for w, c in zip(w2, cur) if w["kind"] == "NOALERT")
    results = [("Công thức + ngưỡng Youden (cửa sổ 2 s)", acc, kap, fa, nfa, n)]
    w10 = windows(rows, ESTRADA_WIN_SEC, a.fps)
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.tree import DecisionTreeClassifier
        for name, cls, kw in (("Estrada 2023 – Decision Tree (cửa sổ 10 s)", DecisionTreeClassifier, {}),
                              ("Estrada 2023 – Random Forest (cửa sổ 10 s)", RandomForestClassifier, {"n_estimators": 100})):
            r = loso(w10, estrada_pred(cls, **kw))
            results.append((name,) + r)
    except ImportError:
        md += ["_Thiếu scikit-learn: bỏ qua so sánh Estrada (pip install -r posture_model/requirements-dev.txt)._", ""]
    md += ["## So sánh leave-one-person-out (bài gốc: accuracy 95,6 %, kappa 0,91)",
           "| Phương pháp | Accuracy | Kappa | Báo giả trên clip phải-KHÔNG-báo | Số cửa sổ GOOD/BAD |", "| --- | --- | --- | --- | --- |"]
    for name, acc, kap, fa, nfa, n in results:
        md.append(f"| {name} | {acc * 100:.1f} % | {kap:.2f} | {fa}/{nfa} | {n} |")
    md += [f"| Ngưỡng hiện tại (|tilt| > 3,5°, chưa nhún vai; cửa sổ 2 s) | – | – | {cur_fa}/{sum(w['kind'] == 'NOALERT' for w in w2)} | – |", "",
           "Lưu ý: bài gốc dùng cam hông + 3 chuyên gia gán nhãn; ở đây là cam trước + nhãn theo kịch bản. "
           "Cửa sổ 10 s của Estrada ít mẫu hơn nhiều so với cửa sổ 2 s, nên số trên không so sánh trực tiếp tuyệt đối.", ""]

    p95, note = multiposture_p95(a.multiposture)
    ours = f"{np.percentile(ga, 95):.2f}°" if len(ga) else "-"
    md += ["## Tham chiếu ngoài: MultiPosture (khung TUP = ngồi thẳng)", f"- {note}; p95 |tiltRel| nhóm = {ours}", ""]

    spath = os.path.join(a.out, "shoulder_threshold_summary.md")
    with open(spath, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"Đã ghi {fcsv} và {spath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
