"""Mẹo ngắn kèm cảnh báo, lấy từ bảng tri thức sức khỏe của máy chủ (GET /api/v1/insights/knowledge).

Desktop KHÔNG gọi Gemini và không tính nguy cơ: chỉ lấy câu khuyên đã soạn trong bảng tri thức (có nguồn) rồi chọn theo loại cảnh báo.
Bản bảng được đồng bộ khi online và lưu cache ra đĩa (out/health_kb_cache.json) để dùng khi offline hoặc chưa đăng nhập.
Chỉ nhận dữ liệu đúng hình dạng; câu quá dài hoặc lạ bị bỏ. Lỗi mạng/định dạng thì giữ bản cache cũ, không làm hỏng cảnh báo.
"""
import json
import os
import tempfile
import threading
import urllib.request

ALERT_TYPES = ("NECK_TRUNK", "SHOULDER_TILT", "TOO_CLOSE", "SIT_TOO_LONG", "EYE_BREAK")
MAX_TIP = 160
MIN_TIP = 5
MAX_BYTES = 1_000_000
PATH = "/api/v1/insights/knowledge"


def _valid(kb):
    return (isinstance(kb, dict) and isinstance(kb.get("kbVersion"), str) and isinstance(kb.get("entries"), list)
            and all(isinstance(e, dict) and isinstance(e.get("factor"), str) and isinstance(e.get("advice"), list)
                    for e in kb["entries"]))


def _slim(kb):
    """Chỉ giữ phần cần để chọn mẹo: phiên bản và (id, factor, advice) của từng mục."""
    entries = []
    for e in kb["entries"]:
        advice = [a.strip() for a in e["advice"] if isinstance(a, str) and MIN_TIP <= len(a.strip()) <= MAX_TIP]
        if e["factor"] in ALERT_TYPES and advice:
            entries.append({"id": str(e.get("id", "")), "factor": e["factor"], "advice": advice})
    return {"kbVersion": kb["kbVersion"], "entries": entries}


class HealthTips:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._tips = {}
        self._turn = {}
        self.version = None
        self._load()

    def _index(self, slim):
        tips = {}
        for e in slim["entries"]:
            tips.setdefault(e["factor"], []).extend(e["advice"])
        with self._lock:
            self._tips, self.version = tips, slim["kbVersion"]

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                kb = json.load(f)
        except (OSError, ValueError):
            return
        if _valid(kb):
            self._index(_slim(kb))

    def tip_for(self, alert_type):
        """Một câu khuyên cho loại cảnh báo, xoay vòng qua các câu có; None nếu chưa có bảng tri thức."""
        with self._lock:
            tips = self._tips.get(alert_type)
            if not tips:
                return None
            n = self._turn.get(alert_type, 0)
            self._turn[alert_type] = n + 1
            return tips[n % len(tips)]

    def refresh(self, auth, timeout=5):
        """Đồng bộ bảng từ máy chủ và lưu cache. True nếu đang dùng bản mới nhất, False nếu giữ bản cũ (offline, lỗi, sai dạng)."""
        try:
            request = urllib.request.Request(auth.base_url + PATH, method="GET")
            with auth.open(request, timeout=timeout) as response:
                kb = json.loads(response.read(MAX_BYTES))
        except (OSError, ValueError):
            return False
        if not _valid(kb):
            return False
        slim = _slim(kb)
        if slim["kbVersion"] != self.version:
            self._index(slim)
            self._save(slim)
        return True

    def _save(self, slim):
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(slim, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass            # không ghi được cache: vẫn dùng bản trong bộ nhớ tới khi tắt app
