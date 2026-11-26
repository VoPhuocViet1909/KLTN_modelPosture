"""Phần dùng chung của pipeline đánh giá A2/A3.

Nguyên tắc: KHÔNG chép code của app. Mọi hàm đặc trưng, nhãn teacher, chọn lớp, bộ lọc median + debounce, ngưỡng
đều được import từ `posture_model/`. Chỉ hai thứ nằm ở đây vì app không có sẵn: (1) dựng nhãn lớp phụ theo từng khung
(`frame_class`, đúng như notebook v4) và (2) cắt cửa sổ/ghi cache landmark ở chế độ ngoại tuyến.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PM = REPO / "posture_model"
if str(PM) not in sys.path:
    sys.path.append(str(PM))   # cuối đường dẫn: posture_model/metrics.py của app không được che metrics.py của A3

import posture_features as pf  # noqa: E402  (của app)
from app_config import DEFAULTS as APP_DEFAULTS  # noqa: E402
from quality import ANGLE_KEYS, angles_ok  # noqa: E402

MODEL_CFG_PATH = PM / "posture_config.json"
ONNX_PATH = PM / "posture_transformer.onnx"
POSE_TASK_PATH = PM / "pose_landmarker_full.task"
DEFAULT_RF_PATH = HERE / "models" / "posture_rf_v4.joblib"

FEATURES = pf.FEATURES
TARGET_FPS = 10
WIN = 20
STRIDE_TRAIN = 5            # notebook: bước 0,5 s khi dựng tập train
SEGMENT_SEC = 2.0
CAL_START, CAL_SEC = 3.0, 15.0     # hiệu chỉnh = giây 3–18 của clip CALIBRATION
MARGIN = 3.0
MIN_VALID, MIN_VIS_HIP = 0.8, 0.3  # luật loại cửa sổ của notebook (MIN_PURE/MIN_STABLE/CLS_MIN_PURE đọc ở build)


def load_model_cfg():
    with open(MODEL_CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lib_versions():
    import platform
    out = {"python": platform.python_version(), "numpy": np.__version__}
    for name in ("sklearn", "mediapipe", "onnxruntime", "joblib", "cv2"):
        try:
            out[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


# ---------------------------------------------------------------- nhãn lớp phụ (đúng notebook v4, ô "Phần 4")
def frame_class(row, lab, classes, rule):
    """Lớp phụ của 1 khung từ góc đã hiệu chỉnh `row` và nhãn teacher `lab` (0/1/NaN). -1 = không xác định.
    Ngưỡng lấy từ `rule` = posture_config["class_rule"] và hằng số của posture_features."""
    if not np.isfinite(lab):
        return -1
    if lab == 0:
        return 0
    iN, iT, iH = (FEATURES.index(k) for k in ("neck", "trunk", "head_pitch"))
    n, t, hp = row[iN], row[iT], row[iH]
    if pf.HEAD_FROM_PITCH and np.isfinite(hp):
        n = max(n, hp)
    flex = rule["flex_deg"]
    if t < -rule["lean_back_tol"]:
        return classes.index("LEAN_BACKWARD")
    if t > flex and n > flex:
        return classes.index("SLOUCH")
    if t > flex:
        return classes.index("LEAN_FORWARD")
    if n > flex:
        return classes.index("FORWARD_HEAD")
    if n < -rule["neck_ext_tol"]:
        return classes.index("NECK_EXTENSION")
    return -1


def teacher_frames(cal, classes, rule):
    """cal: (T,F) góc đã hiệu chỉnh -> (lab, stable, cls) mảng theo khung, dùng rula_frame_label của app."""
    labs = [pf.rula_frame_label(r) for r in cal]
    lab = np.array([a for a, _ in labs], float)
    stab = np.array([b for _, b in labs], bool)
    cls = np.array([frame_class(r, a, classes, rule) for r, a in zip(cal, lab)], int)
    return lab, stab, cls


def win_stats(xw):
    """24 thống kê mean/std/min/max của 6 đặc trưng, theo thứ tự notebook. xw: (N,T,F) hoặc (T,F)."""
    xw = np.asarray(xw)
    if xw.ndim == 2:
        xw = xw[None]
    return np.concatenate([xw.mean(1), xw.std(1), xw.min(1), xw.max(1)], 1)


# ---------------------------------------------------------------- landmark ngoại tuyến (có cache)
def extract_landmarks(video, cache_dir, task=POSE_TASK_PATH, fps_target=TARGET_FPS, tag=None):
    """Landmark ~10 fps trên ảnh thu nhỏ ½ (như notebook v4), dùng PoseDetector của app. Cache .npz theo tên + kích thước file.
    Trả dict(lm (T,33,3) pixel gốc, world (T,33,3), t (T,), fps, wh)."""
    video = str(video)
    st = os.stat(video)
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", tag or Path(video).stem) + f"_{st.st_size}"
    cache = Path(cache_dir) / f"{key}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        return {k: z[k] for k in z.files}
    import cv2
    from realtime_posture import PoseDetector   # của app
    det = PoseDetector(str(task))
    if det.mode != "tasks":
        raise RuntimeError("PoseDetector rơi về mp.solutions: không cùng chế độ với notebook, dừng.")
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(fps / fps_target))
    L, W, T = [], [], []
    i, w, h = -1, 0, 0
    while cap.grab():
        i += 1
        if i % step:
            continue
        ok, fr = cap.retrieve()
        if not ok:
            break
        h, w = fr.shape[:2]
        sm = cv2.resize(fr, (w // 2, h // 2))
        lm, wl = det(sm, int(i * 1000 / fps))
        if lm is None:
            L.append(np.full((33, 3), np.nan, np.float32))
            W.append(np.full((33, 3), np.nan, np.float32))
        else:
            lm = lm.copy()
            lm[:, 0] *= w / sm.shape[1]
            lm[:, 1] *= h / sm.shape[0]
            L.append(lm)
            W.append(wl)
        T.append(i / fps)
    cap.release()
    out = dict(lm=np.array(L, np.float32).reshape(-1, 33, 3), world=np.array(W, np.float32).reshape(-1, 33, 3),
               t=np.array(T, float), fps=np.array(fps), wh=np.array([w, h]))
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **out)
    return out
