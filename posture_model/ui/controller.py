"""AppController: nối engine (QThread) với cửa sổ chính, khay hệ thống, thông báo và cửa sổ camera."""
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QSystemTrayIcon, QVBoxLayout

from engine import EngineOptions, PostureEngine, load_config
from ui import icons
from ui.bridge import EngineBridge, EngineThread, QtNotifier
from ui.camera_view import CameraView
from ui.main_window import MainWindow
from ui.theme import apply_theme
from ui.tokens import alert_info, color, status_color
from ui.tray import TrayController, make_icon


class AlertDialog(QDialog):
    """Hộp thoại mức Cao. Hiện không giành bàn phím (không kích hoạt cửa sổ), luôn nằm trên cùng."""

    def __init__(self, alert_type, title, body, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setObjectName("alertDialog")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        info = alert_info(alert_type)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        ic = QLabel()
        col = color("primary") if info["group"] == "rest" else status_color("BAD")
        ic.setPixmap(icons.pixmap(info["icon"], col, 24))
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        head.addWidget(ic)
        head.addWidget(t, 1)
        lay.addLayout(head)
        msg = QLabel(body)
        msg.setWordWrap(True)
        msg.setMinimumWidth(320)
        lay.addWidget(msg)
        btn = QPushButton("Đã ngồi lại")
        btn.setObjectName("primary")
        btn.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        lay.addLayout(row)


def beep(sev):
    try:
        import winsound
        for _ in range(2 if sev == "HIGH" else 1):
            winsound.Beep(1000, 250)
            time.sleep(0.1)
    except Exception:
        pass


class AppController(QObject):
    def __init__(self, app: QApplication, opts: EngineOptions):
        super().__init__()
        self.app, self.opts = app, opts
        apply_theme(app)
        app.setQuitOnLastWindowClosed(False)
        self.cfg, self.model_cfg = load_config(opts.config)
        self.window = MainWindow()
        self.tray = TrayController()
        self.camera = CameraView()
        self.bridge = EngineBridge()
        self.notifier = QtNotifier(self.cfg)
        self.engine = PostureEngine(opts, cfg=self.cfg, model_cfg=self.model_cfg, notifier=self.notifier,
                                    listener=self.bridge)
        self.thread = EngineThread(self.engine)
        self._dialog = None
        self.window.setWindowIcon(make_icon("GOOD"))

        b = self.bridge
        b.state.connect(self._on_state)
        b.sync.connect(self.window.set_sync)
        b.frame.connect(self.camera.show_frame)
        b.finished.connect(self._on_finished)
        b.error.connect(self._on_error)
        self.notifier.notice.connect(self._on_notice)
        self.window.cameraRequested.connect(self.open_camera)
        self.camera.closed.connect(self._camera_closed)
        self.tray.openRequested.connect(self.show_window)
        self.tray.recalibrateRequested.connect(self.engine.request_recalibrate)
        self.tray.quitRequested.connect(self.quit)
        self.app.aboutToQuit.connect(self._shutdown)

    # ---------------------------------------------------------------- vòng đời
    def start(self):
        self.tray.show()
        self.window.show()
        self.thread.start()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self):
        self.app.quit()

    def _shutdown(self):
        self.engine.want_frames = False
        self.camera.hide()
        if not self.thread.stop(20000):
            self.thread.terminate()
        self.tray.hide()

    # ---------------------------------------------------------------- engine -> giao diện
    def _on_state(self, s):
        self.window.set_state(s)
        self.tray.set_state(s["state"])

    def _on_finished(self, reason, stats):
        self.window.set_state(dict(state="OFFLINE"))
        self.tray.set_state("OFFLINE")
        self.engine.want_frames = False

    def _on_error(self, msg):
        self.window.set_state(dict(state="OFFLINE"))
        self.window.hint.setText(msg)
        self.tray.set_state("OFFLINE")
        if self.tray.isVisible():
            self.tray.showMessage("Posture Monitor", msg, QSystemTrayIcon.Warning, 8000)

    def _on_notice(self, title, body, sev, alert_type, event_type):
        """Kênh theo mức: LOW banner + toast; MEDIUM + bíp; HIGH + hộp thoại (tôn trọng notify_* trong cấu hình)."""
        self.window.show_notice(alert_type, title, body)
        if self.cfg["notify_toast"] and self.tray.isVisible():
            self.tray.showMessage(title, body, QSystemTrayIcon.NoIcon, 6000)
        if sev in ("MEDIUM", "HIGH") and self.cfg["notify_sound"]:
            threading.Thread(target=beep, args=(sev,), daemon=True).start()
        if sev == "HIGH" and self.cfg["notify_popup"] and self._dialog is None:
            self._dialog = AlertDialog(alert_type, title, body)
            self._dialog.destroyed.connect(lambda *_: setattr(self, "_dialog", None))
            self._dialog.show()

    # ---------------------------------------------------------------- camera
    def open_camera(self):
        self.engine.want_frames = True
        self.camera.show()
        self.camera.raise_()

    def _camera_closed(self):
        self.engine.want_frames = False
