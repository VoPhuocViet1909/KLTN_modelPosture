"""Kiểm camera: đo FPS thật của từng camera ở nhiều cấu hình (backend DSHOW / MSMF, FOURCC MJPG / mặc định, 1280x720 / 640x480,
có và không chạy MediaPipe), in bảng và đề xuất cấu hình tốt nhất cho từng camera.

    python posture_model/record_session.py --check-cams --side 1 --front 0 [--check-seconds 10]

Hai camera chạy cùng lúc (như khi quay thật). Kết quả đề xuất lưu ở recording/cam_profile.json (riêng từng máy, không commit);
record_session.py tự dùng file này khi mở camera, trừ khi ghi đè bằng --side-size / --front-size / --no-profile."""
import itertools
import json
import os
import time

from recording.capture import FPS, CamConfig, CameraSource, opener_for

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(HERE, "cam_profile.json")
BACKENDS = ("DSHOW", "MSMF")
FOURCCS = ("MJPG", None)
SIZES = ((1280, 720), (640, 480))
GOOD_FPS = 27.0                  # như ngưỡng cảnh báo của công cụ quay
WARMUP_SEC = 1.0                 # bỏ 1 giây đầu (camera đang lấy sáng / nạp MediaPipe)


def all_configs():
    """Thứ tự cũng là thứ tự ưu tiên khi hai cấu hình bằng nhau: DSHOW, MJPG, độ phân giải lớn."""
    return [CamConfig(b, f, s) for b, f, s in itertools.product(BACKENDS, FOURCCS, SIZES)]


def measure_config(sides, cfg, use_mp, seconds, detector_factory=None, opener_factory=opener_for):
    """sides: {'side': spec, 'front': spec hoặc None}. Trả {cam: {'fps', 'size'}} (fps None nếu không mở được / không có khung)."""
    srcs, out = {}, {}
    for cam, spec in sides.items():
        if spec is None:
            continue
        try:
            srcs[cam] = CameraSource(cam, spec, opener=opener_factory(cfg)).start()
        except RuntimeError:
            out[cam] = dict(fps=None, size=None)
    analyzer = None
    try:
        if use_mp and srcs:
            from recording.analyzer import Analyzer
            mk = detector_factory or _real_detector
            analyzer = Analyzer(srcs.get("side"), srcs.get("front"), mk(), mk() if "front" in srcs else None).start()
        time.sleep(WARMUP_SEC)
        n0, t0 = {c: s.count for c, s in srcs.items()}, time.perf_counter()
        time.sleep(seconds)
        dt = time.perf_counter() - t0
        for cam, s in srcs.items():
            lt = s.latest()
            black = lt is not None and float(lt[1].mean()) < 1.0            # hình đen: camera bị chặn (quyền riêng tư) / chưa có hình
            out[cam] = dict(fps=(s.count - n0[cam]) / dt, size=s.size, black=black)
    finally:
        if analyzer:
            analyzer.stop()
        for s in srcs.values():
            s.close()
    return out


def _real_detector():
    from realtime_posture import PoseDetector
    return PoseDetector(os.path.join(os.path.dirname(HERE), "pose_landmarker_full.task"))


def run_check(sides, seconds=10.0, configs=None, mp_modes=(False, True), log=print, **kw):
    """Chạy mọi cấu hình. Trả list dòng: dict(cfg, mp, side={fps,size}, front={fps,size})."""
    configs = configs or all_configs()
    rows = []
    total = len(configs) * len(mp_modes)
    for i, (cfg, mp) in enumerate(itertools.product(configs, mp_modes), 1):
        log(f"[{i}/{total}] {cfg.label()}  MediaPipe {'bật' if mp else 'tắt'} ...")
        res = measure_config(sides, cfg, mp, seconds, **kw)
        rows.append(dict(cfg=cfg, mp=mp, **res))
        time.sleep(0.5)                                      # cho driver nhả camera
    return rows


def pick_best(rows, cam):
    """Cấu hình tốt nhất cho 1 camera: FPS cao nhất khi CÓ chạy MediaPipe (đúng lúc quay thật); chênh dưới 1 fps thì lấy cấu hình
    đứng trước (ưu tiên DSHOW + MJPG + độ phân giải lớn). Trả (CamConfig, fps) hoặc None nếu không cấu hình nào mở được."""
    cand = [(r["cfg"], r[cam]["fps"]) for r in rows
            if r["mp"] and r.get(cam) and r[cam]["fps"] is not None and not r[cam].get("black")]
    if not cand:
        return None
    top = max(f for _, f in cand)
    return next((c, f) for c, f in cand if f >= top - 1.0)


def format_table(rows, cams=("side", "front")):
    names = {"side": "hông", "front": "laptop"}
    head = f"{'Cấu hình (backend/FOURCC/cỡ)':<30}{'MediaPipe':<11}" + "".join(f"{'FPS ' + names[c]:<14}" for c in cams)
    lines = [head, "-" * len(head)]
    for r in rows:
        cells = []
        for c in cams:
            v = r.get(c)
            cells.append("không mở được" if v is None or v["fps"] is None else f"{v['fps']:.1f}"
                         + (" HÌNH ĐEN" if v.get("black") else " ✓" if v["fps"] >= GOOD_FPS else ""))
        lines.append(f"{r['cfg'].label():<30}{'bật' if r['mp'] else 'tắt':<11}" + "".join(f"{x:<14}" for x in cells))
    return "\n".join(lines)


def recommend(rows, cams=("side", "front")):
    """Văn bản đề xuất + dict profile {cam: {backend, fourcc, size}} (chỉ cam có kết quả)."""
    names = {"side": "hông", "front": "laptop"}
    lines, profile = [], {}
    for c in cams:
        best = pick_best(rows, c)
        if best is None and any(r.get(c) and r[c].get("black") for r in rows):
            lines.append(f"Camera {names[c]}: mở được nhưng hình ĐEN và chỉ ~1 fps ở mọi cấu hình: camera đang bị chặn (Cài đặt Windows > "
                         "Quyền riêng tư > Camera, nắp che / phím tắt tắt camera, Iriun chưa kết nối điện thoại) hoặc ứng dụng khác đang giữ. "
                         "Chưa thể chọn cấu hình, sửa xong chạy lại --check-cams.")
            continue
        elif best is None:
            lines.append(f"Camera {names[c]}: không cấu hình nào mở được. Kiểm chỉ số camera, dây cắm / Iriun, và đóng ứng dụng khác.")
            continue
        cfg, fps = best
        profile[c] = dict(backend=cfg.backend, fourcc=cfg.fourcc, size=list(cfg.size), fps=round(fps, 1))
        ok = "ĐẠT" if fps >= GOOD_FPS else f"CHƯA ĐẠT {GOOD_FPS:.0f} fps"
        lines.append(f"Camera {names[c]}: tốt nhất {cfg.label()} -> {fps:.1f} fps ({ok}).")
        if fps < GOOD_FPS:
            if cfg.size[0] > 640:
                lines.append(f"   Thử --{c}-size 640x480 (cam laptop chỉ dùng cho vai / khoảng cách nên 640x480 là đủ).")
            lines.append("   Tắt ứng dụng khác dùng camera, cắm USB 3 / cổng khác; Iriun: dùng USB thay Wi-Fi, tăng sáng (thiếu sáng làm webcam tự hạ FPS).")
    return "\n".join(lines), profile


def save_profile(profile, path=PROFILE_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=1)


def load_profile(path=PROFILE_PATH):
    """{'side': CamConfig, 'front': CamConfig} từ cam_profile.json; {} nếu chưa có / hỏng."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {c: CamConfig(v["backend"], v["fourcc"], tuple(v["size"])) for c, v in raw.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def main(side, front, seconds=10.0, save=True):
    sides = dict(side=side, front=None if str(front) == "-1" else front)
    print(f"Kiểm camera: hông={side}, laptop={front}; mỗi cấu hình {seconds:g} s, "
          f"{len(all_configs()) * 2} lượt đo (~{int(len(all_configs()) * 2 * (seconds + 2.5))} s). Đừng dùng camera ở ứng dụng khác.")
    rows = run_check(sides, seconds)
    cams = [c for c in ("side", "front") if sides.get(c) is not None]
    print()
    print(format_table(rows, cams))
    text, profile = recommend(rows, cams)
    print()
    print(text)
    if profile and save:
        save_profile(profile)
        print(f"\nĐã lưu {PROFILE_PATH}: record_session.py sẽ mở camera theo cấu hình này.")
    return 0
