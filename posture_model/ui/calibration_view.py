"""Màn hiệu chỉnh: hướng dẫn tư thế, danh sách kiểm tra cập nhật trực tiếp (✓ / ✗ / đang chờ), lý do khi không đạt kèm
đếm ngược làm lại, nút "Hiệu chỉnh lại" và "Bỏ qua camera laptop". Màu chỉ phụ: mỗi mục luôn có icon + chữ."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui import icons
from ui.tokens import color
from ui.widgets import tabular

# thứ tự + nhãn hiển thị lúc chưa có dữ liệu (khớp calibration.CHECKS)
ROWS = [("side_visible", "Thấy bạn ở camera hông"), ("back", "Lưng thẳng"), ("neck", "Cổ thẳng"),
        ("still", "Ngồi yên"), ("shoulders", "Thấy hai vai (camera laptop)"), ("distance", "Khoảng cách tới màn hình")]
FRONT_ROWS = {"shoulders", "distance"}


class CalibrationView(QWidget):
    recalibrateRequested = Signal()
    skipFrontRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.title = QLabel("Hiệu chỉnh tư thế")
        self.title.setObjectName("sectionTitle")
        lay.addWidget(self.title)
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        lay.addWidget(self.guide)
        self.countdown = QLabel("")
        self.countdown.setObjectName("pageTitle")
        self.countdown.setFont(tabular(self.countdown.font()))
        lay.addWidget(self.countdown)

        self.rows = {}
        box = QVBoxLayout()
        box.setSpacing(4)
        for code, text in ROWS:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            ic, tx = QLabel(), QLabel(text)
            ic.setFixedSize(18, 18)
            h.addWidget(ic)
            h.addWidget(tx, 1)
            box.addWidget(row)
            self.rows[code] = (row, ic, tx, text)
        lay.addLayout(box)

        self.reasons = QLabel("")
        self.reasons.setWordWrap(True)
        self.reasons.setTextFormat(Qt.PlainText)
        self.reasons.setAccessibleName("Lý do hiệu chỉnh không đạt")
        self.reasons.hide()
        lay.addWidget(self.reasons)
        self.note = QLabel("")
        self.note.setObjectName("note")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)

        btns = QHBoxLayout()
        self.btn_redo = QPushButton("Hiệu chỉnh lại")
        self.btn_redo.setIcon(icons.icon("rotate-cw", color("foreground"), 16))
        self.btn_redo.clicked.connect(self.recalibrateRequested)
        self.btn_skip = QPushButton("Bỏ qua camera laptop")
        self.btn_skip.setToolTip("Chạy không đo lệch vai và khoảng cách")
        self.btn_skip.clicked.connect(self.skipFrontRequested)
        btns.addWidget(self.btn_redo)
        btns.addWidget(self.btn_skip)
        lay.addLayout(btns)
        self.update_view(None, 10, 10)

    def _set_row(self, code, ok, text, visible=True):
        row, ic, tx, _ = self.rows[code]
        row.setVisible(visible)
        if ok is True:
            ic.setPixmap(icons.pixmap("check", color("primary"), 18))
        elif ok is False:
            ic.setPixmap(icons.pixmap("x", color("destructive"), 18))
        else:
            ic.setPixmap(icons.pixmap("circle-dashed", color("muted-foreground"), 18))
        tx.setText(text)
        state = {True: "đạt", False: "chưa đạt", None: "đang kiểm tra"}[ok]
        ic.setAccessibleName(f"{text}: {state}")

    def update_view(self, calib, left, seconds):
        """calib = payload 'calib' của engine.on_state (None = chưa có); left = số giây còn lại của lượt đo."""
        calib = calib or {}
        failed = calib.get("stage") == "failed"
        by = {c["code"]: c["ok"] for c in calib.get("checks", [])}
        front_ok = calib.get("frontAvailable", False) and not calib.get("frontSkipped", False)
        for code, text in ROWS:
            if code in FRONT_ROWS and not front_ok:
                self._set_row(code, None, text, visible=False)
            else:
                self._set_row(code, by.get(code), text)
        self.guide.setVisible(not failed)
        self.guide.setText(f"Ngồi thẳng lưng, mắt nhìn màn hình, đặt tay lên đùi hoặc bàn, không gõ phím trong "
                           f"{int(seconds)} giây.")
        if failed:
            self.title.setText("Chưa hiệu chỉnh được")
            self.countdown.setText(f"Làm lại sau {max(int(round(calib.get('retryLeft', 0))), 0)} giây")
            self.reasons.setText("\n\n".join(r["message"] for r in calib.get("reasons", [])))
            self.reasons.show()
        else:
            self.title.setText("Hiệu chỉnh tư thế")
            self.countdown.setText(f"Còn {max(int(round(left)), 0)} giây")
            self.reasons.hide()
        skipped = calib.get("frontSkipped", False)
        self.note.setText("Đã bỏ qua camera laptop: không đo lệch vai và khoảng cách." if skipped else "")
        self.btn_skip.setVisible(front_ok)
