"""Thẻ hỏi phút 120 (nghiên cứu): không chặn, không giành bàn phím, luôn nằm trên cùng. Bấm một lựa chọn là xong."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

QUESTION = "Ngay lúc này bạn cảm thấy khó chịu ở vùng nào?"
CHOICES = (("none", "Không"), ("neck", "Cổ"), ("lower_back", "Thắt lưng"), ("both", "Cả hai"), ("skip", "Bỏ qua"))


class SurveyCard(QDialog):
    answered = Signal(str)        # none | neck | lower_back | both | skip

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setObjectName("surveyCard")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Câu hỏi nghiên cứu")
        self.setModal(False)
        self._sent = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(12)
        q = QLabel(QUESTION)
        q.setObjectName("sectionTitle")
        q.setWordWrap(True)
        lay.addWidget(q)
        note = QLabel("Chỉ một câu, trả lời trong 10 phút. Bạn có thể bỏ qua.")
        note.setObjectName("note")
        lay.addWidget(note)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text in CHOICES:
            b = QPushButton(text)
            b.setAccessibleName(text)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(b)
            self.buttons[key] = b
        lay.addLayout(row)

    def present(self):
        self._sent = False
        for b in self.buttons.values():
            b.setEnabled(True)
        self.show()

    def _pick(self, key):
        if self._sent:                               # bấm hai lần chỉ tính một
            return
        self._sent = True
        for b in self.buttons.values():
            b.setEnabled(False)
        self.hide()
        self.answered.emit(key)

    def dismiss(self):
        """Engine báo hết hạn / phiên kết thúc: ẩn thẻ, không phát câu trả lời."""
        self._sent = True
        self.hide()

    def closeEvent(self, event):
        if not self._sent:                           # đóng bằng nút X = Bỏ qua
            self._pick("skip")
        event.accept()
