"""
Desktop App – giai đoạn 1 (bản đầy đủ của realtime_posture.py, file cũ giữ nguyên để so sánh).
Đây là điểm vào dòng lệnh (CLI, cửa sổ OpenCV); lõi xử lý nằm ở engine.py (PostureEngine). Giao diện Qt: app.py.

  Cam hông 90°  -> Pose -> góc cổ/thân -> Transformer ONNX -> median -> AlertTracker NECK_TRUNK
  Cam laptop    -> Pose -> công thức lệch vai         -> median -> AlertTracker SHOULDER_TILT
               -> Face Landmarker (mống mắt) -> cm   -> median -> AlertTracker TOO_CLOSE
  + PresenceTracker (USER_AWAY / USER_BACK) + Reminders (SIT_TOO_LONG, EYE_BREAK)
  -> EventLog: out/events.jsonl (outbox cho giai đoạn 2)  -> Notifier: banner / toast / bíp / hộp thoại

  python realtime_app.py --side 1 --front 0
  python realtime_app.py --side http://192.168.1.5:8080/video --front 0      # điện thoại làm cam hông
  python realtime_app.py --side-video hong.mp4 --front-video truoc.mp4 --no-gui   # chạy thử không cửa sổ

Phím: q = thoát, c = hiệu chỉnh lại. Sửa app_config.json khi app đang chạy -> áp dụng sau ~2 giây.
"""
import argparse
import getpass
import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
import cv2
import numpy as np

from api_session import ApiSession, AuthError
from engine import APP_DIR, EngineError, EngineOptions, PostureEngine, load_config
from notifier import ascii_vi
from realtime_posture import hstack

SEV_COL = {"LOW": (0, 200, 255), "MEDIUM": (0, 140, 255), "HIGH": (0, 0, 255)}


def _local_hms(iso_ts):
    """'2026-10-03T16:11:38.617Z' -> '23:11:38' (giờ máy)."""
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "--:--:--"


def draw_meta_panel(height, elog, snap, last_metric, stats, sync, width=440):
    """Bảng METADATA bên phải cửa sổ: số đo đang có, sự kiện vừa phát, metrics phút trước, trạng thái gửi."""
    p = np.full((height, width, 3), 24, np.uint8)
    y = [24]

    def line(txt, col=(220, 220, 220), scale=0.5, bold=1, gap=22):
        cv2.putText(p, ascii_vi(str(txt))[:62], (12, y[0]), 0, scale, col, bold)
        y[0] += gap

    def head(txt):
        y[0] += 6
        cv2.line(p, (12, y[0] - 16), (width - 12, y[0] - 16), (70, 70, 70), 1)
        line(txt, (0, 200, 255), 0.52, 1)

    f = lambda v, fmt="{:+.1f}": "--" if v is None else fmt.format(v)
    line("METADATA  (m: an / hien)", (255, 255, 255), 0.6, 2, 26)
    line(f"device  {elog.device_id}", (170, 170, 170), 0.45, 1, 18)
    line(f"session {elog.session_id}   user {elog.user_id or '-'}", (170, 170, 170), 0.45, 1, 18)
    head("SNAPSHOT (dang do, gui kem canh bao)")
    line(f"pBad {f(snap.get('pBad'), '{:.2f}')}   neck {f(snap.get('neck'))}   trunk {f(snap.get('trunk'))}")
    line(f"headPitch {f(snap.get('headPitch'))}   rulaB {snap.get('rulaB') if snap.get('rulaB') is not None else '--'}")
    line(f"tiltRel {f(snap.get('tiltRel'))} do   distanceCm {f(snap.get('distanceCm'), '{:.0f}')}")
    head("SU KIEN VUA PHAT (eventType)")
    evs = list(elog.recent)[-7:][::-1]
    if not evs:
        line("(chua co)", (140, 140, 140))
    for e in evs:
        t = e.get("eventType", "")
        col = {"ALERT_STARTED": (60, 60, 255), "ALERT_REPEATED": (0, 140, 255),
               "ALERT_RESOLVED": (80, 200, 80)}.get(t, (220, 220, 220))
        extra = e.get("alertType") or ""
        if e.get("durationSec") is not None and t != "SESSION_END":
            extra += f" {e['durationSec']:.0f}s"
        line(f"{_local_hms(e.get('ts'))}  {t} {extra}", col, 0.47, 1, 20)
    head("METRICS PHUT TRUOC (gui moi 60 s)")
    if last_metric:
        m = last_metric
        line(f"{_local_hms(m['windowStart'])[:5]}  score {m.get('postureScore')}   good {m.get('goodRatio')}")
        line(f"neck tb {f(m.get('neckMean'))}  max {f(m.get('neckMax'))}   canh bao {m.get('alertCount')}", scale=0.45)
        line(f"distance tb {f(m.get('distanceMeanCm'), '{:.0f}')} cm   tilt tb {f(m.get('tiltRelMean'))}", scale=0.45)
    else:
        line("(cho het phut dau tien)", (140, 140, 140))
    head("GUI LEN BACKEND")
    line(sync or "...", (200, 200, 120))
    line(f"da gui {stats.get('sent', 0)}   cho gui {stats.get('pending', 0)}   bi tu choi {stats.get('dead', 0)}",
         (200, 200, 120))
    return p


def draw_overlay(img, banner, sitting_sec, away, sync=""):
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, h - 34), (w, h), (30, 30, 30), -1)
    info = "VANG MAT" if away else f"ngoi lien tuc {int(sitting_sec // 60):02d}:{int(sitting_sec % 60):02d}"
    cv2.putText(img, info + "   (q: thoat, c: hieu chinh lai, m: metadata)", (12, h - 10), 0, 0.6, (220, 220, 220), 1)
    if sync:
        cv2.putText(img, sync, (w - 12 - 9 * len(sync), h - 10), 0, 0.55, (200, 200, 120), 1)
    if banner:
        title, body, sev = banner
        cv2.rectangle(img, (0, h - 110), (w, h - 34), SEV_COL.get(sev, (0, 0, 255)), -1)
        cv2.putText(img, ascii_vi(title), (14, h - 80), 0, 0.8, (255, 255, 255), 2)
        cv2.putText(img, ascii_vi(body)[:110], (14, h - 48), 0, 0.6, (255, 255, 255), 1)
    return img


class CvViewer:
    """Cửa sổ OpenCV cũ, gắn vào engine qua engine.viewer.show(...) (chạy trong luồng của engine)."""

    def __init__(self, show_meta=True):
        self.show_meta = show_meta
        self.sync_txt, self.ob_stats = "", {}

    def show(self, eng, vis_s, vis_f, frame_i):
        if frame_i % 30 == 1:                             # cập nhật trạng thái gửi ~1 lần/giây (đọc SQLite)
            self.sync_txt = eng.sender.status_text()
            self.ob_stats = eng.outbox.stats()
        img = draw_overlay(hstack(vis_s, vis_f), eng.notifier.active_banner(), eng.sitting_sec(), eng.away,
                           self.sync_txt)
        if self.show_meta:
            img = np.hstack([img, draw_meta_panel(img.shape[0], eng.elog, eng.snap, eng.last_metric,
                                                  self.ob_stats, self.sync_txt)])
        cv2.imshow("Posture monitor", img)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("m"):
            self.show_meta = not self.show_meta
        return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="1", help="cam hông ~90°: số webcam hoặc link điện thoại")
    ap.add_argument("--front", default="0", help="cam laptop chính diện: số webcam hoặc link, -1 = tắt")
    ap.add_argument("--side-video", default=None)
    ap.add_argument("--front-video", default=None)
    ap.add_argument("--config", default=os.path.join(APP_DIR, "app_config.json"))
    ap.add_argument("--login", action="store_true", help="đăng nhập API, tự làm mới token trong bộ nhớ")
    ap.add_argument("--sync-config", action="store_true", help="nhận cấu hình qua Socket.IO (cần --login)")
    ap.add_argument("--events", default=os.path.join(APP_DIR, "out", "events.jsonl"))
    ap.add_argument("--metrics-out", default=os.path.join(APP_DIR, "out", "metrics.jsonl"))
    ap.add_argument("--outbox", default=os.path.join(APP_DIR, "out", "outbox.db"))
    ap.add_argument("--log", default=None, help="ghi CSV từng mẫu (như bản cũ, thêm cột khoảng cách)")
    ap.add_argument("--no-gui", action="store_true", help="không mở cửa sổ (chạy thử trên video)")
    ap.add_argument("--hide-meta", action="store_true", help="ẩn bảng METADATA lúc mở (phím m để bật lại)")
    ap.add_argument("--no-face", action="store_true", help="không dùng Face Landmarker, đo bằng khoảng cách 2 mắt")
    ap.add_argument("--max-sec", type=float, default=None, help="dừng sau N giây (kiểm thử)")
    ap.add_argument("--stream-camera", choices=("side", "front"), help="bật truyền hình camera đã chọn; mặc định tắt")
    ap.add_argument("--stream-rtsp-base", default="rtsp://127.0.0.1:8554")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="đường dẫn FFmpeg có encoder libx264")
    a = ap.parse_args()
    if a.sync_config and not a.login:
        ap.error("--sync-config cần --login")

    cfg, model_cfg = load_config(a.config)
    auth = None
    if a.login:
        try:
            auth = ApiSession(cfg["api_base_url"], input("API email: ").strip(), getpass.getpass("API password: "))
        except (AuthError, EOFError):
            raise SystemExit("Đăng nhập không thành công; kiểm tra địa chỉ API và tài khoản") from None
    config_sync = None
    if a.sync_config:
        from config_sync import ConfigSync
        try:
            config_sync = ConfigSync(auth)
        except ImportError:
            raise SystemExit("Cài dependency bằng: python -m pip install -r posture_model/requirements.txt") from None

    opts = EngineOptions(side=a.side, front=a.front, side_video=a.side_video, front_video=a.front_video,
                         config=a.config, events=a.events, metrics_out=a.metrics_out, outbox=a.outbox, log=a.log,
                         no_face=a.no_face, max_sec=a.max_sec, stream_camera=a.stream_camera,
                         stream_rtsp_base=a.stream_rtsp_base, ffmpeg=a.ffmpeg)
    viewer = None if a.no_gui else CvViewer(show_meta=not a.hide_meta)
    engine = PostureEngine(opts, cfg=cfg, model_cfg=model_cfg, auth=auth, config_sync=config_sync, viewer=viewer)
    try:
        engine.run()
    except EngineError as e:
        raise SystemExit(str(e)) from None
    finally:
        if viewer is not None:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
