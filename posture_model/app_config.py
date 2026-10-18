"""
Cấu hình chạy của Desktop App, đọc từ app_config.json và TỰ NẠP LẠI khi file thay đổi (không cần tắt app).

--sync-config nhận toàn bộ cấu hình máy chủ vào overlay trong RAM; khóa bị xóa trở về cấu hình local.
File local vẫn hot reload, không ghi secrets hoặc cấu hình máy chủ xuống file.
"""
import copy
import json
import math
import os

from schema import validate

DEFAULTS = {
    "user_id": None,                 # có sau khi đăng nhập (giai đoạn 3)
    # --- cảnh báo tư thế (dùng chung cho 3 nhánh)
    "alert_sec": 5,                  # BAD liên tục bao lâu mới cảnh báo
    "clear_sec": 3,                  # GOOD liên tục bao lâu mới coi là đã sửa
    "repeat_sec": 240,               # vẫn sai sau bao lâu thì nhắc lại (tăng mức độ)
    "cooldown_sec": 60,              # 2 lần bật cảnh báo cùng loại cách nhau tối thiểu (không bật thông báo)
    # --- nhánh cổ / thân (Transformer)
    "p_bad_threshold": None,         # None = lấy "threshold" trong posture_config.json
    "p_bad_hysteresis": 0.1,         # BAD khi P >= ngưỡng + 0.1, GOOD khi P <= ngưỡng - 0.1
    # --- nhánh lệch vai (công thức)
    "shoulder_tilt_on": None,        # None = lấy từ posture_config.json (3.5°)
    "shoulder_tilt_off": None,       # (2.5°)
    # --- nhánh khoảng cách
    "distance_on_cm": 50,            # gần hơn 50 cm -> quá gần
    "distance_off_cm": 55,           # xa hơn 55 cm mới hết (trễ)
    "calib_distance_cm": None,       # nếu lúc hiệu chỉnh ngồi đúng khoảng cách đã đo (vd 60) -> tính tiêu cự chính xác
    "camera_focal_px": None,         # tiêu cự đã biết (từ distance_check.py), ưu tiên hơn HFOV
    "camera_hfov_deg": 63,
    # --- có mặt / nhắc nghỉ
    "away_sec": 30,
    "sit_limit_min": 50,
    "sit_repeat_min": 10,
    "eye_break_min": 20,
    # --- thông báo
    "notify_toast": True,
    "notify_sound": True,
    "notify_popup": True,            # chỉ bật popup khi mức HIGH (nhắc lần 3 trở đi)
    # --- khác
    "calib_sec": 10,
    # --- kiểm hợp lệ lúc hiệu chỉnh (calibration.py): chỉ ở máy, máy chủ không gửi các khóa này
    "calib_visible_ratio": 0.8,      # cam hông thấy đủ tai-vai-hông ở >= 80% số khung
    "calib_max_neck_deg": 30.0,      # trung vị góc ĐẦU so với phương thẳng đứng (vai->tai) tối đa; p95 khung GOOD 31,2 làm tròn
    "calib_min_neck_deg": 0.0,       # ... và tối thiểu (đầu ngửa ra sau)
    "calib_max_trunk_deg": 20.0,     # trung vị góc thân tối đa (gù / nghiêng ra trước)
    "calib_min_trunk_deg": -20.0,    # trung vị góc thân tối thiểu (ngả sau); -15 cũ loại nhầm 10,6% khung GOOD
    "calib_still_deg": 5.0,          # độ lệch chuẩn góc cổ / thân tối đa (ngồi yên)
    "calib_front_ratio": 0.5,        # cam laptop thấy đủ 2 vai ở >= 50% số khung
    # --- gửi dữ liệu (giai đoạn 2)
    "api_base_url": None,            # vd "http://127.0.0.1:8080" (mock_server.py); null = chỉ lưu outbox
    "api_token": None,               # JWT, có sau khi đăng nhập (giai đoạn 3)
    "batch_interval_sec": 5,         # gửi theo lô mỗi 5 giây (sự kiện khẩn gửi ngay)
    "batch_max": 100,                # tối đa 100 mục / lô
    "metrics_window_sec": 60,        # gộp metrics mỗi 60 giây
}

LOCAL_ONLY_KEYS = {"calib_visible_ratio", "calib_max_neck_deg", "calib_min_neck_deg", "calib_max_trunk_deg",
                   "calib_min_trunk_deg", "calib_still_deg", "calib_front_ratio"}   # không nhận từ máy chủ

LIVE_KEYS = {k for k in DEFAULTS if k not in ("calib_sec",)}   # các khoá áp dụng ngay khi đổi


class AppConfig:
    def __init__(self, path, model_cfg=None):
        self.path = path
        self.model_cfg = model_cfg or {}
        self.values = copy.deepcopy(DEFAULTS)
        self.remote = {}
        self._mtime = None
        if not os.path.exists(path):
            self.save()                              # tạo file mẫu cho người dùng sửa
        self.reload(force=True)

    def __getitem__(self, k):
        v = self.remote[k] if k in self.remote else self.values.get(k)
        if v is None:                                # lấy mặc định của model nếu để null
            fallback = {"p_bad_threshold": "threshold", "shoulder_tilt_on": "shoulder_tilt_on",
                        "shoulder_tilt_off": "shoulder_tilt_off"}.get(k)
            if fallback:
                return self.model_cfg.get(fallback)
        return v

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.values, f, ensure_ascii=False, indent=2)
        self._mtime = os.path.getmtime(self.path)

    def reload(self, force=False):
        """Đọc lại nếu file đổi. Trả về tập khoá đã đổi (rỗng nếu không đổi / file lỗi)."""
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            return set()
        if not force and m == self._mtime:
            return set()
        self._mtime = m
        try:
            with open(self.path, encoding="utf-8") as f:
                new = json.load(f)
        except (OSError, ValueError) as e:
            print("app_config.json lỗi, giữ cấu hình cũ:", e)
            return set()
        errs = validate("config", new)                # giá trị sai (âm, sai kiểu...) -> từ chối cả file
        if not errs:
            candidate = {**self.values, **{k: v for k, v in new.items() if k in DEFAULTS}, **self.remote}
            if candidate["distance_off_cm"] < candidate["distance_on_cm"]:
                errs.append("distance_off_cm must be >= distance_on_cm")
            on, off = candidate["shoulder_tilt_on"], candidate["shoulder_tilt_off"]
            on = self.model_cfg.get("shoulder_tilt_on") if on is None else on
            off = self.model_cfg.get("shoulder_tilt_off") if off is None else off
            if on is not None and off is not None and off > on:
                errs.append("shoulder_tilt_off must be <= shoulder_tilt_on")
        if errs:
            print("app_config.json có giá trị không hợp lệ, giữ cấu hình cũ:", errs[:3])
            return set()
        changed = set()
        for k, v in new.items():
            if k in DEFAULTS and self.values.get(k) != v:
                self.values[k] = v
                changed.add(k)
        return changed

    def apply_remote(self, config):
        """Full server snapshot; missing keys fall back to local config/model defaults. Memory only."""
        if (not isinstance(config, dict) or set(config) - (set(DEFAULTS) - {"api_base_url", "api_token", "user_id"} - LOCAL_ONLY_KEYS)
                or any(isinstance(v, float) and not math.isfinite(v) for v in config.values())
                or validate("config", config)):
            raise ValueError("Invalid remote configuration")
        candidate = {**self.values, **config}
        if candidate["distance_off_cm"] < candidate["distance_on_cm"]:
            raise ValueError("Invalid remote distance thresholds")
        on, off = candidate["shoulder_tilt_on"], candidate["shoulder_tilt_off"]
        on = self.model_cfg.get("shoulder_tilt_on") if on is None else on
        off = self.model_cfg.get("shoulder_tilt_off") if off is None else off
        if on is not None and off is not None and off > on:
            raise ValueError("Invalid remote shoulder thresholds")
        before = {k: self[k] for k in DEFAULTS}
        self.remote = copy.deepcopy(config)
        return {k for k in DEFAULTS if before[k] != self[k]}

    def snapshot(self):
        """Cấu hình đang dùng, gắn vào sự kiện gửi lên server."""
        return {"alertSec": self["alert_sec"], "clearSec": self["clear_sec"], "repeatSec": self["repeat_sec"],
                "pBadThreshold": self["p_bad_threshold"], "shoulderTiltOn": self["shoulder_tilt_on"],
                "distanceOnCm": self["distance_on_cm"]}
