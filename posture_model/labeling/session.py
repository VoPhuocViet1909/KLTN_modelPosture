"""
Lõi của công cụ chấm tay nhãn 6 lớp (A1), không phụ thuộc Qt nên test được bằng video tự sinh.

Quy ước:
- Video được chia thành các đoạn 2,0 giây liên tiếp bắt đầu từ 0. Phần dư cuối video ngắn hơn 2 giây bị bỏ
  (hai người chấm thấy cùng một danh sách đoạn, nên ghép cặp tính κ khớp từng đoạn).
- Nhãn: 6 lớp của model v4 (tên IN HOA như `posture_config.json`, `metrics.POSTURE_CLASSES`) và `UNCLEAR`
  (không nhìn rõ / không chắc). Tên lớp nằm ở đây một nơi, giao diện và script κ dùng lại.
- CSV: `video,t_start,t_end,label,rater`. `video` là tên file (không đường dẫn). Mỗi người chấm một file CSV riêng.
  Ghi nguyên tử (file tạm rồi đổi tên) sau mỗi lần gán nhãn, nên tắt máy giữa chừng không mất phần đã chấm và
  mở lại chấm tiếp từ đoạn chưa chấm đầu tiên.
- Không hiển thị dự đoán của model: người chấm chấm mù.
"""
import csv
import math
import os
import tempfile

SEGMENT_SEC = 2.0
CLASSES = ("GOOD", "FORWARD_HEAD", "LEAN_FORWARD", "SLOUCH", "LEAN_BACKWARD", "NECK_EXTENSION")
UNCLEAR = "UNCLEAR"
LABELS = CLASSES + (UNCLEAR,)
# Phím tắt: 1..6 theo thứ tự lớp của model, 0 = không rõ
KEYS = {str(i + 1): c for i, c in enumerate(CLASSES)}
KEYS["0"] = UNCLEAR
FIELDS = ("video", "t_start", "t_end", "label", "rater")


class LabelFileError(ValueError):
    """CSV hỏng hoặc không khớp người chấm / video."""


def segments_for(duration_sec, segment_sec=SEGMENT_SEC):
    """Danh sách (t_start, t_end) các đoạn đủ dài; phần dư < segment_sec ở cuối bị bỏ."""
    n = int(math.floor(duration_sec / segment_sec + 1e-9))
    return [(round(i * segment_sec, 3), round((i + 1) * segment_sec, 3)) for i in range(n)]


def _fmt(t):
    return f"{t:.3f}".rstrip("0").rstrip(".")


def load_rows(path):
    """Đọc CSV, kiểm từng dòng. Trả list dict (t_start, t_end là float). File chưa có -> []."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise LabelFileError(f"{path}: cột phải là {','.join(FIELDS)}")
        for n, r in enumerate(reader, start=2):
            try:
                t0, t1 = float(r["t_start"]), float(r["t_end"])
            except (TypeError, ValueError):
                raise LabelFileError(f"{path} dòng {n}: t_start/t_end không phải số") from None
            if r["label"] not in LABELS:
                raise LabelFileError(f"{path} dòng {n}: nhãn '{r['label']}' không thuộc {', '.join(LABELS)}")
            if not r["video"] or not r["rater"]:
                raise LabelFileError(f"{path} dòng {n}: thiếu video hoặc rater")
            if abs((t1 - t0) - SEGMENT_SEC) > 1e-6:
                raise LabelFileError(f"{path} dòng {n}: đoạn phải dài {SEGMENT_SEC} giây")
            rows.append(dict(video=r["video"], t_start=t0, t_end=t1, label=r["label"], rater=r["rater"]))
    return rows


def save_rows(path, rows):
    """Ghi nguyên tử, sắp theo (video, t_start)."""
    rows = sorted(rows, key=lambda r: (r["video"], r["t_start"]))
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            for r in rows:
                w.writerow([r["video"], _fmt(r["t_start"]), _fmt(r["t_end"]), r["label"], r["rater"]])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class LabelSession:
    """Trạng thái chấm: danh sách đoạn của các video + nhãn đã gán + vị trí hiện tại.

    videos: list (tên video, thời lượng giây). Thứ tự giữ nguyên."""

    def __init__(self, videos, rater, csv_path):
        rater = (rater or "").strip()
        if not rater:
            raise ValueError("Cần tên người chấm (rater)")
        names = [v for v, _ in videos]
        if len(set(names)) != len(names):
            raise ValueError("Tên video trùng nhau (cột video chỉ lưu tên file)")
        self.rater, self.path = rater, csv_path
        self.segments = [(v, t0, t1) for v, dur in videos for t0, t1 in segments_for(dur)]
        if not self.segments:
            raise ValueError("Không có video nào đủ dài cho một đoạn 2 giây")
        known = {(v, round(t0, 3)) for v, t0, _ in self.segments}
        self.labels = {}
        for r in load_rows(csv_path):
            if r["rater"] != rater:
                raise LabelFileError(f"{csv_path} có nhãn của '{r['rater']}', không phải '{rater}'. "
                                     "Mỗi người chấm dùng một file CSV riêng.")
            if (r["video"], round(r["t_start"], 3)) not in known:
                raise LabelFileError(f"{csv_path}: đoạn {r['video']} {r['t_start']}–{r['t_end']} không có trong video "
                                     "đang mở (sai video hoặc video đã đổi).")
            self.labels[(r["video"], round(r["t_start"], 3))] = r["label"]
        self.index = self.first_unlabeled()

    # ------------------------------------------------------------ truy vấn
    def key(self, i=None):
        v, t0, _ = self.segments[self.index if i is None else i]
        return v, round(t0, 3)

    def current(self):
        return self.segments[self.index]

    def label_of(self, i=None):
        return self.labels.get(self.key(i))

    def first_unlabeled(self):
        for i in range(len(self.segments)):
            if self.key(i) not in self.labels:
                return i
        return len(self.segments) - 1                # đã chấm xong hết: đứng ở đoạn cuối để xem/sửa

    @property
    def done(self):
        return len(self.labels) == len(self.segments)

    def progress(self):
        return len(self.labels), len(self.segments)

    # ------------------------------------------------------------ thao tác
    def assign(self, label, advance=True):
        """Gán nhãn cho đoạn hiện tại (ghi CSV ngay) rồi sang đoạn kế. Gán lại đoạn đã chấm = sửa."""
        if label not in LABELS:
            raise ValueError(f"Nhãn không hợp lệ: {label}")
        self.labels[self.key()] = label
        self.save()
        if advance and self.index < len(self.segments) - 1:
            self.index += 1

    def clear(self):
        """Bỏ nhãn của đoạn hiện tại."""
        if self.labels.pop(self.key(), None) is not None:
            self.save()

    def step(self, delta):
        self.index = max(0, min(len(self.segments) - 1, self.index + delta))

    def goto_next_unlabeled(self):
        for i in list(range(self.index + 1, len(self.segments))) + list(range(0, self.index)):
            if self.key(i) not in self.labels:
                self.index = i
                return True
        return False

    def save(self):
        rows = [dict(video=v, t_start=t0, t_end=round(t0 + SEGMENT_SEC, 3), label=lab, rater=self.rater)
                for (v, t0), lab in self.labels.items()]
        save_rows(self.path, rows)
