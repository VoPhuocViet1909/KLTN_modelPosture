"""Dung lượng ổ cho video quay: còn trống bao nhiêu, ước tính một buổi nặng bao nhiêu, đủ cho mấy buổi."""
import csv
import os
import shutil

import cv2

LOW_BYTES = 5e9                      # dưới 5 GB thì cảnh báo đỏ
RAW_SESSION_BYTES = 77e9 / 30        # đo thực tế: 30 buổi chưa nén ~77 GB
COMPRESSED_SESSION_BYTES = 0.9e9     # ước tính H.264 CRF 23, 2 cam 720p (thay bằng số đo khi đã có file nén trong thư mục)
MIN_MEASURE_SEC = 120.0              # ít hơn chừng này giây video đã quay thì chưa đủ để đo, dùng số mặc định


def _is_h264(path):
    cap = cv2.VideoCapture(path)
    cc = int(cap.get(cv2.CAP_PROP_FOURCC)) if cap.isOpened() else 0
    cap.release()
    return "".join(chr((cc >> 8 * i) & 0xFF) for i in range(4)).lower() in ("avc1", "h264", "x264")


def measured_rate(out_dir, compressed):
    """Byte mỗi giây clip (cả 2 cam) đo từ sessions.csv + các file đã quay; chỉ lấy file H.264 nếu compressed.
    None nếu chưa đủ dữ liệu."""
    path = os.path.join(out_dir, "sessions.csv")
    if not os.path.exists(path):
        return None
    latest = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            latest[(r["nguoi"], r["buoi"], r["clip"])] = r              # bản quay sau cùng của mỗi clip
    size = sec = 0.0
    for (p, s, clip), r in latest.items():
        files = [os.path.join(out_dir, f"{p}_{s}_{clip}_{cam}.mp4") for cam in ("SIDE", "FRONT")]
        files = [x for x in files if os.path.exists(x)]
        if not files or (compressed and not all(_is_h264(x) for x in files)):
            continue
        try:
            size += sum(os.path.getsize(x) for x in files) * (2 / len(files))       # quy về 2 cam nếu buổi chỉ có 1 cam
            sec += float(r["thoi_luong_s"])
        except (OSError, ValueError, KeyError):
            continue
    return size / sec if sec >= MIN_MEASURE_SEC else None


def disk_report(out_dir, session_sec, compressed, usage=shutil.disk_usage, rate=None):
    """dict(free, per_session, sessions, low, text, measured). `rate` truyền vào nếu đã đo (tránh quét lại file)."""
    probe = os.path.abspath(out_dir)
    while not os.path.exists(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    free = usage(probe).free
    if rate is None:
        rate = measured_rate(out_dir, compressed)
    default = COMPRESSED_SESSION_BYTES if compressed else RAW_SESSION_BYTES
    per = rate * session_sec if rate else default
    sessions = int(free // per) if per > 0 else 0
    drive = os.path.splitdrive(os.path.abspath(out_dir))[0] or "Ổ đĩa"
    how = ("đo từ file đã quay" if rate else "ước tính") + (", đã nén H.264" if compressed else ", chưa nén")
    text = f"Ổ {drive} còn {free / 1e9:.1f} GB trống, đủ cho khoảng {sessions} buổi ({per / 1e9:.2f} GB/buổi, {how})"
    return dict(free=free, per_session=per, sessions=sessions, low=free < LOW_BYTES, text=text, measured=bool(rate))
