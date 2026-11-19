"""Kịch bản clip (script_v2.json), mốc thời gian trong clip và chấm "Mức cần đạt". Không phụ thuộc Qt / camera."""
import json
import math
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(HERE, "script_v2.json")

DAT, CHUA_DU, KHONG_THAY, THEO_HIEU_LENH = "DAT", "CHUA_DU", "KHONG_THAY", "THEO_HIEU_LENH"
STATUS_TEXT = {DAT: "ĐẠT", CHUA_DU: "CHƯA ĐỦ", KHONG_THAY: "KHÔNG THẤY NGƯỜI", THEO_HIEU_LENH: "THEO HIỆU LỆNH"}
SIT_STRAIGHT = "NGỒI THẲNG"


@dataclass
class Phase:
    start: float
    label: str
    check: list = None          # None = không có mức số
    cm: int = None


@dataclass
class Clip:
    id: str
    clip: str
    duration: int
    cam: str                    # side | front | both
    cam_text: str
    cue: str
    goal: str
    block: str = ""
    phases: list = field(default_factory=list)
    margin: float = 3.0

    @property
    def is_calibration(self):
        return self.id == "A1"

    def phase_at(self, t):
        cur = self.phases[0]
        for p in self.phases:
            if t >= p.start:
                cur = p
        return cur

    def next_phase(self, t):
        return next((p for p in self.phases if p.start > t), None)

    def marks(self):
        """Mốc bíp giữa clip: [(giây, nhãn mức mới)]. Mức đầu (giây 0) không tính, đã có bíp bắt đầu."""
        return [(p.start, p.label) for p in self.phases if p.start > 0]

    def banner(self, t):
        """Chữ nổi hiện ở giây t: NGỒI THẲNG ở 3 s đầu / cuối, tên mức trong 3 s sau mỗi mốc, còn lại ''."""
        if t < self.margin or t >= self.duration - self.margin:
            return SIT_STRAIGHT
        p = self.phase_at(t)
        if p.label and p.start > 0 and t - p.start < self.margin:
            return p.label
        return ""

    def judged(self, t):
        """Giây t có tính vào % đạt không (bỏ 3 s đầu và cuối, và mức không có điều kiện)."""
        return self.margin <= t < self.duration - self.margin and self.phase_at(t).check is not None

    def has_check(self):
        return any(p.check is not None for p in self.phases)


def load_script(path=SCRIPT_PATH):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    clips = []
    for c in raw["clips"]:
        ph = [Phase(p["start"], p["label"], p.get("check"), p.get("cm")) for p in c["phases"]]
        clips.append(Clip(c["id"], c["clip"], c["duration"], c["cam"], c["cam_text"], c["cue"], c["goal"],
                          c.get("block", ""), ph, float(raw.get("margin_sec", 3))))
    return clips


def select_clips(clips, start_from=None, only=None):
    """--from <tên clip hoặc mã> (bỏ các clip trước đó) và --only a,b,c (chỉ các clip này). Sai tên -> ValueError."""
    def find(key):
        for i, c in enumerate(clips):
            if key.upper() in (c.clip.upper(), c.id.upper()):
                return i
        raise ValueError(f"Không có clip '{key}' trong kịch bản.")
    out = list(clips)
    if only:
        keys = [k.strip() for k in only.split(",") if k.strip()]
        idx = {find(k) for k in keys}
        out = [c for i, c in enumerate(clips) if i in idx]
    if start_from:
        i = find(start_from)
        out = [c for c in out if clips.index(c) >= i]
    return out


# ------------------------------------------------------------------ chấm điểm
def _cond_ok(cond, value):
    v = abs(value) if cond.get("abs") else value
    return ("min" not in cond or v >= cond["min"]) and ("max" not in cond or v <= cond["max"])


def check_status(check, metrics):
    """check: danh sách điều kiện (hoặc None); metrics: dict số đo (None/NaN = không đo được).
    -> THEO_HIEU_LENH | KHONG_THAY | DAT | CHUA_DU"""
    if check is None:
        return THEO_HIEU_LENH
    for cond in check:
        v = metrics.get(cond["m"])
        if v is None or not math.isfinite(v):
            return KHONG_THAY
    return DAT if all(_cond_ok(c, metrics[c["m"]]) for c in check) else CHUA_DU


def describe_check(check):
    """Điều kiện -> chữ ngắn, vd 'cổ 20–30°'."""
    names = {"neck": "cổ", "trunk": "thân", "tilt": "lệch vai", "raise": "nhún vai"}
    parts = []
    for c in check or []:
        n = names[c["m"]]
        if "min" in c and "max" in c:
            parts.append(f"{n} {c['min']:g}–{c['max']:g}°")
        elif "min" in c:
            parts.append(f"{n} > {c['min']:g}°")
        else:
            parts.append(f"{n} < {c['max']:g}°")
    return " và ".join(parts)


class PassCounter:
    """Đếm % thời gian đạt trong một clip: chỉ tính mẫu ở khoảng được chấm (xem Clip.judged)."""

    def __init__(self, clip):
        self.clip = clip
        self.ok = 0
        self.total = 0

    def add(self, t, status):
        if self.clip.judged(t) and status != THEO_HIEU_LENH:
            self.total += 1
            self.ok += status == DAT

    @property
    def pct(self):
        return None if self.total == 0 else 100.0 * self.ok / self.total
