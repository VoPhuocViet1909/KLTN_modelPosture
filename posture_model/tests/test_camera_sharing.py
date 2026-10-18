"""python tests/test_camera_sharing.py — no webcam/network; engine ownership + Qt controls."""
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import EngineOptions, PostureEngine
from live_stream import LivePublisher
from ui.controller import AppController
from ui.main_window import MainWindow
from PySide6.QtWidgets import QApplication


class Publisher:
    instances = []
    def __init__(self, config, device, camera, rtsp, ffmpeg, auth=None):
        self.camera, self.state, self.stopped = camera, "connecting", False
        self.instances.append(self)
    def start(self): self.state = "publishing"
    def stop(self, wait=True): self.stopped = True


def main():
    cfg = {"api_token": "", "api_base_url": "http://localhost:8080"}
    eng = PostureEngine(EngineOptions(), cfg=cfg, auth=object())
    eng.cap_f, eng.elog = object(), SimpleNamespace(device_id="test-device")
    with patch("engine.LivePublisher", Publisher):
        assert eng.stream is None, "No consent: no publisher"
        eng.request_stream("side")
        eng._update_stream()
        first = eng.stream
        assert eng.stream_info()["camera"] == "side" and eng.stream_info()["state"] == "publishing"
        eng.request_stream("front")
        eng._update_stream()
        assert first.stopped and eng.stream.camera == "front", "Switch must stop old publisher"
        second = eng.stream
        eng.request_stream(None)
        eng._update_stream()
        assert second.stopped and eng.stream is None
        eng.request_stream("side")
        eng.request_stream(None)
        eng._update_stream()
        assert eng.stream is None, "Rapid enable/stop must keep last consent"
        eng._front_off = True
        eng.request_stream("front")
        eng._update_stream()
        assert eng.stream is None and eng.stream_error
        eng.auth = None
        eng.request_stream("side")
        eng._update_stream()
        assert eng.stream is None and "Đăng nhập" in eng.stream_error
        eng.auth = object()
        with patch("engine.LivePublisher", side_effect=ValueError("private token must never surface")):
            eng.request_stream("side")
            eng._update_stream()
            assert eng.stream is None and "private" not in eng.stream_error
        try:
            eng.request_stream("unknown")
            raise AssertionError("Unknown camera accepted")
        except ValueError:
            pass

    # Stop during an in-flight grant must return promptly and never spawn FFmpeg afterwards.
    entered, release = threading.Event(), threading.Event()
    publisher = LivePublisher(lambda: ("", ""), "test-device", "side", "rtsp://localhost:8554", sys.executable)
    def grant():
        entered.set()
        release.wait(2)
        return dict(path="camera/test/test-device/side", token="fixture-only", expiresIn=120)
    with patch.object(publisher, "_grant", grant), patch("live_stream.subprocess.Popen") as spawn:
        publisher.start()
        assert entered.wait(2)
        started = time.monotonic()
        publisher.stop(wait=False)
        assert time.monotonic() - started < .5
        release.set()
        publisher.thread.join(2)
        assert not publisher.thread.is_alive() and not spawn.called

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    selected = []
    window.streamRequested.connect(selected.append)
    assert not window.btn_stream.isEnabled()
    window.set_stream(dict(state="off", frontAvailable=False), True)
    assert not window.stream_camera.model().item(1).isEnabled()
    window.btn_stream.click()
    assert selected[-1] == "side"
    window.set_stream(dict(camera="side", state="connecting", frontAvailable=True), True)
    assert not window.stream_camera.isEnabled() and window.btn_stream.isEnabled(), "Stop available while connecting"
    window.btn_stream.click()
    assert selected[-1] is None
    window.set_stream(dict(camera="side", state="retrying"), True)
    assert "thử lại" in window.stream_note.text()
    window.set_stream({}, False)
    assert not window.btn_stream.isEnabled() and not window._sharing

    ctl = AppController(app, EngineOptions(), store=None)
    requested = []
    ctl.engine = SimpleNamespace(request_stream=lambda *args: requested.append(args))
    ctl.request_stream("side")
    assert not requested, "Local/login cannot publish"
    ctl.mode = "session"
    with patch("ui.controller.shutil.which", return_value="ffmpeg"):
        ctl.request_stream("side")
    assert requested[-1][0] == "side"
    ctl.request_stream(None)
    assert requested[-1][0] is None
    with patch("ui.controller.shutil.which", return_value=None), patch("ui.controller.QFileDialog.getOpenFileName", return_value=("", "")):
        before = len(requested)
        ctl.request_stream("side")
        assert len(requested) == before and "Chưa chọn" in ctl.window.stream_note.text()
    ctl._leaving = True
    ctl.request_stream("front")
    assert len(requested) == before
    ctl.app.aboutToQuit.disconnect(ctl._shutdown)
    ctl.engine = None
    ctl.window.hide()
    window.hide()
    print("PASS: consent/default-off, switch/stop, rapid stop, unavailable front, auth, safe errors, Qt controls and FFmpeg cancel")


if __name__ == "__main__":
    main()
