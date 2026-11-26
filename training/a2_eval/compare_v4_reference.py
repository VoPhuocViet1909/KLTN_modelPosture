"""Đối chiếu bộ cửa sổ dựng lại tại máy với bản tham chiếu của notebook v4 (Kaggle).

So: windows_info.csv (local) với windows_info_v4.csv (tham chiếu) khóa (person, session, clip, start): số cửa sổ theo người,
tỷ lệ khớp từng cột kept / reason / label / cls; và n_train_windows + class_counts trong posture_config.json.
Không sửa gì để cho khớp: chỉ báo số. Mã thoát 0 luôn (người đọc quyết định), 2 nếu lệch vượt --tol.

  python compare_v4_reference.py [--local work/windows_info.csv] [--ref D:\KLTN\ChayKaggle\posture_model_v4\windows_info_v4.csv]
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import common as C


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {(r["person"], r["session"], r["clip"], f"{float(r['start']):.2f}"): r for r in csv.DictReader(f)}


def norm(v):
    v = (v or "").strip()
    try:
        return str(int(float(v)))      # tham chiếu ghi 0.0/1.0, bản local ghi 0/1
    except ValueError:
        return v


def compare(local, ref, cfg):
    rep = {"columns": {}, "per_person": {}}
    keys_both = sorted(set(local) & set(ref))
    rep["n_rows"] = dict(local=len(local), ref=len(ref), common=len(keys_both),
                         only_local=len(set(local) - set(ref)), only_ref=len(set(ref) - set(local)))
    for col in ("kept", "reason", "label", "cls"):
        same = sum(norm(local[k][col]) == norm(ref[k][col]) for k in keys_both)
        rep["columns"][col] = same / len(keys_both) if keys_both else float("nan")
    kept_l = {k for k, r in local.items() if norm(r["kept"]) == "True"}
    kept_r = {k for k, r in ref.items() if norm(r["kept"]) == "True"}
    for p in sorted({k[0] for k in list(local) + list(ref)}):
        rep["per_person"][p] = dict(kept_local=sum(k[0] == p for k in kept_l), kept_ref=sum(k[0] == p for k in kept_r),
                                    kept_both=sum(k[0] == p for k in kept_l & kept_r))
    rep["kept_total"] = dict(local=len(kept_l), ref=len(kept_r), both=len(kept_l & kept_r),
                             jaccard=len(kept_l & kept_r) / max(len(kept_l | kept_r), 1))
    cc_l = Counter(local[k]["cls"] for k in kept_l)
    rep["class_counts"] = {c: dict(local=cc_l.get(c, 0), config=cfg["class_counts"].get(c)) for c in cfg["classes"]}
    rep["class_counts"]["-(không lớp)"] = dict(local=cc_l.get("-", 0), config=None)
    rep["n_train_windows"] = dict(local=len(kept_l), config=cfg["n_train_windows"])
    by_reason = defaultdict(lambda: [0, 0])
    for k in keys_both:
        by_reason[norm(ref[k]["reason"]) or "giữ lại"][0] += 1
        by_reason[norm(ref[k]["reason"]) or "giữ lại"][1] += norm(local[k]["reason"]) == norm(ref[k]["reason"])
    rep["by_ref_reason"] = {r: dict(n=n, same=s, rate=s / n) for r, (n, s) in by_reason.items()}
    return rep


def to_markdown(rep):
    L = ["| cột | tỷ lệ khớp |", "|---|---|"]
    L += [f"| {c} | {v:.4f} |" for c, v in rep["columns"].items()]
    L += ["", f"Hàng: {rep['n_rows']}", "", "| người | kept local | kept tham chiếu | kept cả hai |", "|---|---|---|---|"]
    L += [f"| {p} | {d['kept_local']} | {d['kept_ref']} | {d['kept_both']} |" for p, d in rep["per_person"].items()]
    L += ["", f"Kept tổng: {rep['kept_total']}", "", "| lớp | local | posture_config |", "|---|---|---|"]
    L += [f"| {c} | {d['local']} | {d['config']} |" for c, d in rep["class_counts"].items()]
    L += ["", f"n_train_windows: {rep['n_train_windows']}"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", default=str(C.HERE / "work" / "windows_info.csv"))
    ap.add_argument("--ref", default=r"D:\KLTN\ChayKaggle\posture_model_v4\windows_info_v4.csv")
    ap.add_argument("--tol", type=float, default=0.99, help="tỷ lệ khớp tối thiểu mỗi cột để mã thoát 0")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    rep = compare(read(a.local), read(a.ref), C.load_model_cfg())
    print(to_markdown(rep))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.exit(0 if min(rep["columns"].values()) >= a.tol else 2)


if __name__ == "__main__":
    main()
