"""Chạy ba cách (Transformer ONNX, Random Forest, luật góc) trên video cam hông 90° và quy về đoạn 2 giây (A2).

Đầu vào: danh sách video (--videos) hoặc manifest CSV (--manifest) với cột
  video[,person][,calib_video][,calib_start][,calib_end]
Mặc định mỗi video tự hiệu chỉnh bằng giây 3–18 của chính nó (ngồi chuẩn 15 s đầu video). Người có nhiều video nên chỉ
calib_video chung (clip CALIBRATION của người đó). `person` mặc định lấy từ tên file `P01_...`, không có thì lấy tên file.
Nhãn tay (tùy chọn): CSV của công cụ A1 `video,t_start,t_end,label,rater` (--labels, có thể nhiều file; nhiều người chấm
thì chọn --rater).

  python evaluate.py --videos nguoi01.mp4 nguoi02.mp4 --labels labels_A.csv --run lan1
  python evaluate.py --manifest manifest.csv --labels labels_A.csv --rater A --run lan1
Đầu ra: out/<run>/predictions.csv, alerts.csv, run_meta.json (xem README).
Mọi tham số lấy từ app (posture_config.json, app_config.DEFAULTS); không có tham số tự chỉnh theo dữ liệu đánh giá.
"""
import argparse
import csv
import datetime
import json
import re
import sys
from pathlib import Path

import numpy as np

import common as C
import pipeline as P

PRED_COLS = ["video", "person", "t_start", "t_end", "true_label", "transformer", "rf", "rule",
             "transformer_bad", "rf_bad", "rule_bad", "transformer_bad_filtered", "rf_bad_filtered", "rule_bad_filtered",
             "coverage"]
ALERT_COLS = ["method", "video", "person", "t_on", "t_off", "class", "started_at", "notify", "end_reason"]


def person_of(path):
    stem = Path(path).stem
    m = re.match(r"^(P\d+)_", stem)
    return m.group(1) if m else stem


def read_manifest(path):
    out = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out.append(dict(video=r["video"], person=(r.get("person") or "").strip() or None,
                            calib_video=(r.get("calib_video") or "").strip() or None,
                            calib_start=float(r["calib_start"]) if (r.get("calib_start") or "").strip() else None,
                            calib_end=float(r["calib_end"]) if (r.get("calib_end") or "").strip() else None))
    return out


def load_labels(paths, rater=None):
    from labeling.session import load_rows
    rows = [r for p in paths for r in load_rows(p)]
    raters = sorted({r["rater"] for r in rows})
    if rater is None and len(raters) > 1:
        raise SystemExit(f"Có {len(raters)} người chấm ({', '.join(raters)}): chọn một bằng --rater")
    if rater is not None:
        if rater not in raters:
            raise SystemExit(f"Không có người chấm '{rater}' (có: {', '.join(raters)})")
        rows = [r for r in rows if r["rater"] == rater]
    keys = [(r["video"], r["t_start"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise SystemExit("Nhãn trùng (video, t_start) trong cùng người chấm")
    return rows


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def evaluate(entries, label_rows, onnx_path, rf_path, out_dir, cache_dir, hash_videos=True, argv=None,
             calib_start=C.CAL_START, calib_end=C.CAL_START + C.CAL_SEC):
    import joblib
    import onnxruntime as ort
    from labeling.video import probe
    cfg = C.load_model_cfg()
    classes = cfg["classes"]
    prm = P.app_filter_params(cfg)
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    bundle = joblib.load(rf_path)
    assert list(bundle["classes"]) == classes and list(bundle["features"]) == C.FEATURES
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    preds, alerts, vmeta = [], [], []
    for e in entries:
        vp = Path(e["video"])
        name = vp.name
        person = e["person"] or person_of(vp)
        z = C.extract_landmarks(vp, cache_dir)
        cv = Path(e["calib_video"]) if e["calib_video"] else vp
        zc = z if cv == vp else C.extract_landmarks(cv, cache_dir)
        cs = e["calib_start"] if e["calib_start"] is not None else calib_start
        ce = e["calib_end"] if e["calib_end"] is not None else calib_end
        tc = zc["t"] - zc["t"][0]
        sel = (tc >= cs) & (tc < ce)
        try:
            side, f, base = P.calibrate(zc["lm"][sel], zc["world"][sel])
        except ValueError as ex:
            print(f"BỎ {name}: {ex}", file=sys.stderr)
            vmeta.append(dict(video=name, skipped=str(ex)))
            continue
        cal, valid = P.calibrated_angles(z["lm"], side, f, base)
        w = P.make_windows(cal, valid, z["t"] - z["t"][0])
        if not len(w["end"]):
            print(f"BỎ {name}: ngắn hơn một cửa sổ", file=sys.stderr)
            vmeta.append(dict(video=name, skipped="ngắn hơn một cửa sổ"))
            continue
        ok = w["ok"]
        N, K = len(w["end"]), len(classes)
        pr = {}
        pt, prt = np.full(N, np.nan), np.zeros((N, K))
        pt[ok], prt[ok] = P.predict_transformer(sess, w["X"][ok])
        pr["transformer"] = (pt, prt)
        pf_, prf = np.full(N, np.nan), np.zeros((N, K))
        pf_[ok], prf[ok] = P.predict_rf(bundle, w["X"][ok], K)
        pr["rf"] = (pf_, prf)
        pr["rule"] = P.predict_rule(cal, w["end"], classes, cfg["class_rule"])
        duration = probe(str(vp))[1]
        rows_by, n_alert = {}, {}
        t_stop = float(z["t"][-1] - z["t"][0])
        for m in P.METHODS:
            p, probs = pr[m]
            rows_by[m], ev = P.run_filter(p, probs, ok, w["t_end"], classes, prm, t_stop=t_stop)
            ar = P.alert_rows(ev, m, name, person)
            for a in ar:
                a["class"] = a.pop("cls")
            alerts += ar
            n_alert[m] = len(ar)
        seg = P.segments_table(name, person, duration, w["t_center"], rows_by, classes)
        preds += P.attach_labels(seg, label_rows)
        vmeta.append(dict(video=name, path=str(vp), person=person, calib_video=str(cv), calib_start=cs, calib_end=ce,
                          side="left" if side == 0 else "right", facing=f, baseline=base, n_frames=int(len(z["t"])),
                          n_windows=int(N), n_windows_ok=int(ok.sum()), duration_sec=duration,
                          n_segments=len(seg), n_no_pose=sum(r["transformer"] == P.NO_POSE for r in seg),
                          n_alerts=n_alert, sha256=C.sha256_file(vp) if hash_videos else None))
        print(f"{name}: {len(seg)} đoạn, {int(ok.sum())}/{N} cửa sổ hợp lệ, cảnh báo {n_alert}", flush=True)

    write_csv(out_dir / "predictions.csv", PRED_COLS, preds)
    write_csv(out_dir / "alerts.csv", ALERT_COLS, alerts)
    rf_meta = Path(rf_path).with_suffix(".meta.json")
    meta = dict(
        created=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), argv=argv,
        sha256=dict(onnx=C.sha256_file(onnx_path), rf=C.sha256_file(rf_path), posture_config=C.sha256_file(C.MODEL_CFG_PATH),
                    pose_task=C.sha256_file(C.POSE_TASK_PATH),
                    rf_meta=C.sha256_file(rf_meta) if rf_meta.exists() else None,
                    labels=None),   # main() điền hash các file nhãn
        libraries=C.lib_versions(),
        params=dict(filter=prm, window=C.WIN, fps=C.TARGET_FPS, segment_sec=C.SEGMENT_SEC, window_stride_frames=1,
                    min_window_valid=C.MIN_VALID, min_vis_hip=C.MIN_VIS_HIP, min_coverage=P.MIN_COVERAGE,
                    class_rule=cfg["class_rule"], calibration_default=[calib_start, calib_end],
                    segment_rule="BAD thô = >=50% cửa sổ hợp lệ BAD; lớp = lớp xấu nhiều nhất trong cửa sổ BAD; "
                                 "bad_filtered = >=50% cửa sổ có trạng thái rõ sau lọc là BAD; tâm cửa sổ quyết định đoạn"),
        videos=vmeta, n_segments=len(preds), n_labeled=sum(bool(r["true_label"]) for r in preds), n_alerts=len(alerts))
    (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", nargs="*", default=[])
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--labels", nargs="*", default=[])
    ap.add_argument("--rater", default=None)
    ap.add_argument("--run", default=datetime.datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    ap.add_argument("--out-root", default=str(C.HERE / "out"))
    ap.add_argument("--onnx", default=str(C.ONNX_PATH))
    ap.add_argument("--rf", default=str(C.DEFAULT_RF_PATH))
    ap.add_argument("--cache", default=str(C.HERE / "work" / "lm_eval"))
    ap.add_argument("--calib-start", type=float, default=C.CAL_START)
    ap.add_argument("--calib-end", type=float, default=C.CAL_START + C.CAL_SEC)
    ap.add_argument("--no-hash-videos", action="store_true")
    a = ap.parse_args()
    entries = read_manifest(a.manifest) if a.manifest else []
    entries += [dict(video=v, person=None, calib_video=None, calib_start=None, calib_end=None) for v in a.videos]
    if not entries:
        ap.error("cần --videos hoặc --manifest")
    labels = load_labels(a.labels, a.rater) if a.labels else []
    out = evaluate(entries, labels, a.onnx, a.rf, Path(a.out_root) / a.run, a.cache, not a.no_hash_videos, sys.argv,
                   a.calib_start, a.calib_end)
    if a.labels:   # ghi hash file nhãn vào run_meta
        mp = out / "run_meta.json"
        meta = json.loads(mp.read_text(encoding="utf-8"))
        meta["sha256"]["labels"] = {str(p): C.sha256_file(p) for p in a.labels}
        meta["rater"] = a.rater
        mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("->", out)


if __name__ == "__main__":
    main()
