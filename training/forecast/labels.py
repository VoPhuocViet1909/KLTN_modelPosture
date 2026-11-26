"""C1 – nhãn dự báo 5 phút tới (tham số đọc từ protocol.json, mục "label").

Mốc t hợp lệ khi phút t "chủ yếu GOOD" và đủ dữ liệu; y = 1 nếu BAD(t+1..t+H) >= bad_fraction * phân loại được(t+1..t+H).
Mốc bị bỏ (mỗi mốc một lý do, theo thứ tự kiểm): cuối phiên (thiếu H phút sau), phút t ít dữ liệu, phút t không chủ yếu GOOD,
phần thiếu của t+1..t+H quá lớn. Không cắt ngang phiên.
"""
from collections import Counter

REASONS = ("cuối phiên", "phút hiện tại ít dữ liệu", "phút hiện tại không chủ yếu GOOD", "tương lai thiếu dữ liệu")


def anchor_label(s, t, P):
    """-> (y hoặc None, lý do hoặc None) cho mốc t của phiên s."""
    L = P["label"]
    H = L["horizon_min"]
    if t + H > s.n - 1:
        return None, REASONS[0]
    cl, good = s.classified, s.good
    if cl[t] < L["anchor_min_classified_sec"]:
        return None, REASONS[1]
    if good[t] / cl[t] < L["anchor_min_good_fraction"]:
        return None, REASONS[2]
    sl = slice(t + 1, t + H + 1)
    classified = float(cl[sl].sum())
    missing = float((s.window_sec - cl[sl]).sum()) / (H * s.window_sec)
    if missing > L["max_missing_fraction"] or classified <= 0:
        return None, REASONS[3]
    return int(float(s.bad[sl].sum()) >= L["bad_fraction"] * classified), None


def build_anchors(s, P):
    """-> (list[(t, y)], Counter lý do bỏ)."""
    out, drop = [], Counter()
    for t in range(s.n):
        y, why = anchor_label(s, t, P)
        if why:
            drop[why] += 1
        else:
            out.append((t, y))
    return out, drop


def first_bad_minute_offset(s, t, P):
    """Số phút từ t tới phút đầu tiên trong t+1..t+H có BAD >= lead_bad_fraction * phân loại được; None nếu không có."""
    H, f = P["label"]["horizon_min"], P["reminder"]["lead_bad_fraction"]
    for k in range(1, H + 1):
        if t + k < s.n and s.classified[t + k] > 0 and s.bad[t + k] >= f * s.classified[t + k]:
            return k
    return None
