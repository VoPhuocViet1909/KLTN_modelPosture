"""RTSP settings and existing shared-capture path, no camera/network."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication
from live_stream import validate_rtsp_base
from engine import EngineOptions, PostureEngine
from ui.controller import AppController
from ui.main_window import MainWindow
from ui.theme import apply_theme
import iot_config
import ui.setup_view as setup


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    for value in ('rtsp://127.0.0.1:8554', 'rtsp://media.example:8554/', 'rtsp://[::1]:8554'):
        assert validate_rtsp_base(value) == value.rstrip('/')
    for value in ('http://host', 'rtsp://user:secret@host', 'rtsp://host/path', 'rtsp://host?token=x',
                  'rtsp://host#token', 'rtsp://host:bad', 'rtsp://host:0', 'rtsp://host:65536', 'rtsp://ho st', 'rtsp://[bad'):
        try:
            validate_rtsp_base(value)
            raise AssertionError('Invalid media origin accepted')
        except ValueError:
            pass
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.IniFormat)
        with patch.object(setup, 'preferences', return_value=settings), patch.object(iot_config, 'PATH', str(Path(directory) / 'iot.json')):
            dialog = setup.SetupDialog('1', '-1', 'http://localhost:8080')
            assert dialog.media_rtsp.text() == 'rtsp://127.0.0.1:8554'
            dialog.media_rtsp.setText('rtsp://192.168.1.20:8554/')
            if len(sys.argv) > 1:
                output = Path(sys.argv[1])
                output.mkdir(parents=True, exist_ok=True)
                dialog.show()
                app.processEvents()
                assert dialog.grab().save(str(output / 'desktop-media-settings.png'))
            dialog.save()
            assert dialog.result_values == ('1', '-1', 'http://localhost:8080')
            assert setup.media_rtsp_base(settings, 'http://localhost:8080/') == 'rtsp://192.168.1.20:8554'
            assert setup.media_rtsp_base(settings, 'http://other:8080') == 'rtsp://127.0.0.1:8554'
            another = setup.SetupDialog('1', '-1', 'http://localhost:8080')
            another.media_rtsp.setText('rtsp://host?token=secret')
            another.save()
            assert another.result_values is None and another.error.text()
            assert settings.value('media_rtsp_base') == 'rtsp://192.168.1.20:8554'
            another.server.setText('http://other:8080')
            another.server.textEdited.emit('http://other:8080')
            assert another.media_rtsp.text() == 'rtsp://127.0.0.1:8554'
            ctl = AppController(app, EngineOptions(), store=None)
            ctl.cfg.values['api_base_url'] = 'http://localhost:8080'
            with patch('ui.controller.PostureEngine') as engine, patch('ui.controller.EngineThread') as thread:
                ctl._run_engine(ctl.opts, None, None, 'local')
                assert engine.call_args.args[0].stream_rtsp_base == 'rtsp://192.168.1.20:8554'
            ctl.engine = ctl.thread = None
            ctl.app.aboutToQuit.disconnect(ctl._shutdown)
            ctl._shutdown()
            window = MainWindow()
            window.set_stream(dict(deviceId='desktop-test', frontAvailable=True), True)
            assert 'desktop-test' in window.stream_device.text()
            if len(sys.argv) > 1:
                from PySide6.QtWidgets import QScrollArea
                window.show_status()
                window.show()
                window.findChild(QScrollArea).ensureWidgetVisible(window.stream_device)
                app.processEvents()
                assert window.grab().save(str(output / 'desktop-media-device.png'))
            window.set_stream({}, False)
            assert window.stream_device.text() == ''
            for widget in (dialog, another, ctl.window, ctl.camera, ctl.tray, ctl.tray.menu, window):
                widget.deleteLater()
            ctl.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.shutdown()
    print('PASS: RTSP validation, scoped persistence, invalid-save guard, engine endpoint and device ID privacy')


if __name__ == '__main__':
    main()
