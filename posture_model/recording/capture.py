"""Đọc camera và ghi file ở thread riêng (không dính tới MediaPipe / giao diện), để hình ghi ra không rớt khung.

CameraSource  : 1 thread đọc 1 camera (hoặc file video để chạy thử), giữ khung mới nhất + nhịp FPS thật.
ClipWriter    : 1 thread ghi 1 file mp4 của 1 clip. Khung nhận theo thời điểm đọc, xếp vào ô 1/fps gần nhất
                (mất khung -> lặp khung trước, thừa khung -> bỏ) nên file luôn đúng duration * fps khung, đúng thời lượng thật.
"""
import collections
import os
import queue
import threading
import time
from dataclasses import dataclass

import cv2

FPS = 30
SIZE = (1280, 720)


def _is_index(spec):
    return str(spec).lstrip("-").isdigit()


BACKENDS = {"DSHOW": cv2.CAP_DSHOW, "MSMF": cv2.CAP_MSMF, "ANY": cv2.CAP_ANY}


def parse_size(text):
    """'640x480' -> (640, 480)."""
    try:
        w, h = str(text).lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise ValueError(f"Kích thước '{text}' sai, dùng dạng 1280x720 hoặc 640x480.") from None


@dataclass
class CamConfig:
    """Cấu hình mở camera. fourcc None = để driver tự chọn. backend None = thử lần lượt theo `order`."""
    backend: str = None
    fourcc: str = "MJPG"
    size: tuple = SIZE
    order: tuple = ("DSHOW", "MSMF", "ANY")       # mặc định: MJPG + DSHOW trước

    def label(self):
        return f"{self.backend or 'auto'}/{self.fourcc or 'mặc định'}/{self.size[0]}x{self.size[1]}"


def _try_open(v, backend, cfg, fps):
    c = cv2.VideoCapture(v, BACKENDS[backend])
    if not c.isOpened():
        c.release()
        return None
    if cfg.fourcc:                                                       # MJPG mới đạt 30 fps trên đa số webcam / Iriun
        c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfg.fourcc))
    c.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.size[0])
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.size[1])
    c.set(cv2.CAP_PROP_FPS, fps)
    c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(15):                                                  # bỏ vài khung đầu (camera đang lấy sáng)
        ok, fr = c.read()
        if ok and fr is not None:
            return c
        time.sleep(0.1)
    c.release()
    return None


def open_camera(spec, cfg=None, fps=FPS):
    """spec: số (chỉ số camera) hoặc đường dẫn file video. cfg: CamConfig (mặc định MJPG + DSHOW trước, 1280x720)."""
    cfg = cfg or CamConfig()
    if not _is_index(spec):
        return cv2.VideoCapture(str(spec))
    v = int(spec)
    for backend in ((cfg.backend,) if cfg.backend else ()) + tuple(b for b in cfg.order if b != cfg.backend):
        c = _try_open(v, backend, cfg, fps)
        if c is not None:
            return c
    return cv2.VideoCapture(v)


def opener_for(cfg):
    """Hàm mở camera cho CameraSource với cấu hình cfg."""
    return lambda spec: open_camera(spec, cfg)


class CameraSource:
    LOST_SEC = 2.0

    def __init__(self, name, spec, opener=open_camera, clock=time.perf_counter):
        self.name, self.spec, self.clock = name, spec, clock
        self.cap = opener(spec)
        if not self.cap.isOpened():
            raise RuntimeError(f"Không mở được camera {name} ({spec}). Kiểm tra dây cắm, Iriun / quyền camera, "
                               "và đóng ứng dụng khác đang giữ camera.")
        self.is_file = not _is_index(spec)
        self.native_fps = self.cap.get(cv2.CAP_PROP_FPS) or FPS
        self.size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self._lock = threading.Lock()
        self._latest = None                  # (t, frame)
        self._stamps = collections.deque(maxlen=120)
        self._sink = None
        self._stop = threading.Event()
        self.count = 0
        self.lost = False
        self._th = threading.Thread(target=self._run, name=f"cam-{name}", daemon=True)

    def start(self):
        self._th.start()
        return self

    def set_sink(self, sink):
        with self._lock:
            self._sink = sink

    def latest(self):
        with self._lock:
            return self._latest

    def fps(self, window=2.0):
        """FPS thật trong `window` giây gần nhất (None nếu chưa đủ khung)."""
        with self._lock:
            ts = list(self._stamps)
        now = self.clock()
        ts = [t for t in ts if now - t <= window]
        if len(ts) < 5:
            return None
        return (len(ts) - 1) / max(ts[-1] - ts[0], 1e-6)

    def _run(self):
        last_ok = self.clock()
        period = 1.0 / self.native_fps
        nxt = self.clock()
        while not self._stop.is_set():
            ok, fr = self.cap.read()
            t = self.clock()
            if not ok or fr is None:
                if self.is_file:                                  # file ngắn: quay lại đầu để chạy thử đủ lâu
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, fr = self.cap.read()
                    t = self.clock()
                if not ok or fr is None:
                    if t - last_ok > self.LOST_SEC:
                        self.lost = True
                    time.sleep(0.02)
                    continue
            if self.is_file:                                      # giả lập nhịp camera thật
                nxt += period
                time.sleep(max(0.0, nxt - self.clock()))
                t = self.clock()
            last_ok, self.lost = t, False
            self.count += 1
            with self._lock:
                self._latest = (t, fr)
                self._stamps.append(t)
                sink = self._sink
            if sink is not None:
                sink.push(t, fr)

    def close(self):
        self._stop.set()
        if self._th.is_alive():
            self._th.join(timeout=2)
        self.cap.release()


class ClipWriter:
    """Ghi `duration` giây (đúng round(duration*fps) khung) vào `tmp_path`; finish() xong thì trả danh sách thời điểm từng khung."""

    def __init__(self, tmp_path, t_start, duration, fps=FPS, max_queue=900):
        self.path, self.t0, self.duration, self.fps = tmp_path, t_start, duration, fps
        self.n_total = int(round(duration * fps))
        self.q = queue.Queue(maxsize=max_queue)
        self.rows = []                       # (n, t_rel, video_frame) video_frame = -1 nếu bỏ
        self.dropped = 0                     # bỏ vì hàng đợi đầy (ổ đĩa chậm)
        self.written = 0
        self.error = None
        self._vw = None
        self._last = None
        self._n = 0
        self._th = threading.Thread(target=self._run, name="writer", daemon=True)
        self._th.start()

    def push(self, t_abs, frame):
        t = t_abs - self.t0
        if t < 0 or t >= self.duration:
            return
        try:
            self.q.put_nowait((t, frame))
        except queue.Full:
            self.dropped += 1

    def _write(self, frame):
        if self._vw is None:
            h, w = frame.shape[:2]
            self._vw = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
            if not self._vw.isOpened():
                raise RuntimeError(f"Không tạo được file video {self.path}")
        self._vw.write(frame)
        self.written += 1

    def _run(self):
        try:
            while True:
                item = self.q.get()
                if item is None:
                    break
                t, frame = item
                k = int(t * self.fps + 0.5)
                n = self._n
                self._n += 1
                if k < self.written or self.written >= self.n_total:
                    self.rows.append((n, t, -1))
                    continue
                while self.written < k and self.written < self.n_total:       # khung bị mất: lặp khung trước (hoặc khung này)
                    self._write(self._last if self._last is not None else frame)
                self.rows.append((n, t, self.written))
                self._write(frame)
                self._last = frame
            while self._last is not None and self.written < self.n_total:     # camera dừng sớm: lặp khung cuối cho đủ thời lượng
                self._write(self._last)
        except Exception as e:                                                # noqa: BLE001
            self.error = str(e)
        finally:
            if self._vw is not None:
                self._vw.release()

    def finish(self):
        self.q.put(None)
        self._th.join(timeout=30)
        return self.rows

    @property
    def ok(self):
        return self.error is None and self.written >= self.n_total and os.path.exists(self.path)
