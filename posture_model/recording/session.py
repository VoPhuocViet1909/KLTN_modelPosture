"""Lõi một buổi quay (không phụ thuộc Qt): trạng thái, đồng hồ, bíp, ghi file, baseline, chấm điểm trực tiếp, nhật ký.

Trạng thái: IDLE -> COUNTDOWN (3-2-1) -> RECORDING -> (AWAIT_CM nếu là E7) -> IDLE. Giao diện chỉ gọi press_*() và tick() ~30 lần/giây."""
import csv
import json
import math
import os
import shutil
import time
from collections import deque
from datetime import datetime

import numpy as np

import calibration
from posture_features import (FEATURES, apply_calibration, calibration_baseline, choose_side, facing_sign,
                              sequence_angles, shoulder_raise, shoulder_tilt)
from quality import dist_ok
from recording.capture import FPS, ClipWriter
from recording.disk import LOW_BYTES, disk_report, measured_rate
from recording.script import KHONG_THAY, THEO_HIEU_LENH, PassCounter, check_status

IDLE, COUNTDOWN, RECORDING, AWAIT_CM = "IDLE", "COUNTDOWN", "RECORDING", "AWAIT_CM"
CAL_SEC = 15.0               # baseline lấy từ 15 s giữa A1 (sau 3 s đầu)
FPS_WARN = 27.0              # FPS thật thấp hơn mức này thì cảnh báo
SKEW_WARN_SEC = 0.100        # 2 cam lệch thời gian hơn mức này thì cảnh báo
HINT_LOW_PCT = 70.0          # % đạt thấp hơn mức này thì gợi ý quay lại (chỉ là gợi ý)
SESSION_COLS = ["nguoi", "buoi", "clip", "gio_bat_dau", "thoi_luong_s", "fps_hong", "fps_laptop", "phan_tram_dat",
                "so_lan_quay_lai", "cm_thuoc", "ghi_chu", "nguoi_cham_1", "nguoi_cham_2"]
CAM_NAME = {"side": "hông", "front": "laptop"}


def default_config():
    """Cấu hình như engine: app_config.DEFAULTS đè bởi app_config.json (cần các khóa calib_* và distance_on_cm)."""
    from app_config import DEFAULTS
    cfg = dict(DEFAULTS)
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_config.json")
    try:
        with open(p, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def _num(x, nd=1):
    return "" if x is None or not math.isfinite(x) else f"{x:.{nd}f}"


class Session:
    def __init__(self, clips, out_dir, person, session, sources, analyzer, cfg=None, ed=None, calib_clip=None,
                 beeper=None, clock=time.perf_counter, countdown=3.0, fps=FPS, wall=datetime.now,
                 compressor=None, full_seconds=None, disk_usage=shutil.disk_usage):
        self.clips, self.out_dir, self.person, self.session = clips, out_dir, person, session
        self.sources = {k: v for k, v in sources.items() if v is not None}      # {"side": src, "front": src}
        self.analyzer, self.cfg, self.ed = analyzer, cfg or default_config(), ed
        self.calib_clip = calib_clip or next((c for c in clips if c.is_calibration), None)
        self.beeper = beeper or (lambda kind: None)
        self.clock, self.countdown_sec, self.fps, self.wall = clock, countdown, fps, wall
        os.makedirs(out_dir, exist_ok=True)
        self.state = IDLE
        self.idx = 0
        self._override = None                # A1 chọn bằng phím C khi A1 không nằm ở vị trí hiện tại
        self.last_clip = None                # clip vừa quay xong / vừa bỏ dở (cho phím R)
        self.baseline = None
        self.takes = {}                      # id -> số lần quay xong
        self.done = {}                       # id -> {pct, time}
        self.message = ""                    # dòng thông báo lớn (kết quả clip vừa rồi, lý do A1 hỏng...)
        self.message_level = "info"          # info | ok | warn | bad
        self.beep_log = []                   # [(loại, giây trong clip)] để kiểm thử
        self.warnings = []
        self.live = self._empty_live()
        self.calib_view = []                 # [(nhãn, ok)] danh sách kiểm khi đang / vừa xong A1
        self.t_count0 = 0.0
        self.compressor = compressor
        self.full_seconds = full_seconds or sum(c.duration for c in clips)
        self._disk_usage = disk_usage
        self.disk = None
        self._disk_t = self._rate_t = -1e9
        self._rate = None
        self._last_front_w = 640
        self._dist_hist = deque(maxlen=5)
        self._reset_run()

    # ------------------------------------------------------------------ đường dẫn
    @property
    def progress_path(self):
        return os.path.join(self.out_dir, f"record_progress_{self.person}_{self.session}.json")

    @property
    def csv_path(self):
        return os.path.join(self.out_dir, "sessions.csv")

    def base_name(self, clip):
        return f"{self.person}_{self.session}_{clip.clip}"

    def file_path(self, clip, cam):
        return os.path.join(self.out_dir, f"{self.base_name(clip)}_{cam.upper()}.mp4")

    # ------------------------------------------------------------------ clip hiện tại / điều hướng
    @property
    def current(self):
        if self._override is not None:
            return self._override
        return self.clips[min(self.idx, len(self.clips) - 1)] if self.clips else None

    @property
    def finished(self):
        """Đã qua clip cuối của danh sách: hiện màn hình tóm tắt, Space không làm gì."""
        return self.idx >= len(self.clips) and self._override is None

    def summary_rows(self):
        """[(mã, tên clip, % đạt hoặc None, số lần quay, nên quay lại?)] cho từng clip trong danh sách."""
        rows = []
        for c in self.clips:
            pct = (self.done.get(c.id) or {}).get("pct")
            rows.append((c.id, c.clip, pct, self.takes.get(c.id, 0), pct is not None and pct < HINT_LOW_PCT))
        return rows

    @property
    def position(self):
        """(số thứ tự clip hiện tại trong danh sách đang quay, tổng)."""
        return min(self.idx, len(self.clips) - 1) + 1, len(self.clips)

    def press_next(self):
        if self.state != IDLE:
            return
        self._override = None
        self.idx = min(self.idx + 1, len(self.clips))          # ở clip cuối thì sang màn hình xong buổi
        self._save_progress()

    def press_prev(self):
        if self.state != IDLE:
            return
        self._override = None
        self.idx = max(0, self.idx - 1)
        self._save_progress()

    def press_redo(self):
        """R: quay lại clip vừa rồi."""
        if self.state != IDLE or self.last_clip is None:
            return
        self._set_current(self.last_clip)
        self.message, self.message_level = f"Quay lại {self.last_clip.clip}. Bấm Space để bắt đầu.", "info"

    def press_calibrate(self):
        """C: quay lại A1 (lỡ dịch camera / ghế)."""
        if self.state != IDLE or self.calib_clip is None:
            return
        self._set_current(self.calib_clip)
        self.message, self.message_level = "Quay lại A1 CALIBRATION. Bấm Space để bắt đầu.", "info"

    def _set_current(self, clip):
        if clip in self.clips:
            self._override, self.idx = None, self.clips.index(clip)
        else:
            self._override = clip
        self._save_progress()

    # ------------------------------------------------------------------ tiến độ (Q thoát rồi mở lại)
    def _save_progress(self):
        cur = self.current
        data = dict(person=self.person, session=self.session, next=None if self.finished or not cur else cur.id, takes=self.takes,
                    done=self.done, baseline=self.baseline)
        tmp = self.progress_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.progress_path)

    def saved_progress(self):
        try:
            with open(self.progress_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def resume_text(self):
        """Câu hỏi 'tiếp từ clip nào' cho lần mở lại; None nếu buổi này chưa quay gì."""
        p = self.saved_progress()
        if not p or not p.get("done"):
            return None
        nxt = next((c for c in self.clips if c.id == p.get("next")), None)
        if nxt is None:
            return f"Buổi {self.person} {self.session} đã quay xong. Mở màn hình tóm tắt?" if p.get("next") is None else None
        return f"Buổi {self.person} {self.session} đã quay {len(p['done'])} clip. Tiếp từ {nxt.id} {nxt.clip}?"

    def resume(self):
        p = self.saved_progress()
        if not p:
            return False
        self.takes, self.done, self.baseline = p.get("takes", {}), p.get("done", {}), p.get("baseline")
        if p.get("next") is None:
            self.idx = len(self.clips)
        for i, c in enumerate(self.clips):
            if c.id == p.get("next"):
                self.idx = i
        self._override = None
        return True

    # ------------------------------------------------------------------ phím Space / Esc / Q
    def press_start(self):
        if self.state != IDLE or self.current is None or self.finished:
            return False
        lost = [k for k, s in self.sources.items() if s.lost or s.latest() is None]
        if lost:
            self.message = "Camera " + ", ".join(CAM_NAME[k] for k in lost) + " chưa có hình, chưa thể quay."
            self.message_level = "bad"
            return False
        self.state = COUNTDOWN
        self.t_count0 = self.clock()
        self._reset_run()
        self.message, self.message_level = "", "info"
        if self.baseline is None and not self.current.is_calibration:
            self.message = "Chưa có baseline (A1): vẫn ghi hình nhưng chưa chấm được. Bấm C để quay A1."
            self.message_level = "warn"
        return True

    def press_cancel(self):
        """Esc: hủy clip đang đếm ngược / đang quay; file dở bị bỏ."""
        if self.state in (COUNTDOWN, RECORDING):
            self.last_clip = self.current
            self._abort("Đã hủy clip, chưa lưu. Bấm Space để quay lại.")

    def close(self):
        """Q: dừng clip dở (nếu có), ghi nốt nhật ký chờ, lưu tiến độ."""
        if self.state in (COUNTDOWN, RECORDING):
            self._abort("")
        if self.state == AWAIT_CM:
            self.submit_cm(None)
        self._save_progress()

    # ------------------------------------------------------------------ vòng lặp
    def _reset_run(self):
        self.t_start = None
        self.writers = {}
        self.counter = None
        self.cal = None
        self.cal_t = 0.0
        self.fired = set()
        self.skew_max = 0.0
        self.run_start_wall = None
        self.pending_row = None

    def elapsed(self):
        return None if self.t_start is None else self.clock() - self.t_start

    def count_left(self):
        return max(0.0, self.countdown_sec - (self.clock() - self.t_count0)) if self.state == COUNTDOWN else 0.0

    def refresh_disk(self, force=False):
        """Dung lượng ổ còn trống + ước tính số buổi. Free đọc mỗi 5 s; ước tính từ file đã quay mỗi 60 s."""
        now = self.clock()
        if not force and self.disk is not None and now - self._disk_t < 5.0:
            return self.disk
        compressed = bool(self.compressor and self.compressor.enabled)
        if force or now - self._rate_t >= 60.0:
            self._rate, self._rate_t = measured_rate(self.out_dir, compressed), now
        self.disk, self._disk_t = disk_report(self.out_dir, self.full_seconds, compressed, self._disk_usage, self._rate), now
        return self.disk

    def compress_status(self):
        """(mức, chữ) trạng thái nén nền; ("info", "Nén nền: tắt") nếu không dùng bộ nén."""
        if self.compressor is None:
            return "info", "Nén nền: tắt (--no-compress)"
        return self.compressor.status()

    def compress_text(self):
        return self.compress_status()[1]

    def tick(self):
        self._update_warnings()
        if self.analyzer is not None:
            for s in self.analyzer.drain():
                self._on_sample(s)
        if self.state == COUNTDOWN and self.clock() - self.t_count0 >= self.countdown_sec:
            self._begin_recording()
        elif self.state == RECORDING:
            self._tick_recording()

    def _begin_recording(self):
        clip = self.current
        self.t_start = self.clock()
        self.run_start_wall = self.wall()
        self.state = RECORDING
        self.counter = PassCounter(clip)
        if clip.is_calibration:
            self.cal = calibration.new_samples()
        for cam, src in self.sources.items():
            tmp = os.path.join(self.out_dir, f"{self.base_name(clip)}_{cam.upper()}.rec.mp4")
            w = ClipWriter(tmp, self.t_start, clip.duration, self.fps)
            self.writers[cam] = w
            src.set_sink(w)
        self._beep("start", 0.0)

    def _beep(self, kind, t):
        self.beep_log.append((kind, round(t, 3)))
        try:
            self.beeper(kind)
        except Exception:                                                          # noqa: BLE001  bíp lỗi không được làm hỏng clip
            pass

    def _tick_recording(self):
        clip, t = self.current, self.elapsed()
        for t_mark, _label in clip.marks():
            if t >= t_mark and t_mark not in self.fired:
                self.fired.add(t_mark)
                self._beep("mark", t)
        a, b = self.sources.get("side"), self.sources.get("front")
        if a is not None and b is not None and a.latest() and b.latest():
            self.skew_max = max(self.skew_max, abs(a.latest()[0] - b.latest()[0]))
        if t >= clip.duration:
            self._beep("end", t)
            self._finish()

    # ------------------------------------------------------------------ mẫu pose -> số đo -> trạng thái
    @staticmethod
    def _empty_live():
        return dict(neck=None, trunk=None, tilt=None, raise_=None, dist=None, status=THEO_HIEU_LENH,
                    seen_side=None, seen_front=None, Ls=None, Lf=None)

    def metrics(self, s):
        """Sample -> số đo so với baseline (None nếu không đo được), dùng đúng hàm của engine."""
        b = self.baseline
        m = dict(neck=None, trunk=None, tilt=None, raise_=None)
        if b is None:
            return m
        if s.has_side and s.Ls is not None:
            raw = sequence_angles(s.Ls[None], b["side"], b["f"])
            vis = raw[0, [FEATURES.index(k) for k in ("vis_ear", "vis_shoulder", "vis_hip")]]
            cal = apply_calibration(raw, b["base"])[0]
            neck, trunk = cal[FEATURES.index("neck")], cal[FEATURES.index("trunk")]
            if np.nan_to_num(vis, nan=0).min() >= calibration.MIN_VIS and np.isfinite(neck) and np.isfinite(trunk):
                m["neck"], m["trunk"] = float(neck), float(trunk)
        if s.has_front and s.Lf is not None:
            tv = shoulder_tilt(s.Lf)
            if b.get("tilt") is not None and np.isfinite(tv):
                m["tilt"] = float(tv - b["tilt"])
            rb, rv = b.get("raise"), shoulder_raise(s.Lf)
            if rb and np.isfinite(rv):
                m["raise_"] = float((rb - rv) / rb)            # như engine: dương = vai nâng lên
        return m

    def _on_sample(self, s):
        clip, live = self.current, self.live
        if s.has_side:
            live["seen_side"], live["Ls"] = s.Ls is not None, s.Ls
        if s.has_front:
            live["seen_front"], live["Lf"] = s.Lf is not None, s.Lf
            if s.Lf is None:
                self._dist_hist.clear()
            elif self.ed is not None and s.dkind:
                cm = float(self.ed.to_cm(s.dpx, s.dkind, s.width_f))
                if dist_ok(cm):
                    self._dist_hist.append(cm)
            live["dist"] = float(np.median(self._dist_hist)) if self._dist_hist else None
            self._last_front_w = s.width_f
        m = self.metrics(s)
        if s.has_side:
            live["neck"], live["trunk"] = m["neck"], m["trunk"]
        if s.has_front:
            live["tilt"], live["raise_"] = m["tilt"], m["raise_"]
        if clip is None:
            return
        if self.state == RECORDING:
            t = s.t - self.t_start
            if t >= 0:
                self._accumulate_calibration(s, t)
                live["status"] = self._status_at(clip, t)
                if t < clip.duration:
                    self.counter.add(t, live["status"])
        elif self.state == IDLE:
            live["status"] = self._status_at(clip, clip.margin)       # xem trước theo mức đầu của clip, chưa tính điểm

    def _status_at(self, clip, t):
        if clip.is_calibration:
            return THEO_HIEU_LENH
        chk = clip.phase_at(t).check
        if chk is None:
            return THEO_HIEU_LENH
        if self.baseline is None:
            return KHONG_THAY
        live = self.live
        needs_side = any(c["m"] in ("neck", "trunk") for c in chk)
        needs_front = any(c["m"] in ("tilt", "raise") for c in chk)
        if (needs_side and live["seen_side"] is False) or (needs_front and live["seen_front"] is False):
            return KHONG_THAY
        return check_status(chk, {"neck": live["neck"], "trunk": live["trunk"], "tilt": live["tilt"], "raise": live["raise_"]})

    def _accumulate_calibration(self, s, t):
        clip = self.current
        if self.cal is None or not (clip.margin <= t < clip.margin + CAL_SEC):
            return
        cal = self.cal
        if cal["t0"] is None:
            cal["t0"] = t
        if s.has_side:
            cal["n_s"] += 1
            if s.Ls is not None:
                cal["L"].append(s.Ls)
                cal["W"].append(s.Ws)
        if s.has_front:
            cal["n_f"] += 1
            if s.Lf is not None:
                cal["tilt"].append(shoulder_tilt(s.Lf))
                cal.setdefault("raise", []).append(shoulder_raise(s.Lf))
        if s.dkind:
            cal["dpx"].append(s.dpx)
            cal["dkind"].append(s.dkind)
        if t - self.cal_t >= 0.5:
            self.cal_t = t
            res = calibration.evaluate(cal, self.cfg, "front" in self.sources, self.ed, self._last_front_w, final=False)
            self.calib_view = [(c["label"], c["ok"]) for c in res["checks"]]

    # ------------------------------------------------------------------ cảnh báo FPS / lệch 2 cam
    def _update_warnings(self):
        w = []
        for cam, src in self.sources.items():
            if src.lost:
                w.append(f"Mất hình camera {CAM_NAME[cam]}!")
                continue
            f = src.fps()
            if f is not None and f < FPS_WARN:
                w.append(f"FPS camera {CAM_NAME[cam]} chỉ {f:.0f} (cần ≥ {FPS_WARN:.0f}): tắt ứng dụng khác dùng camera, "
                         "kiểm cổng USB / Wi-Fi.")
        d = self.refresh_disk()
        if d["low"]:
            w.append(f"{d['text'].split(' còn')[0]} chỉ còn {d['free'] / 1e9:.1f} GB (dưới {LOW_BYTES / 1e9:.0f} GB): "
                     "chuyển / nén video cũ trước khi quay tiếp.")
        a, b = self.sources.get("side"), self.sources.get("front")
        if a is not None and b is not None and a.latest() and b.latest():
            d = abs(a.latest()[0] - b.latest()[0])
            if d > SKEW_WARN_SEC:
                w.append(f"Hai camera lệch thời gian {d * 1000:.0f} ms (> {SKEW_WARN_SEC * 1000:.0f} ms).")
        self.warnings = w

    # ------------------------------------------------------------------ kết thúc / hủy clip
    def _stop_sinks(self):
        for src in self.sources.values():
            src.set_sink(None)

    def _abort(self, msg):
        self._stop_sinks()
        for w in self.writers.values():
            w.finish()
            try:
                os.remove(w.path)               # chỉ là file tạm của lần quay dở, chưa phải bản chính thức
            except OSError:
                pass
        self.state = IDLE
        self._reset_run()
        if msg:
            self.message, self.message_level = msg, "warn"

    @staticmethod
    def _real_fps(rows):
        ts = [r[1] for r in rows]
        return (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) >= 2 and ts[-1] > ts[0] else None

    def _finish(self):
        clip = self.current
        self._stop_sinks()
        rows = {cam: w.finish() for cam, w in self.writers.items()}
        bad = [cam for cam, w in self.writers.items() if not w.ok]
        if bad:
            err = "; ".join(f"{CAM_NAME[c]}: {self.writers[c].error or 'thiếu khung hình'}" for c in bad)
            for w in self.writers.values():
                try:
                    os.remove(w.path)
                except OSError:
                    pass
            self.state = IDLE
            self._reset_run()
            self.message, self.message_level = f"Ghi {clip.clip} lỗi ({err}). Quay lại clip này (Space).", "bad"
            self.last_clip = clip
            return
        fps = {cam: self._real_fps(r) for cam, r in rows.items()}
        self._publish_files(clip, rows)
        if self.compressor is not None:
            for cam in self.writers:
                self.compressor.submit(self.file_path(clip, cam))      # nén nền, không chặn clip kế
        pct = self.counter.pct
        note = []
        low = [c for c, f in fps.items() if f is not None and f < FPS_WARN]
        if low:
            note.append("FPS thấp: " + ", ".join(f"{CAM_NAME[c]} {fps[c]:.1f}" for c in low))
        if self.skew_max > SKEW_WARN_SEC:
            note.append(f"2 cam lệch tối đa {self.skew_max * 1000:.0f} ms")
        drops = sum(w.dropped for w in self.writers.values())
        if drops:
            note.append(f"rớt {drops} khung do ghi đĩa chậm")
        n_prev = self.takes.get(clip.id, 0)
        self.takes[clip.id] = n_prev + 1
        self.done[clip.id] = dict(pct=pct, time=self.run_start_wall.isoformat(timespec="seconds"))
        self.pending_row = dict(
            nguoi=self.person, buoi=self.session, clip=clip.clip, gio_bat_dau=self.run_start_wall.strftime("%Y-%m-%d %H:%M:%S"),
            thoi_luong_s=clip.duration, fps_hong=_num(fps.get("side")), fps_laptop=_num(fps.get("front")),
            phan_tram_dat=_num(pct), so_lan_quay_lai=n_prev, cm_thuoc="", ghi_chu="; ".join(note),
            nguoi_cham_1="", nguoi_cham_2="")
        self.last_clip = clip
        self._after_clip(clip, pct, note)

    def _after_clip(self, clip, pct, note):
        advance = True
        if clip.is_calibration:
            advance = self._finish_calibration()
        elif pct is None:
            self.message, self.message_level = f"Xong {clip.clip}: theo hiệu lệnh (không chấm số).", "ok"
        elif pct >= HINT_LOW_PCT:
            self.message, self.message_level = f"Xong {clip.clip}: ĐẠT {pct:.0f}% thời gian.", "ok"
        else:
            self.message = f"Xong {clip.clip}: ĐẠT {pct:.0f}% thời gian – thấp, nên quay lại (R)."
            self.message_level = "warn"
        if note:
            self.message += "  ⚠ " + "; ".join(note)
            if self.message_level == "ok":
                self.message_level = "warn"
        if advance:
            if self._override is clip:
                self._override = None
            else:
                self.idx = min(self.idx + 1, len(self.clips))
            if self.finished:
                self.message += "  Đây là clip cuối của danh sách."
            else:
                self.message += (f"  Tự chuyển sang {self.current.clip}. "
                                 "Bấm Space để bắt đầu (N = bỏ qua clip này).")
        warn = self.compressor.warning_once() if self.compressor is not None else None
        if warn:
            self.message += "  ⚠ " + warn
            self.message_level = "warn" if self.message_level == "ok" else self.message_level
        self.state = AWAIT_CM if clip.id == "E7" else IDLE
        if self.state == IDLE:
            self._write_row()
        self.counter, self.cal = None, None
        self._save_progress()

    def _finish_calibration(self):
        """Đánh giá A1 bằng calibration.evaluate(final=True); đạt thì tính baseline giống engine. Trả True nếu đạt."""
        cal = self.cal
        res = calibration.evaluate(cal, self.cfg, "front" in self.sources, self.ed, self._last_front_w, final=True)
        self.calib_view = [(c["label"], c["ok"]) for c in res["checks"]]
        for line in calibration.describe(res):
            print("Kiểm A1:", line)
        if not res["ok"]:
            self.message = "A1 KHÔNG ĐẠT, phải quay lại A1 (Space): " + " ".join(r["message"] for r in res["reasons"])
            self.message_level = "bad"
            self.done.pop("A1", None)
            codes = ",".join(r["code"] for r in res["reasons"])
            self.pending_row["ghi_chu"] = "; ".join(filter(None, [self.pending_row["ghi_chu"], "A1 không đạt: " + codes]))
            return False
        Lc, Wc = np.stack(cal["L"]), np.stack(cal["W"])
        side = choose_side(Lc, Wc)
        f = facing_sign(Lc, side)
        base = calibration_baseline(sequence_angles(Lc, side, f))
        tilts = np.array(cal["tilt"], float)
        tilt_base = float(np.nanmedian(tilts)) if np.isfinite(tilts).sum() >= 5 else None
        raises = np.array(cal.get("raise", []), float)
        raise_base = float(np.nanmedian(raises)) if np.isfinite(raises).sum() >= 5 else None
        if raise_base is not None and raise_base <= 0:
            raise_base = None                    # tai ở dưới vai = bắt sai điểm khớp (như engine)
        if self.ed is not None and hasattr(self.ed, "calibrate"):
            self.ed.calibrate(cal["dpx"], cal["dkind"], self.cfg.get("calib_distance_cm"))
        self.baseline = dict(side=int(side), f=float(f), base={k: float(v) for k, v in base.items()},
                             tilt=tilt_base, **{"raise": raise_base})
        self.message = (f"A1 ĐẠT. Baseline: cổ {base['neck']:+.1f}°, thân {base['trunk']:+.1f}°"
                        + ("" if tilt_base is None else f", lệch vai {tilt_base:+.1f}°") + ".")
        self.message_level = "ok"
        return True

    # ------------------------------------------------------------------ file + nhật ký
    def _publish_files(self, clip, rows):
        """Chuyển bản cũ vào _cu/ (không xóa), đổi .rec.mp4 thành tên chính thức, ghi _frames.csv."""
        cu = os.path.join(self.out_dir, "_cu")
        frames_path = os.path.join(self.out_dir, f"{self.base_name(clip)}_frames.csv")
        finals = [self.file_path(clip, cam) for cam in self.writers] + [frames_path]
        for p in finals:
            if os.path.exists(p):
                if self.compressor is not None:
                    self.compressor.wait_for(p)             # đang nén file này nền: chờ xong rồi mới chuyển
                os.makedirs(cu, exist_ok=True)
                stem, ext = os.path.splitext(os.path.basename(p))
                n = 1
                while os.path.exists(os.path.join(cu, f"{stem}__cu{n}{ext}")):
                    n += 1
                os.replace(p, os.path.join(cu, f"{stem}__cu{n}{ext}"))
        for cam, w in self.writers.items():
            os.replace(w.path, self.file_path(clip, cam))
        with open(frames_path, "w", encoding="utf-8", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["cam", "n", "t_rel_s", "video_frame"])
            for cam, r in rows.items():
                for n, t, vf in r:
                    wr.writerow([cam, n, f"{t:.4f}", vf])

    def submit_cm(self, values):
        """E7: số cm đo bằng thước ở từng mức (danh sách, hoặc None nếu bỏ qua)."""
        if self.state != AWAIT_CM:
            return
        if values:
            self.pending_row["cm_thuoc"] = "/".join(_num(v, 0) if isinstance(v, (int, float)) else str(v) for v in values)
        self.state = IDLE
        self._write_row()

    def _write_row(self):
        new = not os.path.exists(self.csv_path)
        with open(self.csv_path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=SESSION_COLS)
            if new:
                wr.writeheader()
            wr.writerow(self.pending_row)
        self.pending_row = None
