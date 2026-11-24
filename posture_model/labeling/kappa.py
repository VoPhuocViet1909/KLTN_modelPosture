"""
Cohen's κ giữa các người chấm trên phần video trùng.

  python -m labeling.kappa labels_A.csv labels_B.csv
  python -m labeling.kappa labels_A.csv labels_B.csv --include-unclear --json kappa.json

Ghép cặp theo (video, t_start): chỉ tính các đoạn cả hai người đều đã chấm. Mặc định bỏ đoạn mà một trong hai chọn
UNCLEAR (và báo số đoạn bị bỏ); `--include-unclear` coi UNCLEAR là lớp thứ 7. Có hơn hai người chấm thì tính mọi cặp.
κ không xác định (NaN) khi hai người chỉ dùng đúng một lớp giống nhau (pe = 1) hoặc không có đoạn trùng nào.
"""
import argparse
import itertools
import json
import math
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from labeling.session import CLASSES, LABELS, UNCLEAR, LabelFileError, load_rows  # noqa: E402


def cohen_kappa(a, b, labels):
    """a, b: nhãn cùng độ dài. Trả dict n, observed, expected, kappa, ci95, matrix (hàng = người A, cột = người B)."""
    if len(a) != len(b):
        raise ValueError("Hai danh sách nhãn phải cùng độ dài")
    n = len(a)
    idx = {c: i for i, c in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for x, y in zip(a, b):
        m[idx[x]][idx[y]] += 1
    if n == 0:
        return dict(n=0, observed=None, expected=None, kappa=float("nan"), ci95=None, matrix=m)
    po = sum(m[i][i] for i in range(len(labels))) / n
    row = [sum(r) / n for r in m]
    col = [sum(m[i][j] for i in range(len(labels))) / n for j in range(len(labels))]
    pe = sum(r * c for r, c in zip(row, col))
    if abs(1 - pe) < 1e-12:
        return dict(n=n, observed=po, expected=pe, kappa=float("nan"), ci95=None, matrix=m)
    k = (po - pe) / (1 - pe)
    se = math.sqrt(po * (1 - po) / (n * (1 - pe) ** 2))          # xấp xỉ đơn giản, đủ để báo độ bất định
    return dict(n=n, observed=po, expected=pe, kappa=k, ci95=(max(-1.0, k - 1.96 * se), min(1.0, k + 1.96 * se)), matrix=m)


def pair_labels(rows_a, rows_b, include_unclear=False):
    """-> (nhãn A, nhãn B, thống kê ghép cặp)."""
    la = {(r["video"], round(r["t_start"], 3)): r["label"] for r in rows_a}
    lb = {(r["video"], round(r["t_start"], 3)): r["label"] for r in rows_b}
    common = sorted(set(la) & set(lb))
    a, b, dropped = [], [], 0
    for k in common:
        if not include_unclear and UNCLEAR in (la[k], lb[k]):
            dropped += 1
            continue
        a.append(la[k])
        b.append(lb[k])
    return a, b, dict(only_a=len(set(la) - set(lb)), only_b=len(set(lb) - set(la)), overlap=len(common),
                      dropped_unclear=dropped)


def by_rater(paths):
    raters = {}
    for p in paths:
        if not os.path.exists(p):
            raise LabelFileError(f"Không thấy file nhãn: {p}")
        for r in load_rows(p):
            d = raters.setdefault(r["rater"], {})
            k = (r["video"], round(r["t_start"], 3))
            if k in d:
                raise LabelFileError(f"Người chấm '{r['rater']}' có hai nhãn cho {k[0]} {k[1]}")
            d[k] = r
    return {name: list(d.values()) for name, d in raters.items()}


def compare(paths, include_unclear=False):
    raters = by_rater(paths)
    if len(raters) < 2:
        raise LabelFileError("Cần ít nhất hai người chấm khác nhau (cột rater) trong các file đã cho")
    labels = LABELS if include_unclear else CLASSES
    out = []
    for x, y in itertools.combinations(sorted(raters), 2):
        a, b, stats = pair_labels(raters[x], raters[y], include_unclear)
        out.append(dict(rater_a=x, rater_b=y, labels=list(labels), **stats, **cohen_kappa(a, b, labels)))
    return out


def format_report(res):
    lines = []
    for r in res:
        k = r["kappa"]
        lines.append(f"{r['rater_a']} vs {r['rater_b']}: trùng {r['overlap']} đoạn, tính {r['n']} "
                     f"(bỏ {r['dropped_unclear']} đoạn UNCLEAR; chỉ {r['rater_a']} chấm {r['only_a']}, chỉ {r['rater_b']} chấm {r['only_b']})")
        if r["n"] == 0:
            lines.append("  κ: không tính được (không có đoạn trùng)")
            continue
        ci = "" if r["ci95"] is None else f"  (95%: {r['ci95'][0]:.3f} đến {r['ci95'][1]:.3f})"
        ks = "không xác định (cả hai chỉ dùng một lớp)" if math.isnan(k) else f"{k:.3f}{ci}"
        lines.append(f"  độ đồng thuận quan sát {r['observed']:.3f}, kỳ vọng ngẫu nhiên {r['expected']:.3f}, κ = {ks}")
        names = r["labels"]
        lines.append("  ma trận nhầm lẫn (hàng = " + r["rater_a"] + ", cột = " + r["rater_b"] + "):")
        w = max(len(n) for n in names)
        lines.append("  " + " " * w + " " + " ".join(f"{n[:6]:>6}" for n in names))
        for n, row in zip(names, r["matrix"]):
            lines.append("  " + f"{n:<{w}} " + " ".join(f"{v:>6}" for v in row))
    return "\n".join(lines)


def _clean(x):
    """NaN không hợp lệ trong JSON chuẩn: đổi thành null."""
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cohen's κ giữa người chấm nhãn 6 lớp")
    ap.add_argument("csv", nargs="+", help="file CSV nhãn (mỗi người một file, hoặc gộp nhiều người trong một file)")
    ap.add_argument("--include-unclear", action="store_true", help="coi UNCLEAR là lớp thứ 7 thay vì bỏ đoạn đó")
    ap.add_argument("--json", default=None, help="ghi kết quả ra file JSON")
    a = ap.parse_args(argv)
    try:
        res = compare(a.csv, a.include_unclear)
    except (LabelFileError, OSError) as e:
        print("Lỗi:", e, file=sys.stderr)
        return 2
    print(format_report(res))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(_clean(res), f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
