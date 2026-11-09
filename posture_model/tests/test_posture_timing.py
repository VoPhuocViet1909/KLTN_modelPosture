"""Run directly: no camera, server or Docker."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrics import MetricsAggregator
from schema import validate


def metric(enabled):
    agg = MetricsAggregator(None, 1800000000, "session", "device", timing_v1=enabled)
    for t in range(21):
        agg.add(t, True, "GOOD" if t <= 5 else "BAD" if t <= 10 else None)
    return agg.flush()


def test_optional_and_measured():
    assert "postureKnownSec" not in metric(False)
    row = metric(True)
    assert row["presenceSec"] == 20
    assert row["postureKnownSec"] == 10 and row["postureGoodSec"] == 5
    assert row["goodRatio"] == .5 and validate("metrics", row) == []


def test_invalid_timing():
    original = metric(True)
    for changes in ({"postureKnownSec": None}, {"postureGoodSec": 30},
                    {"postureKnownSec": float("nan")}, {"goodRatio": .9},
                    {"postureKnownSec": 0, "postureGoodSec": 0, "goodRatio": .5}):
        assert validate("metrics", {**original, **changes}), changes
    missing = dict(original)
    del missing["postureGoodSec"]
    assert validate("metrics", missing)


if __name__ == "__main__":
    test_optional_and_measured()
    test_invalid_timing()
    print("PASS: opt-in, measured vs presence, missing/nonfinite/inconsistent timing")
