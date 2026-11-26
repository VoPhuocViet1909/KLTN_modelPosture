"""D1 – xu hướng tỷ lệ BAD theo thời gian trong buổi.

Mô hình chính: statsmodels MixedLM `bad_rate ~ hours`, hệ số chặn + độ dốc ngẫu nhiên theo người, chỉ các khối không thiếu của phiên đủ điều kiện.
MixedLM không hỗ trợ trọng số nên mô hình chính không trọng số. Không hội tụ / sai số không hữu hạn -> dùng GEE (Gaussian, exchangeable theo người,
trọng số classified_sec) và ghi lại. GEE có trọng số luôn được tính thêm như phân tích độ nhạy. Độ dốc đổi sang điểm phần trăm BAD mỗi giờ.
Trục phụ: thời gian ngồi liên tục (giờ) tại cuối khối. `curves.json`: đường cong trung bình theo khối cho từng người (Dashboard H3).
"""
import warnings

import numpy as np
import pandas as pd


def to_frame(analyses):
    """Các khối KHÔNG thiếu của phiên đủ điều kiện -> DataFrame (hours = điểm giữa khối, sit_hours = ngồi liên tục tại cuối khối)."""
    rows = []
    for a in analyses.values():
        if not a["eligible"]:
            continue
        for r in a["rows"]:
            if not r["missing"]:
                rows.append(dict(participant=r["participant"], session_id=r["session_id"], block_idx=r["block_idx"],
                                 bad_rate=r["bad_rate"], classified_sec=r["classified_sec"],
                                 start=r["block_start_min"], sit_hours=r["sitting_end_min"] / 60.0))
    return pd.DataFrame(rows)


def _gee(df, x, ci):
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    m = smf.gee(f"bad_rate ~ {x}", "participant", df, cov_struct=sm.cov_struct.Exchangeable(),
                family=sm.families.Gaussian(), weights=df["classified_sec"].to_numpy())
    r = m.fit()
    lo, hi = r.conf_int(alpha=1 - ci).loc[x]
    return dict(method="gee_exchangeable_weighted", slope_pp_per_hour=float(r.params[x] * 100),
                ci95_pp_per_hour=[float(lo * 100), float(hi * 100)], p_value=float(r.pvalues[x]))


def _mixed(df, x, P):
    import statsmodels.formula.api as smf
    t = P["trend"]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = smf.mixedlm(f"bad_rate ~ {x}", df, groups=df["participant"], re_formula=f"~{x}")
        r = m.fit(method=t["mixedlm_method"], maxiter=t["mixedlm_maxiter"], reml=True)
    ok = bool(r.converged) and bool(np.isfinite(r.bse[x])) and np.isfinite(r.params[x])
    cov = np.asarray(r.cov_re)
    singular = bool(np.linalg.eigvalsh(cov).min() <= 1e-10) if cov.size else True
    lo, hi = r.conf_int(alpha=1 - t["ci"]).loc[x]
    re = {p: float(v[x]) for p, v in r.random_effects.items()}
    return r, dict(method="mixedlm", converged=bool(r.converged), ok=ok, singular_random_effects=singular,
                   slope_pp_per_hour=float(r.params[x] * 100), ci95_pp_per_hour=[float(lo * 100), float(hi * 100)],
                   p_value=float(r.pvalues[x]), person_slopes_mixed_pp_per_hour={p: float((r.params[x] + v) * 100) for p, v in re.items()},
                   warnings=sorted({str(i.message)[:120] for i in w})), ok


def person_ols(df, x):
    """Độ dốc OLS từng người (gộp mọi khối của người đó), điểm phần trăm / giờ; None nếu < 3 khối hoặc x không đổi."""
    out = {}
    for p, g in df.groupby("participant"):
        if len(g) >= 3 and g[x].nunique() >= 2:
            out[p] = float(np.polyfit(g[x].to_numpy(), g["bad_rate"].to_numpy(), 1)[0] * 100)
        else:
            out[p] = None
    return out


def fit_axis(df, x, P):
    """Một trục thời gian (cột x): mô hình chính + (nếu cần) GEE + GEE độ nhạy + độ dốc từng người."""
    res = dict(n_blocks=int(len(df)), n_persons=int(df["participant"].nunique()),
               n_sessions=int(df[["participant", "session_id"]].drop_duplicates().shape[0]), person_slopes_ols_pp_per_hour=person_ols(df, x))
    if res["n_persons"] < 2 or df[x].nunique() < 2:
        return dict(res, primary=None, note="không đủ người/khối để ước lượng")
    try:
        _, mixed, ok = _mixed(df, x, P)
    except Exception as e:  # noqa: BLE001
        mixed, ok = dict(method="mixedlm", error=str(e)[:200]), False
    res["mixedlm"] = mixed
    try:
        gee = _gee(df, x, P["trend"]["ci"])
    except Exception as e:  # noqa: BLE001
        gee = dict(method="gee_exchangeable_weighted", error=str(e)[:200])
    res["gee_weighted"] = gee
    if ok:
        res["primary"], res["primary_method"] = "mixedlm", "mixedlm"
    elif "slope_pp_per_hour" in gee:
        res["primary"], res["primary_method"] = "gee_weighted", "gee_weighted (MixedLM không hội tụ)"
    else:
        res["primary"], res["primary_method"] = None, "không ước lượng được"
    return res


def run_trend(analyses, P):
    df = to_frame(analyses)
    if df.empty:
        return dict(note="không có phiên đủ điều kiện"), df
    df["hours"] = (df["start"] + P["block"]["minutes"] / 2) / 60.0
    return dict(unit=P["trend"]["unit"], time_axis=fit_axis(df, "hours", P), sitting_axis=fit_axis(df, "sit_hours", P)), df


def curves(analyses, P):
    """`curves.json`: tỷ lệ BAD trung bình theo khối cho từng người (gộp các phiên đủ điều kiện, trọng số = phân loại được) + chung."""
    B = P["block"]["minutes"]

    def agg(rows):
        by = {}
        for r in rows:
            d = by.setdefault(r["block_idx"], dict(bad=0.0, cl=0.0, sess=set()))
            d["bad"] += r["bad_rate"] * r["classified_sec"]
            d["cl"] += r["classified_sec"]
            d["sess"].add(r["session_id"])
        return [dict(block_idx=k, start_min=k * B, mean_bad_rate=round(d["bad"] / d["cl"], 4), n_sessions=len(d["sess"]),
                     classified_sec=round(d["cl"], 1)) for k, d in sorted(by.items()) if d["cl"] > 0]
    ok = [r for a in analyses.values() if a["eligible"] for r in a["rows"] if not r["missing"]]
    people = sorted({r["participant"] for r in ok})
    return dict(version=1, block_min=B, unit="fraction (0..1) = Σ BAD / Σ phân loại được của khối", only="phiên đủ điều kiện, khối không thiếu",
                participants={p: dict(n_sessions=len({r["session_id"] for r in ok if r["participant"] == p}),
                                      blocks=agg([r for r in ok if r["participant"] == p])) for p in people},
                overall=dict(n_sessions=len({(r["participant"], r["session_id"]) for r in ok}), blocks=agg(ok)))
