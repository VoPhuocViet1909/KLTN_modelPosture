"""Chọn lớp tư thế xấu (6 lớp của model v4) từ output "posture_logits". Hàm thuần, không phụ thuộc camera/ONNX.

Thứ tự lớp theo posture_config.json["classes"]; chỉ số 0 luôn là GOOD. Model cũ chỉ có output "logit" -> không có lớp.
"""
import numpy as np

GOOD = "GOOD"

# Tên tiếng Việt hiện trên UI PySide6
CLASS_VI = {
    "GOOD": "Ngồi tốt",
    "FORWARD_HEAD": "Đầu đưa ra trước",
    "LEAN_FORWARD": "Cúi người về trước",
    "SLOUCH": "Gù lưng",
    "LEAN_BACKWARD": "Ngả ra sau",
    "NECK_EXTENSION": "Ngửa cổ",
}


def class_label_vi(cls):
    """Tên tiếng Việt của lớp; None nếu không có lớp, tên lạ thì trả nguyên tên."""
    return None if cls is None else CLASS_VI.get(cls, cls)


def find_posture_output(output_names):
    """Chỉ số output "posture_logits" trong ONNX; None nếu model cũ chỉ có 1 output."""
    names = list(output_names)
    return names.index("posture_logits") if "posture_logits" in names else None


def softmax(logits):
    z = np.asarray(logits, dtype=np.float64)
    z = np.exp(z - z.max())
    return z / z.sum()


def mean_probs(prob_hist):
    """Trung bình xác suất các cửa sổ gần nhất (làm mượt như p_hist); None nếu chưa có."""
    return np.mean(np.stack(list(prob_hist)), axis=0) if len(prob_hist) else None


def pick_posture_class(probs, classes, state):
    """Lớp tư thế để báo.

    state: "GOOD" -> "GOOD"; "BAD" -> lớp xấu có xác suất trung bình cao nhất (bỏ lớp GOOD ra);
    trạng thái khác (UNKNOWN, AWAY, ...) hoặc chưa có xác suất (model cũ) -> None.
    """
    if probs is None or not classes or len(probs) != len(classes):
        return None
    if state == GOOD:
        return GOOD
    if state != "BAD":
        return None
    bad = [(p, c) for p, c in zip(probs, classes) if c != GOOD]
    return max(bad, key=lambda x: x[0])[1] if bad else None


def probs_dict(probs, classes, ndigits=3):
    if probs is None or len(probs) != len(classes):
        return None
    return {c: round(float(p), ndigits) for c, p in zip(classes, probs)}
