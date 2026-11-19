"""Công cụ quay dữ liệu 2 camera cho kịch bản 35 clip (thay OBS + ffmpeg). Xem TaiLieu/HuongDan_QuayDuLieu.md.

    python posture_model/record_session.py --person P01 --session S01 --side 1 --front 0 [--out D:\KLTN\video_tach]
        [--from GOOD_01] [--only SHOULDER_TILT_L,SHOULDER_TILT_R] [--side-video a.mp4 --front-video b.mp4]

Ra file P01_S01_<CLIP>_SIDE.mp4, _FRONT.mp4, _frames.csv và sessions.csv trong thư mục --out (chỉ lưu trên máy)."""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _s in (sys.stdout, sys.stderr):                       # console Windows cp1252 không in được tiếng Việt
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_OUT = r"D:\KLTN\video_tach"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", help="mã người, vd P01")
    ap.add_argument("--session", help="mã buổi, vd S01")
    ap.add_argument("--compress-dir", help="chỉ nén lại các _SIDE/_FRONT.mp4 đã quay trong thư mục này sang H.264 (cần ffmpeg), rồi thoát")
    ap.add_argument("--ffmpeg", help="đường dẫn ffmpeg (mặc định: biến FFMPEG, PATH, rồi gói imageio-ffmpeg)")
    ap.add_argument("--no-compress", action="store_true", help="không nén nền sau mỗi clip (giữ file mp4v gốc, ~110 MB/phút)")
    ap.add_argument("--check-cams", action="store_true",
                    help="chỉ đo FPS thật của từng camera ở nhiều cấu hình, in bảng + đề xuất, rồi thoát")
    ap.add_argument("--check-seconds", type=float, default=10.0, help="giây đo mỗi cấu hình khi --check-cams (mặc định 10)")
    ap.add_argument("--side-size", help="cỡ hình camera hông, vd 1280x720 (mặc định theo cam_profile.json hoặc 1280x720)")
    ap.add_argument("--front-size", help="cỡ hình camera laptop, vd 640x480 nếu cam laptop không đạt 30 fps ở 720p")
    ap.add_argument("--no-profile", action="store_true", help="không dùng recording/cam_profile.json (kết quả --check-cams)")
    ap.add_argument("--side", default="1", help="camera hông (số hoặc đường dẫn); iPhone qua Iriun. Mặc định 1")
    ap.add_argument("--front", default="0", help="camera laptop (số, hoặc -1 = không dùng). Mặc định 0")
    ap.add_argument("--side-video", help="chạy thử: dùng file video thay camera hông")
    ap.add_argument("--front-video", help="chạy thử: dùng file video thay camera laptop")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"thư mục ra (mặc định {DEFAULT_OUT})")
    ap.add_argument("--from", dest="start_from", help="bắt đầu từ clip này (tên hoặc mã, vd GOOD_01 / A2)")
    ap.add_argument("--only", help="chỉ quay các clip này, cách nhau dấu phẩy (vd SHOULDER_TILT_L,E2)")
    ap.add_argument("--resume", choices=["ask", "yes", "no"], default="ask", help="buổi quay dở: hỏi / tiếp / bắt đầu lại")
    ap.add_argument("--no-face", action="store_true", help="đo khoảng cách bằng 2 mắt của Pose, không tải Face Landmarker")
    ap.add_argument("--script", help="file kịch bản JSON khác (mặc định recording/script_v2.json)")
    ap.add_argument("--countdown", type=float, default=3.0, help="giây đếm ngược trước khi ghi (mặc định 3)")
    a = ap.parse_args(argv)
    if not (a.check_cams or a.compress_dir) and not (a.person and a.session):
        ap.error("cần --person và --session (trừ khi dùng --check-cams hoặc --compress-dir)")
    return a


def cam_configs(args):
    """CamConfig cho từng camera: mặc định MJPG + DSHOW trước 1280x720; cam_profile.json (từ --check-cams) đè mặc định;
    --side-size / --front-size đè cỡ hình."""
    from recording.capture import CamConfig, parse_size
    from recording.check_cams import load_profile
    prof = {} if args.no_profile else load_profile()
    out = {}
    for cam, size in (("side", args.side_size), ("front", args.front_size)):
        cfg = prof.get(cam, CamConfig())
        if size:
            cfg = CamConfig(cfg.backend, cfg.fourcc, parse_size(size), cfg.order)
        out[cam] = cfg
    return out


def build(args):
    """Mở camera + thread đọc + thread phân tích + Session. Trả (session, đóng_hết)."""
    from distance import EyeDistance
    from realtime_posture import PoseDetector
    from recording.analyzer import Analyzer
    from recording.capture import CameraSource, opener_for
    from recording.compress import Compressor
    from recording.script import load_script, select_clips
    from recording.session import Session

    full = load_script(args.script) if args.script else load_script()
    clips = select_clips(full, args.start_from, args.only)
    if not clips:
        raise SystemExit("Không có clip nào để quay (kiểm --from / --only).")
    calib = next((c for c in full if c.is_calibration), None)
    side_spec = args.side_video or args.side
    front_spec = args.front_video or (None if str(args.front) == "-1" else args.front)
    cfgs = cam_configs(args)
    side = CameraSource("hông", side_spec, opener=opener_for(cfgs["side"])).start()
    front = None
    try:
        if front_spec is not None:
            front = CameraSource("laptop", front_spec, opener=opener_for(cfgs["front"])).start()
    except Exception:
        side.close()
        raise
    task = os.path.join(HERE, "pose_landmarker_full.task")
    ed = EyeDistance(os.path.join(HERE, "face_landmarker.task"), use_face=not args.no_face) if front else None
    det_s = PoseDetector(task)
    det_f = PoseDetector(task) if front else None
    an = Analyzer(side, front, det_s, det_f, ed).start()
    from recording.ui import make_beeper
    comp = None if args.no_compress else Compressor(args.ffmpeg)
    sess = Session(clips, args.out, args.person, args.session, dict(side=side, front=front), an, ed=ed,
                   calib_clip=calib, beeper=make_beeper(), countdown=args.countdown, compressor=comp,
                   full_seconds=sum(c.duration for c in full))
    if comp is not None:
        from recording.compress import clean_stale
        clean_stale(args.out)

    def shutdown():
        if comp is not None and comp.busy:
            print(f"Đang nén nốt {comp.busy} file, đừng tắt máy…")
            comp.wait_all()
        an.stop()
        side.close()
        if front:
            front.close()
    return sess, shutdown


def main(argv=None):
    args = parse_args(argv)
    if args.compress_dir:
        from recording.compress import compress_dir
        return compress_dir(args.compress_dir, args.ffmpeg)
    if args.check_cams:
        from recording.check_cams import main as check_main
        return check_main(args.side_video or args.side, args.front_video or args.front, args.check_seconds)
    from PySide6.QtWidgets import QApplication
    from recording.ui import RecorderWindow, ask_resume
    from ui.theme import apply_theme
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    try:
        sess, shutdown = build(args)
    except RuntimeError as e:
        print("LỖI:", e)
        return 2
    if not (args.start_from or args.only):
        txt = sess.resume_text()
        if txt and (args.resume == "yes" or (args.resume == "ask" and ask_resume(None, txt))):
            sess.resume()
    elif sess.saved_progress():
        sess.resume()                                   # --from / --only: giữ baseline đã lưu nhưng đứng ở clip được chọn
        sess.idx = 0
    win = RecorderWindow(sess)
    win.showMaximized()
    try:
        return app.exec()
    finally:
        shutdown()


if __name__ == "__main__":
    sys.exit(main())
