"""Nén video đã quay (mp4v ~110 MB/phút) sang H.264 bằng ffmpeg, giữ nguyên số khung và thời lượng.

compress_file : nén 1 file; chỉ thay file gốc khi file nén có ĐÚNG số khung + thời lượng (sai thì giữ gốc).
Compressor    : hàng đợi + thread nền (ưu tiên thấp, 2 luồng) để không giành CPU với camera / MediaPipe của clip kế.
compress_dir  : nén lại thư mục có sẵn (record_session.py --compress-dir)."""
import glob
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

import cv2

CRF, PRESET = 23, "veryfast"
VIDEO_RE = re.compile(r"_(SIDE|FRONT)(__cu\d+)?\.mp4$", re.I)       # file quay chính thức hoặc bản cũ trong _cu/
TMP_SUFFIX = ".cmp.mp4"
FFMPEG_MISSING = ("Không tìm thấy ffmpeg nên video giữ nguyên bản gốc (rất nặng, ~110 MB/phút). Cài ffmpeg "
                  "(winget install Gyan.FFmpeg, hoặc pip install imageio-ffmpeg) rồi nén lại bằng --compress-dir.")


def find_ffmpeg(explicit=None):
    """Thứ tự: --ffmpeg, biến môi trường FFMPEG, ffmpeg trong PATH, gói imageio-ffmpeg. None nếu không có."""
    for cand in (explicit, os.environ.get("FFMPEG")):
        if cand and os.path.isfile(cand):
            return cand
    p = shutil.which("ffmpeg")
    if p:
        return p
    base = os.environ.get("LOCALAPPDATA")                                 # WinGet (Gyan.FFmpeg): PATH của terminal đang mở có thể chưa cập nhật
    if base:
        pat = [os.path.join(base, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
               os.path.join(base, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe")]
        for g in pat:
            hits = sorted(glob.glob(g, recursive=True))
            if hits:
                return hits[-1]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:                                                   # noqa: BLE001
        return None


def probe(path):
    """(số khung thật bằng cách đọc hết, fps khai báo, fourcc 4 ký tự) của file video."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0, 0.0, ""
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    cc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc = "".join(chr((cc >> 8 * i) & 0xFF) for i in range(4)).lower()
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    return n, fps, fourcc


def is_h264(fourcc):
    return fourcc in ("avc1", "h264", "x264")


def _replace_retry(src, dst, tries=6):
    """os.replace có thử lại: trên Windows antivirus / indexer đôi khi giữ file vừa tạo vài trăm ms (PermissionError)."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


def _run(cmd):
    """Chạy ffmpeg ở mức ưu tiên thấp. Trả (mã lỗi, stderr)."""
    flags = 0x00004000 if sys.platform == "win32" else 0          # BELOW_NORMAL_PRIORITY_CLASS
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=flags)
    return p.returncode, p.stderr


def compress_file(path, ffmpeg, crf=CRF, preset=PRESET, runner=_run):
    """Nén `path` tại chỗ. Trả dict(status, before, after, frames, error); status: ok | skipped | failed."""
    before = os.path.getsize(path)
    n0, fps0, cc0 = probe(path)
    res = dict(path=path, status="failed", before=before, after=before, frames=n0, error=None)
    if n0 == 0:
        res["error"] = "không đọc được file gốc"
        return res
    if is_h264(cc0):
        res["status"] = "skipped"                                       # đã nén rồi
        return res
    tmp = path[:-4] + TMP_SUFFIX
    base = [ffmpeg, "-y", "-v", "error", "-i", path, "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart"]
    try:
        for keep in (["-fps_mode", "passthrough"], ["-vsync", "0"]):     # giữ nguyên từng khung (tên cờ tùy bản ffmpeg)
            code, err = runner(base + keep + [tmp])
            if code == 0:
                break
        if code != 0 or not os.path.exists(tmp):
            res["error"] = f"ffmpeg lỗi: {(err or '').strip()[-200:]}"
            return res
        n1, fps1, cc1 = probe(tmp)
        if n1 != n0 or abs(n1 / (fps1 or 1) - n0 / (fps0 or 1)) > 0.05 or not is_h264(cc1):
            res["error"] = f"file nén không khớp (khung {n1} vs {n0}, fps {fps1:g} vs {fps0:g}, codec {cc1}): giữ file gốc"
            return res
        _replace_retry(tmp, path)                                        # chỉ thay khi đã kiểm khớp
        res.update(status="ok", after=os.path.getsize(path))
        return res
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


class Compressor:
    """Nén nền, lần lượt từng file. submit() không chặn. wait_for(path) chờ riêng file đó (trước khi đổi tên / chuyển file)."""

    def __init__(self, ffmpeg=None, log=print, runner=_run):
        """ffmpeg: None / "auto" = tự dò (find_ffmpeg); đường dẫn = dùng file đó (không có thì tự dò); False = coi như không có ffmpeg."""
        if ffmpeg is False:
            self.ffmpeg = None
        else:
            self.ffmpeg = find_ffmpeg(None if ffmpeg in (None, "auto") else ffmpeg)
        self.log, self.runner = log, runner
        self.failed = {}                        # path -> lý do, các file nén lỗi chưa được nén lại thành công
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.pending = {}                       # path -> Event
        self.results = []
        self.saved = 0
        self._warned = False
        self._th = None

    @property
    def enabled(self):
        return self.ffmpeg is not None

    def warning_once(self):
        """Chữ cảnh báo thiếu ffmpeg, chỉ trả MỘT lần (None các lần sau hoặc khi có ffmpeg)."""
        if self.enabled or self._warned:
            return None
        self._warned = True
        self.log(FFMPEG_MISSING)
        return FFMPEG_MISSING

    def submit(self, path):
        if not self.enabled:
            return False
        with self.lock:
            if path in self.pending:
                return True
            self.pending[path] = threading.Event()
            if self._th is None or not self._th.is_alive():
                self._th = threading.Thread(target=self._run, name="compress", daemon=True)
                self._th.start()
        self.q.put(path)
        return True

    def _run(self):
        while True:
            try:
                path = self.q.get(timeout=1.0)
            except queue.Empty:
                with self.lock:
                    if not self.pending:
                        self._th = None                  # submit() sau đó sẽ tạo thread mới
                        return
                continue
            try:
                r = compress_file(path, self.ffmpeg, runner=self.runner)
            except Exception as e:                                       # noqa: BLE001  một file lỗi không được giết thread
                r = dict(path=path, status="failed", before=0, after=0, frames=0, error=str(e))
            with self.lock:
                self.results.append(r)
                if r["status"] == "ok":
                    self.saved += r["before"] - r["after"]
                if r["status"] == "failed":
                    self.failed[path] = r["error"]
                else:
                    self.failed.pop(path, None)
                ev = self.pending.pop(path, None)
            if r["status"] == "failed":
                self.log(f"Nén {os.path.basename(path)} thất bại, giữ file gốc: {r['error']}")
            if ev:
                ev.set()

    @property
    def busy(self):
        with self.lock:
            return len(self.pending)

    def wait_for(self, path, timeout=None):
        with self.lock:
            ev = self.pending.get(path)
        return True if ev is None else ev.wait(timeout)

    def wait_all(self, timeout=None):
        with self.lock:
            evs = list(self.pending.values())
        return all(e.wait(timeout) for e in evs)

    def status(self):
        """(mức, chữ) hiển thị trên giao diện: mức = ok | info | warn | bad."""
        if not self.enabled:
            return "bad", "Chưa nén: không tìm thấy ffmpeg, video giữ bản gốc (~110 MB/phút). Cài ffmpeg rồi nén lại bằng --compress-dir."
        with self.lock:
            busy, failed, saved = len(self.pending), dict(self.failed), self.saved
        parts, level = [], "ok"
        if busy:
            parts.append(f"đang nén {busy} file")
            level = "info"
        if failed:
            name, why = next(reversed(failed.items()))
            parts.append(f"nén lỗi ({len(failed)} file, giữ bản gốc): {os.path.basename(name)}: {why}")
            level = "bad"
        if saved and not busy:
            parts.append(f"đã nén, tiết kiệm {saved / 1e9:.2f} GB")
        if not parts:
            parts.append("nén nền H.264: bật")
            level = "info"
        return level, "; ".join(parts)

    def failures(self):
        return [r for r in self.results if r["status"] == "failed"]


def clean_stale(folder):
    """Xóa file nén dở (.cmp.mp4) còn sót lần trước (đóng đột ngột)."""
    for root, _d, files in os.walk(folder):
        for f in files:
            if f.endswith(TMP_SUFFIX):
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass


def compress_dir(folder, ffmpeg=None, log=print):
    """Nén lại mọi *_SIDE.mp4 / *_FRONT.mp4 (cả bản cũ trong _cu/) của thư mục. Trả mã thoát (0 = ổn)."""
    ff = find_ffmpeg(ffmpeg)
    if not os.path.isdir(folder):
        log(f"Không có thư mục {folder}")
        return 2
    if ff is None:
        log(FFMPEG_MISSING)
        return 2
    clean_stale(folder)
    files = sorted(os.path.join(r, f) for r, _d, fs in os.walk(folder) for f in fs if VIDEO_RE.search(f))
    log(f"Nén {len(files)} file trong {folder} (H.264 CRF {CRF}, preset {PRESET}) bằng {ff}")
    tot_b = tot_a = fail = skip = 0
    for i, p in enumerate(files, 1):
        r = compress_file(p, ff)
        tot_b += r["before"]
        tot_a += r["after"]
        if r["status"] == "failed":
            fail += 1
            log(f"[{i}/{len(files)}] LỖI {os.path.basename(p)}: {r['error']}")
        elif r["status"] == "skipped":
            skip += 1
            log(f"[{i}/{len(files)}] bỏ qua (đã nén) {os.path.basename(p)}")
        else:
            log(f"[{i}/{len(files)}] {os.path.basename(p)}: {r['before'] / 1e6:.0f} MB -> {r['after'] / 1e6:.0f} MB")
    log(f"Xong: {tot_b / 1e9:.2f} GB -> {tot_a / 1e9:.2f} GB (tiết kiệm {(tot_b - tot_a) / 1e9:.2f} GB), "
        f"{skip} file đã nén sẵn, {fail} file lỗi (giữ nguyên bản gốc).")
    return 1 if fail else 0
