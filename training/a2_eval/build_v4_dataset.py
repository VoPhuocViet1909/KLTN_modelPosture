"""Dựng lại bộ cửa sổ v4 tại máy từ video SIDE (mặc định D:\\KLTN\\video_kaggle_v4, P01–P03), đúng quy trình
`training/notebook_v4_retrain_kaggle.ipynb` Phần 3–4:

  landmark 10 fps (ảnh ½) -> chọn bên/hướng mặt trên mọi clip của người -> hiệu chỉnh = CALIBRATION giây 3–18
  -> nhãn khung bằng rula_frame_label của app -> lớp phụ -> bỏ khung 3 s đầu/cuối clip -> cửa sổ 20 khung bước 5
  -> loại cửa sổ (chuyển tư thế / thiếu điểm / nhãn lẫn / sát ngưỡng) -> NPZ + windows_info.csv

Chạy:  python build_v4_dataset.py [--videos DIR] [--persons P01 P02 P03] [--out work]
Đầu ra (không commit, nằm trong .gitignore): <out>/dataset_windows_v4_local.npz (X, y_bad, y_cls, group, classes)
và <out>/windows_info.csv, <out>/baselines.json.
"""
import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np

import common as C
from common import pf

NAME_RE = re.compile(r"^(P\d+)_(S\d+)_(.+)_(SIDE|FRONT)$")
MIN_PURE, MIN_STABLE, CLS_MIN_PURE = 0.8, 0.6, 0.7   # hằng số của notebook (ô Phần 4)
SCRIPT_V2 = C.PM / "recording" / "script_v2.json"


def load_script():
    """clip -> (thời lượng s, [giây bắt đầu từng mức]) từ script_v2.json (nguồn mà notebook ghi chép lại)."""
    d = json.load(open(SCRIPT_V2, encoding="utf-8"))
    return {c["clip"]: (c["duration"], [p["start"] for p in c["phases"]]) for c in d["clips"]}


def judged_mask(t, clip, script, margin):
    dur, starts = script[clip]
    end = min(dur, t[-1] + 1e-6) if len(t) else dur
    m = (t >= margin) & (t < end - margin)
    for s in starts[1:]:
        m &= ~((t >= s) & (t < s + margin))
    return m


def find_side_videos(root, persons):
    out = {}
    for p in sorted(Path(root).rglob("*.mp4")):
        m = NAME_RE.match(p.stem)
        if not m or m.group(4) != "SIDE" or m.group(1) not in persons or "_cu" in p.parts:
            continue
        out[p.stem] = p
    return out


def build(videos_dir, persons, out_dir, task=C.POSE_TASK_PATH, verbose=True):
    cfg = C.load_model_cfg()
    classes, rule = cfg["classes"], cfg["class_rule"]
    script = load_script()
    margin = cfg["data"]["margin_sec"]
    train_clips = [c for c in script if c != "CALIBRATION" and not c.startswith("SHOULDER_")]
    vids = find_side_videos(videos_dir, persons)
    if not vids:
        raise SystemExit(f"Không thấy *_SIDE.mp4 của {persons} trong {videos_dir}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lm_dir = out_dir / "lm"
    meta = []
    for k, (stem, path) in enumerate(vids.items(), 1):
        p, ses, clip, _ = NAME_RE.match(stem).groups()
        if clip not in train_clips + ["CALIBRATION"]:
            continue
        z = C.extract_landmarks(path, lm_dir, task=task)
        if verbose:
            print(f"[{k}/{len(vids)}] {stem}: {len(z['t'])} khung", flush=True)
        meta.append(dict(z=z, stem=stem, person=p, session=ses, clip=clip,
                         setup="x".join(str(int(v)) for v in z["wh"])))

    X, Y, CL, G, INFO, BASES = [], [], [], [], [], {}
    groups = {}
    for m in meta:
        groups.setdefault((m["person"], m["session"], m["setup"]), []).append(m)
    iV = C.FEATURES.index("vis_hip")
    for (person, session, setup), grp in sorted(groups.items()):
        data = {m["clip"]: m["z"] for m in grp}
        all_lm = np.concatenate([d["lm"] for d in data.values()])
        all_w = np.concatenate([d["world"] for d in data.values()])
        side = pf.choose_side(all_lm, all_w)
        f = pf.facing_sign(all_lm, side)
        raw = {c: pf.sequence_angles(d["lm"], side, f) for c, d in data.items()}
        tt = {c: d["t"] - d["t"][0] for c, d in data.items()}
        if "CALIBRATION" in raw:
            sel = (tt["CALIBRATION"] >= C.CAL_START) & (tt["CALIBRATION"] < C.CAL_START + C.CAL_SEC)
            base = pf.calibration_baseline(raw["CALIBRATION"][sel])
            src = "CALIBRATION 3–18 s"
        elif "GOOD_01" in raw:
            sel = (tt["GOOD_01"] >= margin) & (tt["GOOD_01"] < margin + 10)
            base = pf.calibration_baseline(raw["GOOD_01"][sel])
            src = "GOOD_01 10 s"
        else:
            print(f"{person}_{session} [{setup}]: không có CALIBRATION/GOOD_01 -> bỏ")
            continue
        BASES[f"{person}_{session}_{setup}"] = dict(side=int(side), facing=float(f), source=src, **base)
        for clip, r in raw.items():
            if clip == "CALIBRATION" or clip not in train_clips:
                continue
            cal = pf.apply_calibration(r, base)
            lab, stab, cls = C.teacher_frames(cal, classes, rule)
            valid = np.isfinite(cal[:, :2]).all(1)
            judged = judged_mask(tt[clip], clip, script, margin)
            xin = pf.to_model_input(cal)
            for s in range(0, len(cal) - C.WIN + 1, C.STRIDE_TRAIN):
                sl = slice(s, s + C.WIN)
                info = dict(person=person, session=session, clip=clip, start=round(float(tt[clip][s]), 2))
                if not judged[sl].all():
                    INFO.append({**info, "kept": False, "reason": "đoạn chuyển tư thế"})
                    continue
                lw = lab[sl]
                ok = np.isfinite(lw)
                if valid[sl].mean() < C.MIN_VALID or ok.sum() == 0 or np.nanmean(cal[sl, iV]) < C.MIN_VIS_HIP:
                    INFO.append({**info, "kept": False, "reason": "thiếu điểm"})
                    continue
                pbad = np.nanmean(lw)
                if MIN_PURE > pbad > 1 - MIN_PURE:
                    INFO.append({**info, "kept": False, "reason": "nhãn lẫn"})
                    continue
                if stab[sl][ok].mean() < MIN_STABLE:
                    INFO.append({**info, "kept": False, "reason": "sát ngưỡng"})
                    continue
                y = int(pbad >= 0.5)
                cs = cls[sl][cls[sl] >= 0]
                c = -1
                if len(cs):
                    vals, cnt = np.unique(cs, return_counts=True)
                    if cnt.max() / C.WIN >= CLS_MIN_PURE:
                        c = int(vals[cnt.argmax()])
                if (y == 0) != (c == 0):
                    c = 0 if y == 0 else -1
                X.append(xin[sl])
                Y.append(y)
                CL.append(c)
                G.append(person)
                INFO.append({**info, "kept": True, "reason": "", "label": y, "cls": classes[c] if c >= 0 else "-"})

    X, Y, CL, G = np.stack(X).astype(np.float32), np.array(Y), np.array(CL), np.array(G)
    npz = out_dir / "dataset_windows_v4_local.npz"
    np.savez_compressed(npz, X=X, y_bad=Y, y_cls=CL, group=G, classes=np.array(classes))
    cols = ["person", "session", "clip", "start", "kept", "reason", "label", "cls"]
    with open(out_dir / "windows_info.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in INFO:
            w.writerow({k: r.get(k, "") for k in cols})
    json.dump(BASES, open(out_dir / "baselines.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    if verbose:
        print(f"Cửa sổ giữ lại: {len(Y)} | BAD {Y.mean():.1%} | có lớp phụ {(CL >= 0).mean():.1%}")
        print("->", npz)
    return npz


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", default=r"D:\KLTN\video_kaggle_v4")
    ap.add_argument("--persons", nargs="+", default=["P01", "P02", "P03"])
    ap.add_argument("--out", default=str(C.HERE / "work"))
    a = ap.parse_args()
    build(a.videos, set(a.persons), a.out)


if __name__ == "__main__":
    main()
