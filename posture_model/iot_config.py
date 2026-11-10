"""
Cấu hình gửi cảnh báo xuống thiết bị ESP32-S3: file riêng `iot_config.json` cạnh app, chỉ ở máy này.
Không nằm trong app_config.json vì file đó bị kiểm theo config.schema.json và đồng bộ với server;
file này có khóa thiết bị nên cũng không commit (xem iot_config.example.json).

  cfg = iot_config.load()          # thiếu file / file hỏng -> mặc định (enabled = False)
  iot_config.save(cfg)             # ghi nguyên tử; trả về True/False, không ném lỗi
"""
import json
import os
import sys
from urllib.parse import urlsplit

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(APP_DIR, "iot_config.json")

# tên mDNS posture-esp32.local thường không phân giải được trên Windows -> mặc định dùng IP
DEFAULTS = {
    "enabled": False,
    "url": "http://192.168.1.20",
    "key": "",
    "mute_pc_beep": True,
    "timeout_sec": 1.0,
    "heartbeat_sec": 15,
    "status_every_sec": 60,
}


def normalize_url(url):
    """Thêm http:// nếu thiếu, bỏ dấu / cuối. Trả về None nếu không phải địa chỉ http(s) hợp lệ."""
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    try:
        u = urlsplit(url)
        u.port                                    # cổng sai ném ValueError khi đọc
        if u.scheme not in ("http", "https") or not u.hostname or any(c.isspace() for c in url):
            return None
    except ValueError:
        return None
    return url.rstrip("/")


def _number(value, default, low, high, cast):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return default
    return v if low <= v <= high else default


def clean(raw):
    """Gộp raw vào mặc định, sửa kiểu; giá trị sai thì dùng mặc định. Khóa lạ bị bỏ."""
    raw = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULTS)
    for k in ("enabled", "mute_pc_beep"):
        if isinstance(raw.get(k), bool):
            cfg[k] = raw[k]
    cfg["url"] = normalize_url(raw.get("url")) or DEFAULTS["url"]
    cfg["key"] = raw["key"].strip() if isinstance(raw.get("key"), str) else ""
    cfg["timeout_sec"] = _number(raw.get("timeout_sec"), DEFAULTS["timeout_sec"], 0.1, 10, float)
    cfg["heartbeat_sec"] = _number(raw.get("heartbeat_sec"), DEFAULTS["heartbeat_sec"], 1, 3600, float)
    cfg["status_every_sec"] = _number(raw.get("status_every_sec"), DEFAULTS["status_every_sec"], 1, 3600, float)
    return cfg


def load(path=None):
    path = path or PATH
    try:
        with open(path, encoding="utf-8") as f:
            return clean(json.load(f))
    except (OSError, ValueError):
        return clean(None)


def save(cfg, path=None):
    """Ghi cấu hình (đã làm sạch). True nếu ghi được."""
    path = path or PATH
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean(cfg), f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False
