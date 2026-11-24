"""postureClassSeconds trong metrics: cộng dồn theo lớp, tương thích ngược, đúng schema. Không cần camera/server."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics import MetricsAggregator, POSTURE_CLASSES
from schema import validate


def run(classes, present=True):
    """classes: lớp ở mỗi giây (None = không có lớp)."""
    agg = MetricsAggregator(None, 1800000000, "session", "device", user_id=None)
    for t, c in enumerate(classes):
        agg.add(float(t), present, "GOOD" if c == "GOOD" else "BAD" if c else None, posture_class=c)
    return agg.flush()


def test_seconds_per_class():
    row = run(["GOOD"] * 11 + ["FORWARD_HEAD"] * 6 + ["SLOUCH"] * 4 + [None] * 4)
    secs = row["postureClassSeconds"]
    assert secs == {"GOOD": 10.0, "FORWARD_HEAD": 6.0, "SLOUCH": 4.0}, secs   # mẫu đầu tiên có dt = 0
    assert sum(secs.values()) <= row["presenceSec"]
    assert validate("metrics", row) == []


def test_no_class_means_field_omitted():
    row = run([None] * 30)                    # model cũ 1 output: không có lớp -> không gửi trường, vẫn hợp lệ
    assert "postureClassSeconds" not in row and validate("metrics", row) == []


def test_absent_person_not_counted():
    row = run(["SLOUCH"] * 30, present=False)
    assert row is None or "postureClassSeconds" not in row


def test_unknown_class_ignored():
    row = run(["GOOD"] * 12 + ["WEIRD"] * 12)
    assert row["postureClassSeconds"] == {"GOOD": 11.0}


def test_schema_rules():
    base = run(["GOOD"] * 12)
    assert validate("metrics", {**base, "postureClassSeconds": {"GOOD": 5, "SLOUCH": 2.5}}) == []
    for bad in ({"WEIRD": 3}, {"GOOD": -1}, {"GOOD": "3"}, [], 5):
        assert validate("metrics", {**base, "postureClassSeconds": bad}), bad
    old = dict(base)
    old.pop("postureClassSeconds", None)
    assert validate("metrics", old) == []     # client cũ


def test_classes_match_model_config():
    import json
    cfg = json.load(open(Path(__file__).resolve().parents[1] / "posture_config.json", encoding="utf-8"))
    assert tuple(cfg["classes"]) == POSTURE_CLASSES


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("PASS: postureClassSeconds")
