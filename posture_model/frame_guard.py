"""
Phát hiện camera trả mãi một khung cũ (driver đứng nhưng cap.read() vẫn ok).

Chỉ coi là đứng khi khung (ảnh xám, nguyên độ phân giải: giảm kích thước sẽ làm mịn nhiễu và dễ báo nhầm) TRÙNG Y HỆT (chênh lệch pixel lớn nhất = 0) liên tục ≥ FREEZE_SEC.
Không dựa vào landmark: người ngồi yên vẫn có nhiễu cảm biến nên khung thật gần như không bao giờ trùng từng pixel.
"""
import cv2
import numpy as np

FREEZE_SEC = 2.0


class FrozenFrameGuard:
    def __init__(self, freeze_sec=FREEZE_SEC):
        self.freeze_sec = freeze_sec
        self.prev = None
        self.prev_t = None
        self.same_since = None

    def update(self, frame, now):
        """Gọi mỗi mẫu. Trả True khi khung đã trùng y hệt liên tục ≥ freeze_sec (coi như mất tín hiệu)."""
        if frame is None:
            self.reset()
            return False
        small = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.prev is not None and self.prev.shape == small.shape and int(cv2.absdiff(small, self.prev).max()) == 0:
            if self.same_since is None:
                self.same_since = self.prev_t          # khung này xuất hiện lần đầu ở mẫu trước
        else:
            self.same_since = None
        self.prev, self.prev_t = small, now
        return self.same_since is not None and now - self.same_since >= self.freeze_sec

    def reset(self):
        self.prev = self.prev_t = self.same_since = None
