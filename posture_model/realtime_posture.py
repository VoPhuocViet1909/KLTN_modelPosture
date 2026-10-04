"""
Chạy realtime với 2 camera:
  - Cam hông (đặt ~90°, ngang vai)  -> MediaPipe Pose -> góc cổ/thân -> Transformer (ONNX) -> GOOD/BAD
  - Cam laptop (chính diện)         -> MediaPipe Pose -> công thức lệch vai (không train) -> SHOULDER_TILT
  -> median filter + debounce (+ cooldown) cho từng nhánh -> cảnh báo.

  python realtime_posture.py --side 1 --front 0                 # cam hông = webcam 1, cam laptop = webcam 0
  python realtime_posture.py --side 0 --front -1                # chỉ cam hông (tắt đo lệch vai)
  python realtime_posture.py --side-video hong.mp4 --front-video truoc.mp4   # chạy thử trên 2 video quay cùng lúc

Phím: q = thoát, c = hiệu chỉnh lại (ngồi thẳng, nhìn màn hình 10 giây).
"""
import argparse, collections, json, os, time, urllib.request
os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
import cv2, numpy as np, onnxruntime as ort
from posture_features import (FEATURES, IDX, choose_side, facing_sign, sequence_angles, calibration_baseline,
                              apply_calibration, to_model_input, rula_frame_label, shoulder_tilt)

HERE = os.path.dirname(os.path.abspath(__file__))
POSE_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
            "pose_landmarker_full/float16/latest/pose_landmarker_full.task")


# ------------------------------------------------------------------ MediaPipe (Tasks API, dự phòng Solutions)
class PoseDetector:
    def __init__(self, task_path):
        import mediapipe as mp
        self.mp = mp
        try:
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision
            if not os.path.exists(task_path):
                print("Đang tải pose_landmarker_full.task ..."); urllib.request.urlretrieve(POSE_URL, task_path)
            opts = vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=task_path),
                                                running_mode=vision.RunningMode.VIDEO, num_poses=1)
            self.det = vision.PoseLandmarker.create_from_options(opts); self.mode = "tasks"
        except Exception as e:
            print("Tasks API lỗi (", e, ") -> dùng mp.solutions.pose")
            self.det = mp.solutions.pose.Pose(model_complexity=1, smooth_landmarks=True); self.mode = "solutions"
        self.last_ts = -1

    def __call__(self, frame_bgr, ts_ms):
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self.mode == "tasks":
            ts_ms = max(ts_ms, self.last_ts + 1); self.last_ts = ts_ms      # timestamp phải tăng dần
            r = self.det.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), ts_ms)
            if not r.pose_landmarks:
                return None, None
            lm, wl = r.pose_landmarks[0], r.pose_world_landmarks[0]
        else:
            r = self.det.process(rgb)
            if not r.pose_landmarks:
                return None, None
            lm, wl = r.pose_landmarks.landmark, r.pose_world_landmarks.landmark
        L = np.array([[p.x * w, p.y * h, getattr(p, "visibility", 1.0) or 0.0] for p in lm], np.float32)
        W = np.array([[p.x, p.y, p.z] for p in wl], np.float32)
        return L, W


# ------------------------------------------------------------------ debounce + cooldown
class Debounce:
    """bad=True/False/None (None = không rõ, giữ nguyên). BAD liên tục >= alert_sec -> CANH BAO;
    GOOD liên tục >= clear_sec -> GOOD. Sự kiện cảnh báo (in/bíp/gửi server) cách nhau >= cooldown."""

    def __init__(self, alert_sec, clear_sec, cooldown):
        self.alert_sec, self.clear_sec, self.cooldown = alert_sec, clear_sec, cooldown
        self.reset()

    def reset(self):
        self.status, self.bad_since, self.good_since, self.last_event = "...", None, None, -1e9

    def update(self, bad, now):
        event = False
        if bad is True:
            self.good_since = None
            self.bad_since = now if self.bad_since is None else self.bad_since
            if now - self.bad_since >= self.alert_sec:
                if self.status != "CANH BAO" and now - self.last_event >= self.cooldown:
                    event, self.last_event = True, now
                self.status = "CANH BAO"
            elif self.status != "CANH BAO":
                self.status = "BAD"
        elif bad is False:
            self.bad_since = None
            self.good_since = now if self.good_since is None else self.good_since
            if now - self.good_since >= self.clear_sec:
                self.status = "GOOD"
        return event


COL = {"GOOD": (60, 200, 60), "BAD": (0, 165, 255), "CANH BAO": (0, 0, 255), "...": (180, 180, 180)}


def draw_side(frame, L, side, status, prob, ang, rula_lab, calib_left=None):
    if L is not None and side is not None:
        pts = {k: tuple(int(v) for v in L[IDX[k][side], :2]) for k in IDX}
        for a, b in [("ear", "shoulder"), ("shoulder", "hip"), ("ear", "eye")]:
            cv2.line(frame, pts[a], pts[b], (255, 255, 255), 3)
        for p in pts.values():
            cv2.circle(frame, p, 6, (0, 200, 255), -1)
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 90), (30, 30, 30), -1)
    cv2.putText(frame, "CAM HONG - co / than", (15, 25), 0, 0.7, (200, 200, 200), 2)
    if calib_left is not None:
        cv2.putText(frame, f"HIEU CHINH: ngoi thang... {calib_left:.0f}s", (15, 70), 0, 1.0, (0, 255, 255), 2)
        return frame
    cv2.putText(frame, status, (15, 75), 0, 1.4, COL[status], 4)
    txt = f"P(BAD)={prob:.2f}"
    if ang is not None:
        txt += f" | co {ang['neck']:+.0f} than {ang['trunk']:+.0f} dau {ang['head_pitch']:+.0f}"
    if rula_lab is not None and np.isfinite(rula_lab):
        txt += f" | RULA-B: {'BAD' if rula_lab else 'GOOD'}"
    cv2.putText(frame, txt, (260, 70), 0, 0.65, (255, 255, 255), 2)
    if status == "CANH BAO":
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 12)
    return frame


def draw_front(frame, L, status, tilt_rel, calib_left=None):
    if L is not None:
        a, b = tuple(int(v) for v in L[11, :2]), tuple(int(v) for v in L[12, :2])
        cv2.line(frame, a, b, (255, 255, 255), 3)
        for p in (a, b):
            cv2.circle(frame, p, 7, (0, 200, 255), -1)
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 90), (30, 30, 30), -1)
    cv2.putText(frame, "CAM LAPTOP - lech vai", (15, 25), 0, 0.7, (200, 200, 200), 2)
    if calib_left is not None:
        cv2.putText(frame, f"HIEU CHINH... {calib_left:.0f}s", (15, 70), 0, 1.0, (0, 255, 255), 2)
        return frame
    label = {"GOOD": "VAI CAN", "BAD": "LECH VAI", "CANH BAO": "LECH VAI!", "...": "..."}[status]
    cv2.putText(frame, label, (15, 75), 0, 1.4, COL[status], 4)
    if tilt_rel is not None and np.isfinite(tilt_rel):
        cv2.putText(frame, f"lech {tilt_rel:+.1f} do", (330, 70), 0, 0.8, (255, 255, 255), 2)
    if status == "CANH BAO":
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 12)
    return frame


def hstack(a, b, height=540):
    rs = lambda f: cv2.resize(f, (int(f.shape[1] * height / f.shape[0]), height))
    return np.hstack([rs(a), rs(b)]) if b is not None else rs(a)


# ------------------------------------------------------------------ chính
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="1", help="cam bên hông (~90°): số webcam (1) hoặc link điện thoại (http://192.168.1.5:8080/video)")
    ap.add_argument("--front", default="0", help="cam laptop chính diện: số webcam hoặc link, -1 = tắt")
    ap.add_argument("--side-video", default=None)
    ap.add_argument("--front-video", default=None)
    ap.add_argument("--calib-sec", type=float, default=10)
    ap.add_argument("--alert-sec", type=float, default=5, help="BAD kéo dài bao lâu mới cảnh báo")
    ap.add_argument("--clear-sec", type=float, default=3, help="GOOD kéo dài bao lâu mới tắt cảnh báo")
    ap.add_argument("--cooldown", type=float, default=60, help="khoảng cách tối thiểu giữa 2 cảnh báo cùng loại")
    ap.add_argument("--log", default=None, help="ghi CSV kết quả")
    a = ap.parse_args()

    cfg = json.load(open(os.path.join(HERE, "posture_config.json")))
    sess = ort.InferenceSession(os.path.join(HERE, "posture_transformer.onnx"), providers=["CPUExecutionProvider"])
    WIN, FPS, THR = cfg["window"], cfg["fps"], cfg["threshold"]
    T_ON, T_OFF = cfg["shoulder_tilt_on"], cfg["shoulder_tilt_off"]
    task = os.path.join(HERE, "pose_landmarker_full.task")

    use_video = a.side_video is not None
    src = lambda v: int(v) if str(v).lstrip("-").isdigit() else v      # số webcam hoặc link stream
    def open_cam(v):
        v = src(v)
        if isinstance(v, str):                                             # link stream điện thoại
            c = cv2.VideoCapture(v); c.set(cv2.CAP_PROP_BUFFERSIZE, 1); return c
        for api in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_FFMPEG, cv2.CAP_ANY):             # Windows: DirectShow ổn định hơn MSMF
            c = cv2.VideoCapture(v, api)
            if c.isOpened():
                for _ in range(15):                                        # bỏ vài khung rỗng lúc cam vừa bật
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
            print("Không mở được cam laptop -> chỉ chạy nhánh cổ/thân"); cap_f = None
    det_s = PoseDetector(task)
    det_f = PoseDetector(task) if cap_f is not None else None
    vid_fps = cap_s.get(cv2.CAP_PROP_FPS) or 30

    logf = open(a.log, "w", encoding="utf-8") if a.log else None
    if logf:
        logf.write("time,posture,p_bad," + ",".join(FEATURES) + ",rula_b,shoulder,tilt_rel\n")

    deb_p = Debounce(a.alert_sec, a.clear_sec, a.cooldown)          # nhánh cổ/thân
    deb_t = Debounce(a.alert_sec, a.clear_sec, a.cooldown)          # nhánh lệch vai

    def start_calib():
        deb_p.reset(); deb_t.reset()
        return dict(L=[], W=[], tilt=[], t0=None)

    cal, side, f, base, tilt_base = start_calib(), None, None, None, None
    buf = collections.deque(maxlen=WIN)
    p_hist, t_hist = collections.deque(maxlen=5), collections.deque(maxlen=5)      # median filter 5 kết quả
    p_med, t_med, ang, rula_lab = 0.0, np.nan, None, None
    last_s = last_f = -1e9
    Ls_draw = Lf_draw = None
    frame_i, t_start = 0, time.time()

    while True:
        ok, fs = cap_s.read()
        if not ok:
            if use_video:
                break
            miss = globals().setdefault("_miss", [0]); miss[0] += 1
            if miss[0] > 100:                                              # cam mất hình ~vài giây -> thoát
                print("Mất hình cam hông quá lâu, thoát."); break
            time.sleep(0.03); continue
        globals().setdefault("_miss", [0])[0] = 0
        ff = None
        if cap_f is not None:
            okf, ff = cap_f.read()
            if not okf:
                ff = None
        frame_i += 1
        now = (frame_i / vid_fps) if use_video else (time.time() - t_start)
        ts = int(now * 1000)
        sample_s = now - last_s >= 1.0 / FPS                      # lấy mẫu ~10 fps như lúc train
        sample_f = ff is not None and now - last_f >= 1.0 / FPS
        Ls, Ws = det_s(fs, ts) if sample_s else (None, None)
        Lf = det_f(ff, ts)[0] if sample_f else None
        if sample_s: last_s, Ls_draw = now, Ls                   # giữ khung xương giữa 2 lần lấy mẫu để vẽ
        if sample_f: last_f, Lf_draw = now, Lf

        if base is None:                                          # ---------- hiệu chỉnh
            if cal["t0"] is None:
                cal["t0"] = now
            if Ls is not None:
                cal["L"].append(Ls); cal["W"].append(Ws)
            if Lf is not None:
                cal["tilt"].append(shoulder_tilt(Lf))
            left = a.calib_sec - (now - cal["t0"])
            if left <= 0:
                if len(cal["L"]) < 10:
                    print("Cam hông không thấy người đủ lâu, hiệu chỉnh lại."); cal = start_calib()
                else:
                    Lc, Wc = np.stack(cal["L"]), np.stack(cal["W"])
                    side = choose_side(Lc, Wc); f = facing_sign(Lc, side)
                    base = calibration_baseline(sequence_angles(Lc, side, f))
                    tilts = np.array(cal["tilt"], float)
                    tilt_base = float(np.nanmedian(tilts)) if np.isfinite(tilts).sum() >= 5 else None
                    print(f"Hiệu chỉnh xong: phía {'trái' if side == 0 else 'phải'}, baseline",
                          {k: round(v, 1) for k, v in base.items()},
                          "| lệch vai baseline:", None if tilt_base is None else round(tilt_base, 1))
                    buf.clear(); p_hist.clear(); t_hist.clear()
            lc = max(left, 0)
            vis_s = draw_side(fs, Ls_draw, side, "...", 0, None, None, calib_left=lc)
            vis_f = draw_front(ff, Lf_draw, "...", None, calib_left=lc) if ff is not None else None
        else:                                                     # ---------- theo dõi
            now_s = time.strftime("%H:%M:%S")
            # nhánh 1: cổ / thân (student)
            if sample_s:
                if Ls is not None:
                    c = apply_calibration(sequence_angles(Ls[None], side, f), base)
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
                    bad = True if p_med >= THR + 0.1 else False if p_med <= THR - 0.1 else None
                    if deb_p.update(bad, now):
                        print(f"[{now_s}] CẢNH BÁO tư thế cổ/thân (P(BAD)={p_med:.2f})")
            # nhánh 2: lệch vai (công thức)
            tilt_rel = np.nan
            if sample_f and tilt_base is not None:
                tv = shoulder_tilt(Lf) if Lf is not None else np.nan
                if np.isfinite(tv):
                    t_hist.append(tv - tilt_base)
                if t_hist:
                    t_med = float(np.median(t_hist))
                    bad = True if abs(t_med) > T_ON else False if abs(t_med) < T_OFF else None
                    if deb_t.update(bad if np.isfinite(tv) else None, now):
                        print(f"[{now_s}] CẢNH BÁO lệch vai ({t_med:+.1f}°)")
            if logf and sample_s:
                logf.write(f"{now:.2f},{deb_p.status},{p_med:.3f},"
                           + ",".join(f"{ang[k]:.2f}" if ang else "" for k in FEATURES)
                           + f",{rula_lab},{deb_t.status if tilt_base is not None else ''},{t_med:.2f}\n")
            vis_s = draw_side(fs, Ls_draw, side, deb_p.status, p_med, ang, rula_lab)
            vis_f = draw_front(ff, Lf_draw, deb_t.status if tilt_base is not None else "...", t_med) if ff is not None else None

        cv2.imshow("Posture monitor (q: thoat, c: hieu chinh lai)", hstack(vis_s, vis_f))
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("c"):
            cal, base, tilt_base = start_calib(), None, None
    cap_s.release()
    if cap_f is not None:
        cap_f.release()
    cv2.destroyAllWindows()
    if logf:
        logf.close()


if __name__ == "__main__":
    main()
