"""Khối 10 phút, phiên đủ điều kiện, mức đầu buổi và onset (thời điểm xuống sức). Tham số đọc từ fatigue/protocol.json.

Định nghĩa (đã khóa):
- Khối k = phút [10k, 10k+9], chỉ lấy khối đủ 10 phút. bad_rate = Σ BAD / Σ phân loại được; khối thiếu khi Σ phân loại được < 50% * 10 * 60 s.
- Phiên đủ điều kiện: >= 60 phút, >= 4 khối không thiếu, và có mức đầu buổi.
- Mức đầu buổi = Σ BAD / Σ phân loại được của các khối không thiếu trong 20 phút đầu.
- Onset = phút bắt đầu của khối đầu tiên (từ khối sau baseline) mà bad_rate >= baseline + delta và giữ >= 2 khối liên tiếp (khối thiếu làm đứt
  chuỗi). Không có -> kiểm duyệt tại cuối khối đủ cuối cùng.
"""
import numpy as np

import common as C


def block_rows(s, P, Pf):
    """-> list dict một dòng cho mỗi khối đủ 10 phút của phiên s."""
    B = P["block"]["minutes"]
    need = P["block"]["min_classified_fraction"] * B * s.window_sec
    tab = C.FE.minute_table(s, Pf)
    cl, bad = s.classified, s.bad
    rows = []
    for k in range(s.n // B):
        sl = slice(k * B, (k + 1) * B)
        classified = float(cl[sl].sum())
        missing = classified < need or classified <= 0
        rows.append(dict(participant=s.participant, session_id=s.session_id, block_idx=k, block_start_min=k * B,
                         bad_rate=float("nan") if classified <= 0 else float(bad[sl].sum() / classified),
                         classified_sec=classified, missing=bool(missing),
                         sitting_end_min=float(tab["sitting"][(k + 1) * B - 1])))
    return rows


def baseline_level(rows, P):
    """Mức đầu buổi từ các khối không thiếu trong baseline.minutes phút đầu; None nếu không có khối nào."""
    B = P["block"]["minutes"]
    first = [r for r in rows if r["block_start_min"] < P["baseline"]["minutes"] and not r["missing"]]
    if not first:
        return None
    tot = sum(r["classified_sec"] for r in first)
    return float(sum(r["bad_rate"] * r["classified_sec"] for r in first) / tot)


def find_onset(rows, base, P):
    """Phút onset hoặc None. Chỉ xét khối từ sau baseline; cần onset.min_consecutive_blocks khối liên tiếp không thiếu và cao."""
    m, delta = P["onset"]["min_consecutive_blocks"], P["onset"]["delta"]
    start_block = P["baseline"]["minutes"] // P["block"]["minutes"]
    high = [(not r["missing"]) and r["bad_rate"] >= base + delta - 1e-12 for r in rows]
    for k in range(start_block, len(rows) - m + 1):
        if all(high[k:k + m]):
            return rows[k]["block_start_min"]
    return None


def analyse_session(s, P, Pf):
    """-> dict: rows, eligible, reason, baseline, onset (phút hoặc None), censored, censor_min, n_valid_blocks, n_min."""
    rows = block_rows(s, P, Pf)
    valid = sum(not r["missing"] for r in rows)
    base = baseline_level(rows, P)
    reason = None
    if s.n < P["eligible"]["min_session_min"]:
        reason = "phiên ngắn hơn min_session_min"
    elif valid < P["eligible"]["min_valid_blocks"]:
        reason = "ít khối không thiếu"
    elif base is None:
        reason = "không có mức đầu buổi"
    onset = find_onset(rows, base, P) if reason is None else None
    B = P["block"]["minutes"]
    return dict(participant=s.participant, session_id=s.session_id, rows=rows, eligible=reason is None, reason=reason,
                baseline=base, onset=onset, censored=reason is None and onset is None, censor_min=len(rows) * B,
                n_valid_blocks=valid, n_min=s.n)


def analyse_all(sessions, P, Pf):
    return {key: analyse_session(sessions[key], P, Pf) for key in sorted(sessions)}


def shuffle_minutes(sessions, P, seed):
    """Đối chứng thứ 5: xáo thứ tự PHÚT trong từng phiên (mọi cấu trúc thời gian, kể cả bên trong khối, bị phá)."""
    out = {}
    for i, key in enumerate(sorted(sessions)):
        s = sessions[key]
        out[key] = C.minute_permuted(s, np.random.default_rng([seed, i, 1]).permutation(s.n))
    return out


def shuffle_blocks(sessions, P, seed):
    """Đối chứng: xáo thứ tự các khối trong từng phiên (xu hướng theo thời gian bị phá, nội dung khối giữ nguyên)."""
    B = P["block"]["minutes"]
    out = {}
    for i, key in enumerate(sorted(sessions)):
        s = sessions[key]
        order = np.random.default_rng([seed, i]).permutation(s.n // B)
        out[key] = C.block_permuted(s, order, B)
    return out
