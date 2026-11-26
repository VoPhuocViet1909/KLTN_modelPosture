"""Train Random Forest v4 đúng như notebook v4 (Phần 5) và đối chiếu LOSO với `loso_random_forest` trong posture_config.json.

Notebook dùng HAI rừng, mỗi rừng 300 cây, class_weight="balanced", random_state=0, đầu vào 24 thống kê
(mean/std/min/max của 6 đặc trưng, thứ tự `features`):
  - rf_bad: GOOD/BAD trên mọi cửa sổ
  - rf_cls: 6 lớp trên các cửa sổ có lớp phụ (y_cls >= 0)

LOSO theo người rồi fit bản cuối trên toàn bộ người trong NPZ. Không dò tham số.
Nếu LOSO lệch quá --tol so với config thì DỪNG (mã thoát 2) và KHÔNG ghi model, trừ khi có --export-anyway.

  python train_rf_v4.py [--npz work/dataset_windows_v4_local.npz] [--out models] [--tol 0.02]
Đầu ra: models/posture_rf_v4.joblib, models/posture_rf_v4.meta.json, models/loso_rf_v4_local.json (không commit).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score

import common as C

KEYS = ("acc", "f1_bad", "acc_cls", "macro_f1")     # các cột phải khớp config (đủ theo yêu cầu A2)
N_TREES, SEED = 300, 0


def scores(y, yh):
    """Công thức của notebook (ô Phần 5)."""
    y, yh = np.asarray(y).astype(int), np.asarray(yh).astype(int)
    tp = ((y == 1) & (yh == 1)).sum()
    tn = ((y == 0) & (yh == 0)).sum()
    fp = ((y == 0) & (yh == 1)).sum()
    fn = ((y == 1) & (yh == 0)).sum()
    acc = (tp + tn) / len(y)
    pe = (y == 1).mean() * (yh == 1).mean() + (y == 0).mean() * (yh == 0).mean()
    return dict(n=int(len(y)), acc=float(acc), kappa=float((acc - pe) / (1 - pe + 1e-9)),
                sens_bad=float(tp / max(tp + fn, 1)), spec_good=float(tn / max(tn + fp, 1)),
                f1_bad=float(2 * tp / max(2 * tp + fp + fn, 1)))


def cls_scores(c, ch):
    ok = c >= 0
    if not ok.any():
        return dict(n_cls=0, acc_cls=float("nan"), macro_f1=float("nan"))
    present = sorted(set(c[ok]))
    return dict(n_cls=int(ok.sum()), acc_cls=float((c[ok] == ch[ok]).mean()),
                macro_f1=float(f1_score(c[ok], ch[ok], labels=present, average="macro", zero_division=0)))


def new_rf():
    return RandomForestClassifier(N_TREES, class_weight="balanced", n_jobs=-1, random_state=SEED)


def fit_pair(X, y, c):
    S = C.win_stats(X)
    rf_bad = new_rf().fit(S, y)
    m = c >= 0
    rf_cls = new_rf().fit(S[m], c[m])
    return rf_bad, rf_cls


def loso(X, y, c, g, n_classes):
    res, cm = {}, np.zeros((n_classes, n_classes), int)
    for p in np.unique(g):
        tr, te = g != p, g == p
        if len(np.unique(y[tr])) < 2:
            print("Bỏ fold", p, "(train chỉ có 1 lớp)")
            continue
        rf_bad, rf_cls = fit_pair(X[tr], y[tr], c[tr])
        St = C.win_stats(X[te])
        ch = rf_cls.predict(St)
        res[str(p)] = {**scores(y[te], rf_bad.predict(St)), **cls_scores(c[te], ch)}
        ok = c[te] >= 0
        cm += confusion_matrix(c[te][ok], ch[ok], labels=range(n_classes))
    return res, cm


def compare_loso(res, ref):
    rows, worst = [], 0.0
    for p, r in res.items():
        for k in KEYS:
            d = abs(r[k] - ref[p][k])
            worst = max(worst, d)
            rows.append((p, k, r[k], ref[p][k], d))
    return rows, worst


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--npz", default=str(C.HERE / "work" / "dataset_windows_v4_local.npz"))
    ap.add_argument("--out", default=str(C.HERE / "models"))
    ap.add_argument("--tol", type=float, default=0.02, help="lệch tuyệt đối tối đa của acc/f1_bad/acc_cls/macro_f1 so với config")
    ap.add_argument("--export-anyway", action="store_true", help="vẫn ghi model dù LOSO lệch (chỉ để điều tra)")
    a = ap.parse_args()

    cfg = C.load_model_cfg()
    z = np.load(a.npz, allow_pickle=False)
    X, y, c, g = z["X"], z["y_bad"], z["y_cls"], z["group"]
    classes = [str(s) for s in z["classes"]]
    assert classes == cfg["classes"], "thứ tự lớp trong NPZ khác posture_config.json"
    print(f"{len(y)} cửa sổ | người {sorted(set(map(str, g)))} | BAD {y.mean():.1%} | có lớp phụ {(c >= 0).mean():.1%}")

    res, cm = loso(X, y, c, g, len(classes))
    rows, worst = compare_loso(res, cfg["loso_random_forest"])
    print("\n| người | chỉ số | local | config | |lệch| |\n|---|---|---|---|---|")
    for p, k, v, r, d in rows:
        print(f"| {p} | {k} | {v:.4f} | {r:.4f} | {d:.4f} |")
    n_ref = {p: (cfg["loso_random_forest"][p]["n"], cfg["loso_random_forest"][p]["n_cls"]) for p in res}
    n_loc = {p: (res[p]["n"], res[p]["n_cls"]) for p in res}
    print("\nSố cửa sổ (n, n_cls) local:", n_loc, "| config:", n_ref)
    print(f"Lệch lớn nhất: {worst:.4f} (ngưỡng {a.tol})")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "loso_rf_v4_local.json").write_text(json.dumps(
        dict(loso=res, confusion=cm.tolist(), compare=[dict(person=p, key=k, local=v, config=r, abs_diff=d) for p, k, v, r, d in rows],
             worst_abs_diff=worst), indent=2, ensure_ascii=False), encoding="utf-8")
    if worst > a.tol and not a.export_anyway:
        print("\nDỪNG: LOSO không khớp số liệu tham chiếu, không ghi model. Báo lại, không sửa code cho khớp.")
        sys.exit(2)

    rf_bad, rf_cls = fit_pair(X, y, c)
    import joblib
    model_path = out / "posture_rf_v4.joblib"
    joblib.dump(dict(rf_bad=rf_bad, rf_cls=rf_cls, classes=classes, features=C.FEATURES, n_stats=24,
                     stats=["mean", "std", "min", "max"]), model_path)
    meta = dict(
        model_sha256=C.sha256_file(model_path),
        npz_sha256=C.sha256_file(a.npz),
        posture_config_sha256=C.sha256_file(C.MODEL_CFG_PATH),
        onnx_sha256=C.sha256_file(C.ONNX_PATH),
        libraries=C.lib_versions(),
        features=C.FEATURES, stats_order=["mean", "std", "min", "max"], n_stats=24, classes=classes,
        window=cfg["window"], fps=cfg["fps"],
        rf=dict(n_estimators=N_TREES, class_weight="balanced", random_state=SEED, forests=["rf_bad (GOOD/BAD)", "rf_cls (6 lớp, y_cls>=0)"]),
        train=dict(n_windows=int(len(y)), people=sorted(map(str, set(g))), n_cls_windows=int((c >= 0).sum())),
        loso_worst_abs_diff_vs_config=worst, loso_exported_despite_mismatch=bool(worst > a.tol),
        note="Mô hình fit lại tại máy từ video v4; không phải bản train trên Kaggle. Không commit.")
    (out / "posture_rf_v4.meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nĐã ghi", model_path)


if __name__ == "__main__":
    main()
