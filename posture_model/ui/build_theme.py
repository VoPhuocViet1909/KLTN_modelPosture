"""Sinh ui/theme.qss từ ui/design_tokens.json:  python ui/build_theme.py   (chạy lại mỗi khi đổi tokens)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.tokens import UI_DIR, tokens  # noqa: E402

TEMPLATE = """/* TỰ SINH từ design_tokens.json bởi build_theme.py – đừng sửa tay. */
* {{ font-family: "{family}"; font-size: {body}px; color: {foreground}; outline: none; }}
QMainWindow, QDialog, QWidget#root {{ background: {surface}; }}
QToolTip {{ background: {background}; color: {foreground}; border: 1px solid {border}; padding: 4px 8px; }}

QFrame#panel {{ background: {card}; border: 1px solid {border}; border-radius: {panel}px; }}
QFrame#panel QLabel {{ background: transparent; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {surface}; border: none; }}
QFrame#panel QLabel#preview {{ background: {muted}; border: 1px solid {border}; border-radius: {control}px; color: {muted_foreground}; }}

QLabel {{ background: transparent; }}
QLabel#pageTitle {{ font-size: {page_title}px; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: {section_title}px; font-weight: 500; }}
QLabel#note {{ font-size: {note}px; color: {muted_foreground}; }}
QLabel#bigNumber {{ font-size: {big_number}px; font-weight: 600; }}
QLabel#stateText {{ font-size: {section_title}px; font-weight: 500; color: {foreground}; }}
QLabel#error {{ color: {destructive}; font-size: {body}px; }}

QPushButton {{ background: {background}; border: 1px solid {input}; border-radius: {control}px; padding: 8px 16px; min-height: 26px;
  font-weight: 500; }}
QPushButton:hover {{ background: {accent}; }}
QPushButton:focus {{ border: 2px solid {ring}; padding: 7px 15px; }}
QPushButton:disabled {{ color: {muted_foreground}; background: {muted}; }}
QPushButton#primary {{ background: {primary}; color: {primary_foreground}; border: 1px solid {primary}; }}
QPushButton#primary:hover {{ background: {chart_3}; border-color: {chart_3}; }}
QPushButton#primary:disabled {{ background: {chart_2}; border-color: {chart_2}; color: {primary_foreground}; }}
QPushButton#link {{ border: none; background: transparent; color: {primary}; padding: 4px 8px; }}
QPushButton#link:hover {{ background: transparent; text-decoration: underline; }}
QPushButton#link:focus {{ border: 2px solid {ring}; padding: 2px 6px; }}

QLineEdit {{ background: {background}; border: 1px solid {input}; border-radius: {control}px; padding: 8px 12px; min-height: 26px;
  selection-background-color: {chart_4}; selection-color: {foreground}; }}
QLineEdit:focus {{ border: 2px solid {ring}; padding: 7px 11px; }}
QLineEdit[invalid="true"] {{ border-color: {destructive}; }}
QComboBox {{ background: {background}; border: 1px solid {input}; border-radius: {control}px; min-height: 30px; padding: 6px 12px; }}
QComboBox:focus {{ border: 2px solid {ring}; padding: 5px 11px; }}
QComboBox QAbstractItemView {{ background: {background}; selection-background-color: {accent}; selection-color: {foreground}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {input}; border-radius: 4px; background: {background}; }}
QCheckBox::indicator:checked {{ background: {primary}; border-color: {primary}; image: url("{icons}/check-white.svg"); }}
QCheckBox::indicator:focus {{ border: 2px solid {ring}; }}

QMenu {{ background: {background}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent}; color: {foreground}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QFrame#banner {{ background: {background}; border: 1px solid {border}; border-radius: {control}px; }}
QFrame#banner QLabel {{ background: transparent; }}
QDialog#alertDialog {{ background: {background}; }}
"""


def build():
    t = tokens()
    c, f = t["colors"], t["font"]
    v = {k.replace("-", "_"): val for k, val in c.items()}
    v.update(family=f["family"], body=f["size"]["body"], note=f["size"]["note"],
             page_title=f["size"]["page-title"], section_title=f["size"]["section-title"],
             big_number=f["size"]["big-number"], panel=t["radius"]["panel"], control=t["radius"]["control"],
             icons="@ICONS@")        # app thay bằng đường dẫn thật lúc chạy (qss không chứa đường dẫn máy)
    out = TEMPLATE.format(**v)
    with open(os.path.join(UI_DIR, "theme.qss"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    return out


if __name__ == "__main__":
    build()
    print("Đã sinh", os.path.join(UI_DIR, "theme.qss"))
