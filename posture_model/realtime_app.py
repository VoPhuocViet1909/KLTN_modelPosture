"""
Desktop App – giai đoạn 1 (bản đầy đủ của realtime_posture.py, file cũ giữ nguyên để so sánh).

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
import collections
import json
import os
import sys
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
import cv2
import numpy as np
import onnxruntime as ort

from alerts import AlertTracker, EventLog, PresenceTracker, Reminders
from app_config import AppConfig
from distance import EyeDistance
from metrics import MetricsAggregator
from quality import ANGLE_KEYS, angles_ok, dist_ok
from notifier import Notifier, ascii_vi
from outbox import Outbox
from sender import Sender
from live_stream import LivePublisher
from posture_features import (FEATURES, apply_calibration, calibration_baseline, choose_side, facing_sign,
                              rula_frame_label, sequence_angles, shoulder_tilt, to_model_input)
from realtime_posture import PoseDetector, draw_front, draw_side, hstack

HERE = os.path.dirname(os.path.abspath(__file__))                       # model, file .task (đi kèm app)
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE   # cấu hình, sự kiện (ghi được)
SEV_COL = {"LOW": (0, 200, 255), "MEDIUM": (0, 140, 255), "HIGH": (0, 0, 255)}


def apply_config(cfg, trackers, rem, pres):
    for t in trackers:
        t.configure(alert_sec=cfg["alert_sec"], clear_sec=cfg["clear_sec"],
                    repeat_sec=cfg["repeat_sec"], cooldown_sec=cfg["cooldown_sec"])
    rem.configure(sit_limit_min=cfg["sit_limit_min"], sit_repeat_min=cfg["sit_repeat_min"],
                  eye_break_min=cfg["eye_break_min"])
    pres.away_sec = cfg["away_sec"]


def draw_distance(frame, cm, status):
    if frame is None:
        return
    txt = f"cach man hinh {cm:.0f} cm" if np.isfinite(cm) else "cach man hinh: --"
    col = {"CANH BAO": (0, 0, 255), "BAD": (0, 165, 255)}.get(status, (255, 255, 255))
    cv2.rectangle(frame, (0, 90), (frame.shape[1], 130), (30, 30, 30), -1)
    cv2.putText(frame, txt, (15, 120), 0, 0.8, col, 2)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="1", help="cam hông ~90°: số webcam hoặc link điện thoại")
    ap.add_argument("--front", default="0", help="cam laptop chính diện: số webcam hoặc link, -1 = tắt")
    ap.add_argument("--side-video", default=None)
    ap.add_argument("--front-video", default=None)
    ap.add_argument("--config", default=os.path.join(APP_DIR, "app_config.json"))
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

    model_cfg = json.load(open(os.path.join(HERE, "posture_config.json"), encoding="utf-8"))
    cfg = AppConfig(a.config, model_cfg)
    sess = ort.InferenceSession(os.path.join(HERE, "posture_transformer.onnx"), providers=["CPUExecutionProvider"])
    WIN, FPS = model_cfg["window"], model_cfg["fps"]
    task = os.path.join(HERE, "pose_landmarker_full.task")

    # ---------------------------------------------------------------- camera
    use_video = a.side_video is not None
    src = lambda v: int(v) if str(v).lstrip("-").isdigit() else v

    def open_cam(v):
        v = src(v)
        if isinstance(v, str):
            c = cv2.VideoCapture(v)
            c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return c
        for api in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            c = cv2.VideoCapture(v, api)
            if c.isOpened():
                for _ in range(15):
                    ok, fr = c.read()
                    if ok and fr is not None:
                        return c
                    time.sleep(0.1)
            c.release()
        return cv2.VideoCapture(v)

    cap_s = cv2.VideoCapture(a.side_video) if use_video else open_cam(a.side)
    if not cap_s.isOpened():
        raise SystemExit("Không mở được cam hông")
    cap_f = None
    if a.front_video or (not use_video and src(a.front) != -1):
        cap_f = cv2.VideoCapture(a.front_video) if a.front_video else open_cam(a.front)
        if not cap_f.isOpened():
            print("Không mở được cam laptop -> chỉ chạy nhánh cổ/thân")
            cap_f = None
    det_s = PoseDetector(task)
    det_f = PoseDetector(task) if cap_f is not None else None
    ed = None
    if cap_f is not None:
        ed = EyeDistance(os.path.join(HERE, "face_landmarker.task"), cfg["camera_hfov_deg"], use_face=not a.no_face)
        ed.focal = cfg["camera_focal_px"]
    vid_fps = cap_s.get(cv2.CAP_PROP_FPS) or 30

    # ---------------------------------------------------------------- cảnh báo + sự kiện
    tr_neck, tr_tilt, tr_dist = AlertTracker("NECK_TRUNK"), AlertTracker("SHOULDER_TILT"), AlertTracker("TOO_CLOSE")
    trackers = (tr_neck, tr_tilt, tr_dist)
    pres, rem = PresenceTracker(), Reminders()
    apply_config(cfg, trackers, rem, pres)
    notifier = Notifier(cfg)
    elog = EventLog(a.events, model_cfg.get("version"), wall_t0=time.time(), user_id=cfg["user_id"],
                    listeners=[notifier])

    # ---------------------------------------------------------------- gửi dữ liệu (giai đoạn 2)
    outbox = Outbox(a.outbox)
    sender = Sender(outbox, cfg["api_base_url"], cfg["api_token"], elog.device_id,
                    interval=cfg["batch_interval_sec"], batch_max=cfg["batch_max"])
    os.makedirs(os.path.dirname(os.path.abspath(a.metrics_out)), exist_ok=True)
    metrics_f = open(a.metrics_out, "a", encoding="utf-8")

    last_metric = [None]                              # để bảng METADATA hiện bản metrics mới nhất

    def on_metric(m):
        last_metric[0] = m
        metrics_f.write(json.dumps(m, ensure_ascii=False) + "\n")
        metrics_f.flush()
        sender.enqueue_metric(m)

    agg = MetricsAggregator(on_metric, elog.wall_t0, elog.session_id, elog.device_id, cfg["user_id"],
                            window_sec=cfg["metrics_window_sec"], model_version=model_cfg.get("version"),
                            app_version=EventLog.APP_VERSION)
    elog.listeners += [sender.enqueue_event, agg.on_event]
    sender.start()
    elog.emit(dict(eventType="SESSION_START", t=0.0, frontCam=cap_f is not None,
                   distanceMethod=None if ed is None else ("iris" if ed.det else "ipd")), config=cfg.snapshot())
    snap = dict(pBad=None, neck=None, trunk=None, headPitch=None, rulaB=None, tiltRel=None, distanceCm=None)

    def emit(events):
        if events:
            elog.emit_all(events, snapshot=snap, config=cfg.snapshot())

    logf = open(a.log, "w", encoding="utf-8") if a.log else None
    if logf:
        logf.write("time,posture,p_bad," + ",".join(FEATURES) + ",rula_b,shoulder,tilt_rel,distance_cm,distance\n")

    def start_calib(now=None):
        evs = []
        for t in trackers:
            evs += t.reset(now, "RECALIBRATE")
        emit(evs)
        return dict(L=[], W=[], tilt=[], dpx=[], dkind=[], t0=None)

    cal, side, f, base, tilt_base = start_calib(), None, None, None, None
    buf = collections.deque(maxlen=WIN)
    p_hist, t_hist, d_hist = (collections.deque(maxlen=5) for _ in range(3))     # median filter 5 kết quả
    p_med, t_med, d_med, ang, rula_lab = 0.0, np.nan, np.nan, None, None
    last_s = last_f = last_cfg = -1e9
    Ls_draw = Lf_draw = None
    frame_i, t_start, miss, now = 0, time.time(), 0, 0.0
    sync_txt = ""
    ob_stats = {}
    show_meta = not a.hide_meta

    stream = None
    if a.stream_camera:
        if a.stream_camera == "front" and cap_f is None:
            raise SystemExit("Camera front chưa mở; không thể truyền hình")
        stream = LivePublisher(lambda: (cfg["api_base_url"], cfg["api_token"]), elog.device_id,
                               a.stream_camera, a.stream_rtsp_base, a.ffmpeg)
        stream.start()
        print("Live camera enabled:", a.stream_camera, "device:", elog.device_id)

    while True:
        ok, fs = cap_s.read()
        if not ok:
            if use_video:
                break
            miss += 1
            if miss > 100:
                print("Mất hình cam hông quá lâu, thoát.")
                break
            time.sleep(0.03)
            continue
        miss = 0
        ff = None
        if cap_f is not None:
            okf, ff = cap_f.read()
            if not okf:
                ff = None
        frame_i += 1
        if stream:
            stream.submit(fs if a.stream_camera == "side" else ff)
        now = (frame_i / vid_fps) if use_video else (time.time() - t_start)
        if a.max_sec and now > a.max_sec:
            break
        ts = int(now * 1000)
        sample_s = now - last_s >= 1.0 / FPS
        sample_f = ff is not None and now - last_f >= 1.0 / FPS
        Ls, Ws = det_s(fs, ts) if sample_s else (None, None)
        Lf = det_f(ff, ts)[0] if sample_f else None
        dpx, dkind = (ed.measure(ff, ts, Lf) if (sample_f and ed is not None) else (np.nan, None))
        if sample_s:
            last_s, Ls_draw = now, Ls
        if sample_f:
            last_f, Lf_draw = now, Lf

        # ------------------------------------------------ nạp lại cấu hình mỗi 2 giây
        if now - last_cfg >= 2:
            last_cfg = now
            changed = cfg.reload()
            if changed:
                apply_config(cfg, trackers, rem, pres)
                if "camera_focal_px" in changed and ed is not None and cfg["camera_focal_px"]:
                    ed.focal = cfg["camera_focal_px"]
                elog.user_id = agg.user_id = cfg["user_id"]
                if changed & {"api_base_url", "api_token", "batch_interval_sec", "batch_max"}:
                    sender.configure(cfg["api_base_url"], cfg["api_token"], cfg["batch_interval_sec"], cfg["batch_max"])
                if "metrics_window_sec" in changed:
                    agg.flush()
                    agg.window = int(cfg["metrics_window_sec"])
                elog.emit(dict(eventType="CONFIG_APPLIED", t=now, changedKeys=sorted(changed)), config=cfg.snapshot())
                print("Đã áp dụng cấu hình mới:", sorted(changed))

        if base is None:  # ============================================ hiệu chỉnh
            if cal["t0"] is None:
                cal["t0"] = now
            if Ls is not None:
                cal["L"].append(Ls)
                cal["W"].append(Ws)
            if Lf is not None:
                cal["tilt"].append(shoulder_tilt(Lf))
            if dkind:
                cal["dpx"].append(dpx)
                cal["dkind"].append(dkind)
            left = cfg["calib_sec"] - (now - cal["t0"])
            if left <= 0:
                if len(cal["L"]) < 10:
                    print("Cam hông không thấy người đủ lâu, hiệu chỉnh lại.")
                    cal = start_calib()
                else:
                    Lc, Wc = np.stack(cal["L"]), np.stack(cal["W"])
                    side = choose_side(Lc, Wc)
                    f = facing_sign(Lc, side)
                    base = calibration_baseline(sequence_angles(Lc, side, f))
                    tilts = np.array(cal["tilt"], float)
                    tilt_base = float(np.nanmedian(tilts)) if np.isfinite(tilts).sum() >= 5 else None
                    dist_base = np.nan
                    if ed is not None:
                        med_px = ed.calibrate(cal["dpx"], cal["dkind"], cfg["calib_distance_cm"])
                        if med_px is not None:
                            dist_base = ed.to_cm(med_px, ed.kind, ff.shape[1] if ff is not None else 640)
                    elog.emit(dict(eventType="CALIBRATED", t=now, side="left" if side == 0 else "right",
                                   baseline={"neck": round(base["neck"], 2), "trunk": round(base["trunk"], 2),
                                             "headPitch": round(base["head_pitch"], 2)},
                                   shoulderTiltBase=None if tilt_base is None else round(tilt_base, 2),
                                   distanceCm=None if not np.isfinite(dist_base) else round(dist_base, 1),
                                   distanceMethod=None if ed is None else ed.kind,
                                   focalPx=None if ed is None or not ed.focal else round(ed.focal, 1)))
                    print(f"Hiệu chỉnh xong: phía {'trái' if side == 0 else 'phải'}, baseline",
                          {k: round(v, 1) for k, v in base.items()},
                          "| lệch vai:", None if tilt_base is None else round(tilt_base, 1),
                          "| khoảng cách:", None if not np.isfinite(dist_base) else f"{dist_base:.0f} cm")
                    buf.clear(); p_hist.clear(); t_hist.clear(); d_hist.clear()
                    if rem.sit_start is None:
                        rem.start(now)
            lc = max(left, 0)
            vis_s = draw_side(fs, Ls_draw, side, "...", 0, None, None, calib_left=lc)
            vis_f = draw_front(ff, Lf_draw, "...", None, calib_left=lc) if ff is not None else None

        else:  # ========================================================= theo dõi
            # ---- có mặt / vắng mặt
            if sample_s or sample_f:
                present = (Ls is not None) or (Lf is not None) or (dkind is not None)
                pevs = pres.update(present, now)
                for e in pevs:
                    if e["eventType"] == "USER_AWAY":
                        for t in trackers:
                            pevs = pevs + t.reset(now, "AWAY")
                        rem.stop()
                        buf.clear(); p_hist.clear(); t_hist.clear(); d_hist.clear()
                    else:
                        rem.start(now)
                emit(pevs)

            if not pres.away:
                # ---- nhánh 1: cổ / thân
                if sample_s:
                    c = None
                    if Ls is not None:
                        c = apply_calibration(sequence_angles(Ls[None], side, f), base)
                        if not angles_ok({k: float(c[0, FEATURES.index(k)]) for k in ANGLE_KEYS}):
                            c = None                      # góc phi lý = bắt sai điểm khớp -> coi như không thấy
                    if c is not None:
                        ang = {k: float(c[0, i]) for i, k in enumerate(FEATURES)}
                        rula_lab, _ = rula_frame_label(c[0])
                        buf.append(to_model_input(c)[0])
                    else:
                        ang = rula_lab = None
                        buf.append(np.zeros(len(FEATURES), np.float32))
                    if len(buf) == WIN:
                        logit = sess.run(None, {"x": np.stack(buf)[None]})[0][0]
                        p_hist.append(1 / (1 + np.exp(-logit)))
                        p_med = float(np.median(p_hist))
                        thr, hy = cfg["p_bad_threshold"], cfg["p_bad_hysteresis"]
                        bad = True if p_med >= thr + hy else False if p_med <= thr - hy else None
                        if ang:
                            snap.update(neck=ang["neck"], trunk=ang["trunk"], headPitch=ang["head_pitch"])
                        snap.update(pBad=p_med, rulaB=None if rula_lab is None or not np.isfinite(rula_lab) else int(rula_lab))
                        emit(tr_neck.update(bad, now))

                # ---- nhánh 2: lệch vai
                if sample_f and tilt_base is not None:
                    tv = shoulder_tilt(Lf) if Lf is not None else np.nan
                    if np.isfinite(tv):
                        t_hist.append(tv - tilt_base)
                    if t_hist:
                        t_med = float(np.median(t_hist))
                        on, off = cfg["shoulder_tilt_on"], cfg["shoulder_tilt_off"]
                        bad = True if abs(t_med) > on else False if abs(t_med) < off else None
                        snap["tiltRel"] = t_med
                        emit(tr_tilt.update(bad if np.isfinite(tv) else None, now))

                # ---- nhánh 3: khoảng cách mắt – màn hình
                if sample_f and ed is not None:
                    cm = ed.to_cm(dpx, dkind, ff.shape[1])
                    cm_ok = dist_ok(float(cm))            # ngoài 20–150 cm = đo sai, bỏ mẫu
                    if cm_ok:
                        d_hist.append(cm)
                    if d_hist:
                        d_med = float(np.median(d_hist))
                        on, off = cfg["distance_on_cm"], cfg["distance_off_cm"]
                        bad = True if d_med < on else False if d_med > off else None
                        snap["distanceCm"] = round(d_med, 1)
                        emit(tr_dist.update(bad if cm_ok else None, now))

                # ---- nhắc nghỉ
                emit(rem.update(now))

            if sample_s:                                  # cùng mẫu với log.csv -> gộp metrics 60 giây
                agg.add(now, present=not pres.away and (Ls is not None or Lf is not None),
                        neck_status=tr_neck.status, p_bad=p_med if len(buf) == WIN else None, ang=ang,
                        tilt_rel=t_med if tilt_base is not None else None,
                        tilt_status=tr_tilt.status if tilt_base is not None else None,
                        dist_cm=d_med if ed is not None else None,
                        dist_status=tr_dist.status if ed is not None else None)
            if logf and sample_s:
                logf.write(f"{now:.2f},{tr_neck.status},{p_med:.3f},"
                           + ",".join(f"{ang[k]:.2f}" if ang else "" for k in FEATURES)
                           + f",{rula_lab},{tr_tilt.status if tilt_base is not None else ''},{t_med:.2f}"
                           + f",{d_med:.1f},{tr_dist.status if ed is not None else ''}\n")
            vis_s = draw_side(fs, Ls_draw, side, "..." if pres.away else tr_neck.status, p_med, ang, rula_lab)
            vis_f = None
            if ff is not None:
                vis_f = draw_front(ff, Lf_draw, tr_tilt.status if tilt_base is not None and not pres.away else "...", t_med)
                draw_distance(vis_f, d_med, tr_dist.status)

        if not a.no_gui:
            if frame_i % 30 == 1:                         # cập nhật trạng thái gửi ~1 lần/giây (đọc SQLite)
                sync_txt = sender.status_text()
                ob_stats = outbox.stats()
            img = draw_overlay(hstack(vis_s, vis_f), notifier.active_banner(), rem.sitting_sec(now), pres.away,
                               sync_txt)
            if show_meta:
                img = np.hstack([img, draw_meta_panel(img.shape[0], elog, snap, last_metric[0], ob_stats, sync_txt)])
            cv2.imshow("Posture monitor", img)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord("m"):
                show_meta = not show_meta
            if k == ord("c"):
                cal, base, tilt_base = start_calib(now), None, None

    # ---------------------------------------------------------------- kết thúc phiên
    if stream:
        stream.stop()
    evs = []
    for t in trackers:
        evs += t.reset(now, "SESSION_END")
    emit(evs)
    elog.emit(dict(eventType="SESSION_END", t=now, durationSec=round(now, 1),
                   alertCount={t.alert_type: t.count for t in trackers}))
    elog.close()
    agg.flush()                                       # cửa sổ metrics cuối (chưa đủ 60 giây)
    metrics_f.close()
    sender.stop(timeout=8)                            # gửi nốt; chưa gửi được thì vẫn nằm trong outbox
    st = outbox.stats()
    outbox.close()
    print(f"Outbox: đã gửi {st['sent']}, còn chờ {st['pending']}, bị từ chối {st['dead']}")
    for d in (det_s, det_f, ed):                     # đóng model MediaPipe trước khi Python thoát (tránh lỗi __del__)
        try:
            if d is not None and d.det is not None and hasattr(d.det, "close"):
                d.det.close()
        except Exception:
            pass
    cap_s.release()
    if cap_f is not None:
        cap_f.release()
    if not a.no_gui:
        cv2.destroyAllWindows()
    if logf:
        logf.close()
    print("Sự kiện đã ghi vào", a.events)


if __name__ == "__main__":
    main()
