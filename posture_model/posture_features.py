"""
Đặc trưng tư thế + RULA nhóm B + công thức lệch vai — DÙNG CHUNG cho lúc train và lúc chạy realtime.

- Cam hông 90° (train + chạy thật): góc cổ / thân / cúi đầu -> RULA nhóm B (teacher) -> Transformer (student).
- Cam laptop chính diện (chỉ lúc chạy thật): công thức lệch vai, KHÔNG train.

Đầu vào mỗi khung: 33 landmark MediaPipe Pose 2D (toạ độ pixel x, y, visibility),
world landmark 3D chỉ dùng để chọn phía cơ thể gần camera.
"""
import math
import numpy as np

# chỉ số MediaPipe Pose: (trái, phải)
IDX = {"ear": (7, 8), "eye": (2, 5), "shoulder": (11, 12), "hip": (23, 24)}
NOSE = 0

FEATURES = ["neck", "trunk", "head_pitch", "vis_ear", "vis_shoulder", "vis_hip"]
CALIBRATED = ["neck", "trunk", "head_pitch"]      # trừ giá trị lúc ngồi chuẩn của từng người
ANGLE_SCALE = 30.0                                 # chia góc cho 30° trước khi vào model

# ================================================================ CAM HÔNG 90°
def choose_side(lm_seq, world_seq=None):
    """0 = trái, 1 = phải. Ưu tiên world z (nhỏ = gần camera), dự phòng bằng visibility."""
    if world_seq is not None and np.isfinite(world_seq).any():
        zl = np.nanmedian(world_seq[:, 11, 2] + world_seq[:, 23, 2])
        zr = np.nanmedian(world_seq[:, 12, 2] + world_seq[:, 24, 2])
        if np.isfinite(zl) and np.isfinite(zr):
            return 0 if zl < zr else 1
    vl = np.nanmean(lm_seq[:, [7, 11, 23], 2]); vr = np.nanmean(lm_seq[:, [8, 12, 24], 2])
    return 0 if vl >= vr else 1


def facing_sign(lm_seq, side):
    """+1 nếu người quay mặt sang phải khung hình, -1 nếu sang trái (mũi so với tai)."""
    d = np.nanmedian(lm_seq[:, NOSE, 0] - lm_seq[:, IDX["ear"][side], 0])
    return 1.0 if (np.isfinite(d) and d > 0) else -1.0


def _ang(v, f):
    """Góc (độ) của vector v so với phương thẳng đứng hướng LÊN, dương khi nghiêng về phía mặt."""
    return math.degrees(math.atan2(v[0] * f, -v[1]))


def frame_angles(p, side, f):
    """p: (33,3) pixel x,y,vis. Trả dict góc (độ) + visibility, None nếu thiếu tai/vai/hông."""
    g = lambda k: p[IDX[k][side], :2]
    ear, eye, sh, hip = g("ear"), g("eye"), g("shoulder"), g("hip")
    if not np.isfinite(np.concatenate([ear, sh, hip])).all():
        return None
    trunk = _ang(sh - hip, f)                       # thân so với phương đứng (+ = gập ra trước, − = ngả sau)
    neck = _ang(ear - sh, f) - trunk                # cổ so với đường thân (+ = gập)
    # cúi đầu: đường tai -> mắt so với phương ngang (+ = mắt thấp hơn tai = cúi)
    head_pitch = math.degrees(math.atan2(eye[1] - ear[1], (eye[0] - ear[0]) * f)) if np.isfinite(eye).all() else np.nan
    vis = lambda k: float(p[IDX[k][side], 2])
    return dict(neck=neck, trunk=trunk, head_pitch=head_pitch,
                vis_ear=vis("ear"), vis_shoulder=vis("shoulder"), vis_hip=vis("hip"))


def sequence_angles(lm_seq, side, f):
    """(T,33,3) -> (T, len(FEATURES)) góc thô (chưa hiệu chỉnh), NaN nếu thiếu."""
    out = np.full((len(lm_seq), len(FEATURES)), np.nan, np.float32)
    for t, p in enumerate(lm_seq):
        if not np.isfinite(p).any():
            continue
        a = frame_angles(p, side, f)
        if a is not None:
            out[t] = [a[k] for k in FEATURES]
    return out


def calibration_baseline(raw):
    """raw: (T,F) góc thô lúc ngồi chuẩn -> dict baseline cho các góc cần hiệu chỉnh."""
    return {k: float(np.nanmedian(raw[:, FEATURES.index(k)])) for k in CALIBRATED}


def apply_calibration(raw, base):
    x = raw.copy()
    for k in CALIBRATED:
        x[:, FEATURES.index(k)] -= base[k]
    return x


def to_model_input(cal):
    """Góc đã hiệu chỉnh -> mảng chuẩn hoá cho model (NaN -> 0, visibility giữ nguyên 0..1)."""
    x = cal.copy()
    for i, k in enumerate(FEATURES):
        if not k.startswith("vis_"):
            x[:, i] = x[:, i] / ANGLE_SCALE
    return np.nan_to_num(x, nan=0.0).astype(np.float32)

# ================================================================ RULA NHÓM B (teacher)
# McAtamney & Corlett (1993). Chỉ Cổ – Thân – Chân; bỏ nhóm A, điểm cơ, điểm lực.
# Side cam không thấy xoay / nghiêng sang bên -> các cờ điều chỉnh = 0. Chân mặc định = 1.
TABLE_B = {  # neck -> [T1L1, T1L2, T2L1, T2L2, ..., T6L1, T6L2]
    1: [1, 3, 2, 3, 3, 4, 5, 5, 6, 6, 7, 7], 2: [2, 3, 2, 3, 4, 5, 5, 5, 6, 7, 7, 7],
    3: [3, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7], 4: [5, 5, 5, 6, 6, 7, 7, 7, 7, 7, 8, 8],
    5: [7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8], 6: [8, 8, 8, 8, 8, 8, 8, 9, 9, 9, 9, 9],
}
BAD_SCORE = 3          # điểm nhóm B >= 3 -> BAD
NEUTRAL_TOL = 5.0      # thân: <= 5° so với lúc hiệu chỉnh vẫn coi là thẳng (1 điểm)
NECK_EXT_TOL = 15.0    # cổ chỉ tính "ngửa" (4 điểm) khi ngửa hơn lúc hiệu chỉnh > 15°
LEAN_BACK_TOL = 15.0   # luật bổ sung ngoài RULA: thân ngả sau > 15° -> BAD (LEAN_BACKWARD)
HEAD_FROM_PITCH = True # góc cổ = max(tai–vai so với thân, cúi mặt tai->mắt): bắt kiểu gù mà cúi mặt


def score_neck(a):
    if a < -NECK_EXT_TOL: return 4
    if a <= 10:           return 1
    if a <= 20:           return 2
    return 3


def score_trunk(a):
    if a <= NEUTRAL_TOL: return 1          # thẳng, hoặc ngả sau có tựa
    if a <= 20:          return 2
    if a <= 60:          return 3
    return 4


def group_b_score(neck, trunk, legs=1):
    """Góc cổ, thân (độ, đã hiệu chỉnh) -> điểm nhóm B (1..9), NaN nếu thiếu."""
    if not (np.isfinite(neck) and np.isfinite(trunk)):
        return np.nan
    return TABLE_B[score_neck(neck)][(score_trunk(trunk) - 1) * 2 + (legs - 1)]


def b_label(neck, trunk):
    """-> 0 = GOOD, 1 = BAD, NaN nếu thiếu."""
    b = group_b_score(neck, trunk)
    if not np.isfinite(b):
        return np.nan
    return int(b >= BAD_SCORE or trunk < -LEAN_BACK_TOL)


def rula_frame_label(cal_row, margin=2.0):
    """cal_row: 1 khung đặc trưng đã hiệu chỉnh. Trả (nhãn 0/1/NaN, ổn_định?).
    'Ổn định' = nhãn không đổi khi xê dịch cổ/thân ±margin độ (khung sát ngưỡng sẽ không ổn định)."""
    n, t, hp = (cal_row[FEATURES.index(k)] for k in ("neck", "trunk", "head_pitch"))
    if HEAD_FROM_PITCH and np.isfinite(hp) and np.isfinite(n):
        n = max(n, hp)
    lab = b_label(n, t)
    if not np.isfinite(lab):
        return np.nan, False
    stable = all(b_label(n + dn, t + dt) == lab for dn in (-margin, margin) for dt in (-margin, margin))
    return int(lab), stable

# ================================================================ CAM LAPTOP: LỆCH VAI (không train)
SHOULDER_TILT_ON = 3.5     # |lệch vai so với lúc hiệu chỉnh| > 3.5° -> lệch (clip P01 nghiêng chủ ý chỉ ~4–5°)
SHOULDER_TILT_OFF = 2.5    # < 2.5° mới coi là hết lệch (trễ, tránh bật/tắt liên tục); ngồi thẳng dao động ~±2°
MIN_SHOULDER_VIS = 0.5     # vai bị che / ra khỏi khung -> bỏ khung


def shoulder_tilt(p):
    """p: (33,3) pixel x,y,vis từ cam CHÍNH DIỆN. Góc (độ) của đường nối 2 vai so với phương ngang.
    Đường vai lấy từ vai bên trái ảnh -> vai bên phải ảnh, nên ảnh lật gương (selfie) vẫn đúng độ lớn.
    Dấu: + = vai bên phải ẢNH thấp hơn. Chỉ dùng |tilt − baseline| để cảnh báo."""
    L, R = p[11], p[12]
    if not (np.isfinite(L).all() and np.isfinite(R).all()) or min(L[2], R[2]) < MIN_SHOULDER_VIS:
        return np.nan
    dx, dy = R[0] - L[0], R[1] - L[1]
    if dx < 0:
        dx, dy = -dx, -dy
    if dx < 1e-6:
        return np.nan
    return math.degrees(math.atan2(dy, dx))


def sequence_shoulder_tilt(lm_seq):
    return np.array([shoulder_tilt(p) if np.isfinite(p).any() else np.nan for p in lm_seq], np.float32)
