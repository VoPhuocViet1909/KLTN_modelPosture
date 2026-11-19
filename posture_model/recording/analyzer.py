"""Chạy MediaPipe trên ảnh thu nhỏ, ~10 lần/giây, ở thread riêng chỉ để HIỂN THỊ / chấm điểm trực tiếp (file video ghi từ ảnh gốc,
không đi qua đây nên không bị rớt khung). Landmark trả về đã quy về toạ độ pixel của ảnh gốc, nên các hàm của engine
(posture_features) cho cùng kết quả như khi chạy trên ảnh gốc: góc và tỉ lệ không đổi theo kích thước."""
import collections
import threading
import time
from dataclasses import dataclass

import numpy as np

SCALE_W = 480                   # chiều rộng ảnh đưa vào MediaPipe


@dataclass
class Sample:
    t: float                    # thời điểm khung (cùng đồng hồ với CameraSource)
    Ls: object = None           # (33,3) pixel ảnh gốc, cam hông; None = không thấy người
    Ws: object = None
    Lf: object = None           # cam laptop
    dpx: float = float("nan")   # kích thước mống mắt / 2 mắt (px ảnh gốc) để đo khoảng cách
    dkind: str = None
    width_f: int = 640          # độ rộng ảnh gốc cam laptop
    has_side: bool = False      # có khung từ cam hông (phân biệt "không thấy người" với "chưa có khung")
    has_front: bool = False


def _shrink(frame):
    h, w = frame.shape[:2]
    if w <= SCALE_W:
        return frame, 1.0
    import cv2
    s = SCALE_W / w
    return cv2.resize(frame, (SCALE_W, int(round(h * s))), interpolation=cv2.INTER_AREA), s


def _upscale(L, s):
    if L is None or s == 1.0:
        return L
    L = L.copy()
    L[:, :2] /= s
    return L


class Analyzer:
    """det_side / det_front: callable(frame_bgr, ts_ms) -> (L, W) như realtime_posture.PoseDetector (hoặc bản giả khi test).
    ed: distance.EyeDistance hoặc None (không đo khoảng cách)."""

    def __init__(self, side_src, front_src, det_side, det_front, ed=None, hz=10.0, clock=time.perf_counter):
        self.side_src, self.front_src = side_src, front_src
        self.det_s, self.det_f, self.ed = det_side, det_front, ed
        self.period = 1.0 / hz
        self.clock = clock
        self._q = collections.deque(maxlen=600)
        self._stop = threading.Event()
        self._t0 = clock()
        self._last = {"side": None, "front": None}
        self._th = threading.Thread(target=self._run, name="analyzer", daemon=True)
        self.last_sample = None
        self.last_ms = 0.0          # thời gian xử lý một vòng (ms), để báo nếu máy quá chậm

    def start(self):
        self._th.start()
        return self

    def drain(self):
        out = []
        while True:
            try:
                out.append(self._q.popleft())
            except IndexError:
                return out

    def _run(self):
        nxt = self.clock()
        while not self._stop.is_set():
            t_begin = self.clock()
            try:
                s = self.step()
            except Exception as e:                                       # noqa: BLE001  một khung lỗi không được làm chết thread
                print("Analyzer:", e)
                s = None
            self.last_ms = (self.clock() - t_begin) * 1000
            if s is not None:
                self.last_sample = s
                self._q.append(s)
            nxt += self.period
            time.sleep(max(0.0, nxt - self.clock()))
            if self.clock() - nxt > 1.0:                                 # chậm quá thì bỏ nhịp, không dồn việc
                nxt = self.clock()

    def step(self):
        """Xử lý khung mới nhất của mỗi camera (nếu có khung mới). Trả Sample hoặc None."""
        ls = self.side_src.latest() if self.side_src else None
        lf = self.front_src.latest() if self.front_src else None
        new_s = ls is not None and ls[0] != self._last["side"]
        new_f = lf is not None and lf[0] != self._last["front"]
        if not (new_s or new_f):
            return None
        smp = Sample(t=max(x[0] for x in (ls, lf) if x is not None))
        if new_s:
            self._last["side"] = ls[0]
            img, s = _shrink(ls[1])
            L, W = self.det_s(img, int((ls[0] - self._t0) * 1000))
            smp.Ls, smp.Ws, smp.has_side = _upscale(L, s), W, True
        if new_f:
            self._last["front"] = lf[0]
            img, s = _shrink(lf[1])
            ts = int((lf[0] - self._t0) * 1000)
            L, _ = self.det_f(img, ts)
            smp.Lf, smp.has_front = _upscale(L, s), True
            smp.width_f = lf[1].shape[1]
            if self.ed is not None:
                px, kind = self.ed.measure(img, ts, L)
                smp.dpx, smp.dkind = (px / s if np.isfinite(px) else px), kind
        return smp

    def stop(self):
        self._stop.set()
        if self._th.is_alive():
            self._th.join(timeout=3)
