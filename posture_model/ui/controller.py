"""AppController: nối engine (QThread) với cửa sổ chính, khay hệ thống, thông báo, cửa sổ camera và phiên đăng nhập.

Vòng đời:  màn đăng nhập --đăng nhập / mở lại phiên đã nhớ--> chạy engine (có gửi, có config sync)
                         --"Dùng không đăng nhập"-----------> chạy engine chế độ local (chỉ nhắc, không gửi)
           đăng xuất (menu khay) / phiên hết hạn ------------> dừng engine, về màn đăng nhập (outbox vẫn giữ)
"""
import dataclasses
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Slot
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QSystemTrayIcon, QVBoxLayout

import login_service
from api_session import AuthError
from engine import APP_DIR, EngineOptions, PostureEngine, load_config
from ui import icons
from ui.bridge import EngineBridge, EngineThread, QtNotifier, Task
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


def make_store():
    """CredentialStore (Windows Credential Manager); None nếu keyring không dùng được (app vẫn chạy, chỉ không nhớ phiên)."""
    try:
        from credentials import CredentialStore
        return CredentialStore()
    except Exception as e:
        print("Không dùng được kho khóa của hệ điều hành, sẽ không ghi nhớ đăng nhập:", e)
        return None


class AppController(QObject):
    def __init__(self, app: QApplication, opts: EngineOptions, store="auto", base_url=None, auto_resume=True):
        super().__init__()
        self.app, self.opts, self.auto_resume = app, opts, auto_resume
        apply_theme(app)
        app.setQuitOnLastWindowClosed(False)
        self.cfg, self.model_cfg = load_config(opts.config)
        if base_url:                                   # --api-base-url: ưu tiên hơn app_config.json (chỉ trong RAM)
            self.cfg.values["api_base_url"] = base_url
        self.store = make_store() if store == "auto" else store
        self.default_outbox = os.path.join(APP_DIR, "out", "outbox.db")

        self.mode = "login"                            # login | session | local
        self.auth = None
        self.remember = False
        self.engine = self.thread = None
        self._leaving = False
        self._tasks = {}
        self._dialog = None

        self.window = MainWindow()
        self.tray = TrayController()
        self.camera = CameraView()
        self.bridge = EngineBridge()
        self.notifier = QtNotifier(self.cfg)
        self.window.setWindowIcon(make_icon("GOOD"))

        b = self.bridge
        b.state.connect(self._on_state)
        b.sync.connect(self._on_sync)
        b.frame.connect(self.camera.show_frame)
        b.finished.connect(self._on_finished)
        b.error.connect(self._on_error)
        self.notifier.notice.connect(self._on_notice)
        self.window.cameraRequested.connect(self.open_camera)
        self.window.loginClicked.connect(self.go_login)
        self.window.recalibrateRequested.connect(self.request_recalibrate)
        self.window.skipFrontRequested.connect(self.request_skip_front)
        self.window.setupRequested.connect(self.configure_devices)
        self.window.login.loginRequested.connect(self._on_login_submit)
        self.window.login.localRequested.connect(self._on_local)
        self.camera.closed.connect(self._camera_closed)
        self.tray.openRequested.connect(self.show_window)
        self.tray.recalibrateRequested.connect(self.request_recalibrate)
        self.tray.logoutRequested.connect(self.logout)
        self.tray.loginRequested.connect(self.go_login)
        self.tray.quitRequested.connect(self.quit)
        self.app.aboutToQuit.connect(self._shutdown)

    @property
    def base_url(self):
        return self.cfg["api_base_url"]

    # ---------------------------------------------------------------- khởi động / thoát
    def start(self):
        self.tray.show()
        self.window.show()
        self._to_login()
        saved = self.store.load() if self.store else None
        if saved:
            self.window.login.prefill(saved["email"])
            if self.auto_resume and self.base_url:
                self._begin_resume()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def configure_devices(self):
        # Đợi engine trả camera trước khi xem ảnh kiểm tra; giữ phiên và outbox hiện có.
        if self._leaving or any(t.isRunning() for t in self._tasks):
            return
        mode = self.mode
        self.window.btn_setup.setEnabled(False)

        def configure():
            from ui.setup_view import SetupDialog
            self.camera.hide()
            dialog = SetupDialog(self.opts.side, self.opts.front, self.base_url, self.window,
                                 server_editable=mode != "session")
            if dialog.exec() == SetupDialog.Accepted:
                side, front, server = dialog.result_values
                self.opts = dataclasses.replace(self.opts, side=side, front=front,
                                                side_video=None, front_video=None)
                self.cfg.values["api_base_url"] = server
            self._leaving = False
            self.window.btn_setup.setEnabled(True)
            if mode == "session":
                self._start_session(self.auth, self.remember)
            elif mode == "local":
                self._on_local()
            else:
                self.window.login.set_server(self.base_url)
        self._stop_engine(configure)

    def quit(self):
        self.app.quit()

    def _shutdown(self):
        self._leaving = True
        self.camera.hide()
        if self.engine is not None:
            self.engine.want_frames = False
            self.engine.stop()
        if self.thread is not None and not self.thread.wait(20000):
            self.thread.terminate()
        if self.auth is not None and not self.remember:     # không nhớ đăng nhập: thu hồi phiên khi thoát
            login_service.logout(self.auth, self.store)
        self.tray.hide()

    def _track(self, task, on_done, on_failed):
        """Chạy task nền; kết quả trả về luồng giao diện qua slot của QObject (lambda nối trực tiếp sẽ chạy ở luồng nền)."""
        self._tasks[task] = (on_done, on_failed)
        task.done.connect(self._task_done)
        task.failed.connect(self._task_failed)
        task.finished.connect(self._task_finished)
        task.start()

    @Slot(object)
    def _task_done(self, result):
        cb = self._tasks.get(self.sender())
        if cb:
            cb[0](result)

    @Slot(object)
    def _task_failed(self, error):
        cb = self._tasks.get(self.sender())
        if cb:
            cb[1](error)

    @Slot()
    def _task_finished(self):
        t = self.sender()
        if t in self._tasks and t.isFinished():
            QTimer.singleShot(0, lambda: self._tasks.pop(t, None))

    # ---------------------------------------------------------------- đăng nhập
    def _to_login(self, error=None, info=None):
        """Về màn đăng nhập. Engine đã dừng. Outbox vẫn giữ trên đĩa."""
        self.auth, self.remember, self.mode = None, False, "login"
        self.engine = self.thread = None
        self._leaving = False
        self.cfg.remote = {}                           # bỏ cấu hình máy chủ của tài khoản cũ
        self.window.show_login()
        self.window.set_state(dict(state="OFFLINE"))
        self.window.set_sync(None)
        self.tray.set_state("OFFLINE")
        self.tray.set_mode("login")
        lg = self.window.login
        lg.set_server(self.base_url)
        lg.reset()
        lg.show_error(error or "")
        if info:
            lg.show_info(info)

    def go_login(self):
        """Từ chế độ không đăng nhập quay về màn đăng nhập."""
        self._stop_engine(lambda: (self._to_login(), self.show_window()))

    def _begin_resume(self):
        self.window.login.set_busy(True, "Đang mở lại phiên…")
        self._track(Task(lambda: login_service.resume(self.base_url, self.store)),
                    self._on_resumed, lambda e: self._on_resumed((None, f"Lỗi không mong đợi: {e}", False)))

    def _on_resumed(self, result):
        auth, message, _cleared = result
        lg = self.window.login
        lg.set_busy(False)
        if auth is not None:
            self._start_session(auth, remember=True)
        elif message:
            lg.show_error(message)

    def _on_login_submit(self, email, password, remember):
        lg = self.window.login
        lg.set_busy(True)
        base = self.base_url
        self._track(Task(lambda: login_service.login(base, email, password, self.store, remember)),
                    lambda auth: self._on_logged_in(auth, remember),
                    lambda e: self._on_login_failed(e, base))

    def _on_logged_in(self, auth, remember):
        self.window.login.set_busy(False)
        self._start_session(auth, remember)

    def _on_login_failed(self, error, base):
        lg = self.window.login
        lg.set_busy(False)
        if isinstance(error, AuthError):
            lg.show_error(login_service.describe(error, base, "login"))
        else:
            lg.show_error(f"Có lỗi không mong đợi khi đăng nhập: {error}")

    # ---------------------------------------------------------------- chạy engine
    def _user_outbox(self, auth):
        """Mỗi tài khoản một outbox riêng (outbox-<userId>.db) để dữ liệu người này không chặn người kia."""
        if self.opts.outbox != self.default_outbox:
            return self.opts.outbox
        return os.path.join(os.path.dirname(self.default_outbox), f"outbox-{auth.user_id}.db")

    def _start_session(self, auth, remember):
        self.auth, self.remember = auth, remember
        config_sync = None
        try:
            from config_sync import ConfigSync       # bật config sync sau đăng nhập (như --sync-config)
            config_sync = ConfigSync(auth)
        except ImportError:
            print("Thiếu python-socketio: không đồng bộ cấu hình. Cài bằng pip install -r requirements.txt")
        opts = dataclasses.replace(self.opts, send=True, outbox=self._user_outbox(auth))
        self._run_engine(opts, auth, config_sync, "session")
        self.window.set_account(auth.email or auth.name)

    def _on_local(self):
        """'Dùng không đăng nhập': chỉ nhắc tại chỗ, không ghi outbox, không gửi gì."""
        self._run_engine(dataclasses.replace(self.opts, send=False), None, None, "local")
        self.window.set_account(None)

    def _run_engine(self, opts, auth, config_sync, mode):
        self.mode = mode
        self._leaving = False
        self.engine = PostureEngine(opts, cfg=self.cfg, model_cfg=self.model_cfg, auth=auth, config_sync=config_sync,
                                    notifier=self.notifier, listener=self.bridge)
        self.engine.want_frames = self.camera.isVisible()
        self.thread = EngineThread(self.engine)
        self.window.login.reset()
        self.window.show_status()
        self.window.set_state(dict(state="CALIBRATING", calibLeft=self.cfg["calib_sec"]))
        self.tray.set_mode(mode)
        self.thread.start()

    def _stop_engine(self, then):
        """Dừng engine không chặn giao diện; xong thì gọi then(). Không có engine thì gọi ngay."""
        th = self.thread
        if th is None or th.isFinished() or not th.isRunning():
            then()
            return
        self._leaving = True
        self.engine.want_frames = False
        self.engine.stop()
        poll = QTimer(self)
        poll.setInterval(100)

        def check():
            if th.isFinished() or not th.isRunning():
                poll.stop()
                poll.deleteLater()
                then()
        poll.timeout.connect(check)
        poll.start()

    # ---------------------------------------------------------------- đăng xuất / hết phiên
    def logout(self):
        """Menu khay 'Đăng xuất': dừng engine (gửi nốt lô cuối), gọi /auth/logout, xóa keyring, về màn đăng nhập."""
        if self.mode != "session" or self._leaving:
            return
        auth = self.auth
        self.tray.act_logout.setEnabled(False)

        def after_stop():
            self._track(Task(lambda: login_service.logout(auth, self.store)),
                        lambda ok: self._after_logout(ok), lambda e: self._after_logout(False))
        self._stop_engine(after_stop)

    def _after_logout(self, server_revoked):
        self.tray.act_logout.setEnabled(True)
        note = "Đã đăng xuất. Dữ liệu chưa gửi vẫn được giữ trên máy."
        if not server_revoked:
            note += " (Không báo được cho máy chủ; phiên trên máy này đã xóa.)"
        self._to_login(info=note)
        self.show_window()

    def _session_lost(self, kind):
        """Không làm mới được phiên (401/hết hạn/bị thu hồi/mất kết nối lúc làm mới): về màn đăng nhập kèm lý do."""
        if kind in ("invalid", "inactive") and self.store:
            self.store.clear()
        msg = login_service.describe(AuthError("", kind or "invalid"), self.base_url, "runtime")
        self._stop_engine(lambda: (self._to_login(error=msg), self.show_window()))

    # ---------------------------------------------------------------- engine -> giao diện
    def _on_state(self, s):
        if self._leaving or self.mode == "login":
            return
        self.window.set_state(s)
        self.tray.set_state(s["state"])

    def _on_sync(self, info):
        if self._leaving or self.mode == "login":
            return
        self.window.set_sync(info)
        if self.mode == "session" and info.get("authLost"):
            self._session_lost(info.get("lostKind"))

    def _on_finished(self, reason, stats):
        if self.mode != "login" and not self._leaving:
            self.window.set_state(dict(state="OFFLINE"))
            self.tray.set_state("OFFLINE")
        if self.engine is not None:
            self.engine.want_frames = False

    def _on_error(self, msg):
        if self.mode == "login":
            return
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

    def request_recalibrate(self):
        if self.engine is not None and self.mode != "login":
            self.engine.request_recalibrate()

    def request_skip_front(self):
        if self.engine is not None and self.mode != "login":
            self.engine.request_skip_front()

    # ---------------------------------------------------------------- camera
    def open_camera(self):
        if self.engine is not None:
            self.engine.want_frames = True
        self.camera.show()
        self.camera.raise_()

    def _camera_closed(self):
        if self.engine is not None:
            self.engine.want_frames = False
