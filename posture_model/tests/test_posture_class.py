"""Kiểm thử chọn lớp tư thế của model v4 (6 lớp), gồm trường hợp model cũ 1 output:  python tests/test_posture_class.py"""
import json
import os
import sys
import collections

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import posture_class as pc  # noqa: E402

CLASSES = ["GOOD", "FORWARD_HEAD", "LEAN_FORWARD", "SLOUCH", "LEAN_BACKWARD", "NECK_EXTENSION"]


def test_softmax_sums_to_one():
    p = pc.softmax([1000.0, 0.0, -5.0])          # không tràn số
    assert abs(p.sum() - 1) < 1e-9 and p.argmax() == 0


def test_bad_state_picks_best_bad_class_not_good():
    probs = np.array([0.40, 0.10, 0.05, 0.30, 0.10, 0.05])    # GOOD cao nhất nhưng tổng thể đang BAD
    assert pc.pick_posture_class(probs, CLASSES, "BAD") == "SLOUCH"


def test_good_state_is_good_even_if_bad_class_leads():
    probs = np.array([0.2, 0.6, 0.05, 0.05, 0.05, 0.05])
    assert pc.pick_posture_class(probs, CLASSES, "GOOD") == "GOOD"


def test_other_states_give_none():
    probs = np.full(6, 1 / 6)
    for st in ("UNKNOWN", "AWAY", "CALIBRATING", None):
        assert pc.pick_posture_class(probs, CLASSES, st) is None


def test_old_model_single_output():
    assert pc.find_posture_output(["logit"]) is None
    assert pc.find_posture_output(["logit", "posture_logits"]) == 1
    assert pc.mean_probs(collections.deque()) is None
    for st in ("GOOD", "BAD"):
        assert pc.pick_posture_class(None, CLASSES, st) is None
    assert pc.pick_posture_class(np.full(6, 1 / 6), [], "BAD") is None
    assert pc.probs_dict(None, CLASSES) is None


def test_mean_over_history_is_stable():
    hist = collections.deque(maxlen=5)
    for i in range(5):                                         # 1 cửa sổ nhiễu giữa 4 cửa sổ FORWARD_HEAD
        hist.append(np.array([0.05, 0.1, 0.8, 0.02, 0.02, 0.01]) if i == 2 else
                    np.array([0.05, 0.7, 0.1, 0.05, 0.05, 0.05]))
    assert pc.pick_posture_class(pc.mean_probs(hist), CLASSES, "BAD") == "FORWARD_HEAD"


def test_labels_vietnamese_cover_config_classes():
    cfg = json.load(open(os.path.join(os.path.dirname(HERE), "posture_config.json"), encoding="utf-8"))
    assert cfg["classes"] == CLASSES
    assert all(pc.CLASS_VI.get(c) for c in cfg["classes"])
    assert pc.class_label_vi("SLOUCH") == "Gù lưng" and pc.class_label_vi(None) is None


def test_onnx_outputs_match_config():
    import onnxruntime as ort
    s = ort.InferenceSession(os.path.join(os.path.dirname(HERE), "posture_transformer.onnx"),
                             providers=["CPUExecutionProvider"])
    idx = pc.find_posture_output(o.name for o in s.get_outputs())
    assert idx is not None
    out = s.run(None, {"x": np.zeros((1, 20, 6), np.float32)})
    assert out[idx].shape == (1, len(CLASSES))


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"{len(fns)}/{len(fns)} test đạt")
