"""Mẹo sức khỏe kèm cảnh báo: đồng bộ bảng tri thức, cache offline, chọn mẹo, và không làm hỏng cảnh báo khi lỗi."""
import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from health_tips import HealthTips, MAX_TIP  # noqa: E402
from notifier import format_message  # noqa: E402

KB = {"kbVersion": "1.0.0", "entries": [
    {"id": "HK-NECK-FHP", "factor": "NECK_TRUNK", "advice": ["Nâng màn hình lên ngang tầm mắt.", "Kéo cằm vào, thả lỏng vai."]},
    {"id": "HK-EYE-DISTANCE", "factor": "TOO_CLOSE", "advice": ["Ngồi cách màn hình ít nhất một sải tay."]},
    {"id": "X", "factor": "UNKNOWN_FACTOR", "advice": ["Câu không thuộc loại cảnh báo nào."]},
]}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def auth_returning(body=None, error=None):
    auth = MagicMock()
    auth.base_url = "http://server"
    if error is not None:
        auth.open.side_effect = error
    else:
        auth.open.return_value = FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())
    return auth


def ev(kind, alert, **extra):
    return {"eventType": kind, "alertType": alert, "level": 1, "severity": "LOW", "notify": True, **extra}


def main():
    with tempfile.TemporaryDirectory() as d:
        cache = os.path.join(d, "out", "health_kb_cache.json")

        # chưa có bảng, chưa đồng bộ: không có mẹo, cảnh báo không đổi
        tips = HealthTips(cache)
        assert tips.tip_for("NECK_TRUNK") is None
        plain = format_message(ev("ALERT_STARTED", "NECK_TRUNK"))
        assert format_message(ev("ALERT_STARTED", "NECK_TRUNK"), None, tips) == plain

        # đồng bộ khi online: lấy đúng đường dẫn, lưu cache, chọn mẹo xoay vòng theo loại
        auth = auth_returning(KB)
        assert tips.refresh(auth) is True
        request = auth.open.call_args.args[0]
        assert request.full_url == "http://server/api/v1/insights/knowledge" and request.get_method() == "GET"
        assert tips.version == "1.0.0" and os.path.exists(cache)
        assert tips.tip_for("NECK_TRUNK") == "Nâng màn hình lên ngang tầm mắt."
        assert tips.tip_for("NECK_TRUNK") == "Kéo cằm vào, thả lỏng vai."
        assert tips.tip_for("NECK_TRUNK") == "Nâng màn hình lên ngang tầm mắt.", "xoay vòng"
        assert tips.tip_for("TOO_CLOSE") == "Ngồi cách màn hình ít nhất một sải tay."
        assert tips.tip_for("SHOULDER_TILT") is None and tips.tip_for("UNKNOWN_FACTOR") is None

        # cache dùng được khi offline (app mở lại, không có mạng)
        offline = HealthTips(cache)
        assert offline.version == "1.0.0" and offline.tip_for("TOO_CLOSE")
        assert offline.refresh(auth_returning(error=urllib.error.URLError("down"))) is False, "offline: giữ bản cũ"
        assert offline.version == "1.0.0" and offline.tip_for("TOO_CLOSE")

        # chỉ cảnh báo bắt đầu/lặp mới kèm mẹo; sự kiện khác thì không
        tips2 = HealthTips(cache)
        _, body = format_message(ev("ALERT_STARTED", "TOO_CLOSE"), None, tips2)
        assert body.endswith("\nMẹo: Ngồi cách màn hình ít nhất một sải tay.")
        _, repeated = format_message(ev("ALERT_REPEATED", "TOO_CLOSE", level=2), None, tips2)
        assert "Mẹo:" in repeated
        for kind in ("ALERT_RESOLVED", "REMINDER", "SESSION_START"):
            assert "Mẹo:" not in format_message(ev(kind, "TOO_CLOSE"), None, tips2)[1], kind

        # dữ liệu xấu không làm hỏng: sai dạng, JSON hỏng, quá lớn, câu quá dài
        bad = HealthTips(os.path.join(d, "bad.json"))
        for body in (b"not json", b"[]", json.dumps({"kbVersion": 1, "entries": []}).encode(),
                     json.dumps({"kbVersion": "1", "entries": [{"factor": "NECK_TRUNK"}]}).encode()):
            assert bad.refresh(auth_returning(body)) is False
        assert bad.tip_for("NECK_TRUNK") is None
        long_tip = {"kbVersion": "9.9.9", "entries": [{"id": "a", "factor": "NECK_TRUNK", "advice": ["x" * (MAX_TIP + 1), "Câu hợp lệ ngắn."]}]}
        assert bad.refresh(auth_returning(long_tip)) is True
        assert bad.tip_for("NECK_TRUNK") == "Câu hợp lệ ngắn.", "câu quá dài bị bỏ"
        assert bad.refresh(auth_returning(KB)) is True and bad.version == "1.0.0", "bản mới hơn thay bản cũ"

        # cache hỏng không làm app lỗi
        with open(os.path.join(d, "corrupt.json"), "w") as f:
            f.write("{{{")
        assert HealthTips(os.path.join(d, "corrupt.json")).tip_for("NECK_TRUNK") is None
    print("PASS: mẹo sức khỏe (đồng bộ, cache offline, xoay vòng, chỉ cảnh báo bắt đầu/lặp, dữ liệu xấu không làm hỏng)")


if __name__ == "__main__":
    main()
