"""C4 – đánh giá LOSO theo người cho bốn mô hình dự báo (a: giống phút hiện tại, b: Markov, c: logistic, d: GRU).

Mỗi fold giữ một người làm test. Trong phần train: tách một phần NGƯỜI làm validation (early stopping của GRU và chọn ngưỡng
nhắc của cả 4 mô hình), 4 mô hình fit trên phần train còn lại. Ngưỡng nhắc = ngưỡng THẤP nhất mà nhắc nhầm/giờ trên validation
<= mục tiêu khóa trong protocol.json, rồi áp nguyên lên người test.

Luật nhắc: nhắc tại mốc khi p >= ngưỡng, sau đó im ít nhất `silence_min` phút (theo từng phiên). Nhắc nhầm = nhắc tại mốc y = 0.
Nhắc nhầm/giờ = số nhắc nhầm / (tổng presence_sec / 3600). Phút nhắc trước = từ mốc nhắc (y = 1) tới phút đầu tiên trong t+1..t+H
có BAD >= lead_bad_fraction * phân loại được (bỏ các nhắc không có phút như vậy, số bị bỏ được báo).

  python evaluate.py --data DIR --run NAME [--shuffle-control] [--out-root out]
KẾT QUẢ TRÊN DỮ LIỆU GIẢ LÀ KIỂM CODE, KHÔNG PHẢI KẾT QUẢ NGHIÊN CỨU.
"""
import argparse
import csv
import json
import platform
import time
from pathlib import Path

import numpy as np

import data as D
import dataset as DS
import models as MD
import protocol as PR

METRIC_KEYS = ("pr_auc", "brier", "sensitivity", "false_per_hour", "lead_mean")
LOWER_BETTER = {"brier", "false_per_hour"}


# ---------------------------------------------------------------- luật nhắc
def reminder_minutes(minutes, p, thr, silence):
    """Chỉ số (trong mảng đã sắp theo phút) các mốc có nhắc: p >= thr, rồi im >= silence phút."""
    out, last = [], None
    for i in np.argsort(minutes, kind="stable"):
        if p[i] >= thr and (last is None or minutes[i] - last >= silence):
            out.append(int(i))
            last = minutes[i]
    return out


def all_alerts(ds, p, thr, silence):
    """Chỉ số các mốc được nhắc trên toàn ds, theo từng phiên."""
    out = []
    keys = ds["participant"].astype(object) + "|" + ds["session_id"].astype(object)
    for k in np.unique(keys):
        idx = np.where(keys == k)[0]
        out += [int(idx[j]) for j in reminder_minutes(ds["minute"][idx], p[idx], thr, silence)]
    return out


def false_per_hour(ds, p, thr, silence):
    al = all_alerts(ds, p, thr, silence)
    hours = sum(ds["hours"].values())
    return (sum(ds["y"][i] == 0 for i in al) / hours if hours > 0 else float("nan")), len(al)


def pick_threshold(val, p_val, P):
    """Ngưỡng thấp nhất sao cho nhắc nhầm/giờ trên validation <= mục tiêu. Không có -> ngưỡng > 1 (không nhắc)."""
    R = P["reminder"]
    for thr in sorted(set(np.round(p_val, 12))):
        fph, _ = false_per_hour(val, p_val, thr - 1e-12, R["silence_min"])
        if fph <= R["target_false_per_hour"]:
            return float(thr) - 1e-12
    return 1.0 + 1e-9


def person_agg(ds, p, thr, P):
    """Gom số liệu của MỘT người test (để cộng gộp và bootstrap theo người)."""
    al = all_alerts(ds, p, thr, P["reminder"]["silence_min"])
    y = ds["y"]
    true_al = [i for i in al if y[i] == 1]
    leads = [int(ds["lead"][i]) for i in true_al if ds["lead"][i] >= 1]
    return dict(y=y.copy(), p=np.asarray(p, float).copy(), thr=float(thr), hours=sum(ds["hours"].values()),
                false=sum(y[i] == 0 for i in al), true=len(true_al), leads=leads, n_alerts=len(al))


def pooled(aggs):
    from sklearn.metrics import average_precision_score
    y = np.concatenate([a["y"] for a in aggs])
    p = np.concatenate([a["p"] for a in aggs])
    thr = np.concatenate([np.full(len(a["y"]), a["thr"]) for a in aggs])
    hours = sum(a["hours"] for a in aggs)
    leads = [x for a in aggs for x in a["leads"]]
    pos = y == 1
    return dict(n=int(len(y)), positive_rate=float(y.mean()),
                pr_auc=float(average_precision_score(y, p)) if pos.any() else float("nan"),
                brier=float(np.mean((p - y) ** 2)),
                sensitivity=float((p[pos] >= thr[pos]).mean()) if pos.any() else float("nan"),
                false_per_hour=sum(a["false"] for a in aggs) / hours if hours > 0 else float("nan"),
                false_alerts=int(sum(a["false"] for a in aggs)), true_alerts=int(sum(a["true"] for a in aggs)),
                alerts=int(sum(a["n_alerts"] for a in aggs)), hours=float(hours),
                lead_mean=float(np.mean(leads)) if leads else float("nan"), lead_n=len(leads))


def bootstrap(per_person, boot, models):
    """per_person: {model: {person: agg}}. Lấy mẫu NGƯỜI có hoàn lại. -> CI từng chỉ số và chênh lệch so với (a)."""
    persons = sorted(next(iter(per_person.values())))
    rng = np.random.default_rng(boot["seed"])
    vals = {m: {k: [] for k in METRIC_KEYS} for m in models}
    diffs = {m: {k: [] for k in METRIC_KEYS} for m in models if m != "a"}
    for _ in range(boot["n"]):
        pick = [persons[i] for i in rng.integers(0, len(persons), len(persons))]
        res = {m: pooled([per_person[m][q] for q in pick]) for m in models}
        for m in models:
            for k in METRIC_KEYS:
                vals[m][k].append(res[m][k])
                if m != "a":
                    diffs[m][k].append(res[m][k] - res["a"][k])
    lo, hi = (1 - boot["ci"]) / 2 * 100, (1 + boot["ci"]) / 2 * 100

    def ci(v):
        v = np.array(v, float)
        v = v[np.isfinite(v)]
        return None if len(v) < max(10, boot["n"] // 10) else [float(np.percentile(v, lo)), float(np.percentile(v, hi))]
    return ({m: {k: ci(v) for k, v in d.items()} for m, d in vals.items()},
            {m: {k: ci(v) for k, v in d.items()} for m, d in diffs.items()})


# ---------------------------------------------------------------- chạy
def split_val(train_people, P, fold):
    V = P["validation"]
    n_val = max(V["min_val_persons"], int(round(V["person_fraction"] * len(train_people))))
    n_val = min(n_val, len(train_people) - 1)
    rng = np.random.default_rng(P["seed"] + 1000 + fold)
    order = rng.permutation(sorted(train_people))
    return sorted(order[:n_val].tolist()), sorted(order[n_val:].tolist())


def oof_predictions(m, train, train_people, P):
    """LOSO lồng trong train fold: dự đoán ngoài lượt cho từng người train (mô hình m fit trên các người train còn lại)."""
    oof = np.full(len(train["y"]), np.nan)
    for q in train_people:
        inner_fit = DS.subset(train, [x for x in train_people if x != q])
        held = DS.subset(train, [q])
        assert q not in set(inner_fit["participant"])
        oof[train["participant"] == q] = MD.MODELS[m](P).fit(inner_fit, None).predict(held)
    return oof


def run_loso(ds, P, model_names=("a", "b", "c", "d", "e"), log=print):
    people = sorted(set(ds["participant"]))
    if len(people) < P["min_persons"]:
        raise SystemExit(f"Chỉ có {len(people)} người, cần >= {P['min_persons']} (protocol.min_persons)")
    preds = {m: np.full(len(ds["y"]), np.nan) for m in model_names}
    folds, per_person = [], {m: {} for m in model_names}
    for f, test_p in enumerate(people):
        train_people = [q for q in people if q != test_p]
        val_p, fit_p = split_val(train_people, P, f)
        assert test_p not in val_p and test_p not in fit_p and not set(val_p) & set(fit_p)
        fit, val, test = DS.subset(ds, fit_p), DS.subset(ds, val_p), DS.subset(ds, [test_p])
        train = DS.subset(ds, train_people)
        info = dict(test=test_p, val=val_p, fit=fit_p, n_train=int(len(train["y"])), n_fit=int(len(fit["y"])),
                    n_val=int(len(val["y"])), n_test=int(len(test["y"])), thresholds={}, threshold_method={})
        tmask = ds["participant"] == test_p
        nested, by_val = set(P["threshold_selection"]["nested_loso"]), set(P["threshold_selection"]["validation_split"])
        for m in model_names:
            if m in nested:      # ngưỡng từ dự đoán ngoài lượt của mọi người train, rồi fit lại trên toàn bộ train fold
                thr = pick_threshold(train, oof_predictions(m, train, train_people, P), P)
                mdl = MD.MODELS[m](P).fit(train, None)
                info["threshold_method"][m] = "nested_loso"
            else:                # validation theo người (GRU)
                assert m in by_val, f"protocol.threshold_selection thiếu mô hình {m}"
                mdl = MD.MODELS[m](P).fit(fit, val)
                thr = pick_threshold(val, mdl.predict(val), P)
                info["threshold_method"][m] = "validation_split"
            pt = mdl.predict(test)
            info["thresholds"][m] = thr
            if m == "d":
                info["gru_epochs"] = int(mdl.epochs)
            preds[m][tmask] = pt
            per_person[m][test_p] = person_agg(test, pt, thr, P)
        log(f"fold {f + 1}/{len(people)} test={test_p} val={val_p} thr=" +
            " ".join(f"{m}:{info['thresholds'][m]:.3f}" for m in model_names))
        folds.append(info)
    return preds, per_person, folds


def to_markdown(res, note):
    ms = res["models"]
    names = dict(a="(a) giống phút hiện tại", b="(b) Markov", c="(c) Logistic L2", d="(d) GRU", e="(e) Logistic: chỉ thời gian ngồi")
    h = ["Chỉ số"] + [names[m] for m in ms]
    L = [note, "", f"Mốc: {res['pooled'][ms[0]]['n']}, tỷ lệ dương {res['pooled'][ms[0]]['positive_rate']:.3f}, "
         f"{res['n_people']} người, bootstrap {res['bootstrap']['n']} lần theo người.", "",
         "| " + " | ".join(h) + " |", "|" + "---|" * len(h)]
    lab = dict(pr_auc="PR-AUC", brier="Brier", sensitivity="Độ nhạy @ngưỡng khóa", false_per_hour="Nhắc nhầm / giờ",
               lead_mean="Phút nhắc trước TB")
    for k in METRIC_KEYS:
        cells = []
        for m in ms:
            v, c = res["pooled"][m][k], res["ci95"][m][k]
            cells.append("—" if v != v else f"{v:.3f}" + (f" [{c[0]:.3f}; {c[1]:.3f}]" if c else ""))
        L.append(f"| {lab[k]} | " + " | ".join(cells) + " |")
    L += ["", "Chênh lệch so với (a) (mô hình − (a); Brier và nhắc nhầm/giờ càng thấp càng tốt):", "",
          "| Chỉ số | " + " | ".join(names[m] for m in ms if m != "a") + " |", "|" + "---|" * len(ms)]
    for k in METRIC_KEYS:
        cells = []
        for m in ms:
            if m == "a":
                continue
            c = res["diff_vs_a_ci95"][m][k]
            d = res["pooled"][m][k] - res["pooled"]["a"][k]
            cells.append("—" if d != d else f"{d:+.3f}" + (f" [{c[0]:+.3f}; {c[1]:+.3f}]" if c else ""))
        L.append(f"| {lab[k]} | " + " | ".join(cells) + " |")
    L += ["", "Ngưỡng nhắc khóa theo fold ((a),(b),(c),(e): LOSO lồng trong train fold; (d): validation theo người, cột Val):", "",
          "| Test | Val (d) | " + " | ".join(f"thr {m}" for m in ms) + " |", "|" + "---|" * (2 + len(ms))]
    for f in res["folds"]:
        L.append(f"| {f['test']} | {','.join(f['val'])} | " + " | ".join(f"{f['thresholds'][m]:.3f}" for m in ms) + " |")
    L += ["", "Số liệu nhắc (pooled): " + "; ".join(
        f"{m}: {res['pooled'][m]['alerts']} nhắc ({res['pooled'][m]['false_alerts']} nhầm), {res['pooled'][m]['hours']:.1f} giờ, "
        f"lead n={res['pooled'][m]['lead_n']}" for m in ms)]
    return "\n".join(L) + "\n"


def plots(out, ds, preds, models, y):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve
    names = dict(a="a: giống phút hiện tại", b="b: Markov", c="c: Logistic", d="d: GRU", e="e: Logistic (thời gian ngồi)")
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    for m in models:
        pr, rc, _ = precision_recall_curve(y, preds[m])
        ax.plot(rc, pr, label=names[m])
    ax.axhline(y.mean(), color="gray", ls=":", label=f"tỷ lệ dương {y.mean():.2f}")
    ax.set_xlabel("Recall"), ax.set_ylabel("Precision"), ax.set_title("PR (LOSO, gộp mọi người)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "pr_curve.png", dpi=130)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    ax.plot([0, 1], [0, 1], color="gray", ls=":")
    for m in models:
        p = preds[m]
        q = np.unique(np.quantile(p, np.linspace(0, 1, 9)))
        b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, max(len(q) - 2, 0))
        xs = [p[b == k].mean() for k in range(len(q) - 1) if (b == k).any()]
        ys = [y[b == k].mean() for k in range(len(q) - 1) if (b == k).any()]
        ax.plot(xs, ys, marker="o", label=names[m])
    ax.set_xlabel("Xác suất dự đoán"), ax.set_ylabel("Tần suất thực"), ax.set_title("Calibration (nhóm tứ phân vị)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "calibration.png", dpi=130)
    plt.close(fig)


def run(data_dir, out_dir, P=None, shuffle_control=False, model_names=("a", "b", "c", "d", "e"), boot_n=None, log=print):
    t0 = time.time()
    P = P or PR.load()
    boot = dict(P["bootstrap"])
    override = boot_n is not None and boot_n != boot["n"]
    if boot_n:
        boot["n"] = boot_n
    sessions = D.load(data_dir, P["window_sec"])
    ds = DS.build_dataset(sessions, P, shuffle_within_person_seed=P["seed"] if shuffle_control else None)
    st = DS.stats(ds)
    log(f"mốc: {st['n_anchors']}/{st['n_minutes']} phút | tỷ lệ dương {st['positive_rate']:.3f} | bỏ: {st['dropped']}")
    for p, d in st["per_person"].items():
        log(f"  {p}: {d['n']} mốc, dương {d['positive_rate']:.3f}")
    preds, per_person, folds = run_loso(ds, P, model_names, log)
    models = list(model_names)
    pool = {m: pooled(list(per_person[m].values())) for m in models}
    ci, dci = bootstrap(per_person, boot, models) if "a" in models else ({}, {})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "predictions.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant", "session_id", "minute_idx", "y", *[f"p_{m}" for m in models]])
        for i in range(len(ds["y"])):
            w.writerow([ds["participant"][i], ds["session_id"][i], int(ds["minute"][i]), int(ds["y"][i]),
                        *[f"{preds[m][i]:.6f}" for m in models]])
    res = dict(models=models, n_people=len(per_person[models[0]]), pooled=pool, ci95=ci, diff_vs_a_ci95=dci,
               bootstrap=boot, folds=folds, dataset=st, shuffle_control=shuffle_control,
               per_person={m: {p: {k: v for k, v in pooled([a]).items()} for p, a in per_person[m].items()} for m in models},
               note="KẾT QUẢ TRÊN DỮ LIỆU GIẢ LÀ KIỂM CODE, KHÔNG PHẢI KẾT QUẢ NGHIÊN CỨU.")
    (out / "metrics.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    note = res["note"] + (" Chạy đối chứng: nhãn xáo trong từng người." if shuffle_control else "")
    if "a" in models:
        (out / "metrics.md").write_text(to_markdown(res, note), encoding="utf-8")
    plots(out, ds, preds, models, ds["y"])
    import sklearn
    libs = dict(python=platform.python_version(), numpy=np.__version__, sklearn=sklearn.__version__)
    try:
        import torch
        libs["torch"] = torch.__version__
    except Exception:  # noqa: BLE001
        libs["torch"] = None
    meta = dict(data_dir=str(data_dir), data_sha256=D.data_hash(data_dir), protocol_sha256=PR.protocol_hash(),
                git=PR.git_info(), libraries=libs, runtime_sec=round(time.time() - t0, 1), shuffle_control=shuffle_control,
                protocol_override=dict(bootstrap_n=boot["n"]) if override else None, models=models,
                summary=D.summary(sessions), note=res["note"])
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"xong trong {meta['runtime_sec']} s -> {out}")
    return res, meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="thư mục có minutes.jsonl và sessions.jsonl")
    ap.add_argument("--run", required=True)
    ap.add_argument("--out-root", default=str(PR.HERE / "out"))
    ap.add_argument("--shuffle-control", action="store_true", help="đối chứng: xáo nhãn y trong từng người")
    ap.add_argument("--models", default="abcde")
    ap.add_argument("--boot-n", type=int, default=None, help="CHỈ để chạy thử nhanh; ghi vào run_meta là đã ghi đè protocol")
    a = ap.parse_args()
    res, _ = run(a.data, Path(a.out_root) / a.run, shuffle_control=a.shuffle_control, model_names=tuple(a.models), boot_n=a.boot_n)
    if "a" in res["models"]:
        print((Path(a.out_root) / a.run / "metrics.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
