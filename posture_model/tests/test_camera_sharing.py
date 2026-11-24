"""python tests/test_camera_sharing.py — no webcam/network; engine ownership + Qt controls."""
import json
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
        self.frames = []
        self.instances.append(self)
    def submit(self, frame): self.frames.append(frame)
    def start(self): self.state = "publishing"
    def stop(self, wait=True): self.stopped = True


def main():
    cfg = {"api_token": "", "api_base_url": "http://localhost:8080"}
    eng = PostureEngine(EngineOptions(), cfg=cfg, auth=object())
    eng.cap_f, eng.elog = object(), SimpleNamespace(device_id="test-device")
    with patch("engine.LivePublisher", Publisher):
        assert not eng.streams, "No consent: no publisher"
        eng.request_stream("side")
        eng._update_stream()
        first = eng.streams["side"]
        assert eng.stream_info()["states"] == {"side": "publishing"}
        eng.request_stream("front")
        eng._update_stream()
        assert first.stopped and set(eng.streams) == {"front"}, "Switch must stop old publisher"
        second = eng.streams["front"]
        eng.request_stream(None)
        eng._update_stream()
        assert second.stopped and not eng.streams
        eng.request_stream("side")
        eng.request_stream(None)
        eng._update_stream()
        assert not eng.streams, "Rapid enable/stop must keep last consent"
        eng.request_stream("both")
        eng._update_stream()
        side, front = (eng.streams[angle] for angle in ("side", "front"))
        eng._submit_stream_frames("side-frame", "front-frame")
        assert side.frames == ["side-frame"] and front.frames == ["front-frame"]
        front.state = "retrying"
        assert eng.stream_info()["states"] == {"side": "publishing", "front": "retrying"}
        eng.request_stream(None)
        eng._update_stream()
        assert side.stopped and front.stopped and not eng.streams

        eng.request_stream("both")
        eng._update_stream()
        side, front = (eng.streams[angle] for angle in ("side", "front"))
        eng._front_off = True
        eng._submit_stream_frames("side-after-skip", None)
        assert front.stopped and not side.stopped and side.frames == ["side-after-skip"]
        assert eng.stream_info()["states"] == {"side": "publishing"}
        eng.request_stream("both")
        eng._update_stream()
        assert not eng.streams and eng.stream_error

        eng._front_off = False
        side = Publisher(None, "test-device", "side", "", "")
        with patch("engine.LivePublisher", side_effect=[side, ValueError("front failed")]):
            eng.request_stream("both")
            eng._update_stream()
            assert side.stopped and not eng.streams and eng.stream_error
        eng._front_off = True
        eng.request_stream("front")
        eng._update_stream()
        assert not eng.streams and eng.stream_error
        eng.auth = None
        eng.request_stream("side")
        eng._update_stream()
        assert not eng.streams and "Đăng nhập" in eng.stream_error
        eng.auth = object()
        with patch("engine.LivePublisher", side_effect=ValueError("private token must never surface")):
            eng.request_stream("side")
            eng._update_stream()
            assert not eng.streams and "private" not in eng.stream_error
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

    org_id = "01234567-1234-1234-1234-0123456789ab"
    owner_id = "01234567-1234-1234-1234-0123456789ac"
    share_id = "01234567-1234-1234-1234-0123456789ad"
    path = f"org-camera/{org_id}/{owner_id}/test-device/side/{share_id}"
    publisher = LivePublisher(lambda: ("", ""), "test-device", "side", "rtsp://localhost:8554", sys.executable,
                              auth=SimpleNamespace(org_id=org_id, user_id=owner_id), organization=True)
    with patch.object(publisher, "_post", return_value=json.dumps({
        "path": path, "token": "fixture-only", "expiresIn": 120, "action": "publish"
    }).encode()) as post:
        grant = publisher._grant()
        post.assert_called_once_with("media-token", {
            "deviceId": "test-device", "camera": "side", "action": "publish", "scope": "organization"
        }, timeout=5)
        publisher._revoke_share(grant)
        post.assert_called_with("media-share/stop", {
            "deviceId": "test-device", "camera": "side", "shareId": share_id
        }, timeout=2)

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    selected = []
    window.streamRequested.connect(selected.append)
    assert not window.btn_stream.isEnabled()
    window.set_stream(dict(frontAvailable=False), True)
    assert not window.stream_camera.model().item(1).isEnabled()
    assert not window.stream_camera.model().item(2).isEnabled()
    window.btn_stream.click()
    assert selected[-1] == "side"
    assert not window.stream_org.isEnabled() and not window.stream_org.isChecked()
    window.set_stream(dict(organizationAvailable=True), True)
    assert window.stream_org.isEnabled() and not window.stream_org.isChecked()
    window.stream_org.setChecked(True)
    window.set_stream(dict(states={"side": "publishing"}, organizationAvailable=True, organizationSharing=True), True)
    assert window.stream_org.isChecked() and not window.stream_org.isEnabled()
    window.set_stream(dict(organizationAvailable=True), True)
    assert not window.stream_org.isChecked() and window.stream_org.isEnabled()
    window.set_stream(dict(frontAvailable=True), True)
    window.stream_camera.setCurrentIndex(2)
    window.btn_stream.click()
    assert selected[-1] == "both"
    window.set_stream(dict(states={"side": "connecting", "front": "connecting"}, frontAvailable=True), True)
    assert not window.stream_camera.isEnabled() and window.btn_stream.isEnabled(), "Stop available while connecting"
    window.btn_stream.click()
    assert selected[-1] is None
    window.set_stream(dict(states={"side": "retrying", "front": "publishing"}), True)
    assert "Camera hông: Đang thử lại" in window.stream_note.text()
    assert "Camera trước: Đang chia sẻ" in window.stream_note.text()
    window.set_stream({}, False)
    assert not window.btn_stream.isEnabled() and not window._sharing

    ctl = AppController(app, EngineOptions(), store=None)
    requested = []
    ctl.engine = SimpleNamespace(request_stream=lambda *args: requested.append(args))
    ctl.request_stream("side")
    assert not requested, "Local/login cannot publish"
    ctl.mode = "session"
    with patch("ui.controller.shutil.which", return_value="ffmpeg"):
        ctl.request_stream("both")
    assert requested[-1][0] == "both"
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
    ctl._shutdown()
    from PySide6.QtCore import QCoreApplication, QEvent
    for widget in (ctl.window, ctl.camera, ctl.tray, ctl.tray.menu, window):
        widget.deleteLater()
    ctl.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: consent/default-off, dual frame routing and stop, switch, rapid stop, unavailable front, auth, safe errors, Qt controls and FFmpeg cancel")


if __name__ == "__main__":
    main()
