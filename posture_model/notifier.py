"""
Thông báo trên máy người dùng, tăng dần theo mức độ của sự kiện:

  LOW    : banner trên cửa sổ app + thông báo hệ thống (toast)
  MEDIUM : + tiếng bíp
  HIGH   : + hộp thoại nổi lên trên cùng (chỉ 1 hộp thoại tại một thời điểm)

Toast dùng thư viện `plyer` nếu có (pip install plyer), không có thì bỏ qua. Bíp / hộp thoại dùng API Windows,
chạy ở thread riêng để không làm chậm vòng lặp camera. Trên Linux/macOS chỉ in ra console.
"""
import os
import threading
import time
import unicodedata

MESSAGES = {
    "NECK_TRUNK": ("Tư thế cổ / lưng", "Bạn đang cúi hoặc gù lưng. Hãy ngồi thẳng, kéo vai ra sau."),
    "SHOULDER_TILT": ("Lệch vai", "Vai đang bị lệch. Cân bằng lại hai vai, đặt hai tay đều lên bàn."),
    "TOO_CLOSE": ("Quá gần màn hình", "Bạn đang ngồi quá gần màn hình ({distanceCm} cm). Lùi ra tối thiểu {limit} cm."),
    "SIT_TOO_LONG": ("Ngồi quá lâu", "Bạn đã ngồi liên tục {sittingMin:.0f} phút. Đứng dậy đi lại 2–3 phút nhé."),
    "EYE_BREAK": ("Nghỉ mắt 20-20-20", "Nhìn một vật cách xa khoảng 6 m trong 20 giây."),
}


def ascii_vi(s):
    """Bỏ dấu tiếng Việt để vẽ bằng cv2.putText (không hỗ trợ Unicode)."""
    s = s.replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def format_message(ev, cfg=None):
    title, body = MESSAGES.get(ev.get("alertType"), ("Cảnh báo", "Hãy điều chỉnh tư thế."))
    data = dict(ev)
    data.setdefault("distanceCm", (ev.get("snapshot") or {}).get("distanceCm", "?"))
    data.setdefault("sittingMin", 0)
    data["limit"] = cfg["distance_on_cm"] if cfg is not None else 50
    try:
        body = body.format(**data)
    except (KeyError, ValueError):
        pass
    if ev.get("eventType") == "ALERT_REPEATED":
        title += f" (nhắc lần {ev.get('level', 2)})"
    return title, body


class Notifier:
    BANNER_SEC = 6

    def __init__(self, cfg):
        self.cfg = cfg
        self.banner = None              # (hết hạn lúc, tiêu đề, nội dung, mức)
        self._popup_open = False
        self._is_win = os.name == "nt"
        try:
            from plyer import notification
            self._toast = notification
        except Exception:
            self._toast = None

    # gọi từ EventLog (listener)
    def __call__(self, ev):
        if not ev.get("notify"):
            return
        title, body = format_message(ev, self.cfg)
        sev = ev.get("severity", "LOW")
        self.banner = (time.time() + self.BANNER_SEC, title, body, sev)
        print(f"[{time.strftime('%H:%M:%S')}] {sev}: {title} – {body}")
        if self.cfg["notify_toast"]:
            self._run(self._show_toast, title, body)
        if sev in ("MEDIUM", "HIGH") and self.cfg["notify_sound"]:
            self._run(self._beep, sev)
        if sev == "HIGH" and self.cfg["notify_popup"] and not self._popup_open:
            self._popup_open = True
            self._run(self._popup, title, body)

    def active_banner(self):
        if self.banner and time.time() < self.banner[0]:
            return self.banner[1:]
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _run(fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _show_toast(self, title, body):
        if self._toast is None:
            return
        try:
            self._toast.notify(title=title, message=body, app_name="Posture Monitor", timeout=5)
        except Exception:
            pass

    def _beep(self, sev):
        if self._is_win:
            import winsound
            for _ in range(2 if sev == "HIGH" else 1):
                winsound.Beep(1000, 250)
                time.sleep(0.1)
        else:
            print("\a", end="", flush=True)

    def _popup(self, title, body):
        try:
            if self._is_win:
                import ctypes
                MB_ICONWARNING, MB_TOPMOST, MB_SETFOREGROUND = 0x30, 0x40000, 0x10000
                ctypes.windll.user32.MessageBoxW(0, body, title, MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND)
        finally:
            self._popup_open = False
