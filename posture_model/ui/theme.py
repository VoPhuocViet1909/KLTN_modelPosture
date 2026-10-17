"""Nạp font Be Vietnam Pro đóng gói kèm + theme.qss (sinh từ design_tokens.json bởi ui/build_theme.py)."""
import glob
import os

from PySide6.QtGui import QFont, QFontDatabase

from ui.tokens import UI_DIR, tokens


def load_fonts():
    """Trả về tên family đã nạp (Be Vietnam Pro); thiếu file thì dùng font hệ thống."""
    fam = tokens()["font"]["family"]
    for ttf in glob.glob(os.path.join(UI_DIR, "fonts", "*.ttf")):
        QFontDatabase.addApplicationFont(ttf)
    return fam if fam in QFontDatabase.families() else None


def apply_theme(app):
    fam = load_fonts()
    if fam:
        f = QFont(fam)
        f.setPixelSize(tokens()["font"]["size"]["body"])
        app.setFont(f)
    app.setStyle("Fusion")                            # nền tảng ổn định để QSS vẽ giống nhau mọi máy
    with open(os.path.join(UI_DIR, "theme.qss"), encoding="utf-8") as fh:
        qss = fh.read().replace("@ICONS@", os.path.join(UI_DIR, "icons").replace("\\", "/"))
    app.setStyleSheet(qss)
    return fam
