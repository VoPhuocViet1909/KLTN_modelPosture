"""
Kiểm hợp lệ bước hiệu chỉnh: không để tư thế sai (gù lưng, cúi cổ, ngồi lệch, cử động nhiều) bị lấy làm chuẩn.

Dùng GÓC THÔ (chưa trừ baseline) từ posture_features.sequence_angles. Quy ước dấu (xem frame_angles):
  trunk = góc đoạn hông -> vai so với phương thẳng đứng, DƯƠNG khi nghiêng về phía mặt (gập ra trước), ÂM khi ngả ra sau.
  neck  = góc đoạn vai -> tai so với ĐƯỜNG THÂN (thô) = góc(vai->tai so với đứng) - trunk.
  đầu   = góc(vai->tai) so với PHƯƠNG THẲNG ĐỨNG = neck + trunk.  <- dùng cho kiểm "Cổ thẳng"

Vì sao "Cổ thẳng" dùng góc đầu so với phương thẳng đứng chứ không dùng neck thô hay điểm RULA tuyệt đối:
  (1) Điểm tai của MediaPipe luôn nằm trước vai nên khi ngồi chuẩn góc thô đã ~15-27° (không phải ~0°);
  (2) ngả lưng (trunk âm) làm neck = đầu - trunk tăng dù đầu vẫn thẳng. RULA lúc chạy dùng góc ĐÃ trừ baseline nên không
  gặp hai vấn đề này; chỉ bước kiểm hiệu chỉnh (không có baseline) mới cần ngưỡng tuyệt đối, và ngưỡng đó phải lấy từ dữ liệu.

NGUỒN SỐ LIỆU CỦA NGƯỠNG (tính ngày 18/10/2026, xem api_handover/desktop-app.md):
  * posture_model/frames_labeled.csv (58.461 khung, 3 người, 6 phiên) đã TRỪ baseline nên chỉ cho độ lệch so với chuẩn của chính người đó.
  * Baseline thô của từng phiên in trong output notebook ChayKaggle/notebook067dc83140.ipynb (cell 10): đầu so với đứng
    (neck+trunk) = 21,4 / 21,6 / 15,7 / 21,3 / 16,2 / 21,8 / 19,0; thân thô từ -15,6 đến -0,4 (trung vị -1,5).
  * Hai baseline ngồi chuẩn chạy thật: P01 (api_handover/sample_data/p01_events.jsonl) đầu 18,8°; lần chạy thật của chủ dự án
    18/10 (neck 26,8, trunk +0,9) đầu 27,7°.
  Góc thô khung GOOD tái dựng = (góc đã trừ baseline của khung GOOD) + baseline thô của đúng phiên (34.729 khung):
    đầu so với đứng: p50 20,8  p90 28,9  p95 31,2  p99 34,8  (chỉ 6 phiên dataset: p50 19,1  p90 23,5  p95 25,3  p99 27,9)
    thân thô:        p50 -3,2  p90 1,2   p95 3,5   p99 4,8   (GOOD thân > 10°: 0,02%; > 20°: 0%)
  => calib_max_neck_deg = 30 (p95 = 31,2 làm tròn xuống bội 5°; đủ rộng cho cả ngồi chuẩn 27,7° đã đo),
     calib_min_neck_deg = 0 (tai không ra sau vai; GOOD p0,1 = 4,5°).
  Thân ngả sau: khung GOOD thô < -15°: 10,6% (chủ yếu phiên P01_S01 tựa lưng, baseline -15,6°) nên ngưỡng -15° cũ loại nhầm;
  < -20°: 0,11%; còn khung LEAN_BACKWARD thô: < -20°: 89,9%  => calib_min_trunk_deg = -20.
  Thân ra trước: calib_max_trunk_deg = 10 (trước là 20 = điểm RULA 2). Khung GOOD thô > 10°: chỉ 0,02% (p99 thân thô GOOD 4,8°;
  baseline thân thô lớn nhất đã đo +0,9°), trong khi ở ngưỡng 20° có 73% khung SLOUCH và 38,4% khung LEAN_FORWARD lọt qua;
  ở 10° chỉ còn 20,5% SLOUCH và 1,4% LEAN_FORWARD lọt. Nới lại bằng calib_max_trunk_deg nếu người dùng thật hay bị loại nhầm.

Ngưỡng nằm trong app_config.json (khóa calib_*, chỉ ở máy, không đồng bộ từ máy chủ):
  calib_visible_ratio   0.8   cam hông thấy đủ tai-vai-hông ở >= 80% số khung
  calib_max_neck_deg    30    trung vị góc ĐẦU so với phương thẳng đứng tối đa
  calib_min_neck_deg    0     ... và tối thiểu (đầu ngửa ra sau)
  calib_max_trunk_deg   10    trung vị góc thân tối đa (gù / nghiêng ra trước)
  calib_min_trunk_deg   -20   trung vị góc thân tối thiểu (ngả sau)
  calib_still_deg       5.0   độ lệch chuẩn góc cổ / thân tối đa (ngồi yên)
  calib_front_ratio     0.5   cam laptop thấy đủ 2 vai ở >= 50% số khung
  distance_on_cm        (đã có) khoảng cách mắt-màn hình tối thiểu
Lý do trong thông điệp có mã (code) để rẽ nhánh, câu tiếng Việt để hiển thị; mỗi mục có `detail` (số đo + ngưỡng) để chẩn đoán.
"""
import numpy as np

from posture_features import FEATURES, choose_side, facing_sign, sequence_angles

MIN_VIS = 0.5               # visibility tối thiểu của tai/vai/hông (giống MIN_SHOULDER_VIS của cam trước)
MIN_FRAMES = 10             # ít hơn số khung hợp lệ này thì chưa đủ để đánh giá
WARMUP_SAMPLES = 8          # hiển thị kết quả trực tiếp khi đã có ít nhất chừng này mẫu cam hông
EPS_DEG = 0.05              # dung sai làm tròn khi so với ngưỡng (tránh 0,0000001° làm trượt)

DEFAULTS = {"calib_visible_ratio": 0.8, "calib_max_neck_deg": 30.0, "calib_min_neck_deg": 0.0,
            "calib_max_trunk_deg": 10.0, "calib_min_trunk_deg": -20.0, "calib_still_deg": 5.0,
            "calib_front_ratio": 0.5}
RANGES = {"calib_visible_ratio": (0.1, 1.0), "calib_max_neck_deg": (5.0, 90.0), "calib_min_neck_deg": (-45.0, 30.0),
          "calib_max_trunk_deg": (5.0, 60.0), "calib_min_trunk_deg": (-60.0, 0.0), "calib_still_deg": (0.5, 30.0),
          "calib_front_ratio": (0.1, 1.0)}

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
    for k, (lo, hi) in RANGES.items():
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

    checks: [{code, label, ok (True/False/None = chưa đánh giá được), message (câu tiếng Việt khi không đạt),
              value (số đo), detail (số đo + ngưỡng, để chẩn đoán)}]
    reasons: các mục ok=False -> [{code (mã lỗi), message}]. final=False (xem trực tiếp): thiếu dữ liệu -> ok=None, không bị tính là lỗi.
    """
    th = thresholds(cfg)
    out = {k: dict(code=k, label=CHECKS[k][0], ok=None, message="", value=None, detail="chưa đủ dữ liệu")
           for k in CHECKS}
    if not front_enabled:
        del out["shoulders"], out["distance"]

    def fail(key, msg, value, detail):
        out[key].update(ok=False, message=msg, value=value, detail=detail)

    def good(key, value, detail):
        out[key].update(ok=True, message="", value=value, detail=detail)

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
    d_vis = f"thấy đủ tai-vai-hông {ratio * 100:.0f}% khung ({vis}/{n_s}), cần ≥ {th['calib_visible_ratio'] * 100:.0f}% và ≥ {MIN_FRAMES} khung"
    if final or enough:
        if vis >= MIN_FRAMES and ratio >= th["calib_visible_ratio"]:
            good("side_visible", ratio, d_vis)
        elif final or n_s >= 2 * WARMUP_SAMPLES:
            fail("side_visible", "Camera hông không thấy đủ tai, vai và hông "
                 f"({ratio * 100:.0f}% số khung, cần ≥ {th['calib_visible_ratio'] * 100:.0f}%). "
                 "Ngồi vào khung hình của camera hông, nhìn rõ từ tai đến hông.", ratio, d_vis)
    # ---- lưng / cổ / ngồi yên (chỉ đánh giá khi đã thấy người đủ)
    if out["side_visible"]["ok"] is True:
        neck, trunk = raw[:, FEATURES.index("neck")], raw[:, FEATURES.index("trunk")]
        head = neck + trunk                                   # góc vai->tai so với phương thẳng đứng
        mn, mt, mh = float(np.median(neck)), float(np.median(trunk)), float(np.median(head))
        lo_t, hi_t = th["calib_min_trunk_deg"], th["calib_max_trunk_deg"]
        d_back = f"thân {mt:+.1f}° (cho phép {lo_t:+.0f}° … {hi_t:+.0f}°; + = nghiêng ra trước)"
        if lo_t - EPS_DEG <= mt <= hi_t + EPS_DEG:
            good("back", mt, d_back)
        elif mt < lo_t:
            fail("back", f"Lưng đang ngả ra sau ({_fmt(mt)}). Ngồi thẳng lưng, đừng dựa quá thấp.", mt, d_back)
        else:
            fail("back", f"Lưng đang gù hoặc nghiêng ra trước ({_fmt(mt)}). Ngồi thẳng lưng, tựa lưng vào ghế.", mt, d_back)
        lo_n, hi_n = th["calib_min_neck_deg"], th["calib_max_neck_deg"]
        d_neck = (f"đầu {mh:+.1f}° so với phương thẳng đứng (cho phép {lo_n:+.0f}° … {hi_n:+.0f}°; + = đầu ra trước vai); "
                  f"cổ so với thân {mn:+.1f}° (chỉ để tham khảo)")
        if lo_n - EPS_DEG <= mh <= hi_n + EPS_DEG:
            good("neck", mh, d_neck)
        elif mh < lo_n:
            fail("neck", f"Đầu đang ngửa ra sau ({_fmt(mh)}). Nhìn thẳng vào màn hình, hạ cằm một chút.", mh, d_neck)
        else:
            fail("neck", f"Đầu đang cúi hoặc chồm ra trước ({_fmt(mh)} so với phương thẳng đứng, tối đa {hi_n:+.0f}°). "
                 "Nhìn thẳng vào màn hình, kéo cằm vào, đưa đầu thẳng trên vai.", mh, d_neck)
        sn, st = float(np.std(neck)), float(np.std(trunk))
        d_still = f"dao động cổ {sn:.1f}°, thân {st:.1f}° (cho phép ≤ {th['calib_still_deg']:.0f}°)"
        if max(sn, st) <= th["calib_still_deg"]:
            good("still", max(sn, st), d_still)
        else:
            fail("still", f"Bạn cử động nhiều (dao động {max(sn, st):.0f}°, cần ≤ {th['calib_still_deg']:.0f}°). "
                 "Ngồi yên, đặt tay lên đùi hoặc bàn, không gõ phím.", max(sn, st), d_still)
    # ---- camera laptop
    if front_enabled:
        n_f = cal["n_f"]
        tilts = np.array(cal["tilt"], float)
        both = int(np.isfinite(tilts).sum())
        r = both / n_f if n_f else 0.0
        d_sh = f"thấy đủ hai vai {r * 100:.0f}% khung ({both}/{n_f}), cần ≥ {th['calib_front_ratio'] * 100:.0f}% và ≥ {MIN_FRAMES} khung"
        if final or n_f >= WARMUP_SAMPLES:
            if both >= MIN_FRAMES and r >= th["calib_front_ratio"]:
                good("shoulders", r, d_sh)
            elif final or n_f >= 2 * WARMUP_SAMPLES:
                fail("shoulders", f"Camera laptop không thấy đủ hai vai ({r * 100:.0f}% số khung, cần ≥ "
                     f"{th['calib_front_ratio'] * 100:.0f}%). Ngồi lùi ra hoặc chỉnh góc màn hình; "
                     "hoặc bấm \"Bỏ qua camera laptop\" để chạy không đo lệch vai.", r, d_sh)
        cm = estimate_distance_cm(ed, cal, width_px)
        on = float(cfg["distance_on_cm"])
        if cm is not None:
            d_dist = f"cách màn hình {cm:.0f} cm (cần ≥ {on:.0f} cm)"
            if cm >= on:
                good("distance", cm, d_dist)
            else:
                fail("distance", f"Bạn đang cách màn hình khoảng {cm:.0f} cm, gần hơn mức tối thiểu "
                     f"{on:.0f} cm. Lùi ra rồi hiệu chỉnh lại.", cm, d_dist)
        else:
            out["distance"]["detail"] = "chưa đo được khoảng cách (không chặn)"
    checks = list(out.values())
    reasons = [dict(code=CHECKS[c["code"]][1], message=c["message"]) for c in checks if c["ok"] is False]
    ok = not reasons and all(c["ok"] is True for c in checks if c["code"] != "distance")   # đo không được: không chặn
    return dict(ok=ok, checks=checks, reasons=reasons)


def describe(res):
    """Các dòng chẩn đoán (số đo + ngưỡng của từng mục), để in ra console / log khi hiệu chỉnh."""
    mark = {True: "ĐẠT", False: "KHÔNG ĐẠT", None: "chưa rõ"}
    return [f"[{mark[c['ok']]}] {c['label']}: {c['detail']}" for c in res["checks"]]
