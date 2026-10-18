"""Run offscreen without cameras; optionally pass a screenshot output directory."""
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.setup_view import SetupDialog
from ui.theme import apply_theme


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
    window = MainWindow()
    window.show()
    app.processEvents()
    if output:
        window.grab().save(str(output / 'desktop-login.png'))
    window.resize(400, 400)
    app.processEvents()
    scroll = window.centralWidget()
    assert scroll.verticalScrollBar().maximum() > 0, 'Small window must scroll'
    scroll.ensureWidgetVisible(window.btn_setup)
    app.processEvents()
    assert scroll.viewport().rect().contains(window.btn_setup.mapTo(scroll.viewport(), window.btn_setup.rect().center()))
    window.resize(560, 760)
    window.show_status()
    window.set_state(dict(state='GOOD', sittingSec=125, distanceCm=62))
    app.processEvents()
    assert window.sit.text() == '02:05' and window.dist.text() == '62 cm'
    if output:
        window.grab().save(str(output / 'desktop-status.png'))
    dialog = SetupDialog('1', '-1', 'http://localhost:8080')
    assert dialog.front.currentText() == 'Không dùng camera trước'
    assert dialog.values()[1] == '-1'
    dialog.front.setCurrentText('0')
    assert dialog.values()[1] == '0'
    dialog.front.setCurrentText('1')
    try:
        dialog.values()
        raise AssertionError('Duplicate camera must be rejected')
    except ValueError:
        pass
    dialog.front.setCurrentText('Không dùng camera trước')
    dialog.show()
    app.processEvents()
    for image in dialog.images:
        assert image.width() >= 200 and image.height() >= 144
    assert dialog.rect().contains(dialog.check.mapTo(dialog, dialog.check.rect().center())), 'Preview action must stay visible'
    if output:
        dialog.grab().save(str(output / 'desktop-setup.png'))
    dialog.reject()
    window.hide()
    print('PASS: resizable window, scroll access, state values, human camera choice and duplicate validation')


if __name__ == '__main__':
    main()
