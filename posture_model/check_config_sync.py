"""Run directly; --integration uses API_EMAIL/API_PASSWORD and a test user without an organization."""
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from api_session import ApiSession, NoRedirect
from app_config import AppConfig


def local_check():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(dict(alert_sec=7, api_token="local-only")), encoding="utf8")
        cfg = AppConfig(str(path), dict(shoulder_tilt_on=3.5, shoulder_tilt_off=2.5))
        original = path.read_bytes()
        assert cfg.apply_remote({"alert_sec": 19}) == {"alert_sec"}
        assert cfg["alert_sec"] == 19 and cfg["api_token"] == "local-only"
        assert path.read_bytes() == original
        path.write_text(json.dumps(dict(alert_sec=9, api_token="local-only")), encoding="utf8")
        cfg.reload(force=True)
        assert cfg["alert_sec"] == 19  # Server overlay wins while local file reloads.
        assert cfg.apply_remote({}) == {"alert_sec"} and cfg["alert_sec"] == 9
        for invalid in ({"api_token": "remote-secret"}, {"user_id": "other"}, {"unknown": 1},
                        {"alert_sec": -1}, {"alert_sec": float("nan")}, {"distance_off_cm": 20},
                        {"shoulder_tilt_off": 10}, [], None):
            try:
                cfg.apply_remote(invalid)
                raise AssertionError("Invalid remote config accepted")
            except ValueError:
                assert cfg["alert_sec"] == 9 and cfg["api_token"] == "local-only"
    print("PASS: full replacement/fallback, local reload, memory-only overlay and validation")


def integration_check():
    from config_sync import ConfigSync
    auth = ApiSession(os.environ.get("API_BASE_URL", "http://127.0.0.1:8080"),
                      os.environ["API_EMAIL"], os.environ["API_PASSWORD"])

    def request(path, value=None):
        req = urllib.request.Request(auth.base_url + path,
                data=None if value is None else json.dumps(value).encode(),
                headers={"Authorization": "Bearer " + auth.token(), "Content-Type": "application/json"},
                method="GET" if value is None else "PUT")
        with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as response:
            return json.load(response)

    assert not request("/api/v1/auth/me").get("orgId"), "Use a test account without org to restore overrides safely"
    original = request("/api/v1/config/me")
    sync = ConfigSync(auth)

    def await_snapshot(expected):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = sync.take()
            if value == expected:
                return
            time.sleep(0.05)
        raise AssertionError("Expected authoritative config snapshot missing")

    def await_connection():
        deadline = time.monotonic() + 15
        while not sync.sio.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sync.sio.connected

    try:
        sync.start()
        await_snapshot(original)
        await_connection()
        first = {"alert_sec": 17 if original.get("alert_sec") != 17 else 18}
        request("/api/v1/config/me", first)
        await_snapshot(first)
        # Restart the client to guarantee an offline interval with a missed event.
        sync.stop()
        second = {"clear_sec": 4}
        request("/api/v1/config/me", second)
        sync = ConfigSync(auth)
        sync.start()
        await_snapshot(second)
        await_connection()
        # A real dropped connection must also reconnect and fetch, not just startup.
        while sync.take() is not None:
            pass
        sync.sio.disconnect()
        await_snapshot(second)
        await_connection()
        print("PASS: real Gateway startup GET, Socket.IO config, missed update recovery and reconnect GET")
    finally:
        sync.stop()
        request("/api/v1/config/me", original)


if __name__ == "__main__":
    local_check()
    if "--integration" in sys.argv:
        integration_check()
