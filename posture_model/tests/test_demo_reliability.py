"""python posture_model/tests/test_demo_reliability.py (không webcam/backend)."""
import io
import json
import os
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from engine import EngineOptions
from outbox import Outbox
from sender import Sender
from ui.controller import AppController


def main():
    with tempfile.TemporaryDirectory() as directory:
        box = Outbox(os.path.join(directory, "outbox.db"))
        sender = Sender(box, "http://127.0.0.1:1", check_schema=False)
        box.put("event", "one", {"eventId": "one"})
        box.put("event", "two", {"eventId": "two"})
        items = box.due()
        invalid = [{}, [], {"accepted": ["one"], "rejected": []},
                   {"accepted": ["one", "other"], "rejected": []},
                   {"accepted": ["one", "one", "two"], "rejected": []},
                   {"accepted": ["one", "two"], "rejected": [{"id": "one"}]},
                   {"accepted": None, "rejected": []},
                   {"accepted": [], "rejected": [{"id": "one"}, {"id": "one"}, {"id": "two"}]}]
        for response in invalid:
            with patch.object(sender._opener, "open", return_value=io.BytesIO(json.dumps(response).encode())):
                assert not sender._send(items), response
            assert box.stats() == dict(pending=2, sent=0, dead=0), response
        with patch.object(sender._opener, "open", return_value=io.BytesIO(json.dumps(
                dict(accepted=["one"], rejected=[dict(id="two", reason="schema")], duplicates=1)).encode())):
            assert sender._send(items)
        assert box.stats() == dict(pending=0, sent=1, dead=1)
        box.close()

    app = QApplication.instance() or QApplication([])
    ctl = AppController(app, EngineOptions(), store=None, auto_resume=False)
    ctl.mode = "local"
    ctl.cfg.values.update(notify_toast=True, notify_sound=True, notify_popup=True)

    def flush():
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def notice(severity):
        ctl._on_notice("Kiểm cảnh báo", "Nội dung kiểm tự động", severity, "NECK_TRUNK", "ALERT_STARTED")

    with patch.object(ctl.tray, "isVisible", return_value=True), patch.object(ctl.tray, "showMessage") as toast, patch("ui.controller.threading.Thread") as sound:
        notice("LOW")
        assert toast.call_count == 1 and not sound.called and ctl._dialog is None
        notice("MEDIUM")
        assert toast.call_count == 2 and sound.call_count == 1 and ctl._dialog is None
        notice("HIGH")
        first = ctl._dialog
        assert first is not None and first.isVisible()
        notice("HIGH")
        assert ctl._dialog is first, "Only one popup"
        first.close()
        flush()
        assert ctl._dialog is None, "Dismissed popup must release controller reference"
        notice("HIGH")
        assert ctl._dialog is not None and ctl._dialog is not first
        ctl._stop_engine(lambda: None)
        flush()
        assert ctl._dialog is None and ctl.window.banner.isHidden(), "Stop clears notices"
        ctl.cfg.values.update(notify_toast=False, notify_sound=False, notify_popup=False)
        before = toast.call_count, sound.call_count
        notice("HIGH")
        assert (toast.call_count, sound.call_count) == before and ctl._dialog is None
        assert not ctl.window.banner.isHidden(), "In-app banner remains available"
        ctl._to_login()
        for mode, leaving in [("login", False), ("session", True)]:
            ctl.mode, ctl._leaving = mode, leaving
            notice("HIGH")
            assert ctl.window.banner.isHidden() and ctl._dialog is None
        ctl.mode, ctl._leaving = "local", False
        ctl.cfg.values["notify_popup"] = True
        notice("HIGH")
        ctl._on_finished("eof", {})
        flush()
        assert ctl._dialog is None and ctl.window.banner.isHidden()
    ctl.app.aboutToQuit.disconnect(ctl._shutdown)
    ctl.window.hide()
    print("PASS: incomplete/invalid acknowledgements retain IDs; severity/config routing, popup repeat/dismiss, stop/login/finished cleanup")


if __name__ == "__main__":
    main()
