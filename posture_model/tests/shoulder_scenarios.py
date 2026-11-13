"""Kịch bản cam giả dùng chung cho test nhánh vai và để sinh/kiểm log vàng của bản TRƯỚC PR #22.

Chạy trực tiếp để in chữ ký sự kiện của engine ở thư mục hiện tại (dùng sinh tests/golden/shoulder_pre_pr22.json từ một
worktree của commit trước PR #22):  python tests/shoulder_scenarios.py golden.json
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import engine as engine_mod  # noqa: E402
from engine import EngineListener, EngineOptions, PostureEngine  # noqa: E402
from fake_pose import FakeFrontDetector, FakePoseDetector, make_blank_video, write_config  # noqa: E402
from notifier import NotifierBase  # noqa: E402


class Quiet(NotifierBase):
    def __call__(self, ev):
        pass


def square(amp, period_frames=4):
    """Đảo dấu ±amp mỗi nửa chu kỳ (mẫu 10 fps) – cử động mạnh, trung vị vẫn lệch."""
    return lambda t: amp if int(round(t * 10)) % period_frames < period_frames // 2 else -amp


def run(front_schedule, side_schedule=None, seconds=30, **cfg):
    """Chạy engine với video trắng + cam giả. Trả (danh sách sự kiện, nội dung log.csv)."""
    side_sched = side_schedule or [(1e9, 0)]

    class Side(FakePoseDetector):
        schedule = side_sched

    class Front(FakeFrontDetector):
        schedule = front_schedule

    made = []

    def factory(task):
        det = Side(task) if not made else Front(task)
        made.append(det)
        return det
    engine_mod.PoseDetector = factory
    with tempfile.TemporaryDirectory() as d:
        video = os.path.join(d, "v.avi")
        make_blank_video(video, seconds)
        conf = write_config(os.path.join(d, "cfg.json"), **cfg)
        opts = EngineOptions(side_video=video, front_video=video, no_face=True, config=conf,
                             events=os.path.join(d, "ev.jsonl"), metrics_out=os.path.join(d, "m.jsonl"),
                             outbox=os.path.join(d, "ob.db"), send=False, log=os.path.join(d, "log.csv"))
        eng = PostureEngine(opts, notifier=Quiet(), listener=EngineListener())
        assert eng.run() == "video_end"
        ev = [json.loads(l) for l in open(opts.events, encoding="utf-8")]
        log = open(opts.log, encoding="utf-8").read()
    return ev, log


def _sec(ts):
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def signature(ev):
    """Chữ ký so sánh: (loại sự kiện, loại cảnh báo, giây kể từ SESSION_START làm tròn 0,1), bỏ mở/đóng phiên."""
    t0 = _sec(next(e for e in ev if e["eventType"] == "SESSION_START")["ts"])
    return [[e["eventType"], e.get("alertType"), round(_sec(e["ts"]) - t0, 1)] for e in ev
            if e["eventType"] not in ("SESSION_START", "SESSION_END")]


# tên -> (lịch cam trước, lịch cam hông). Nhún vai chỉ đổi khoảng cách tai-vai nên bản cũ (không có shoulder_raise) không thấy.
SCENARIOS = {
    "good": ([(1e9, 0.0, 0.0)], None),
    "tilt": ([(6, 0.0, 0.0), (1e9, 6.0, 0.0)], None),
    "tilt_then_back": ([(6, 0.0, 0.0), (12, 6.0, 0.0), (1e9, 0.0, 0.0)], None),
    "wave": ([(6, 0.0, 0.0), (1e9, square(6.0), 0.0)], None),
    "shrug": ([(6, 0.0, 0.0), (1e9, 0.0, 0.4)], None),
    "bow_and_shrug": ([(6, 0.0, 0.0), (1e9, 0.0, 0.4)], [(6, 0), (1e9, 70)]),
}

if __name__ == "__main__":
    out = {name: signature(run(fs, ss)[0]) for name, (fs, ss) in SCENARIOS.items()}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if len(sys.argv) > 1:
        open(sys.argv[1], "w", encoding="utf-8").write(text + "\n")      # engine in nhiều dòng ra stdout nên ghi file
    else:
        print(text)
