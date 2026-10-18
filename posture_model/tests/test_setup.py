"""Runnable without camera/network: python posture_model/tests/test_setup.py."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
import ui.setup_view as setup


def main():
    app = QApplication.instance() or QApplication([])
    assert setup.validate("1", "0", "http://127.0.0.1:8080/") == ("1", "0", "http://127.0.0.1:8080")
    assert setup.validate("0", "-1", "https://example.org")[1] == "-1"
    for values in [("0", "00", "http://host"), ("x", "0", "http://host"),
                   ("0", "-2", "http://host"), ("100", "0", "http://host"),
                   ("1", "0", "http://host:bad"), ("1", "0", "file:///secret"),
                   ("1", "0", "http://user:pass@host"), ("1", "0", "http://host/api")]:
        try:
            setup.validate(*values)
            raise AssertionError(values)
        except ValueError:
            pass
    opened = []

    class Capture:
        def __init__(self, index):
            self.index = index
            self.closed = False
            opened.append(self)
        def isOpened(self): return True
        def read(self): return self.index != 9, np.zeros((24, 32, 3), dtype=np.uint8)
        def release(self): self.closed = True

    assert len(setup.snapshots("1", "0", Capture)) == 2
    assert setup.snapshots("0", "-1", Capture)[1] is None
    try:
        setup.snapshots("9", "0", Capture)
        raise AssertionError("Missing error")
    except ValueError:
        pass
    assert all(c.closed for c in opened)
    with tempfile.TemporaryDirectory() as tmp:
        setup.preferences = lambda: QSettings(os.path.join(tmp, "settings.ini"), QSettings.IniFormat)
        dialog = setup.SetupDialog("1", "0", "http://localhost:8080")
        dialog.side.setCurrentText("0")
        dialog.save()
        assert dialog.result_values is None
        dialog.front.setCurrentText("-1")
        dialog.save()
        assert dialog.result_values == ("0", "-1", "http://localhost:8080")
        assert setup.preferences().value("side") == "0"
        assert setup.preferences().value("configured", type=bool)
        dialog = setup.SetupDialog("0", "-1", "http://localhost:8080", server_editable=False)
        original = setup.snapshots
        setup.snapshots = lambda a, b: original(a, b, Capture)
        dialog.preview()
        dialog.reject()
        assert dialog.task is not None
        def finish():
            if dialog.task.isRunning():
                QTimer.singleShot(10, finish)
                return
            app.quit()
        QTimer.singleShot(10, finish)
        QTimer.singleShot(5000, app.quit)
        app.exec()
        assert not dialog.task.isRunning()
        app.processEvents()
        assert not dialog.images[0].pixmap().isNull()
        assert dialog.images[1].text() == "Camera trước đã tắt"
        assert not dialog.server.isEnabled()
        assert dialog.check.isEnabled()
        dialog.reject()
        from engine import EngineOptions
        from ui.controller import AppController
        ctl = AppController(app, EngineOptions(), store=None)
        restarted = []
        ctl._on_local = lambda: restarted.append("local")
        ctl.mode = "local"
        class AcceptedSetup:
            Accepted = 1
            result_values = ("3", "-1", "http://localhost:8080")
            def __init__(self, *args, **kwargs):
                assert kwargs["server_editable"] is True
            def exec(self): return self.Accepted
        setup.SetupDialog = AcceptedSetup
        ctl.configure_devices()
        assert (ctl.opts.side, ctl.opts.front) == ("3", "-1")
        assert restarted == ["local"] and not ctl._leaving
        assert ctl.window.btn_setup.isEnabled()
        class CancelledSetup(AcceptedSetup):
            def exec(self): return 0
        setup.SetupDialog = CancelledSetup
        ctl.configure_devices()
        assert restarted == ["local", "local"]
        assert ctl.opts.side == "3"
        ctl.app.aboutToQuit.disconnect(ctl._shutdown)
        ctl.window.deleteLater()
        ctl.camera.deleteLater()
    print("PASS: validation, release on failure, optional front, persistence, async preview")


if __name__ == "__main__":
    main()
