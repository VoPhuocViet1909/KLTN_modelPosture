"""Phân tích sống sót tự viết (không thêm thư viện): Kaplan–Meier, C-index Harrell, phân bố onset theo người (D2)."""
import numpy as np


def kaplan_meier(times, events):
    """times: thời điểm (phút) onset hoặc kiểm duyệt; events: True nếu là onset. -> dict(steps=[(t, S, n_risk, n_event)], median, n, n_events).
    Median = thời điểm đầu tiên S <= 0.5, None nếu đường cong không xuống tới 0,5 (hơn nửa số phiên bị kiểm duyệt/không có onset)."""
    t = np.asarray(times, float)
    e = np.asarray(events, bool)
    steps, S = [], 1.0
    for u in np.unique(t[e]):
        n_risk = int((t >= u).sum())
        d = int(((t == u) & e).sum())
        S *= 1 - d / n_risk
        steps.append((float(u), float(S), n_risk, d))
    med = next((u for u, s, _, _ in steps if s <= 0.5 + 1e-12), None)
    return dict(steps=steps, median=med, n=int(len(t)), n_events=int(e.sum()), censor_times=[float(x) for x in np.sort(t[~e])])


def c_index(times, events, risk):
    """Harrell C. risk càng cao = dự đoán onset càng sớm. Cặp so sánh được (i, j): i có onset và T_i < T_j, hoặc T_i = T_j với j bị kiểm duyệt
    (kiểm duyệt xảy ra sau onset cùng thời điểm). Đồng điểm risk = 0,5. NaN nếu không có cặp nào."""
    t, e, r = (np.asarray(x, float) for x in (times, events, risk))
    num = den = 0.0
    for i in range(len(t)):
        if not e[i]:
            continue
        for j in range(len(t)):
            if i == j or not (t[i] < t[j] or (t[i] == t[j] and not e[j])):
                continue
            den += 1
            num += 1.0 if r[i] > r[j] else 0.5 if r[i] == r[j] else 0.0
    return float(num / den) if den else float("nan")


def onset_distribution(analyses):
    """D2: số phiên có onset/kiểm duyệt, trung vị + IQR onset theo người, KM gộp. Onset là mức nhóm/người, không phải chẩn đoán."""
    el = [a for a in analyses.values() if a["eligible"]]
    people = sorted({a["participant"] for a in el})
    per = {}
    for p in people:
        mine = [a for a in el if a["participant"] == p]
        on = [a["onset"] for a in mine if a["onset"] is not None]
        q = (np.percentile(on, [25, 50, 75]).tolist() if on else [None, None, None])
        per[p] = dict(n_sessions=len(mine), n_onset=len(on), n_censored=len(mine) - len(on), onsets_min=sorted(on),
                      q25=q[0], median=q[1], q75=q[2], iqr=None if not on else q[2] - q[0])
    t = [a["onset"] if a["onset"] is not None else a["censor_min"] for a in el]
    e = [a["onset"] is not None for a in el]
    km = kaplan_meier(t, e) if el else None
    meds = [d["median"] for d in per.values() if d["median"] is not None]
    return dict(n_eligible=len(el), n_onset=int(sum(e)), n_censored=int(len(e) - sum(e)), per_person=per, km=km,
                person_median_summary=None if not meds else dict(
                    n_persons=len(meds), median=float(np.median(meds)), q25=float(np.percentile(meds, 25)),
                    q75=float(np.percentile(meds, 75))),
                note="onset là mức nhóm/người của dữ liệu này, không phải chẩn đoán xuống sức của từng người")
