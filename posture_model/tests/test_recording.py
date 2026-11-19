"""Kiểm thử lõi công cụ quay (recording/) không cần camera: video giả + landmark giả.
Chạy:  PYTHONUTF8=1 python tests/test_recording.py     (mất ~1 phút vì chạy theo thời gian thật)"""
import csv
import json
import math
import os
import shutil
import sys
import tempfile
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from fake_pose import front_landmarks, side_landmarks  # noqa: E402
from posture_features import calibration_baseline, sequence_angles  # noqa: E402
from recording import make_script  # noqa: E402
from recording.analyzer import Analyzer  # noqa: E402
from recording.capture import CameraSource  # noqa: E402
from recording.script import (CHUA_DU, DAT, KHONG_THAY, THEO_HIEU_LENH, Clip, Phase, PassCounter, check_status,  # noqa: E402
                              load_script, select_clips)
from recording.session import AWAIT_CM, COUNTDOWN, IDLE, RECORDING, Session  # noqa: E402

FPS = 30


def make_video(path, seconds=3, fps=30, size=(480, 360), label="FAKE"):
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(int(seconds * fps)):
        img = np.full((size[1], size[0], 3), 60, np.uint8)
        cv2.putText(img, f"{label} {i}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        w.write(img)
    w.release()


def count_frames(path):
    c = cv2.VideoCapture(path)
    n = 0
    while c.read()[0]:
        n += 1
    fps = c.get(cv2.CAP_PROP_FPS)
    c.release()
    return n, fps


class Det:
    """Detector giả: landmark phụ thuộc giây TRONG CLIP (hàm do test cho), gọi như PoseDetector(img, ts)."""

    def __init__(self, kind, fn):
        self.kind, self.fn, self.sess = kind, fn, None

    def __call__(self, img, ts):
        t = self.sess.elapsed() if self.sess is not None and self.sess.elapsed() is not None else -1.0
        v = self.fn(t)
        if v is None:
            return None, None
        return side_landmarks(v) if self.kind == "side" else (front_landmarks(v), None)


class FakeEd:
    """Thay EyeDistance: 2 mắt cách 28 px -> 60 cm."""

    def measure(self, frame, ts, L):
        return (float(np.hypot(*(L[5, :2] - L[2, :2]))), "ipd") if L is not None else (float("nan"), None)

    def to_cm(self, px, kind, width):
        return 1680.0 / px


def mk_clip(cid, name, dur, phases, cam="side", margin=1.0):
    return Clip(cid, name, dur, cam, {"side": "hông", "front": "laptop", "both": "cả hai"}[cam], "Hiệu lệnh thử", "mục tiêu thử",
                "T", phases, margin)


def build(out, clips, side_fn, front_fn=lambda t: 0.0, side_fps=30, front_on=True, ed=None, countdown=0.5, beeps=None, front_fps=30):
    vdir = os.path.join(out, "_src")
    os.makedirs(vdir, exist_ok=True)
    sv, fv = os.path.join(vdir, f"s{side_fps}.mp4"), os.path.join(vdir, f"f{front_fps}.mp4")
    make_video(sv, 3, side_fps, label="SIDE")
    make_video(fv, 3, front_fps, label="FRONT")
    side = CameraSource("hông", sv).start()
    front = CameraSource("laptop", fv).start() if front_on else None
    ds, df = Det("side", side_fn), Det("front", front_fn)
    an = Analyzer(side, front, ds, df if front_on else None, ed).start()
    sess = Session(clips, out, "P01", "S01", dict(side=side, front=front), an, ed=ed, countdown=countdown,
                   beeper=(lambda k: beeps.append((k, time.perf_counter())) if beeps is not None else None))
    ds.sess = df.sess = sess

    def stop():
        an.stop()
        side.close()
        if front:
            front.close()
    return sess, stop


def drive(sess, timeout=60):
    """Space rồi tick tới khi clip xong (IDLE / AWAIT_CM)."""
    assert sess.press_start(), sess.message
    t0 = time.perf_counter()
    while sess.state in (COUNTDOWN, RECORDING):
        sess.tick()
        time.sleep(0.01)
        assert time.perf_counter() - t0 < timeout, "clip không kết thúc"
    sess.tick()


def wait_samples(sess, n=1.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < n:
        sess.tick()
        time.sleep(0.02)


# ====================================================================== các test
def test_script_and_timeline():
    clips = load_script()
    assert len(clips) == 35 and sum(c.duration for c in clips) == 1385
    by = {c.id: c for c in clips}
    assert by["A2"].clip == "GOOD_01" and by["E7"].clip == "DISTANCE_STEPS" and by["F1"].cam == "both"
    assert [c.id for c in clips][:3] == ["A1", "A2", "A3"]
    # mốc đổi: clip 2 mức ở giây 15, C1 mỗi 15 s, E7 mỗi 15 s
    assert by["E1"].marks() == [(15, "MỨC RÕ HƠN")]
    assert [t for t, _ in by["C1"].marks()] == [15, 30, 45, 60, 75, 90, 105]
    assert [lb for _, lb in by["C1"].marks()][:3] == ["FORWARD_HEAD", "GOOD", "LEAN_FORWARD"]
    assert by["E7"].marks() == [(15, "60 cm"), (30, "50 cm"), (45, "40 cm")]
    assert by["A2"].marks() == [] and by["D1"].marks() == []
    # chữ nổi: 3 s đầu / cuối NGỒI THẲNG, sau mốc hiện tên mức
    e1 = by["E1"]
    assert e1.banner(0) == e1.banner(2.9) == e1.banner(27) == e1.banner(29.9) == "NGỒI THẲNG"
    assert e1.banner(10) == "" and e1.banner(15.5) == "MỨC RÕ HƠN" and e1.banner(19) == ""
    assert by["E7"].banner(31) == "50 cm"
    # chỉ chấm giữa clip, và chỉ khi mức có điều kiện
    assert not by["A2"].judged(2.9) and by["A2"].judged(3) and not by["A2"].judged(57)
    assert not by["D1"].judged(10) and e1.judged(10)
    assert not by["E9"].judged(10) and by["E9"].judged(20)           # mức 1 của E9 không có số
    # tiếng Việt có dấu giữ nguyên
    assert "Đưa đầu ra trước" in by["B1"].cue and by["B1"].cam_text == "hông"
    assert select_clips(clips, "GOOD_01")[0].id == "A2" and len(select_clips(clips, "GOOD_01")) == 34
    assert [c.id for c in select_clips(clips, only="SHOULDER_TILT_L,E2")] == ["E1", "E2"]
    try:
        select_clips(clips, "KHONG_CO")
        raise AssertionError("phải báo lỗi tên clip sai")
    except ValueError:
        pass


def test_check_status():
    chk = [{"m": "neck", "min": 20, "max": 30}]
    assert check_status(chk, {"neck": 25}) == DAT
    assert check_status(chk, {"neck": 31}) == CHUA_DU and check_status(chk, {"neck": 5}) == CHUA_DU
    assert check_status(chk, {"neck": None}) == KHONG_THAY and check_status(chk, {"neck": float("nan")}) == KHONG_THAY
    assert check_status(None, {}) == THEO_HIEU_LENH
    t = [{"m": "tilt", "min": 3, "max": 5, "abs": True}]
    assert check_status(t, {"tilt": -4}) == DAT and check_status(t, {"tilt": 6}) == CHUA_DU
    both = [{"m": "trunk", "min": 20}, {"m": "neck", "min": 20}]
    assert check_status(both, {"trunk": 25, "neck": 10}) == CHUA_DU and check_status(both, {"trunk": 25, "neck": 25}) == DAT
    c = mk_clip("X", "X", 10, [Phase(0, "", chk)])
    pc = PassCounter(c)
    for t, st in ((0.5, DAT), (2, DAT), (5, CHUA_DU), (8, DAT), (9.5, CHUA_DU)):    # 0.5 và 9.5 nằm ngoài khoảng chấm
        pc.add(t, st)
    assert pc.total == 3 and abs(pc.pct - 100 * 2 / 3) < 1e-9


def test_script_matches_excel():
    xlsx = make_script.DEFAULT_XLSX
    if not os.path.exists(xlsx):
        print("  (bỏ qua: không có file Excel)")
        return
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("  (bỏ qua: chưa cài openpyxl)")
        return
    gen = make_script.build(xlsx)
    with open(os.path.join(os.path.dirname(make_script.__file__), "script_v2.json"), encoding="utf-8") as f:
        assert json.load(f) == json.loads(json.dumps(gen, ensure_ascii=False)), "script_v2.json lệch Excel: chạy lại make_script.py"


def test_end_to_end():
    out = tempfile.mkdtemp(prefix="rec_")
    beeps = []
    sess = stop = None
    try:
        a1 = mk_clip("A1", "CALIBRATION", 7, [Phase(0, "", None)], "both")
        good = mk_clip("A2", "GOOD_01", 6, [Phase(0, "", [{"m": "neck", "max": 10}])])
        fwd = mk_clip("B1", "FORWARD_HEAD_L1", 8, [Phase(0, "", [{"m": "neck", "min": 20, "max": 30}])])
        two = mk_clip("E1", "SHOULDER_TILT_L", 9, [Phase(0, "MỨC NHẸ", [{"m": "tilt", "min": 3, "max": 5, "abs": True}]),
                                                    Phase(4, "MỨC RÕ HƠN", [{"m": "tilt", "min": 5, "abs": True}])], "front")
        e7 = mk_clip("E7", "DISTANCE_STEPS", 6, [Phase(0, "70 cm", None), Phase(3, "60 cm", None)], "front")
        DX_BASE = 10.0                                   # cổ ~ 11,3 độ lúc hiệu chỉnh
        deg = lambda dx: math.degrees(math.atan2(dx, 50.0))
        dx_for = lambda d: 50.0 * math.tan(math.radians(d))
        # B1: nửa đầu cổ lệch +25 độ so với baseline (đạt), nửa sau lệch +5 (chưa đủ)
        side_fn = lambda t: DX_BASE if t < 0 or not sess.current else (
            DX_BASE if sess.current.id in ("A1", "A2") else
            dx_for(deg(DX_BASE) + (25 if t < 4.5 else 5)) if sess.current.id == "B1" else DX_BASE)
        # E1: tilt 4 độ giữa clip 3 mức nhẹ, 7 độ mức rõ hơn -> chấm đạt cả hai
        front_fn = lambda t: (4.0 if t < 4 else 7.0) if sess and sess.current and sess.current.id == "E1" else 0.0
        sess, stop = build(out, [a1, good, fwd, two, e7], side_fn, front_fn, ed=FakeEd(), beeps=beeps)
        wait_samples(sess, 1.0)
        assert abs(sess.live["dist"] - 60) < 1 if sess.live["dist"] else False, sess.live

        # ---- Space khi chưa có baseline vẫn ghi được, nhưng cảnh báo
        # ---- A1
        drive(sess)
        assert sess.baseline is not None, sess.message
        eng = calibration_baseline(sequence_angles(np.stack([side_landmarks(DX_BASE)[0]] * 5), sess.baseline["side"],
                                                   sess.baseline["f"]))
        assert abs(sess.baseline["base"]["neck"] - eng["neck"]) < 0.01 and abs(sess.baseline["base"]["neck"] - deg(DX_BASE)) < 0.1
        assert "A1 ĐẠT" in sess.message and sess.idx == 1
        assert os.path.exists(os.path.join(out, "P01_S01_CALIBRATION_SIDE.mp4"))

        # ---- tên file, thời lượng ±1 khung/giây, frames.csv
        for clip, cams in ((a1, ("SIDE", "FRONT")),):
            for cam in cams:
                p = os.path.join(out, f"P01_S01_{clip.clip}_{cam}.mp4")
                n, fps = count_frames(p)
                assert abs(n - clip.duration * FPS) <= clip.duration, (p, n)
                assert abs(fps - FPS) < 0.5
        rows = list(csv.DictReader(open(os.path.join(out, "P01_S01_CALIBRATION_frames.csv"), encoding="utf-8")))
        assert {r["cam"] for r in rows} == {"side", "front"} and len(rows) > 2 * 7 * 25

        # ---- beep: bắt đầu / kết thúc đúng giây
        kinds = [k for k, _ in sess.beep_log]
        assert kinds == ["start", "end"], kinds
        assert abs(sess.beep_log[0][1]) < 0.05 and abs(sess.beep_log[1][1] - a1.duration) < 0.15, sess.beep_log

        # ---- GOOD: đạt 100% vì cổ lệch 0 so với baseline
        drive(sess)
        assert sess.done["A2"]["pct"] is not None and sess.done["A2"]["pct"] > 95, sess.done
        assert "ĐẠT" in sess.message and sess.idx == 2

        # ---- B1: nửa chấm đạt, nửa chưa đủ
        drive(sess)
        pct = sess.done["B1"]["pct"]
        assert 25 < pct < 75, pct
        assert sess.message_level == "warn" and "quay lại" in sess.message

        # ---- E1: 2 mức, mốc bíp giây 4, cả 2 mức đạt (tilt 4 rồi 7)
        sess.beep_log.clear()
        drive(sess)
        assert [k for k, _ in sess.beep_log] == ["start", "mark", "end"], sess.beep_log
        assert abs(sess.beep_log[1][1] - 4.0) < 0.15, sess.beep_log
        assert sess.done["E1"]["pct"] > 85, sess.done["E1"]

        # ---- E7: hỏi cm rồi ghi vào sessions.csv
        drive(sess)
        assert sess.state == AWAIT_CM
        sess.submit_cm([70, 61.5, 50, 39])
        assert sess.state == IDLE
        log = list(csv.DictReader(open(os.path.join(out, "sessions.csv"), encoding="utf-8-sig")))
        assert [r["clip"] for r in log] == ["CALIBRATION", "GOOD_01", "FORWARD_HEAD_L1", "SHOULDER_TILT_L", "DISTANCE_STEPS"]
        assert log[-1]["cm_thuoc"] == "70/62/50/39" or log[-1]["cm_thuoc"].startswith("70/6"), log[-1]
        assert log[0]["nguoi"] == "P01" and log[0]["buoi"] == "S01" and log[0]["nguoi_cham_1"] == "" == log[0]["nguoi_cham_2"]
        assert float(log[1]["fps_hong"]) > 27 and log[1]["so_lan_quay_lai"] == "0" and log[4]["phan_tram_dat"] == ""

        # ---- quay lại clip: bản cũ chuyển vào _cu/, bản mới giữ đúng tên
        old = os.path.join(out, "P01_S01_GOOD_01_SIDE.mp4")
        old_size = os.path.getsize(old)
        sess.press_redo()
        assert sess.current is e7           # R = clip vừa quay xong (E7)
        sess.last_clip = good
        sess.press_redo()
        assert sess.current is good
        drive(sess)
        cu = os.listdir(os.path.join(out, "_cu"))
        assert "P01_S01_GOOD_01_SIDE__cu1.mp4" in cu and "P01_S01_GOOD_01_FRONT__cu1.mp4" in cu and "P01_S01_GOOD_01_frames__cu1.csv" in cu
        assert os.path.exists(old) and sess.takes["A2"] == 2
        log = list(csv.DictReader(open(os.path.join(out, "sessions.csv"), encoding="utf-8")))
        assert log[-1]["clip"] == "GOOD_01" and log[-1]["so_lan_quay_lai"] == "1"
        assert not [f for f in os.listdir(out) if f.endswith(".rec.mp4")]

        # ---- thoát giữa chừng rồi mở lại
        assert sess.current is fwd            # xong GOOD thì con trỏ tự sang clip kế
        assert sess.press_start()
        wait_samples(sess, 1.5)
        assert sess.state in (COUNTDOWN, RECORDING)
        sess.close()                                     # = phím Q
        assert sess.state == IDLE
        assert not [f for f in os.listdir(out) if f.endswith(".rec.mp4")], "file dở phải bị bỏ"
        saved = json.load(open(sess.progress_path, encoding="utf-8"))
        assert saved["next"] == "B1" and saved["baseline"]["base"]["neck"] > 11
        s2 = Session([a1, good, fwd, two, e7], out, "P01", "S01", {}, None)
        assert "Tiếp từ B1 FORWARD_HEAD_L1" in s2.resume_text()
        assert s2.resume() and s2.current is fwd and s2.baseline == sess.baseline and s2.takes["A2"] == 2

        # ---- C = quay lại A1
        sess.press_calibrate()
        assert sess.current is a1
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def test_a1_fail_and_not_seen():
    """A1 người cúi (không đạt calibration.evaluate) -> báo lý do, không có baseline, ở lại A1; clip khác 'không thấy người' -> đỏ."""
    out = tempfile.mkdtemp(prefix="rec_")
    sess = stop = None
    try:
        a1 = mk_clip("A1", "CALIBRATION", 6, [Phase(0, "", None)], "both")
        good = mk_clip("A2", "GOOD_01", 5, [Phase(0, "", [{"m": "neck", "max": 10}])])
        mode = {"v": 70.0}                               # cổ ra trước ~54 độ: vượt calib_max_neck_deg
        sess, stop = build(out, [a1, good], lambda t: mode["v"], front_on=False)
        wait_samples(sess, 0.5)
        drive(sess)
        assert sess.baseline is None and sess.idx == 0
        assert "KHÔNG ĐẠT" in sess.message and sess.message_level == "bad"
        assert "A2" not in sess.done and "A1" not in sess.done
        row = list(csv.DictReader(open(os.path.join(out, "sessions.csv"), encoding="utf-8-sig")))[0]
        assert "A1 không đạt" in row["ghi_chu"]
        mode["v"] = 10.0                                 # quay lại A1, lần này ngồi thẳng
        drive(sess)
        assert sess.baseline is not None and sess.idx == 1 and sess.takes["A1"] == 2
        assert len(os.listdir(os.path.join(out, "_cu"))) == 2        # SIDE + frames của lần A1 hỏng
        mode["v"] = None                                 # rời khung hình
        drive(sess)
        assert sess.done["A2"]["pct"] == 0.0
        assert sess.live["status"] in (KHONG_THAY, "KHONG_THAY") and sess.live["seen_side"] is False
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def test_end_of_list():
    """--only 2 clip: quay hết -> màn hình xong buổi; Space không làm gì; R quay lại được; N ở clip cuối cũng sang màn hình xong."""
    out = tempfile.mkdtemp(prefix="rec_")
    sess = stop = None
    try:
        a1 = mk_clip("A1", "CALIBRATION", 6, [Phase(0, "", None)], "both")
        good = mk_clip("A2", "GOOD_01", 5, [Phase(0, "", [{"m": "neck", "max": 10}])])
        clips = select_clips([a1, good], only="A1,GOOD_01")
        sess, stop = build(out, clips, lambda t: 10.0)
        wait_samples(sess, 0.5)
        drive(sess)
        assert not sess.finished and sess.current is good
        assert "Tự chuyển sang GOOD_01" in sess.message and "Space để bắt đầu (N = bỏ qua clip này)" in sess.message
        drive(sess)
        assert sess.finished and sess.idx == len(clips) and "clip cuối" in sess.message
        assert sess.press_start() is False and sess.state == IDLE          # Space không làm gì
        rows = sess.summary_rows()
        assert [r[0] for r in rows] == ["A1", "A2"] and rows[1][2] > 95 and rows[1][3] == 1 and not rows[1][4]
        assert json.load(open(sess.progress_path, encoding="utf-8"))["next"] is None
        assert "đã quay xong" in Session(clips, out, "P01", "S01", {}, None).resume_text()
        s2 = Session(clips, out, "P01", "S01", {}, None)
        assert s2.resume() and s2.finished
        sess.press_redo()                                                  # R: quay lại clip vừa rồi
        assert not sess.finished and sess.current is good
        drive(sess)
        assert sess.finished and sess.takes["A2"] == 2
        sess.press_redo()
        sess.press_next()                                                  # N ở clip cuối -> màn hình xong buổi
        assert sess.finished
        sess.press_prev()                                                  # B về clip trước (clip cuối)
        assert not sess.finished and sess.current is good
        sess.press_prev()
        assert sess.current is a1
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def test_slow_sources_keep_real_duration():
    """Nguồn giả 10 fps (hông) và 15 fps (laptop), clip 30 s -> mỗi file mp4 dài 30 s ±0,1 s ở đúng 30 fps khai báo."""
    out = tempfile.mkdtemp(prefix="rec_")
    sess = stop = None
    try:
        clip = mk_clip("A2", "GOOD_01", 30, [Phase(0, "", None)], "both")
        sess, stop = build(out, [clip], lambda t: 10.0, side_fps=10, front_fps=15)
        wait_samples(sess, 1.0)
        drive(sess, timeout=90)
        for cam, src_fps in (("SIDE", 10), ("FRONT", 15)):
            p = os.path.join(out, f"P01_S01_GOOD_01_{cam}.mp4")
            n, fps = count_frames(p)
            assert abs(fps - 30) < 0.01, (cam, fps)
            assert abs(n / fps - 30) <= 0.1, (cam, n, n / fps)
            rows = [r for r in csv.DictReader(open(os.path.join(out, "P01_S01_GOOD_01_frames.csv"), encoding="utf-8"))
                    if r["cam"] == ("side" if cam == "SIDE" else "front")]
            got = [r for r in rows if r["video_frame"] != "-1"]
            assert abs(len(got) - 30 * src_fps) <= 0.1 * 30 * src_fps + 3, (cam, len(got))   # khung thật ~ fps nguồn x 30 s
        row = list(csv.DictReader(open(os.path.join(out, "sessions.csv"), encoding="utf-8-sig")))[0]
        assert "FPS thấp" in row["ghi_chu"] and abs(float(row["fps_hong"]) - 10) < 1.5, row
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def test_check_cams_logic_and_run():
    from recording import check_cams as cc
    from recording.capture import CamConfig, parse_size
    import record_session as rs
    assert parse_size("640x480") == (640, 480)
    try:
        parse_size("abc")
        raise AssertionError
    except ValueError:
        pass
    # 4 cấu hình thực tế x 2 chế độ = 16 lượt
    assert len(cc.all_configs()) == 8 and cc.all_configs()[0].label() == "DSHOW/MJPG/1280x720"
    # chọn cấu hình tốt nhất theo cam; chênh < 1 fps thì lấy cấu hình ưu tiên (đứng trước)
    cf = cc.all_configs()
    rows = [dict(cfg=cf[0], mp=True, side=dict(fps=29.6, size=(1280, 720)), front=dict(fps=10.0, size=(1280, 720))),
            dict(cfg=cf[1], mp=True, side=dict(fps=30.0, size=(640, 480)), front=dict(fps=29.9, size=(640, 480))),
            dict(cfg=cf[2], mp=True, side=None, front=dict(fps=None, size=None)),
            dict(cfg=cf[3], mp=False, side=dict(fps=60.0, size=(1, 1)), front=dict(fps=60.0, size=(1, 1)))]   # không MediaPipe: không xét
    assert cc.pick_best(rows, "side")[0] is cf[0]
    assert cc.pick_best(rows, "front")[0] is cf[1]
    text, prof = cc.recommend(rows)
    assert "Camera hông: tốt nhất DSHOW/MJPG/1280x720" in text and "ĐẠT" in text and prof["front"]["size"] == [640, 480]
    assert "--front-size 640x480" in cc.recommend([dict(cfg=cf[0], mp=True, side=dict(fps=16.5, size=(1280, 720)),
                                                          front=dict(fps=10.0, size=(1280, 720)))])[0]
    assert "không mở được" in cc.format_table(rows)
    dark = [dict(cfg=cf[0], mp=True, side=dict(fps=1.0, size=(640, 480), black=True), front=dict(fps=1.0, size=(640, 480), black=True))]
    assert cc.pick_best(dark, "side") is None and "HÌNH ĐEN" in cc.format_table(dark) and "hình ĐEN" in cc.recommend(dark)[0]
    d = tempfile.mkdtemp(prefix="prof_")
    try:
        pp = os.path.join(d, "p.json")
        cc.save_profile(prof, pp)
        assert cc.load_profile(pp)["front"] == CamConfig(cf[1].backend, cf[1].fourcc, (640, 480))
        assert cc.load_profile(os.path.join(d, "none.json")) == {}
        # chạy đo thật trên nguồn file (10 fps và 30 fps), có và không "MediaPipe"
        vs, vf = os.path.join(d, "s.mp4"), os.path.join(d, "f.mp4")
        make_video(vs, 3, 10, label="S")
        make_video(vf, 3, 30, label="F")
        logs = []
        res = cc.run_check(dict(side=vs, front=vf), seconds=2.0, configs=cf[:2], log=logs.append,
                           detector_factory=lambda: (lambda img, ts: (None, None)))
        assert len(res) == 4 and len(logs) == 4
        for r in res:
            assert abs(r["side"]["fps"] - 10) < 2 and abs(r["front"]["fps"] - 30) < 4, r
        assert "10." in cc.format_table(res)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # CLI: --check-cams không cần --person; thiếu thì lỗi; --front-size ghi đè cỡ
    assert rs.parse_args(["--check-cams"]).check_cams
    try:
        rs.parse_args([])
        raise AssertionError
    except SystemExit:
        pass
    a = rs.parse_args(["--person", "P01", "--session", "S01", "--front-size", "640x480", "--no-profile"])
    cfgs = rs.cam_configs(a)
    assert cfgs["front"].size == (640, 480) and cfgs["side"].size == (1280, 720) and cfgs["side"].fourcc == "MJPG"


def test_low_fps_warning():
    out = tempfile.mkdtemp(prefix="rec_")
    sess = stop = None
    try:
        a1 = mk_clip("A1", "CALIBRATION", 6, [Phase(0, "", None)])
        sess, stop = build(out, [a1], lambda t: 10.0, side_fps=18, front_on=False)
        wait_samples(sess, 2.5)
        assert any("FPS camera hông" in w and "18" in w for w in sess.warnings), sess.warnings
        drive(sess)
        row = list(csv.DictReader(open(os.path.join(out, "sessions.csv"), encoding="utf-8-sig")))[0]
        assert "FPS thấp" in row["ghi_chu"] and float(row["fps_hong"]) < 27, row
        n, _ = count_frames(os.path.join(out, "P01_S01_CALIBRATION_SIDE.mp4"))
        assert abs(n - 6 * FPS) <= 6, n                  # camera 18 fps vẫn ra đúng thời lượng (lặp khung)
    finally:
        if stop:
            stop()
        shutil.rmtree(out, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t0 = time.time()
        t()
        print(f"ĐẠT  {t.__name__}  ({time.time() - t0:.1f}s)")
    print(f"{len(tests)}/{len(tests)} đạt")


if __name__ == "__main__":
    main()
