"""Kiểm thử nén H.264 sau khi quay (recording/compress.py, disk.py) với video giả, không cần camera.
Cần ffmpeg: có trong PATH, hoặc `pip install imageio-ffmpeg` (requirements-dev.txt).
Chạy:  PYTHONUTF8=1 python tests/test_recording_compress.py"""
import hashlib
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import test_recording as tr  # noqa: E402
from fake_pose import front_landmarks, side_landmarks  # noqa: E402
from posture_features import sequence_angles, shoulder_tilt  # noqa: E402
from recording import compress as cp  # noqa: E402
from recording.compress import Compressor, compress_dir, compress_file, find_ffmpeg, probe  # noqa: E402
from recording.disk import LOW_BYTES, disk_report, measured_rate  # noqa: E402
from recording.script import Phase  # noqa: E402

FF = find_ffmpeg()
SIZE = (1280, 720)
RED, GREEN, BLUE, YELLOW, MAGENTA = (0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255), (255, 0, 255)


def marker_frame(rng, marks):
    """Nền nhiễu (như cảnh thật, khó nén) + chấm màu tại các điểm khớp: video giả mà bộ dò theo màu đọc lại được."""
    img = np.full((SIZE[1], SIZE[0], 3), 90, np.uint8) + rng.integers(0, 14, (SIZE[1], SIZE[0], 3), dtype=np.uint8)
    for (x, y), col in marks:
        cv2.circle(img, (int(round(x)), int(round(y))), 10, col, -1)
    return img


def side_marks(i, n):
    L, _ = side_landmarks(5.0 + 45.0 * i / n, 20.0 * i / n)              # cổ ~6 -> 50 độ, thân 0 -> ~11 độ
    k = 2.5
    return [((L[7][0] * k, L[7][1] * k), RED), ((L[11][0] * k, L[11][1] * k), GREEN),
            ((L[23][0] * k, L[23][1] * k), BLUE), ((L[2][0] * k, L[2][1] * k), YELLOW)]


def front_marks(i, n):
    L = front_landmarks(tilt_deg=-6.0 + 12.0 * i / n)
    k = 3.0
    return [((L[11][0] * k, L[11][1] * k), GREEN), ((L[12][0] * k, L[12][1] * k), MAGENTA)]


def write_video(path, n, marks_fn=None, fps=30, seed=0):
    rng = np.random.default_rng(seed)
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, SIZE)
    for i in range(n):
        w.write(marker_frame(rng, marks_fn(i, n) if marks_fn else [((100 + 4 * i, 300), RED)]))
    w.release()


def find_marker(img, col, tol=110):
    d = np.linalg.norm(img.astype(np.int16) - np.array(col, np.int16), axis=2)
    ys, xs = np.nonzero(d < tol)
    return None if len(xs) < 20 else (float(xs.mean()), float(ys.mean()))


def read_landmarks(path, kind):
    """Bộ dò theo màu -> landmark (33,3) từng khung, dùng đúng hàm góc của engine."""
    cap = cv2.VideoCapture(path)
    out = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        L = np.zeros((33, 3), np.float32)
        spec = {7: RED, 11: GREEN, 23: BLUE, 2: YELLOW} if kind == "side" else {11: GREEN, 12: MAGENTA}
        for idx, col in spec.items():
            p = find_marker(fr, col)
            assert p is not None, f"không thấy chấm {col} ở khung {len(out)}"
            L[idx] = (p[0], p[1], 1.0)
        out.append(L)
    cap.release()
    return out


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ====================================================================== các test
def test_frames_and_duration_unchanged():
    d = tempfile.mkdtemp(prefix="cmp_")
    try:
        p = os.path.join(d, "P01_S01_X_FRONT.mp4")
        write_video(p, 150)
        n0, fps0, cc0 = probe(p)
        size0 = os.path.getsize(p)
        r = compress_file(p, FF)
        assert r["status"] == "ok", r
        n1, fps1, cc1 = probe(p)
        assert n1 == n0 == 150 and fps1 == fps0 == 30.0, (n0, n1, fps0, fps1)
        assert abs(n1 / fps1 - n0 / fps0) < 1e-6                         # thời lượng không đổi
        assert cp.is_h264(cc1) and not cp.is_h264(cc0) and os.path.getsize(p) < size0
        assert compress_file(p, FF)["status"] == "skipped"               # nén lại file đã nén thì bỏ qua
        assert [f for f in os.listdir(d) if f.endswith(cp.TMP_SUFFIX)] == []
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_angles_within_1_degree():
    """MediaPipe được thay bằng bộ dò theo chấm màu (video giả không có người): góc cổ / thân / lệch vai trên file nén lệch < 1 độ."""
    d = tempfile.mkdtemp(prefix="cmp_")
    try:
        ps, pf = os.path.join(d, "P01_S01_X_SIDE.mp4"), os.path.join(d, "P01_S01_X_FRONT.mp4")
        write_video(ps, 90, side_marks, seed=1)
        write_video(pf, 90, front_marks, seed=2)
        ref_s, ref_f = read_landmarks(ps, "side"), read_landmarks(pf, "front")
        assert compress_file(ps, FF)["status"] == "ok" and compress_file(pf, FF)["status"] == "ok"
        new_s, new_f = read_landmarks(ps, "side"), read_landmarks(pf, "front")
        assert len(new_s) == len(ref_s) == 90 and len(new_f) == len(ref_f) == 90
        worst = 0.0
        for a, b in zip(ref_s, new_s):
            ra, rb = (sequence_angles(x[None], 0, 1.0)[0] for x in (a, b))
            worst = max(worst, abs(ra[0] - rb[0]), abs(ra[1] - rb[1]))        # neck, trunk
        assert worst < 1.0, f"góc cổ/thân lệch {worst:.2f} độ"
        worst_t = max(abs(shoulder_tilt(a) - shoulder_tilt(b)) for a, b in zip(ref_f, new_f))
        assert worst_t < 1.0, f"lệch vai lệch {worst_t:.2f} độ"
        # đối chiếu: góc thật của video giả đúng như thiết kế (bộ dò không bịa)
        assert 40 < sequence_angles(ref_s[-1][None], 0, 1.0)[0][0] < 60
        print(f"  (lệch lớn nhất: cổ/thân {worst:.2f} độ, lệch vai {worst_t:.2f} độ)")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_mismatch_keeps_original():
    d = tempfile.mkdtemp(prefix="cmp_")
    try:
        p = os.path.join(d, "P01_S01_X_SIDE.mp4")
        write_video(p, 60)
        h = sha(p)

        def short_runner(cmd):                         # ffmpeg giả: ra file ít khung hơn
            write_video(cmd[-1], 50)
            return 0, ""
        r = compress_file(p, FF, runner=short_runner)
        assert r["status"] == "failed" and "không khớp" in r["error"], r
        assert sha(p) == h and not os.path.exists(p[:-4] + cp.TMP_SUFFIX)
        r = compress_file(p, FF, runner=lambda cmd: (1, "boom"))
        assert r["status"] == "failed" and "ffmpeg lỗi" in r["error"] and sha(p) == h
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_background_compressor_and_no_ffmpeg():
    d = tempfile.mkdtemp(prefix="cmp_")
    try:
        ps = [os.path.join(d, f"P01_S01_C{i}_SIDE.mp4") for i in range(2)]
        for p in ps:
            write_video(p, 60)
        slow = lambda cmd: (time.sleep(1.0), cp._run(cmd))[1]
        c = Compressor(FF, log=lambda m: None, runner=slow)
        t0 = time.perf_counter()
        for p in ps:
            assert c.submit(p)
        assert time.perf_counter() - t0 < 0.3 and c.busy == 2            # submit không chặn
        assert c.wait_for(ps[0], 60)
        assert cp.is_h264(probe(ps[0])[2])
        assert c.wait_all(60) and c.busy == 0 and len(c.results) == 2 and all(r["status"] == "ok" for r in c.results)
        assert c.saved > 0 and all(cp.is_h264(probe(p)[2]) for p in ps)
        c.submit(ps[0])                                                   # sau khi thread đã dừng vẫn nén tiếp được
        assert c.wait_all(60) and c.results[-1]["status"] == "skipped"
        # không có ffmpeg: cảnh báo MỘT lần, giữ file gốc
        raw = os.path.join(d, "P01_S01_R_FRONT.mp4")
        write_video(raw, 30)
        h = sha(raw)
        c2 = Compressor(False, log=lambda m: None)
        assert not c2.enabled and c2.submit(raw) is False
        assert "ffmpeg" in c2.warning_once() and c2.warning_once() is None
        assert sha(raw) == h
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_compress_dir():
    d = tempfile.mkdtemp(prefix="cmp_")
    try:
        os.makedirs(os.path.join(d, "_cu"))
        names = ["P01_S01_A_SIDE.mp4", "P01_S01_A_FRONT.mp4", os.path.join("_cu", "P01_S01_A_SIDE__cu1.mp4")]
        for i, n in enumerate(names):
            write_video(os.path.join(d, n), 45, seed=i)
        other = os.path.join(d, "khac.mp4")
        write_video(other, 10)
        csvp = os.path.join(d, "P01_S01_A_frames.csv")
        open(csvp, "w").write("cam,n\n")
        stale = os.path.join(d, "P01_S01_B_SIDE.cmp.mp4")
        open(stale, "wb").write(b"do")
        h_other, h_csv = sha(other), sha(csvp)
        logs = []
        assert compress_dir(d, None, logs.append) == 0
        assert all(probe(os.path.join(d, n))[0] == 45 and cp.is_h264(probe(os.path.join(d, n))[2]) for n in names)
        assert sha(other) == h_other and sha(csvp) == h_csv and not os.path.exists(stale)
        assert "3 file" in logs[0] and "Xong" in logs[-1] and "0 file lỗi" in logs[-1]
        logs.clear()
        assert compress_dir(d, None, logs.append) == 0 and "3 file đã nén sẵn" in logs[-1]
        assert compress_dir(os.path.join(d, "khong_co"), None, logs.append) == 2
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_session_compresses_in_background():
    """Clip xong -> nén nền, clip kế không bị chặn; quay lại clip khi file cũ đang nén thì chờ chứ không lỗi; số khung giữ nguyên."""
    out = tempfile.mkdtemp(prefix="rec_")
    sess = stop = None
    try:
        good = tr.mk_clip("A2", "GOOD_01", 6, [Phase(0, "", None)], "both")
        nxt = tr.mk_clip("A3", "GOOD_02", 5, [Phase(0, "", None)], "both")
        slow = lambda cmd: (time.sleep(1.5), cp._run(cmd))[1]
        comp = Compressor(FF, log=lambda m: None, runner=slow)
        sess, stop = tr.build(out, [good, nxt], lambda t: 10.0)
        sess.compressor = comp
        tr.wait_samples(sess, 0.5)
        tr.drive(sess)
        assert sess.state == "IDLE" and comp.busy > 0                       # đang nén nền mà đã sẵn sàng clip kế
        assert "đang nén" in sess.compress_text()
        sess.press_redo()                                                    # quay lại ngay: phải chờ nén xong file cũ rồi mới chuyển
        tr.drive(sess)
        assert comp.wait_all(90)
        for cam in ("SIDE", "FRONT"):
            for p in (os.path.join(out, f"P01_S01_GOOD_01_{cam}.mp4"), os.path.join(out, "_cu", f"P01_S01_GOOD_01_{cam}__cu1.mp4")):
                n, fps, cc = probe(p)
                assert n == 6 * 30 and fps == 30.0 and cp.is_h264(cc), (p, n, fps, cc)
        assert not [f for r, _d, fs in os.walk(out) for f in fs if f.endswith(cp.TMP_SUFFIX) or f.endswith(".rec.mp4")]
        assert not comp.failures() and "tiết kiệm" in sess.compress_text()
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def test_record_session_path_compresses():
    """Đúng đường chạy thật: record_session.parse_args -> build (không truyền --ffmpeg) -> Space -> hết clip -> file thành H.264."""
    import record_session as rs
    out = tempfile.mkdtemp(prefix="rec_")
    sess = shutdown = None
    try:
        sv, fv = os.path.join(out, "s.mp4"), os.path.join(out, "f.mp4")
        tr.make_video(sv, 3, 30, label="SIDE")
        tr.make_video(fv, 3, 30, label="FRONT")
        args = rs.parse_args(["--person", "P99", "--session", "S03", "--side-video", sv, "--front-video", fv,
                              "--out", out, "--no-face", "--countdown", "0.5", "--only", "GOOD_01"])
        assert args.ffmpeg is None                                         # người dùng không truyền --ffmpeg
        sess, shutdown = rs.build(args)
        assert sess.compressor is not None and sess.compressor.enabled, "không truyền --ffmpeg phải tự dò ra ffmpeg"
        assert sess.compressor.ffmpeg == FF
        sess.clips[0].duration, sess.clips[0].margin = 5, 1.0
        tr.wait_samples(sess, 0.5)
        tr.drive(sess)
        assert sess.compressor.wait_all(90)
        for cam in ("SIDE", "FRONT"):
            p = os.path.join(out, f"P99_S03_GOOD_01_{cam}.mp4")
            n, fps, cc = probe(p)
            assert n == 150 and fps == 30.0 and cp.is_h264(cc), (cam, n, fps, cc)
        lvl, txt = sess.compress_status()
        assert lvl == "ok" and "đã nén" in txt and not sess.compressor.failed, (lvl, txt)
        assert "Không tìm thấy ffmpeg" not in sess.message
        # --ffmpeg trỏ sai file: tự dò tiếp chứ không tắt nén
        a2 = rs.parse_args(["--person", "P99", "--session", "S03", "--ffmpeg", os.path.join(out, "khong_co.exe")])
        assert Compressor(a2.ffmpeg, log=lambda m: None).enabled
        # nén lỗi: giao diện phải báo lý do và giữ bản gốc
        bad = Compressor(FF, log=lambda m: None, runner=lambda cmd: (1, "Unknown encoder"))
        p = os.path.join(out, "P99_S03_X_SIDE.mp4")
        write_video(p, 30)
        h = sha(p)
        bad.submit(p)
        assert bad.wait_all(60) and sha(p) == h
        lvl, txt = bad.status()
        assert lvl == "bad" and "nén lỗi" in txt and "Unknown encoder" in txt and "P99_S03_X_SIDE.mp4" in txt, txt
        lvl, txt = Compressor(False, log=lambda m: None).status()
        assert lvl == "bad" and "không tìm thấy ffmpeg" in txt
    finally:
        if shutdown:
            shutdown()
        shutil.rmtree(out, ignore_errors=True)


def test_session_warns_once_without_ffmpeg():
    out = tempfile.mkdtemp(prefix="rec_")
    sess = stop = None
    try:
        a = tr.mk_clip("A2", "GOOD_01", 5, [Phase(0, "", None)], "side")
        b = tr.mk_clip("A3", "GOOD_02", 5, [Phase(0, "", None)], "side")
        sess, stop = tr.build(out, [a, b], lambda t: 10.0, front_on=False)
        sess.compressor = Compressor(False, log=lambda m: None)
        tr.wait_samples(sess, 0.5)
        tr.drive(sess)
        assert "Không tìm thấy ffmpeg" in sess.message
        tr.drive(sess)
        assert "Không tìm thấy ffmpeg" not in sess.message                  # chỉ báo một lần
        assert not cp.is_h264(probe(os.path.join(out, "P01_S01_GOOD_01_SIDE.mp4"))[2])      # file gốc còn nguyên
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def test_disk_report_and_warning():
    out = tempfile.mkdtemp(prefix="rec_")
    try:
        usage = lambda free: (lambda p: SimpleNamespace(total=1e12, used=1e12 - free, free=free))
        raw = disk_report(out, 1385, False, usage(68e9))
        assert raw["sessions"] == int(68e9 // (77e9 / 30)) == 26 and not raw["low"] and "68.0 GB" in raw["text"]
        comp = disk_report(out, 1385, True, usage(68e9))
        assert comp["sessions"] > raw["sessions"] * 2 and "đã nén H.264" in comp["text"]
        low = disk_report(out, 1385, True, usage(LOW_BYTES - 1e8))
        assert low["low"] and low["sessions"] >= 0
        # đo từ file đã quay: 2 clip x 100 s, mỗi cam 5 MB -> 0,1 MB/s cả 2 cam
        import csv as _csv
        with open(os.path.join(out, "sessions.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=["nguoi", "buoi", "clip", "thoi_luong_s"])
            w.writeheader()
            for c in ("A", "B"):
                w.writerow(dict(nguoi="P01", buoi="S01", clip=c, thoi_luong_s=100))
                for cam in ("SIDE", "FRONT"):
                    open(os.path.join(out, f"P01_S01_{c}_{cam}.mp4"), "wb").write(b"x" * 5_000_000)
        assert abs(measured_rate(out, False) - 100_000) < 1
        assert measured_rate(out, True) is None                               # file không phải H.264: không dùng để đo mức đã nén
        m = disk_report(out, 1385, False, usage(68e9))
        assert m["measured"] and abs(m["per_session"] - 138.5e6) < 1e3 and "đo từ file đã quay" in m["text"]
        # Session: dưới 5 GB -> cảnh báo đỏ
        from recording.session import Session
        s = Session([tr.mk_clip("A2", "GOOD_01", 5, [Phase(0, "", None)])], out, "P02", "S01", {}, None,
                    disk_usage=usage(3.2e9))
        s.tick()
        assert s.disk["low"] and any("chỉ còn 3.2 GB" in w and "dưới 5 GB" in w for w in s.warnings), s.warnings
        s2 = Session([tr.mk_clip("A2", "GOOD_01", 5, [Phase(0, "", None)])], out, "P02", "S01", {}, None, disk_usage=usage(68e9))
        s2.tick()
        assert not s2.disk["low"] and not [w for w in s2.warnings if "GB" in w]
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main():
    assert FF, "cần ffmpeg (PATH hoặc pip install imageio-ffmpeg)"
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t0 = time.time()
        t()
        print(f"ĐẠT  {t.__name__}  ({time.time() - t0:.1f}s)")
    print(f"{len(tests)}/{len(tests)} đạt")


if __name__ == "__main__":
    main()
