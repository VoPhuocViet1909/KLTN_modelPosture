"""Cầu nối engine (luồng nền) -> giao diện Qt bằng signal. Mọi dữ liệu sang luồng giao diện đi qua signal."""
import time

from PySide6.QtCore import QObject, QThread, Signal

from engine import EngineListener
from notifier import NotifierBase, format_message


class EngineBridge(QObject, EngineListener):
    state = Signal(dict)
    alert = Signal(dict)
    metrics = Signal(dict)
    sync = Signal(dict)
    config = Signal(object)
    frame = Signal(object)
    finished = Signal(str, dict)
    error = Signal(str)

    FRAME_EVERY = 1 / 15          # tối đa 15 khung/giây sang giao diện

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self._last_frame = 0.0

    # --- EngineListener (gọi trong luồng engine) ---
    def on_state(self, s): self.state.emit(s)
    def on_alert(self, e): self.alert.emit(e)
    def on_metrics(self, m): self.metrics.emit(m)
    def on_sync(self, i): self.sync.emit(i)
    def on_config(self, c): self.config.emit(c)
    def on_finished(self, reason, stats): self.finished.emit(reason, stats)
    def on_error(self, msg): self.error.emit(msg)

    def on_frame(self, f):
        now = time.monotonic()
        if now - self._last_frame >= self.FRAME_EVERY:
            self._last_frame = now
            self.frame.emit(f)


class EngineThread(QThread):
    """Chạy PostureEngine trong QThread. Lỗi khởi động/vòng lặp được engine báo qua bridge.error + finished."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        self.engine.run_guarded()

    def stop(self, wait_ms=15000):
        self.engine.stop()
        return self.wait(wait_ms)


class Task(QThread):
    """Chạy một hàm chặn (đăng nhập, đăng xuất, mở lại phiên) ngoài luồng giao diện để cửa sổ không đơ."""
    done = Signal(object)          # kết quả
    failed = Signal(object)        # ngoại lệ

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            self.failed.emit(e)


class QtNotifier(QObject, NotifierBase):
    """Notifier cho giao diện Qt: nhận sự kiện từ luồng engine, đẩy sang luồng giao diện bằng signal.
    Hiển thị (banner / toast / bíp / hộp thoại) do AppController xử lý theo mức độ + cấu hình notify_*."""

    notice = Signal(str, str, str, str, str)       # title, body, severity, alertType, eventType

    def __init__(self, cfg, parent=None):
        QObject.__init__(self, parent)
        self.cfg = cfg

    def __call__(self, ev):
        if not ev.get("notify"):
            return
        title, body = format_message(ev, self.cfg)
        self.notice.emit(title, body, ev.get("severity", "LOW"), ev.get("alertType") or "", ev.get("eventType", ""))
