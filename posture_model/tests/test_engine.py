"""Kiểm thử PostureEngine bằng video trắng + landmark giả (không cần camera):  python tests/test_engine.py"""
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import engine as engine_mod  # noqa: E402
from engine import EngineListener, EngineOptions, PostureEngine  # noqa: E402
from fake_pose import FakePoseDetector, make_blank_video, write_config  # noqa: E402
from notifier import NotifierBase  # noqa: E402


class Rec(EngineListener):
    def __init__(self):
        self.states, self.alerts, self.syncs, self.frames = [], [], [], []
        self.metrics, self.configs, self.finished, self.errors = [], [], None, []

    def on_state(self, s): self.states.append(s)
    def on_alert(self, e): self.alerts.append(e)
    def on_sync(self, i): self.syncs.append(i)
    def on_frame(self, f): self.frames.append(f)
    def on_metrics(self, m): self.metrics.append(m)
    def on_config(self, c): self.configs.append(c)
    def on_error(self, m): self.errors.append(m)
    def on_finished(self, reason, stats): self.finished = (reason, stats)


class QuietNotifier(NotifierBase):
    def __init__(self): self.seen = []
    def __call__(self, ev):
        if ev.get("notify"):
            self.seen.append(ev)


def _opts(d, video, **kw):
    cfg = write_config(os.path.join(d, "cfg.json"))
    return EngineOptions(side_video=video, front="-1", config=cfg, events=os.path.join(d, "ev.jsonl"),
                         metrics_out=os.path.join(d, "m.jsonl"), outbox=os.path.join(d, "ob.db"), **kw)


def _video(d, seconds=30):
    p = os.path.join(d, "v.avi")
    make_blank_video(p, seconds)
    return p


def test_state_transitions_and_events():
    engine_mod.PoseDetector = FakePoseDetector
    with tempfile.TemporaryDirectory() as d:
        rec, nt = Rec(), QuietNotifier()
        eng = PostureEngine(_opts(d, _video(d)), notifier=nt, listener=rec)
        assert eng.run() == "video_end"
        assert rec.finished[0] == "video_end" and not rec.errors
        seq = [s["state"] for s in rec.states]
        order = [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]
        assert order == ["CALIBRATING", "GOOD", "BAD", "GOOD"], order
        kinds = [json.loads(l)["eventType"] for l in open(os.path.join(d, "ev.jsonl"), encoding="utf-8")]
        assert kinds[0] == "SESSION_START" and kinds[-1] == "SESSION_END", kinds
        assert "CALIBRATED" in kinds and "ALERT_STARTED" in kinds and "ALERT_RESOLVED" in kinds, kinds
        assert [a["eventType"] for a in rec.alerts] == ["ALERT_STARTED"]
        assert [a["eventType"] for a in nt.seen] == ["ALERT_STARTED"]
        assert rec.syncs and rec.syncs[-1]["hasServer"] is False and rec.metrics


def test_no_frames_unless_requested():
    engine_mod.PoseDetector = FakePoseDetector
    with tempfile.TemporaryDirectory() as d:
        rec = Rec()
        PostureEngine(_opts(d, _video(d, 6)), notifier=QuietNotifier(), listener=rec).run()
        assert rec.frames == []
        rec = Rec()
        eng = PostureEngine(_opts(d, _video(d, 6)), notifier=QuietNotifier(), listener=rec)
        eng.want_frames = True
        eng.run()
        f = rec.frames[0]
        assert f["side"].shape == (240, 320, 3) and "Ls" in f and f["vis_side"] is None


def test_thread_stop_and_recalibrate():
    engine_mod.PoseDetector = FakePoseDetector
    with tempfile.TemporaryDirectory() as d:
        rec = Rec()
        eng = PostureEngine(_opts(d, _video(d, 60)), notifier=QuietNotifier(), listener=rec)
        eng.start()
        time.sleep(3)
        eng.request_recalibrate()
        time.sleep(1.0)
        eng.stop()
        eng.join(20)
        assert not eng.running and rec.finished is not None and not rec.errors
        assert rec.finished[0] in ("stopped", "video_end")
        assert threading.active_count() <= 2          # luồng Sender đã dừng


def test_open_failure_reports_error():
    engine_mod.PoseDetector = FakePoseDetector
    with tempfile.TemporaryDirectory() as d:
        rec = Rec()
        eng = PostureEngine(_opts(d, os.path.join(d, "khong_co.avi")), notifier=QuietNotifier(), listener=rec)
        eng.start()
        eng.join(20)
        assert rec.errors and "camera" in rec.errors[0].lower() and rec.finished[0] == "error"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        t = time.time()
        fn()
        print(f"OK  {fn.__name__}  ({time.time() - t:.1f}s)")
    print(f"{len(fns)}/{len(fns)} test đạt")
