"""C2 – đặc trưng từ tối đa `history_min` phút gần nhất (t-H+1..t). CHỈ dùng phút <= t.

Mọi đại lượng tích lũy (thời gian ngồi liên tục, phút từ cảnh báo gần nhất) chỉ nhìn về quá khứ, nên đặc trưng tại t không đổi khi
sửa dữ liệu sau t (có test). Phút chưa quan sát được (phân loại được < min_observed_classified_sec, hoặc trước đầu phiên) được đánh dấu,
không nội suy: tỷ lệ BAD thiếu thay bằng trung bình các phút quan sát được trong cửa sổ (chỉ quá khứ), không có thì 0.
"""
import math

import numpy as np

import data as D

FLAT_NAMES = ([f"share_{c}" for c in D.CLASSES] + [f"bad_rate_m{k}" for k in range(9, -1, -1)] +
              ["bad_slope", "sitting_min", "since_alert_min", "minute_in_session", "hour_sin", "hour_cos", "missing_frac"])
SEQ_NAMES = ([f"share_{c}" for c in D.CLASSES] +
             ["bad_rate", "observed", "away_frac", "sitting_norm", "alert", "hour_sin", "hour_cos"])


def minute_table(s, P):
    """Mảng theo phút của một phiên (mỗi phần tử chỉ phụ thuộc phút <= t)."""
    F = P["features"]
    n = s.n
    cl = s.classified
    obs = cl >= F["min_observed_classified_sec"]
    with np.errstate(invalid="ignore", divide="ignore"):
        bad_rate = np.where(cl > 0, s.bad / np.where(cl > 0, cl, 1), np.nan)
        shares = np.where(cl[:, None] > 0, np.nan_to_num(s.cls, nan=0.0) / np.where(cl > 0, cl, 1)[:, None], 0.0)
    bad_rate = np.where(obs, bad_rate, np.nan)
    shares = np.where(obs[:, None], shares, 0.0)
    sitting = np.zeros(n)
    prev = 0.0
    for t in range(n):
        prev = 0.0 if s.away[t] >= F["away_reset_sec"] else prev + 1.0
        sitting[t] = prev
    since = np.zeros(n)
    last = None
    for t in range(n):
        if s.alerts[t] > 0:
            last = t
        since[t] = F["since_alert_cap_min"] if last is None else min(t - last, F["since_alert_cap_min"])
    hours = np.array([s.hour_of_day(t) for t in range(n)])
    return dict(obs=obs, bad_rate=bad_rate, shares=shares, away_frac=s.away / s.window_sec, sitting=sitting, since=since,
                alert=(s.alerts > 0).astype(float), sin=np.sin(2 * math.pi * hours / 24), cos=np.cos(2 * math.pi * hours / 24),
                classified=cl, raw=s.cls)


def _window_idx(t, Hh):
    return [k for k in range(t - Hh + 1, t + 1)]


def flat_features(tab, t, P):
    """Vector đặc trưng phẳng (len(FLAT_NAMES)) tại mốc t."""
    F = P["features"]
    Hh = F["history_min"]
    idx = _window_idx(t, Hh)
    valid = [k for k in idx if k >= 0]
    obs_idx = [k for k in valid if tab["obs"][k]]
    # tỷ trọng từng lớp trên tổng phân loại được của các phút quan sát được
    if obs_idx:
        raw = np.nan_to_num(tab["raw"][obs_idx], nan=0.0).sum(0)
        tot = raw.sum()
        share = raw / tot if tot > 0 else np.zeros(6)
    else:
        share = np.zeros(6)
    rates = np.array([tab["bad_rate"][k] if k >= 0 else np.nan for k in idx])
    fill = float(np.nanmean(rates)) if np.isfinite(rates).any() else 0.0
    rates_f = np.where(np.isfinite(rates), rates, fill)
    ok = np.isfinite(rates)
    if ok.sum() >= F["slope_min_points"]:
        x = np.arange(Hh, dtype=float)[ok]
        slope = float(np.polyfit(x, rates[ok], 1)[0])
    else:
        slope = 0.0
    missing = 1.0 - len(obs_idx) / Hh
    return np.concatenate([share, rates_f, [slope, tab["sitting"][t], tab["since"][t], float(t),
                                            tab["sin"][t], tab["cos"][t], missing]])


def seq_features(tab, t, P):
    """(history_min, len(SEQ_NAMES)) chuỗi theo phút cho GRU; bước trước đầu phiên = 0 hết, observed = 0."""
    Hh = P["features"]["history_min"]
    idx = _window_idx(t, Hh)
    valid = [k for k in idx if k >= 0 and tab["obs"][k]]
    rates = np.array([tab["bad_rate"][k] for k in valid])
    fill = float(rates.mean()) if len(rates) else 0.0
    out = np.zeros((Hh, len(SEQ_NAMES)))
    for i, k in enumerate(idx):
        if k < 0:
            continue
        o = bool(tab["obs"][k])
        out[i] = [*tab["shares"][k], tab["bad_rate"][k] if o else fill, float(o), tab["away_frac"][k],
                  tab["sitting"][k] / 60.0, tab["alert"][k], tab["sin"][k], tab["cos"][k]]
    return out


def state_of_minute(tab, t, edges):
    """Trạng thái cho Markov/mốc (a): chỉ số nhóm tỷ lệ BAD của phút t; len(edges)+1 = X (không phân loại đủ)."""
    if not tab["obs"][t]:
        return len(edges) + 1
    return int(np.searchsorted(edges, tab["bad_rate"][t], side="right"))
