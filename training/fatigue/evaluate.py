"""D1–D3: xu hướng BAD theo thời gian, thời điểm xuống sức (onset), dự báo onset từ 30 phút đầu.

  python evaluate.py --data <thư mục có minutes.jsonl, sessions.jsonl> --run <tên> [--shuffle-control | --shuffle-minutes-control]

Đầu ra out/<run>/: blocks.csv, curves.json (cho Dashboard H3), sessions.csv, metrics.json, metrics.md, curves.png, km.png, run_meta.json.
KẾT QUẢ TRÊN DỮ LIỆU GIẢ LÀ KIỂM CODE, KHÔNG PHẢI KẾT QUẢ NGHIÊN CỨU.
"""
import argparse
import copy
import csv
import json
import platform
import time
from pathlib import Path

import numpy as np

import blocks as BL
import common as C
import d3 as D3
import survival as SV
import trend as TR

NOTE = "KẾT QUẢ TRÊN DỮ LIỆU GIẢ LÀ KIỂM CODE, KHÔNG PHẢI KẾT QUẢ NGHIÊN CỨU."


def _f(v, nd=3):
    return "—" if v is None or v != v else f"{v:.{nd}f}"


def _fc(v, c, nd=3):
    return _f(v, nd) + ("" if not c else f" [{_f(c[0], nd)}; {_f(c[1], nd)}]")


def to_markdown(res, note):
    L = [note, ""]
    ds = res["dataset"]
    L += [f"Phiên: {ds['n_sessions']} (đủ điều kiện {ds['n_eligible']}, onset {ds['n_onset']}, kiểm duyệt {ds['n_censored']}); "
          f"onset < 30 phút (báo riêng): {res['d3']['n_onset_before_min']}; không đủ điều kiện: {ds['n_sessions'] - ds['n_eligible']}.", ""]
    t = res["d1"]["time_axis"]
    if t.get("primary") is not None:
        p = t["mixedlm"] if t["primary"] == "mixedlm" else t["gee_weighted"]
        L += [f"**D1 – độ dốc cố định** ({t['primary_method']}): {_f(p['slope_pp_per_hour'], 2)} điểm % BAD/giờ, "
              f"CI 95% [{_f(p['ci95_pp_per_hour'][0], 2)}; {_f(p['ci95_pp_per_hour'][1], 2)}]; {t['n_persons']} người, {t['n_sessions']} phiên, {t['n_blocks']} khối.",
              f"GEE có trọng số (độ nhạy): {_f(t['gee_weighted'].get('slope_pp_per_hour'), 2)} "
              f"[{_f((t['gee_weighted'].get('ci95_pp_per_hour') or [None, None])[0], 2)}; {_f((t['gee_weighted'].get('ci95_pp_per_hour') or [None, None])[1], 2)}].", ""]
    d2 = res["d2"]
    km = d2["km"]
    L += [f"**D2 – onset**: {d2['n_onset']}/{d2['n_eligible']} phiên có onset; KM trung vị = {_f(km['median'] if km else None, 0)} phút "
          f"(None = đường cong không xuống tới 0,5). Trung vị theo người: {d2['person_median_summary']}", ""]
    d3 = res["d3"]
    if "skipped" in d3:
        return "\n".join(L + [f"**D3 bỏ qua**: {d3['skipped']}"]) + "\n"
    names = dict(m0="m0: luôn nhắc phút 50", m1="m1: trung vị onset (KM)", m2="m2: hazard rời rạc", m3="m3: hazard gọn")
    L += [f"**D3** ({d3['n_compared']} phiên so sánh, bootstrap {d3['bootstrap']['n']} lần theo người)", "",
          "| Chỉ số | " + " | ".join(names[m] for m in D3.METHODS) + " |", "|---|" + "---|" * len(D3.METHODS)]
    lab = dict(timely_rate="Nhắc đúng lúc", late_rate="Nhắc trễ", early_rate="Sớm quá (> 15 phút)", none_rate="Không nhắc/bỏ lỡ",
               mae_min="MAE phút (phiên có nhắc)", c_index="C-index (cả kiểm duyệt)", reminders_per_hour="Nhắc / giờ")
    for k in D3.RATE_KEYS:
        if k == "mae_min":     # MAE chỉ tính phiên có nhắc: báo tỷ lệ không nhắc cạnh MAE
            L.append(f"| {lab[k]} | " + " | ".join(_fc(d3["pooled"][m][k], d3["ci95"][m][k]) + f" (không nhắc {d3['pooled'][m]['none_rate']:.0%})"
                                                    for m in D3.METHODS) + " |")
        else:
            L.append(f"| {lab[k]} | " + " | ".join(_fc(d3["pooled"][m][k], d3["ci95"][m][k]) for m in D3.METHODS) + " |")
    L += ["", "Chênh lệch so với m0:", "", "| Chỉ số | m1 − m0 | m2 − m0 | m3 − m0 |", "|---|---|---|---|"]
    for k in D3.RATE_KEYS:
        row = []
        for m in ("m1", "m2", "m3"):
            row.append(_fc(d3["pooled"][m][k] - d3["pooled"]["m0"][k], d3["diff_vs_m0_ci95"][m][k]))
        L.append(f"| {lab[k]} | " + " | ".join(row) + " |")
    return "\n".join(L) + "\n"


def plots(out, curves, km):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for p, d in curves["participants"].items():
        ax.plot([b["start_min"] for b in d["blocks"]], [b["mean_bad_rate"] for b in d["blocks"]], lw=0.8, alpha=0.55, label=p)
    o = curves["overall"]["blocks"]
    ax.plot([b["start_min"] for b in o], [b["mean_bad_rate"] for b in o], color="black", lw=2.2, label="chung")
    ax.set_xlabel("Phút trong phiên (đầu khối)"), ax.set_ylabel("Tỷ lệ BAD"), ax.set_title("Tỷ lệ BAD theo khối 10 phút")
    if len(curves["participants"]) <= 12:
        ax.legend(fontsize=6, ncol=2)
    fig.tight_layout(), fig.savefig(out / "curves.png", dpi=130), plt.close(fig)
    fig, ax = plt.subplots(figsize=(5.5, 4))
    if km:
        xs, ys = [0.0], [1.0]
        for t, s, _, _ in km["steps"]:
            xs += [t, t]
            ys += [ys[-1], s]
        ax.step(xs, ys, where="post")
        ax.plot(km["censor_times"], [np.interp(c, xs, ys) for c in km["censor_times"]], "|", color="gray")
    ax.axhline(0.5, color="gray", ls=":")
    ax.set_xlabel("Phút trong phiên"), ax.set_ylabel("Tỷ lệ phiên chưa xuống sức"), ax.set_title("Kaplan–Meier gộp (| = kiểm duyệt)")
    fig.tight_layout(), fig.savefig(out / "km.png", dpi=130), plt.close(fig)


def run(data_dir, out_dir, P=None, shuffle_control=False, boot_n=None, log=print, shuffle_minutes=False):
    t0 = time.time()
    P = copy.deepcopy(P or C.load_protocol())
    override = boot_n is not None and boot_n != P["bootstrap"]["n"]
    if boot_n:
        P["bootstrap"]["n"] = boot_n
    Pf = C.forecast_protocol()
    sessions = C.D.load(data_dir, P["window_sec"])
    assert not (shuffle_control and shuffle_minutes), "chỉ một đối chứng xáo mỗi lần chạy"
    if shuffle_control:
        sessions = BL.shuffle_blocks(sessions, P, P["controls"]["shuffle_blocks_seed"])
    elif shuffle_minutes:
        sessions = BL.shuffle_minutes(sessions, P, P["controls"]["shuffle_minutes_seed"])
    analyses = BL.analyse_all(sessions, P, Pf)
    n_el = sum(a["eligible"] for a in analyses.values())
    ds = dict(n_sessions=len(analyses), n_eligible=n_el, n_onset=sum(a["onset"] is not None for a in analyses.values()),
              n_censored=sum(a["censored"] for a in analyses.values()),
              ineligible_reasons={r: sum(a["reason"] == r for a in analyses.values()) for r in {a["reason"] for a in analyses.values()} if r})
    log(f"phiên {ds['n_sessions']} | đủ điều kiện {n_el} | onset {ds['n_onset']} | kiểm duyệt {ds['n_censored']} | không đủ: {ds['ineligible_reasons']}")
    trend, df = TR.run_trend(analyses, P)
    curves = TR.curves(analyses, P)
    d2 = SV.onset_distribution(analyses)
    d3, per_session, _ = D3.run_d3(sessions, analyses, P, Pf, log)
    res = dict(dataset=ds, d1=trend, d2=d2, d3=d3, shuffle_control=shuffle_control, shuffle_minutes=shuffle_minutes, note=NOTE)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "blocks.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant", "session_id", "block_idx", "block_start_min", "bad_rate", "classified_sec", "missing"])
        for a in analyses.values():
            for r in a["rows"]:
                w.writerow([r["participant"], r["session_id"], r["block_idx"], r["block_start_min"],
                            "" if r["bad_rate"] != r["bad_rate"] else f"{r['bad_rate']:.6f}", f"{r['classified_sec']:.1f}", int(r["missing"])])
    cmp_keys, early_keys, _ = D3.split_groups(analyses, P)
    with open(out / "sessions.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant", "session_id", "onset", "censored", *[f"r_{m}" for m in D3.METHODS], "eligible", "group", "n_min"])
        for k, a in analyses.items():
            grp = "compared" if k in cmp_keys else "onset_lt_min" if k in early_keys else "ineligible"
            r = per_session.get(k, {})
            w.writerow([a["participant"], a["session_id"], "" if a["onset"] is None else a["onset"], int(a["censored"]) if a["eligible"] else "",
                        *["" if r.get(m) is None else f"{r[m]:.0f}" for m in D3.METHODS], int(a["eligible"]), grp, a["n_min"]])
    (out / "curves.json").write_text(json.dumps(curves, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    note = NOTE + (" Chạy đối chứng: xáo thứ tự các khối trong từng phiên." if shuffle_control else
                   " Chạy đối chứng: xáo thứ tự các PHÚT trong từng phiên." if shuffle_minutes else "")
    (out / "metrics.md").write_text(to_markdown(res, note), encoding="utf-8")
    plots(out, curves, d2["km"])
    import scipy, sklearn, statsmodels
    pf = C.PF
    git = pf.git_info(C.PROTOCOL_PATH)
    git["fatigue_code_dirty"] = bool(pf._git("status", "--porcelain", "--", str(C.HERE)))
    meta = dict(data_dir=str(data_dir), data_sha256=C.D.data_hash(data_dir), protocol_sha256=pf.protocol_hash(C.PROTOCOL_PATH),
                forecast_protocol_sha256=pf.protocol_hash(), protocol_version=P["version"], git=git,
                libraries=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                               sklearn=sklearn.__version__, statsmodels=statsmodels.__version__),
                runtime_sec=round(time.time() - t0, 1), shuffle_control=shuffle_control, shuffle_minutes=shuffle_minutes,
                protocol_override=dict(bootstrap_n=P["bootstrap"]["n"]) if override else None, summary=C.D.summary(sessions), note=NOTE)
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"xong trong {meta['runtime_sec']} s -> {out}")
    return res, meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out-root", default=str(C.HERE / "out"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--shuffle-control", action="store_true", help="đối chứng: xáo thứ tự các khối trong từng phiên")
    g.add_argument("--shuffle-minutes-control", action="store_true", help="đối chứng thứ 5: xáo thứ tự các PHÚT trong từng phiên")
    ap.add_argument("--boot-n", type=int, default=None, help="CHỈ để chạy thử nhanh; ghi vào run_meta là đã ghi đè protocol")
    a = ap.parse_args()
    out = Path(a.out_root) / a.run
    run(a.data, out, shuffle_control=a.shuffle_control, boot_n=a.boot_n, shuffle_minutes=a.shuffle_minutes_control)
    print((out / "metrics.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
