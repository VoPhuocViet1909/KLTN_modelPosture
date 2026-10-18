"""Dữ liệu giả cho kiểm thử lõi mà không cần camera/người: video trắng + PoseDetector trả landmark tổng hợp."""
import json
import os

import cv2
import numpy as np


def make_blank_video(path, seconds=30, fps=30, size=(320, 240)):
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    for _ in range(int(seconds * fps)):
        w.write(np.full((size[1], size[0], 3), 40, np.uint8))
    w.release()


def side_landmarks(ear_dx, trunk_dx=0.0):
    """Cam hông, người quay mặt sang phải. ear_dx = tai lệch ra trước vai (px; 0 = cổ thẳng, 29 ~ 30 độ),
    trunk_dx = vai lệch ra trước hông (px; 0 = lưng thẳng, 36 ~ 20 độ, 58 ~ 30 độ)."""
    L = np.zeros((33, 3), np.float32)
    W = np.zeros((33, 3), np.float32)
    for i in (11, 23, 7):          # nửa người trái (gần camera)
        W[i, 2] = -0.5
    for i in (12, 24, 8):
        W[i, 2] = 0.5
    sx = 150 + trunk_dx
    L[11] = (sx, 150, 1)
    L[12] = (sx, 150, 0.2)
    L[23] = (150, 250, 1)
    L[24] = (150, 250, 0.2)
    # tai: cổ nghiêng ear_dx/50 so với thân (góc tuyệt đối = góc thân + góc cổ), nên ear_dx đo đúng góc cổ tương đối
    th = np.arctan2(trunk_dx, 100.0) + np.arctan2(ear_dx, 50.0)
    r = float(np.hypot(ear_dx, 50.0))
    ex, ey = sx + r * np.sin(th), 150 - r * np.cos(th)
    L[7] = (ex, ey, 1)
    L[8] = (ex, ey, 0.2)
    L[2] = (ex + 10, ey, 1)
    L[5] = (ex + 10, ey, 0.2)
    L[0] = (ex + 25, ey + 5, 1)
    return L, W


class FakePoseDetector:
    """schedule: list (đến giây, ear_dx[, trunk_dx]) hoặc ear_dx = None = không thấy người. Tra theo timestamp video."""
    schedule = [(5, 0), (12, 70), (1e9, 0)]
    det = None

    def __init__(self, task_path=None):
        pass

    def __call__(self, frame_bgr, ts_ms):
        t = ts_ms / 1000.0
        for item in self.schedule:
            until, dx = item[0], item[1]
            if t < until:
                return (None, None) if dx is None else side_landmarks(dx, item[2] if len(item) > 2 else 0.0)
        return None, None


def write_config(path, **over):
    cfg = {"calib_sec": 3, "alert_sec": 1, "clear_sec": 1, "cooldown_sec": 0, "repeat_sec": 240,
           "away_sec": 30, "api_base_url": None}
    cfg.update(over)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path
