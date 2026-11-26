"""Đọc và kiểm `minutes.jsonl` + `sessions.jsonl` (hợp đồng kế hoạch mục 3.1–3.2, snake_case). Không đọc DB/API.

Mỗi phiên -> `Session` với các mảng theo phút. Lớp bị thiếu (null cả 6 trường) KHÔNG bị biến thành 0 ở mức lưu trữ:
`cls` là NaN, còn `classified` (tổng 6 lớp) = 0 ở phút đó. Phút thiếu bản ghi/không phân lớp được xử lý ở labels/features qua `classified`.
"""
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

CLASSES = ("good", "forward_head", "lean_forward", "slouch", "lean_backward", "neck_extension")
CLASS_FIELDS = tuple(f"{c}_sec" for c in CLASSES)
SESSION_FIELDS = {"participant", "session_id", "started_at", "ended_at", "duration_min", "camera_setup",
                  "study_opt_in", "ended_early", "note"}
MINUTE_FIELDS = {"participant", "session_id", "minute_idx", "window_start", "covered_sec", "presence_sec", "away_sec",
                 "unknown_sec", "unclassified_sec", "alerts_total", "model_version", "app_version", *CLASS_FIELDS}


class DataError(ValueError):
    pass


def _req(cond, msg):
    if not cond:
        raise DataError(msg)


def _num(v, lo, hi):
    return type(v) in (int, float) and not isinstance(v, bool) and lo <= v <= hi


def _ts(v):
    _req(isinstance(v, str), "timestamp phải là chuỗi")
    d = datetime.fromisoformat(v)
    _req(d.utcoffset() is not None, "timestamp phải có múi giờ")
    return d


@dataclass
class Session:
    participant: str
    session_id: str
    started_at: datetime
    n: int
    window_sec: float
    window_start: list
    covered: np.ndarray
    presence: np.ndarray
    away: np.ndarray
    unknown: np.ndarray
    cls: np.ndarray            # (n,6) giây từng lớp, NaN khi thiếu
    alerts: np.ndarray         # (n,) số cảnh báo trong phút
    model_version: list = field(default_factory=list)

    @property
    def classified(self):      # tổng 6 lớp, 0 khi thiếu
        return np.nan_to_num(self.cls, nan=0.0).sum(1)

    @property
    def good(self):
        return np.nan_to_num(self.cls[:, 0], nan=0.0)

    @property
    def bad(self):             # tổng 5 lớp xấu
        return np.nan_to_num(self.cls[:, 1:], nan=0.0).sum(1)

    def hour_of_day(self, t):
        w = self.window_start[t]
        return w.hour + w.minute / 60.0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path):
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield i, json.loads(line)
            except ValueError:
                raise DataError(f"{Path(path).name} dòng {i}: JSON hỏng") from None


def check_minute(row, start, count, window_sec=60.0):
    """Quy tắc kiểm 3.1. Ném DataError khi sai."""
    idx = row["minute_idx"]
    _req(type(idx) is int and 0 <= idx < count, "minute_idx ngoài phiên")
    _req(_ts(row["window_start"]) == start + timedelta(minutes=idx), "window_start không khớp minute_idx")
    cov, pre, away, unk = (row[k] for k in ("covered_sec", "presence_sec", "away_sec", "unknown_sec"))
    _req(all(_num(v, 0, window_sec) for v in (cov, pre, away, unk)), "thời gian phủ không hợp lệ")
    _req(pre <= cov + 1e-9 and abs(away + pre - cov) <= 1 and abs(unk + cov - window_sec) <= 1
         and abs(away + pre + unk - window_sec) <= 1, "away + unknown + presence != window_sec (sai số > 1 s)")
    vals = [row[k] for k in CLASS_FIELDS]
    unc = row["unclassified_sec"]
    if all(v is None for v in vals):
        _req(unc == pre, "thiếu lớp thì unclassified_sec phải bằng presence_sec")
    else:
        _req(all(_num(v, 0, window_sec) for v in vals), "giây lớp không hợp lệ (không được trộn null và số)")
        _req(sum(vals) <= pre + 0.3 + 1e-9, "tổng 6 lớp > presence_sec + 0,3")
        _req(_num(unc, 0, window_sec) and abs(sum(vals) + unc - pre) <= 1, "lớp + unclassified không khớp presence")
    _req(type(row["alerts_total"]) is int and row["alerts_total"] >= 0, "alerts_total không hợp lệ")
    return idx


def load(directory, window_sec=60.0):
    """-> dict (participant, session_id) -> Session. Chỉ nhận phiên study_opt_in; thiếu dòng phút là lỗi (phải có dòng unknown)."""
    d = Path(directory)
    sessions, timing, minutes = {}, {}, {}
    for i, r in _rows(d / "sessions.jsonl"):
        try:
            _req(r.keys() == SESSION_FIELDS, "thiếu hoặc thừa trường")
            start, end = _ts(r["started_at"]), _ts(r["ended_at"])
            dur = (end - start).total_seconds() / 60
            _req(dur > 0 and _num(r["duration_min"], 0, math.inf) and abs(r["duration_min"] - dur) <= 1 / 60,
                 "duration_min không khớp")
            _req(r["study_opt_in"] is True, "phiên không có study_opt_in")
            key = (r["participant"], r["session_id"])
            _req(all(isinstance(k, str) and k for k in key), "mã người/phiên rỗng")
            _req(key not in sessions, "phiên trùng")
            floor = start.replace(second=0, microsecond=0)
            sessions[key] = r
            timing[key] = (floor, math.ceil((end - floor).total_seconds() / 60))
            minutes[key] = {}
        except (DataError, KeyError, TypeError, ValueError) as e:
            raise DataError(f"sessions.jsonl dòng {i}: {e}") from None
    _req(bool(sessions), "không có phiên nào")
    for i, r in _rows(d / "minutes.jsonl"):
        try:
            _req(r.keys() == MINUTE_FIELDS, "thiếu hoặc thừa trường")
            key = (r["participant"], r["session_id"])
            _req(key in timing, "phút không có phiên")
            idx = check_minute(r, *timing[key], window_sec=window_sec)
            _req(idx not in minutes[key], "phút trùng")
            minutes[key][idx] = r
        except (DataError, KeyError, TypeError, ValueError) as e:
            raise DataError(f"minutes.jsonl dòng {i}: {e}") from None
    out = {}
    for key, (floor, n) in timing.items():
        _req(len(minutes[key]) == n, f"phiên {key}: thiếu dòng phút ({len(minutes[key])}/{n}), phải có dòng unknown")
        rows = [minutes[key][k] for k in range(n)]
        cls = np.array([[np.nan if r[f] is None else r[f] for f in CLASS_FIELDS] for r in rows], float)
        out[key] = Session(
            participant=key[0], session_id=key[1], started_at=floor, n=n, window_sec=window_sec,
            window_start=[_ts(r["window_start"]) for r in rows],
            covered=np.array([r["covered_sec"] for r in rows], float), presence=np.array([r["presence_sec"] for r in rows], float),
            away=np.array([r["away_sec"] for r in rows], float), unknown=np.array([r["unknown_sec"] for r in rows], float),
            cls=cls, alerts=np.array([r["alerts_total"] for r in rows], int), model_version=[r["model_version"] for r in rows])
    return out


def data_hash(directory):
    """Hash cố định của hai file đầu vào."""
    d = Path(directory)
    return dict(minutes=sha256_file(d / "minutes.jsonl"), sessions=sha256_file(d / "sessions.jsonl"))


def summary(sessions):
    people = sorted({s.participant for s in sessions.values()})
    n_min = sum(s.n for s in sessions.values())
    miss = sum(int((s.classified == 0).sum()) for s in sessions.values())
    versions = sorted({v for s in sessions.values() for v in s.model_version if v})
    return dict(participants=people, n_sessions=len(sessions), n_minutes=n_min, minutes_without_classes=miss,
                model_versions=versions)
