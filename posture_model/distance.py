"""
Ước lượng khoảng cách mắt – màn hình từ CAM LAPTOP (chính diện), theo mô hình camera lỗ kim:

    khoảng cách (mm) = tiêu cự (px) × kích thước thật (mm) / kích thước trên ảnh (px)

Cách 1 (chính): MediaPipe Face Landmarker có 10 điểm mống mắt (468–477).
    Đường kính mống mắt người trưởng thành gần như không đổi: ~11.7 mm (ít phụ thuộc người).
Cách 2 (dự phòng, khi không tải được model mặt): khoảng cách 2 mắt (điểm 2 và 5 của Pose), ~63 mm.
    Kém chính xác hơn (phụ thuộc người, giảm khi quay đầu).

Tiêu cự:
    - Có hiệu chỉnh (calib_distance_cm, ví dụ ngồi đúng 50 cm lúc hiệu chỉnh): f = d × px / kích_thước_thật.
    - Không hiệu chỉnh: f = W / (2·tan(HFOV/2)), HFOV mặc định 63° (webcam laptop thường 60–70°).
"""
import math
import os
import urllib.request

import cv2
import numpy as np

FACE_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
            "face_landmarker/float16/latest/face_landmarker.task")
IRIS_MM = 11.7
IPD_MM = 63.0
# viền mống mắt: (phải-ảnh, trên, trái-ảnh, dưới) cho từng mắt
IRIS_RINGS = ((469, 470, 471, 472), (474, 475, 476, 477))


class EyeDistance:
    def __init__(self, task_path, hfov_deg=63.0, use_face=True):
        self.hfov_deg = hfov_deg
        self.focal = None          # px, có sau hiệu chỉnh
        self.kind = None           # "iris" | "ipd"
        self.det = None
        self.last_ts = -1
        if use_face:
            try:
                import mediapipe as mp
                from mediapipe.tasks import python as mpt
                from mediapipe.tasks.python import vision
                if not os.path.exists(task_path):
                    print("Đang tải face_landmarker.task ...")
                    urllib.request.urlretrieve(FACE_URL, task_path)
                opts = vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=task_path),
                                                    running_mode=vision.RunningMode.VIDEO, num_faces=1)
                self.det = vision.FaceLandmarker.create_from_options(opts)
                self.mp = mp
            except Exception as e:
                print("Không dùng được Face Landmarker (", e, ") -> đo bằng khoảng cách 2 mắt của Pose")
                self.det = None

    # ------------------------------------------------------------------ đo kích thước trên ảnh
    def iris_px(self, frame_bgr, ts_ms):
        """Đường kính mống mắt (px), NaN nếu không thấy mặt. Lấy mắt lớn hơn (mắt gần / ít bị quay hơn)."""
        if self.det is None or frame_bgr is None:
            return np.nan
        h, w = frame_bgr.shape[:2]
        ts_ms = max(int(ts_ms), self.last_ts + 1)
        self.last_ts = ts_ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        r = self.det.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), ts_ms)
        if not r.face_landmarks or len(r.face_landmarks[0]) < 478:
            return np.nan
        lm = r.face_landmarks[0]
        P = lambda i: np.array([lm[i].x * w, lm[i].y * h])
        sizes = []
        for a, b, c, d in IRIS_RINGS:
            horiz = np.linalg.norm(P(a) - P(c))
            vert = np.linalg.norm(P(b) - P(d))
            sizes.append((horiz + vert) / 2)
        return float(max(sizes))

    @staticmethod
    def ipd_px(pose_L, min_vis=0.5):
        """Khoảng cách 2 mắt (px) từ landmark Pose (33,3) của cam chính diện."""
        if pose_L is None:
            return np.nan
        l, r = pose_L[2], pose_L[5]
        if min(l[2], r[2]) < min_vis:
            return np.nan
        return float(np.hypot(*(r[:2] - l[:2])))

    def measure(self, frame_bgr, ts_ms, pose_L=None):
        """-> (kích thước px, loại). Ưu tiên mống mắt."""
        px = self.iris_px(frame_bgr, ts_ms)
        if np.isfinite(px) and px > 1:
            return px, "iris"
        px = self.ipd_px(pose_L)
        if np.isfinite(px) and px > 1:
            return px, "ipd"
        return np.nan, None

    # ------------------------------------------------------------------ đổi sang cm
    def default_focal(self, width_px):
        return width_px / (2 * math.tan(math.radians(self.hfov_deg) / 2))

    def calibrate(self, px_samples, kinds, known_cm=None):
        """Gọi sau giai đoạn hiệu chỉnh. Nếu biết khoảng cách thật lúc hiệu chỉnh thì tính tiêu cự."""
        px = np.array([p for p, k in zip(px_samples, kinds) if k is not None and np.isfinite(p)], float)
        ks = [k for k in kinds if k]
        if len(px) < 5:
            return None
        self.kind = max(set(ks), key=ks.count)
        med = float(np.median([p for p, k in zip(px_samples, kinds) if k == self.kind]))
        if known_cm:
            self.focal = known_cm * 10 * med / (IRIS_MM if self.kind == "iris" else IPD_MM)
        return med

    def to_cm(self, px, kind, width_px):
        if not (np.isfinite(px) and px > 1) or kind is None:
            return np.nan
        f = self.focal if self.focal else self.default_focal(width_px)
        real = IRIS_MM if kind == "iris" else IPD_MM
        return f * real / px / 10.0
