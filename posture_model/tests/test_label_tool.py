"""A1: công cụ chấm tay 6 lớp theo đoạn 2 giây, CSV, chấm tiếp, Cohen's κ. Video tự sinh, không dùng video thật.
  PYTHONUTF8=1 QT_QPA_PLATFORM=offscreen python tests/test_label_tool.py   (hoặc pytest)"""
import csv
import json
import math
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from labeling import kappa as K  # noqa: E402
from labeling.session import (CLASSES, FIELDS, KEYS, LABELS, UNCLEAR, LabelFileError, LabelSession,  # noqa: E402
                              load_rows, save_rows, segments_for)
from labeling.video import VideoError, probe, read_segment  # noqa: E402
from metrics import POSTURE_CLASSES  # noqa: E402


def make_video(path, seconds, fps=10, size=(64, 48)):
    """Video xám, độ sáng = 10 × số giây (giây thứ k sáng 10k) để biết đoạn nào đang được đọc."""
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    assert w.isOpened()
    for i in range(int(round(seconds * fps))):
        w.write(np.full((size[1], size[0], 3), min(255, 10 * (i // fps)), np.uint8))
    w.release()
    return path


def tmp():
    return tempfile.mkdtemp()


# ---------------------------------------------------------------- nhãn và phím
def test_labels_match_model_classes_and_keys():
    import json as _json
    cfg = _json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "posture_config.json"), encoding="utf-8"))
    assert tuple(cfg["classes"]) == CLASSES == POSTURE_CLASSES
    assert LABELS == CLASSES + (UNCLEAR,)
    assert [KEYS[str(i)] for i in range(1, 7)] == list(CLASSES) and KEYS["0"] == UNCLEAR
    assert len(KEYS) == 7


def test_segments_two_seconds_drop_remainder():
    assert segments_for(6.0) == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    assert segments_for(7.9) == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]            # phần dư 1,9 giây bị bỏ
    assert segments_for(1.99) == [] and len(segments_for(120.0)) == 60
    assert len(segments_for(5.999999999)) == 3                                      # sai số float không làm mất đoạn cuối


# ---------------------------------------------------------------- video
def test_probe_and_read_segment_from_generated_video():
    d = tmp()
    p = make_video(os.path.join(d, "v.avi"), 7.0)
    fps, dur = probe(p)
    assert fps == 10 and abs(dur - 7.0) < 0.2
    frames, _ = read_segment(p, 2.0, 4.0)
    assert len(frames) == 20
    levels = {int(f.mean()) for f in frames}
    assert all(18 <= v <= 32 for v in levels), levels                            # giây 2 và 3 (~20, ~30), không lẫn đoạn khác
    for bad in (os.path.join(d, "none.avi"),):
        try:
            probe(bad)
            raise AssertionError("phải báo lỗi")
        except VideoError:
            pass


# ---------------------------------------------------------------- phiên chấm + CSV + chấm tiếp
def new_session(d, rater="A", videos=(("v1.avi", 7.0), ("v2.avi", 4.0))):
    return LabelSession(list(videos), rater, os.path.join(d, f"labels_{rater}.csv"))


def test_assign_writes_csv_and_resumes():
    d = tmp()
    s = new_session(d)
    assert len(s.segments) == 5 and s.progress() == (0, 5) and s.index == 0     # v1: 3 đoạn, v2: 2 đoạn
    s.assign("GOOD")
    s.assign("SLOUCH")
    s.assign(UNCLEAR)
    assert s.index == 3 and s.progress() == (3, 5)
    rows = list(csv.reader(open(s.path, encoding="utf-8", newline="")))
    assert tuple(rows[0]) == FIELDS
    assert rows[1:] == [["v1.avi", "0", "2", "GOOD", "A"], ["v1.avi", "2", "4", "SLOUCH", "A"],
                        ["v1.avi", "4", "6", "UNCLEAR", "A"]]
    assert not [f for f in os.listdir(d) if f.endswith(".tmp")]                  # ghi nguyên tử, không để file tạm
    # tắt rồi mở lại: chấm tiếp từ đoạn chưa chấm đầu tiên
    s2 = new_session(d)
    assert s2.progress() == (3, 5) and s2.index == 3 and s2.current()[0] == "v2.avi"
    s2.assign("LEAN_BACKWARD")
    s2.assign("NECK_EXTENSION")
    assert s2.done and s2.index == 4
    assert [r["label"] for r in load_rows(s2.path)] == ["GOOD", "SLOUCH", "UNCLEAR", "LEAN_BACKWARD", "NECK_EXTENSION"]


def test_relabel_clear_skip_and_jump():
    d = tmp()
    s = new_session(d)
    s.assign("GOOD")
    s.step(-1)
    s.assign("FORWARD_HEAD")                                                      # sửa nhãn đoạn 0
    assert s.labels[("v1.avi", 0.0)] == "FORWARD_HEAD" and s.progress() == (1, 5)
    s.step(1)
    s.step(1)                                                                      # bỏ qua đoạn 1 (không chấm)
    s.assign("SLOUCH")
    assert s.progress() == (2, 5) and s.first_unlabeled() == 1
    assert s.goto_next_unlabeled() and s.index == 1
    s.index = 0
    s.clear()
    assert s.progress() == (1, 5) and ("v1.avi", 0.0) not in s.labels
    assert len(load_rows(s.path)) == 1
    try:
        s.assign("WRONG")
        raise AssertionError("nhãn lạ phải bị từ chối")
    except ValueError:
        pass


def test_bad_files_are_rejected_clearly():
    d = tmp()
    s = new_session(d)
    s.assign("GOOD")
    try:
        LabelSession([("v1.avi", 7.0), ("v2.avi", 4.0)], "B", s.path)             # file của A, mở bằng B
        raise AssertionError("phải từ chối file của người chấm khác")
    except LabelFileError:
        pass
    try:
        LabelSession([("khac.avi", 7.0)], "A", s.path)                             # sai video
        raise AssertionError("phải từ chối video không khớp")
    except LabelFileError:
        pass
    bad = os.path.join(d, "bad.csv")
    open(bad, "w", encoding="utf-8").write("video,t_start,t_end,label,rater\nv1.avi,0,2,HUH,A\n")
    try:
        load_rows(bad)
        raise AssertionError
    except LabelFileError:
        pass
    open(bad, "w", encoding="utf-8").write("video,t_start,t_end,label,rater\nv1.avi,0,3,GOOD,A\n")
    try:
        load_rows(bad)
        raise AssertionError
    except LabelFileError:
        pass
    for args in (([("a.avi", 5.0), ("a.avi", 5.0)], "A"), ([("a.avi", 5.0)], " "), ([("a.avi", 1.0)], "A")):
        try:
            LabelSession(args[0], args[1], os.path.join(d, "x.csv"))
            raise AssertionError(args)
        except ValueError:
            pass


# ---------------------------------------------------------------- giao diện (offscreen)
def test_window_keys_label_and_resume():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from labeling.app import LabelWindow, build_session
    app = QApplication.instance() or QApplication([])
    d = tmp()
    p = make_video(os.path.join(d, "hong.avi"), 8.0)
    out = os.path.join(d, "labels_X.csv")
    s, paths = build_session([p], "X", out)
    assert len(s.segments) == 4
    w = LabelWindow(s, paths)
    w.show()
    assert len(w.frames) == 20
    QTest.keyClick(w, Qt.Key_1)                                                    # GOOD, sang đoạn 2
    QTest.keyClick(w, Qt.Key_4)                                                    # SLOUCH, sang đoạn 3
    QTest.keyClick(w, Qt.Key_Left)                                                 # về đoạn 2, không đổi nhãn
    QTest.keyClick(w, Qt.Key_6)                                                    # sửa thành NECK_EXTENSION
    QTest.keyClick(w, Qt.Key_0)                                                    # UNCLEAR cho đoạn 3
    w.close()
    assert [r["label"] for r in load_rows(out)] == ["GOOD", "NECK_EXTENSION", "UNCLEAR"]
    s2, paths2 = build_session([p], "X", out)                                      # mở lại, chấm tiếp
    assert s2.index == 3 and s2.progress() == (3, 4)
    w2 = LabelWindow(s2, paths2)
    QTest.keyClick(w2, Qt.Key_2)
    assert s2.done and load_rows(out)[-1]["label"] == "FORWARD_HEAD"
    w2.close()


# ---------------------------------------------------------------- Cohen's κ
def pairs(counts):
    a, b = [], []
    for (x, y), n in counts.items():
        a += [x] * n
        b += [y] * n
    return a, b


def test_kappa_known_value():
    # ví dụ kinh điển: 50 mục, đồng ý 20 + 15, lệch 5 + 10 -> po = 0,7, pe = 0,5, κ = 0,4
    a, b = pairs({("GOOD", "GOOD"): 20, ("GOOD", "SLOUCH"): 5, ("SLOUCH", "GOOD"): 10, ("SLOUCH", "SLOUCH"): 15})
    r = K.cohen_kappa(a, b, CLASSES)
    assert r["n"] == 50 and abs(r["observed"] - 0.7) < 1e-9 and abs(r["expected"] - 0.5) < 1e-9
    assert abs(r["kappa"] - 0.4) < 1e-9 and r["ci95"][0] < 0.4 < r["ci95"][1]
    try:
        from sklearn.metrics import cohen_kappa_score
        assert abs(cohen_kappa_score(a, b) - r["kappa"]) < 1e-9
    except ImportError:
        pass


def test_kappa_perfect_chance_and_degenerate():
    labels = list(CLASSES) * 10
    assert abs(K.cohen_kappa(labels, labels, CLASSES)["kappa"] - 1.0) < 1e-9
    rng = np.random.default_rng(0)
    a = list(rng.choice(CLASSES, 6000))
    b = list(rng.choice(CLASSES, 6000))
    assert abs(K.cohen_kappa(a, b, CLASSES)["kappa"]) < 0.03                      # hai người chấm ngẫu nhiên độc lập ~ 0
    assert math.isnan(K.cohen_kappa(["GOOD"] * 5, ["GOOD"] * 5, CLASSES)["kappa"])  # pe = 1: không xác định
    assert K.cohen_kappa([], [], CLASSES)["n"] == 0
    try:
        K.cohen_kappa(["GOOD"], [], CLASSES)
        raise AssertionError
    except ValueError:
        pass


def write_labels(path, rater, items):
    save_rows(path, [dict(video=v, t_start=t, t_end=t + 2.0, label=lab, rater=rater) for v, t, lab in items])


def test_compare_overlap_unclear_and_cli():
    d = tmp()
    A, B = os.path.join(d, "a.csv"), os.path.join(d, "b.csv")
    items = [("v1.avi", 2.0 * i) for i in range(8)]
    la = ["GOOD", "GOOD", "SLOUCH", "SLOUCH", UNCLEAR, "GOOD", "LEAN_FORWARD", "GOOD"]
    lb = ["GOOD", "SLOUCH", "SLOUCH", "SLOUCH", "GOOD", "GOOD", "LEAN_FORWARD", "FORWARD_HEAD"]
    write_labels(A, "A", [(v, t, lab) for (v, t), lab in zip(items, la)])
    write_labels(B, "B", [(v, t, lab) for (v, t), lab in zip(items[:7], lb[:7])] + [("v9.avi", 0.0, "GOOD")])  # B bỏ đoạn 8, thêm v9
    res = K.compare([A, B])
    assert len(res) == 1
    r = res[0]
    assert (r["rater_a"], r["rater_b"]) == ("A", "B") and r["overlap"] == 7 and r["dropped_unclear"] == 1
    assert r["only_a"] == 1 and r["only_b"] == 1 and r["n"] == 6
    assert abs(r["observed"] - 5 / 6) < 1e-9                                       # 6 đoạn tính: lệch đúng 1 (đoạn thứ 2)
    r7 = K.compare([A, B], include_unclear=True)[0]
    assert r7["n"] == 7 and len(r7["labels"]) == 7
    text = K.format_report(res)
    assert "κ" in text and "A vs B" in text
    out = os.path.join(d, "k.json")
    assert K.main([A, B, "--json", out]) == 0
    data = json.load(open(out, encoding="utf-8"))
    assert data[0]["n"] == 6 and data[0]["labels"] == list(CLASSES)
    # hai người chung một file cũng được; chỉ một người thì báo lỗi rõ ràng
    both = os.path.join(d, "both.csv")
    write_labels(both, "A", [(v, t, lab) for (v, t), lab in zip(items, la)])
    assert K.main([both]) == 2
    assert K.main([A, os.path.join(d, "khong_co.csv")]) == 2                      # gõ sai tên file: báo lỗi, không im lặng


def test_cli_degenerate_json_has_null_not_nan():
    d = tmp()
    A, B = os.path.join(d, "a.csv"), os.path.join(d, "b.csv")
    items = [("v.avi", 2.0 * i, "GOOD") for i in range(4)]
    write_labels(A, "A", items)
    write_labels(B, "B", items)
    out = os.path.join(d, "k.json")
    assert K.main([A, B, "--json", out]) == 0
    raw = open(out, encoding="utf-8").read()
    assert "NaN" not in raw and json.loads(raw)[0]["kappa"] is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
