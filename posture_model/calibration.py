"""
Kiểm hợp lệ bước hiệu chỉnh: không để tư thế sai (gù lưng, cúi cổ, ngồi lệch, cử động nhiều) bị lấy làm chuẩn.

Dùng GÓC THÔ (chưa trừ baseline) từ posture_features.sequence_angles. Quy ước dấu (xem frame_angles):
  trunk = góc đoạn hông -> vai so với phương thẳng đứng, DƯƠNG khi nghiêng về phía mặt (gập ra trước), ÂM khi ngả ra sau.
  neck  = góc đoạn vai -> tai so với đường thân, DƯƠNG khi cổ gập ra trước (cúi), ÂM khi ngửa.
Điểm RULA nhóm B dùng làm teacher cho model (score_neck, score_trunk): điểm 1 = thẳng, 2 = ≤ 20°, 3+ = sai.
Cổ ngửa quá 15° (điểm 4) và thân ngả sau quá 15° (LEAN_BACK_TOL, luật bổ sung của teacher) cũng không được coi là thẳng.

Ngưỡng nằm trong app_config.json (khóa calib_*, chỉ ở máy, không đồng bộ từ máy chủ):
  calib_visible_ratio   0.8  cam hông thấy đủ tai-vai-hông ở ≥ 80% số khung
  calib_max_score       2    điểm RULA tối đa cho trung vị góc cổ và góc thân
  calib_still_deg       5.0  độ lệch chuẩn góc cổ / thân tối đa (ngồi yên)
  calib_front_ratio     0.5  cam laptop thấy đủ 2 vai ở ≥ 50% số khung
  distance_on_cm        (đã có) khoảng cách mắt-màn hình tối thiểu
Lý do trong thông điệp có mã (code) để rẽ nhánh, câu tiếng Việt để hiển thị.
"""
import math

import numpy as np

from posture_features import (FEATURES, LEAN_BACK_TOL, choose_side, facing_sign, score_neck, score_trunk,
                              sequence_angles)

MIN_VIS = 0.5               # visibility tối thiểu của tai/vai/hông (giống MIN_SHOULDER_VIS của cam trước)
MIN_FRAMES = 10             # ít hơn số khung hợp lệ này thì chưa đủ để đánh giá
WARMUP_SAMPLES = 8          # hiển thị kết quả trực tiếp khi đã có ít nhất chừng này mẫu cam hông

DEFAULTS = {"calib_visible_ratio": 0.8, "calib_max_score": 2, "calib_still_deg": 5.0, "calib_front_ratio": 0.5}

# mã -> (nhãn ngắn trong danh sách kiểm tra, mã lỗi khi không đạt)
CHECKS = {
    "side_visible": ("Thấy bạn ở camera hông", "SIDE_NOT_VISIBLE"),
    "back": ("Lưng thẳng", "BACK_NOT_STRAIGHT"),
    "neck": ("Cổ thẳng", "NECK_NOT_STRAIGHT"),
    "still": ("Ngồi yên", "MOVING_TOO_MUCH"),
    "shoulders": ("Thấy hai vai (camera laptop)", "SHOULDERS_NOT_VISIBLE"),
    "distance": ("Khoảng cách tới màn hình", "TOO_CLOSE"),
}


def thresholds(cfg):
    """Ngưỡng từ cấu hình; giá trị thiếu/sai kiểu/ngoài khoảng thì dùng mặc định."""
    t = dict(DEFAULTS)
    for k, (lo, hi) in {"calib_visible_ratio": (0.1, 1.0), "calib_max_score": (1, 4), "calib_still_deg": (0.5, 30),
                        "calib_front_ratio": (0.1, 1.0)}.items():
        try:
            v = cfg[k]
            if v is not None and not isinstance(v, bool) and lo <= float(v) <= hi:
                t[k] = float(v)
        except (KeyError, TypeError, ValueError):
            pass
    return t


def new_samples():
    """Bộ nhớ mẫu của một lượt hiệu chỉnh. n_s / n_f = số lần ĐÃ lấy mẫu cam hông / cam laptop (kể cả khung không thấy người)."""
    return dict(L=[], W=[], tilt=[], dpx=[], dkind=[], t0=None, n_s=0, n_f=0)


def _fmt(deg):
    return f"{deg:+.0f}°"


def estimate_distance_cm(ed, cal, width_px):
    """Khoảng cách mắt-màn hình ước lượng (cm) từ trung vị kích thước trên ảnh; None nếu chưa đo được. Không đổi trạng thái ed."""
    pairs = [(p, k) for p, k in zip(cal["dpx"], cal["dkind"]) if k is not None and np.isfinite(p)]
    if ed is None or len(pairs) < 5:
        return None
    kinds = [k for _, k in pairs]
    kind = max(set(kinds), key=kinds.count)
    cm = ed.to_cm(float(np.median([p for p, k in pairs if k == kind])), kind, width_px)
    return float(cm) if np.isfinite(cm) else None


def evaluate(cal, cfg, front_enabled=False, ed=None, width_px=640, final=True):
    """Đánh giá mẫu hiệu chỉnh. Trả {'ok': bool, 'checks': [...], 'reasons': [...]}.

    checks: [{code, label, ok (True/False/None = chưa đánh giá được), message (câu tiếng Việt khi không đạt)}]
    reasons: các mục ok=False -> [{code (mã lỗi), message}]. final=False (xem trực tiếp): thiếu dữ liệu -> ok=None, không bị tính là lỗi.
    """
    th = thresholds(cfg)
    out = {k: dict(code=k, label=CHECKS[k][0], ok=None, message="", value=None) for k in CHECKS}
    if not front_enabled:
        del out["shoulders"], out["distance"]

    def fail(key, msg, value=None):
        out[key].update(ok=False, message=msg, value=value)

    def good(key, value=None):
        out[key].update(ok=True, message="", value=value)

    # ---- camera hông: thấy đủ tai-vai-hông
    n_s, L = cal["n_s"], cal["L"]
    raw, vis = None, 0
    if len(L) >= 1:
        Lc, Wc = np.stack(L), np.stack(cal["W"])
        side = choose_side(Lc, Wc)
        raw = sequence_angles(Lc, side, facing_sign(Lc, side))
        i = {k: FEATURES.index(k) for k in FEATURES}
        seen = (np.isfinite(raw[:, i["neck"]]) & np.isfinite(raw[:, i["trunk"]])
                & (np.nan_to_num(raw[:, [i["vis_ear"], i["vis_shoulder"], i["vis_hip"]]], nan=0).min(axis=1) >= MIN_VIS))
        vis = int(seen.sum())
        raw = raw[seen]
    ratio = vis / n_s if n_s else 0.0
    enough = n_s >= WARMUP_SAMPLES
    if final or enough:
        if vis >= MIN_FRAMES and ratio >= th["calib_visible_ratio"]:
            good("side_visible", ratio)
        elif final or n_s >= 2 * WARMUP_SAMPLES:
            fail("side_visible", "Camera hông không thấy đủ tai, vai và hông "
                 f"({ratio * 100:.0f}% số khung, cần ≥ {th['calib_visible_ratio'] * 100:.0f}%). "
                 "Ngồi vào khung hình của camera hông, nhìn rõ từ tai đến hông.", ratio)
    # ---- lưng / cổ / ngồi yên (chỉ đánh giá khi đã thấy người đủ)
    if out["side_visible"]["ok"] is True:
        neck, trunk = raw[:, FEATURES.index("neck")], raw[:, FEATURES.index("trunk")]
        mn, mt = float(np.median(neck)), float(np.median(trunk))
        mx = th["calib_max_score"]
        if score_trunk(mt) <= mx and mt >= -LEAN_BACK_TOL:
            good("back", mt)
        elif mt < -LEAN_BACK_TOL:
            fail("back", f"Lưng đang ngả ra sau ({_fmt(mt)}). Ngồi thẳng lưng, đừng dựa quá thấp.", mt)
        else:
            fail("back", f"Lưng đang gù hoặc nghiêng ra trước ({_fmt(mt)}). Ngồi thẳng lưng, tựa lưng vào ghế.", mt)
        if score_neck(mn) <= mx:
            good("neck", mn)
        elif mn < 0:
            fail("neck", f"Cổ đang ngửa ra sau ({_fmt(mn)}). Nhìn thẳng vào màn hình, hạ cằm một chút.", mn)
        else:
            fail("neck", f"Cổ đang cúi ({_fmt(mn)}). Nhìn thẳng vào màn hình, kéo cằm vào, đưa đầu thẳng trên vai.", mn)
        sn, st = float(np.std(neck)), float(np.std(trunk))
        if max(sn, st) <= th["calib_still_deg"]:
            good("still", max(sn, st))
        else:
            fail("still", f"Bạn cử động nhiều (dao động {max(sn, st):.0f}°, cần ≤ {th['calib_still_deg']:.0f}°). "
                 "Ngồi yên, đặt tay lên đùi hoặc bàn, không gõ phím.", max(sn, st))
    # ---- camera laptop
    if front_enabled:
        n_f = cal["n_f"]
        tilts = np.array(cal["tilt"], float)
        both = int(np.isfinite(tilts).sum())
        r = both / n_f if n_f else 0.0
        if final or n_f >= WARMUP_SAMPLES:
            if both >= MIN_FRAMES and r >= th["calib_front_ratio"]:
                good("shoulders", r)
            elif final or n_f >= 2 * WARMUP_SAMPLES:
                fail("shoulders", f"Camera laptop không thấy đủ hai vai ({r * 100:.0f}% số khung, cần ≥ "
                     f"{th['calib_front_ratio'] * 100:.0f}%). Ngồi lùi ra hoặc chỉnh góc màn hình; "
                     "hoặc bấm \"Bỏ qua camera laptop\" để chạy không đo lệch vai.", r)
        cm = estimate_distance_cm(ed, cal, width_px)
        if cm is not None:
            if cm >= float(cfg["distance_on_cm"]):
                good("distance", cm)
            else:
                fail("distance", f"Bạn đang cách màn hình khoảng {cm:.0f} cm, gần hơn mức tối thiểu "
                     f"{float(cfg['distance_on_cm']):.0f} cm. Lùi ra rồi hiệu chỉnh lại.", cm)
        # đo không được (ok=None) -> không chặn: "nếu đo được"
    checks = list(out.values())
    reasons = [dict(code=CHECKS[c["code"]][1], message=c["message"]) for c in checks if c["ok"] is False]
    if final:
        required = [c for c in checks if c["code"] != "distance"]
        ok = not reasons and all(c["ok"] is True for c in required)
    else:
        ok = not reasons and all(c["ok"] is True for c in checks if c["code"] != "distance")
    return dict(ok=ok, checks=checks, reasons=reasons)
