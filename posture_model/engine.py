"""
PostureEngine – lõi của Desktop App, tách khỏi cửa sổ OpenCV để giao diện nào cũng dùng được
(CLI `realtime_app.py` và giao diện Qt `app.py`).

Logic giữ nguyên bản cũ của realtime_app.py (model, quality, alerts, metrics, outbox, sender, config sync,
live publisher); file này chỉ gom vòng lặp vào một lớp, thêm start/stop và phát sự kiện qua EngineListener.

  engine = PostureEngine(opts, cfg=..., auth=..., config_sync=..., notifier=..., listener=...)
  engine.run()        # chạy ngay trong luồng hiện tại (CLI)
  engine.start()      # chạy trong luồng riêng, engine.stop() để dừng, engine.join() để chờ
  engine.request_recalibrate()
  engine.want_frames = True/False    # bật/tắt phát khung hình (mặc định tắt, nhẹ máy + riêng tư)

Mọi callback của EngineListener được gọi TRONG luồng của engine; giao diện Qt phải chuyển sang signal.
"""
import collections
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
import cv2
import numpy as np
import onnxruntime as ort

from alerts import AlertTracker, EventLog, PresenceTracker, Reminders
from app_config import AppConfig
from distance import EyeDistance
from live_stream import LivePublisher
from metrics import MetricsAggregator
from notifier import Notifier, NotifierBase
from outbox import Outbox
from posture_features import (FEATURES, apply_calibration, calibration_baseline, choose_side, facing_sign,
                              rula_frame_label, sequence_angles, shoulder_tilt, to_model_input)
from quality import ANGLE_KEYS, angles_ok, dist_ok
from realtime_posture import PoseDetector, draw_front, draw_side
from sender import Sender

HERE = os.path.dirname(os.path.abspath(__file__))                       # model, file .task (đi kèm app)
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE   # cấu hình, sự kiện (ghi được)

STATE_GOOD, STATE_BAD, STATE_AWAY, STATE_CALIBRATING = "GOOD", "BAD", "AWAY", "CALIBRATING"


class EngineError(RuntimeError):
    """Lỗi không thể bắt đầu (không mở được camera...). Thông điệp hiển thị được cho người dùng."""


class EngineListener:
    """Giao diện nhận sự kiện từ engine. Mọi hàm mặc định không làm gì."""

    def on_frame(self, frame):
        """Chỉ khi engine.want_frames. frame = dict(side, front, Ls, Lf, side_idx, vis_side, vis_front); ảnh BGR đã copy."""

    def on_state(self, state):
        """dict(state, calibrating, calibLeft, sittingSec, distanceCm, neck, tilt, distance, away). ~4 lần/giây + khi đổi."""

    def on_alert(self, ev):
        """Sự kiện ALERT_* / REMINDER (đã có notify) – cùng dict với dòng events.jsonl."""

    def on_metrics(self, metric):
        """Bản metrics mỗi 60 giây."""

    def on_sync(self, info):
        """dict(sent, pending, dead, online, text, lastError). ~1 lần/giây."""

    def on_config(self, changed):
        """Cấu hình mới vừa áp dụng (tập khoá đã đổi)."""

    def on_finished(self, reason, stats):
        """reason: quit | video_end | camera_lost | max_sec | stopped | error. stats = thống kê outbox."""

    def on_error(self, message):
        """Không khởi động được hoặc vòng lặp gặp lỗi."""


@dataclass
class EngineOptions:
    side: str = "1"
    front: str = "0"
    side_video: str = None
    front_video: str = None
    config: str = os.path.join(APP_DIR, "app_config.json")
    events: str = os.path.join(APP_DIR, "out", "events.jsonl")
    metrics_out: str = os.path.join(APP_DIR, "out", "metrics.jsonl")
    outbox: str = os.path.join(APP_DIR, "out", "outbox.db")
    log: str = None
    no_face: bool = False
    max_sec: float = None
    stream_camera: str = None
    stream_rtsp_base: str = "rtsp://127.0.0.1:8554"
    ffmpeg: str = "ffmpeg"
    render_legacy: bool = False        # vẽ vis_side/vis_front kiểu OpenCV cũ (CLI); Qt tự vẽ nên để False
    send: bool = True                  # False = chế độ không đăng nhập: chỉ nhắc tại chỗ, không ghi outbox, không gửi


class _LocalOutbox:
    """Thay Outbox khi EngineOptions.send = False: không ghi gì xuống đĩa."""

    def stats(self):
        return dict(sent=0, pending=0, dead=0)

    def close(self):
        pass


class _LocalSender:
    """Thay Sender khi EngineOptions.send = False (không đăng nhập): không xếp hàng, không gửi."""
    base_url = None
    online = None
    last_error = None

    def enqueue_event(self, ev): pass
    def enqueue_metric(self, m): pass
    def configure(self, *a, **k): pass
    def start(self): pass
    def stop(self, timeout=None): pass
    def status_text(self): return "chua dang nhap, khong gui"


def load_config(path):
    """(AppConfig, model_cfg) – dùng khi cần biết api_base_url trước khi tạo engine."""
    model_cfg = json.load(open(os.path.join(HERE, "posture_config.json"), encoding="utf-8"))
    return AppConfig(path, model_cfg), model_cfg


def draw_distance(frame, cm, status):
    if frame is None:
        return
    txt = f"cach man hinh {cm:.0f} cm" if np.isfinite(cm) else "cach man hinh: --"
    col = {"CANH BAO": (0, 0, 255), "BAD": (0, 165, 255)}.get(status, (255, 255, 255))
    cv2.rectangle(frame, (0, 90), (frame.shape[1], 130), (30, 30, 30), -1)
    cv2.putText(frame, txt, (15, 120), 0, 0.8, col, 2)


def apply_config(cfg, trackers, rem, pres):
    for t in trackers:
        t.configure(alert_sec=cfg["alert_sec"], clear_sec=cfg["clear_sec"],
                    repeat_sec=cfg["repeat_sec"], cooldown_sec=cfg["cooldown_sec"])
    rem.configure(sit_limit_min=cfg["sit_limit_min"], sit_repeat_min=cfg["sit_repeat_min"],
                  eye_break_min=cfg["eye_break_min"])
    pres.away_sec = cfg["away_sec"]


class PostureEngine:
    STATE_EVERY = 0.25          # giây giữa hai lần phát on_state
    SYNC_EVERY = 1.0            # giây giữa hai lần đọc trạng thái gửi (SQLite)

    def __init__(self, opts, cfg=None, model_cfg=None, auth=None, config_sync=None, notifier=None,
                 listener=None, viewer=None):
        self.o = opts
        if cfg is None:
            cfg, model_cfg = load_config(opts.config)
        self.cfg, self.model_cfg = cfg, model_cfg or {}
        self.auth, self.config_sync = auth, config_sync
        self.notifier = notifier if notifier is not None else Notifier(cfg)
        self.listener = listener or EngineListener()
        self.viewer = viewer          # CLI: viewer.show(engine, vis_side, vis_front) -> mã phím hoặc -1
        self.want_frames = False
        self._stop = threading.Event()
        self._recalib = threading.Event()
        self._thread = None
        self.finish_reason = None
        # điền ở _setup()
        self.elog = self.snap = self.sender = self.outbox = self.agg = self.rem = self.pres = None
        self.last_metric = None
        self.now = 0.0
        self.sync_info = {}

    # ---------------------------------------------------------------- điều khiển
    def user_id(self):
        return self.auth.user_id if self.auth else self.cfg["user_id"]

    def start(self):
        """Chạy trong luồng riêng. Lỗi khởi động báo qua listener.on_error."""
        self._thread = threading.Thread(target=self.run_guarded, name="PostureEngine", daemon=True)
        self._thread.start()

    def run_guarded(self):
        """Như run() nhưng không ném lỗi: báo qua listener.on_error/on_finished (dùng cho luồng nền, QThread)."""
        try:
            self.run()
        except EngineError as e:
            self.finish_reason = "error"
            self.listener.on_error(str(e))
            self.listener.on_finished("error", {})
        except Exception as e:                     # không để luồng chết im lặng
            self.finish_reason = "error"
            self.listener.on_error(f"Lỗi không mong muốn: {e}")
            self.listener.on_finished("error", {})

    def stop(self):
        self._stop.set()

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def request_recalibrate(self):
        self._recalib.set()

    def sitting_sec(self):
        return self.rem.sitting_sec(self.now) if self.rem else 0.0

    @property
    def away(self):
        return bool(self.pres and self.pres.away)

    # ---------------------------------------------------------------- khởi tạo
    def _open_cam(self, v):
        v = int(v) if str(v).lstrip("-").isdigit() else v
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

    def _setup(self):
        o, cfg = self.o, self.cfg
        self.sess = ort.InferenceSession(os.path.join(HERE, "posture_transformer.onnx"),
                                         providers=["CPUExecutionProvider"])
        self.WIN, self.FPS = self.model_cfg["window"], self.model_cfg["fps"]
        task = os.path.join(HERE, "pose_landmarker_full.task")

        self.use_video = o.side_video is not None
        is_off = lambda v: (int(v) if str(v).lstrip("-").isdigit() else v) == -1
        self.cap_s = cv2.VideoCapture(o.side_video) if self.use_video else self._open_cam(o.side)
        if not self.cap_s.isOpened():
            raise EngineError("Không mở được camera hông")
        self.cap_f = None
        if o.front_video or (not self.use_video and not is_off(o.front)):
            self.cap_f = cv2.VideoCapture(o.front_video) if o.front_video else self._open_cam(o.front)
            if not self.cap_f.isOpened():
                print("Không mở được cam laptop -> chỉ chạy nhánh cổ/thân")
                self.cap_f = None
        self.det_s = PoseDetector(task)
        self.det_f = PoseDetector(task) if self.cap_f is not None else None
        self.ed = None
        if self.cap_f is not None:
            self.ed = EyeDistance(os.path.join(HERE, "face_landmarker.task"), cfg["camera_hfov_deg"],
                                  use_face=not o.no_face)
            self.ed.focal = cfg["camera_focal_px"]
        self.vid_fps = self.cap_s.get(cv2.CAP_PROP_FPS) or 30

        # cảnh báo + sự kiện
        self.tr_neck, self.tr_tilt, self.tr_dist = (AlertTracker("NECK_TRUNK"), AlertTracker("SHOULDER_TILT"),
                                                    AlertTracker("TOO_CLOSE"))
        self.trackers = (self.tr_neck, self.tr_tilt, self.tr_dist)
        self.pres, self.rem = PresenceTracker(), Reminders()
        apply_config(cfg, self.trackers, self.rem, self.pres)
        self.elog = EventLog(o.events, self.model_cfg.get("version"), wall_t0=time.time(), user_id=self.user_id(),
                             listeners=[self.notifier, self._relay_alert])

        # gửi dữ liệu
        if o.send:
            self.outbox = Outbox(o.outbox)
            self.sender = Sender(self.outbox, cfg["api_base_url"], cfg["api_token"], self.elog.device_id,
                                 interval=cfg["batch_interval_sec"], batch_max=cfg["batch_max"], auth=self.auth)
        else:
            self.outbox, self.sender = _LocalOutbox(), _LocalSender()
        os.makedirs(os.path.dirname(os.path.abspath(o.metrics_out)), exist_ok=True)
        self.metrics_f = open(o.metrics_out, "a", encoding="utf-8")
        self.agg = MetricsAggregator(self._on_metric, self.elog.wall_t0, self.elog.session_id, self.elog.device_id,
                                     self.user_id(), window_sec=cfg["metrics_window_sec"],
                                     model_version=self.model_cfg.get("version"), app_version=EventLog.APP_VERSION)
        self.elog.listeners += [self.sender.enqueue_event, self.agg.on_event]
        self.sender.start()
        self.elog.emit(dict(eventType="SESSION_START", t=0.0, frontCam=self.cap_f is not None,
                            distanceMethod=None if self.ed is None else ("iris" if self.ed.det else "ipd")),
                       config=cfg.snapshot())
        self.snap = dict(pBad=None, neck=None, trunk=None, headPitch=None, rulaB=None, tiltRel=None, distanceCm=None)
        self.logf = open(o.log, "w", encoding="utf-8") if o.log else None
        if self.logf:
            self.logf.write("time,posture,p_bad," + ",".join(FEATURES)
                            + ",rula_b,shoulder,tilt_rel,distance_cm,distance\n")

        self.stream = None
        if o.stream_camera:
            if o.stream_camera == "front" and self.cap_f is None:
                raise EngineError("Camera front chưa mở; không thể truyền hình")
            self.stream = LivePublisher(lambda: self.auth.credentials(cfg["api_base_url"]) if self.auth else
                                        (cfg["api_base_url"], cfg["api_token"]), self.elog.device_id,
                                        o.stream_camera, o.stream_rtsp_base, o.ffmpeg, auth=self.auth)
            self.stream.start()
            print("Live camera enabled:", o.stream_camera, "device:", self.elog.device_id)
        if self.config_sync:
            self.config_sync.start()

    def _on_metric(self, m):
        self.last_metric = m
        self.metrics_f.write(json.dumps(m, ensure_ascii=False) + "\n")
        self.metrics_f.flush()
        self.sender.enqueue_metric(m)
        self.listener.on_metrics(m)

    def _relay_alert(self, ev):
        if ev.get("notify"):
            self.listener.on_alert(ev)

    def _emit(self, events):
        if events:
            self.elog.emit_all(events, snapshot=self.snap, config=self.cfg.snapshot())

    def _start_calib(self, now=None):
        evs = []
        for t in self.trackers:
            evs += t.reset(now, "RECALIBRATE")
        self._emit(evs)
        return dict(L=[], W=[], tilt=[], dpx=[], dkind=[], t0=None)

    # ---------------------------------------------------------------- phát trạng thái
    def _posture_state(self, calibrating):
        if calibrating:
            return STATE_CALIBRATING
        if self.pres.away:
            return STATE_AWAY
        if any(t.status in ("BAD", "CANH BAO") for t in self.trackers):
            return STATE_BAD
        return STATE_GOOD

    def _publish_sync(self):
        st = self.outbox.stats()
        self.sync_info = dict(sent=st.get("sent", 0), pending=st.get("pending", 0), dead=st.get("dead", 0),
                              online=self.sender.online if self.sender.base_url else None,
                              hasServer=bool(self.sender.base_url), text=self.sender.status_text(),
                              lastError=self.sender.last_error,
                              authLost=bool(self.auth is not None and self.auth.lost),
                              lostKind=self.auth.lost_kind if self.auth is not None else None)
        self.listener.on_sync(self.sync_info)

    # ---------------------------------------------------------------- chạy
    def run(self):
        """Chạy tới khi hết video / người dùng thoát / stop(). Trả về lý do kết thúc."""
        try:
            self._setup()
        except BaseException:
            for c in (getattr(self, "cap_s", None), getattr(self, "cap_f", None)):
                if c is not None:
                    c.release()
            raise
        reason = "stopped"
        try:
            reason = self._loop()
        except Exception as e:
            reason = "error"
            print("Engine lỗi:", e)
            self.listener.on_error(f"Lỗi khi xử lý: {e}")
        finally:
            stats = self._shutdown()
        self.finish_reason = reason
        self.listener.on_finished(reason, stats)
        return reason

    def _loop(self):
        o, cfg = self.o, self.cfg
        cap_s, cap_f, det_s, det_f, ed = self.cap_s, self.cap_f, self.det_s, self.det_f, self.ed
        trackers, tr_neck, tr_tilt, tr_dist = self.trackers, self.tr_neck, self.tr_tilt, self.tr_dist
        pres, rem, agg, snap, emit = self.pres, self.rem, self.agg, self.snap, self._emit
        WIN, FPS, sess = self.WIN, self.FPS, self.sess
        use_video, vid_fps = self.use_video, self.vid_fps
        render = o.render_legacy or self.viewer is not None

        cal, side, f, base, tilt_base = self._start_calib(), None, None, None, None
        buf = collections.deque(maxlen=WIN)
        p_hist, t_hist, d_hist = (collections.deque(maxlen=5) for _ in range(3))     # median filter 5 kết quả
        p_med, t_med, d_med, ang, rula_lab = 0.0, np.nan, np.nan, None, None
        last_s = last_f = last_cfg = -1e9
        Ls_draw = Lf_draw = None
        frame_i, t_start, miss, now = 0, time.time(), 0, 0.0
        last_state_t = last_sync_t = -1e9
        last_state = None

        while not self._stop.is_set():
            ok, fs = cap_s.read()
            if not ok:
                if use_video:
                    return "video_end"
                miss += 1
                if miss > 100:
                    print("Mất hình cam hông quá lâu, thoát.")
                    return "camera_lost"
                time.sleep(0.03)
                continue
            miss = 0
            ff = None
            if cap_f is not None:
                okf, ff = cap_f.read()
                if not okf:
                    ff = None
            frame_i += 1
            if self.stream:
                self.stream.submit(fs if o.stream_camera == "side" else ff)
            now = self.now = (frame_i / vid_fps) if use_video else (time.time() - t_start)
            if o.max_sec and now > o.max_sec:
                return "max_sec"
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
            raw = None
            if self.want_frames:      # ảnh sạch (chưa vẽ) để giao diện tự vẽ khung xương
                raw = dict(side=fs.copy(), front=None if ff is None else ff.copy(), Ls=Ls_draw, Lf=Lf_draw)

            # ------------------------------------------------ nạp lại cấu hình mỗi 2 giây
            if now - last_cfg >= 2:
                last_cfg = now
                changed = cfg.reload()
                remote = self.config_sync.take() if self.config_sync else None
                if remote is not None:
                    try:
                        changed |= cfg.apply_remote(remote)
                    except ValueError:
                        print("Cấu hình máy chủ không hợp lệ; giữ cấu hình đang dùng")
                if changed:
                    apply_config(cfg, trackers, rem, pres)
                    if "camera_focal_px" in changed and ed is not None and cfg["camera_focal_px"]:
                        ed.focal = cfg["camera_focal_px"]
                    self.elog.user_id = agg.user_id = self.user_id()
                    if changed & {"api_base_url", "api_token", "batch_interval_sec", "batch_max"}:
                        self.sender.configure(cfg["api_base_url"], cfg["api_token"], cfg["batch_interval_sec"],
                                              cfg["batch_max"])
                    if "metrics_window_sec" in changed:
                        agg.flush()
                        agg.window = int(cfg["metrics_window_sec"])
                    self.elog.emit(dict(eventType="CONFIG_APPLIED", t=now, changedKeys=sorted(changed)),
                                   config=cfg.snapshot())
                    print("Đã áp dụng cấu hình mới:", sorted(changed))
                    self.listener.on_config(set(changed))

            calibrating = base is None
            if calibrating:  # ======================================== hiệu chỉnh
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
                        cal = self._start_calib()
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
                        self.elog.emit(dict(eventType="CALIBRATED", t=now, side="left" if side == 0 else "right",
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
                vis_s = vis_f = None
                if render:
                    vis_s = draw_side(fs, Ls_draw, side, "...", 0, None, None, calib_left=lc)
                    vis_f = draw_front(ff, Lf_draw, "...", None, calib_left=lc) if ff is not None else None

            else:  # ================================================= theo dõi
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
                                c = None                  # góc phi lý = bắt sai điểm khớp -> coi như không thấy
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
                            snap.update(pBad=p_med, rulaB=None if rula_lab is None or not np.isfinite(rula_lab)
                                        else int(rula_lab))
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
                        cm_ok = dist_ok(float(cm))        # ngoài 20–150 cm = đo sai, bỏ mẫu
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

                if sample_s:                              # cùng mẫu với log.csv -> gộp metrics 60 giây
                    agg.add(now, present=not pres.away and (Ls is not None or Lf is not None),
                            neck_status=tr_neck.status, p_bad=p_med if len(buf) == WIN else None, ang=ang,
                            tilt_rel=t_med if tilt_base is not None else None,
                            tilt_status=tr_tilt.status if tilt_base is not None else None,
                            dist_cm=d_med if ed is not None else None,
                            dist_status=tr_dist.status if ed is not None else None)
                if self.logf and sample_s:
                    self.logf.write(f"{now:.2f},{tr_neck.status},{p_med:.3f},"
                                    + ",".join(f"{ang[k]:.2f}" if ang else "" for k in FEATURES)
                                    + f",{rula_lab},{tr_tilt.status if tilt_base is not None else ''},{t_med:.2f}"
                                    + f",{d_med:.1f},{tr_dist.status if ed is not None else ''}\n")
                vis_s = vis_f = None
                if render:
                    vis_s = draw_side(fs, Ls_draw, side, "..." if pres.away else tr_neck.status, p_med, ang, rula_lab)
                    if ff is not None:
                        vis_f = draw_front(ff, Lf_draw, tr_tilt.status if tilt_base is not None and not pres.away
                                           else "...", t_med)
                        draw_distance(vis_f, d_med, tr_dist.status)

            # ------------------------------------------------ phát cho giao diện
            wall = time.time()
            st = self._posture_state(calibrating)
            if st != last_state or wall - last_state_t >= self.STATE_EVERY:
                last_state, last_state_t = st, wall
                self.listener.on_state(dict(
                    state=st, calibrating=calibrating, calibLeft=max(left, 0) if calibrating else 0.0,
                    sittingSec=rem.sitting_sec(now), away=pres.away,
                    distanceCm=None if not np.isfinite(d_med) or ed is None else float(d_med),
                    neck=tr_neck.status, tilt=tr_tilt.status if tilt_base is not None else "...",
                    distance=tr_dist.status if ed is not None else "...", pBad=snap.get("pBad")))
            if wall - last_sync_t >= self.SYNC_EVERY:
                last_sync_t = wall
                self._publish_sync()
            if raw is not None:
                raw.update(side_idx=side, vis_side=vis_s, vis_front=vis_f)
                self.listener.on_frame(raw)
            if self.viewer is not None:
                k = self.viewer.show(self, vis_s, vis_f, frame_i)
                if k == ord("q"):
                    return "quit"
                if k == ord("c"):
                    self._recalib.set()
            if self._recalib.is_set():
                self._recalib.clear()
                cal, base, tilt_base = self._start_calib(now), None, None
        return "stopped"

    # ---------------------------------------------------------------- kết thúc phiên
    def _shutdown(self):
        now = self.now
        if self.config_sync:
            self.config_sync.stop()
        if self.stream:
            self.stream.stop()
        evs = []
        for t in self.trackers:
            evs += t.reset(now, "SESSION_END")
        self._emit(evs)
        self.elog.emit(dict(eventType="SESSION_END", t=now, durationSec=round(now, 1),
                            alertCount={t.alert_type: t.count for t in self.trackers}))
        self.elog.close()
        self.agg.flush()                                  # cửa sổ metrics cuối (chưa đủ 60 giây)
        self.metrics_f.close()
        self.sender.stop(timeout=None)                    # Chờ worker xong trước khi đóng SQLite, kể cả refresh.
        st = self.outbox.stats()
        self.outbox.close()
        print(f"Outbox: đã gửi {st['sent']}, còn chờ {st['pending']}, bị từ chối {st['dead']}")
        for d in (self.det_s, self.det_f, self.ed):      # đóng model MediaPipe trước khi Python thoát
            try:
                if d is not None and d.det is not None and hasattr(d.det, "close"):
                    d.det.close()
            except Exception:
                pass
        self.cap_s.release()
        if self.cap_f is not None:
            self.cap_f.release()
        if self.logf:
            self.logf.close()
        print("Sự kiện đã ghi vào", self.o.events)
        return st
