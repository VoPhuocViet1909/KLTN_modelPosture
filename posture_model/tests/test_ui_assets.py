"""Kiểm tokens/labels/theme khớp web và widget cơ bản (offscreen):  python tests/test_ui_assets.py"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ui import build_theme  # noqa: E402
from ui.tokens import UI_DIR, labels, tokens  # noqa: E402

WEB = os.environ.get("KLTN_WEB_ROOT", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "FE", "KLTN_dashboard"))
CSS, LABELS_TS = os.path.join(WEB, "src", "index.css"), os.path.join(WEB, "src", "lib", "labels.ts")


def _skip(msg):
    print("   (bỏ qua:", msg + ")")


def test_tokens_match_web_css():
    if not os.path.exists(CSS):
        return _skip("không thấy web tại " + WEB)
    css = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", open(CSS, encoding="utf-8").read()))
    t = tokens()
    for k, v in t["colors"].items():
        assert css[k].lower() == v.lower(), (k, css[k], v)
    for k, v in t["status"].items():
        assert css["status-" + k.lower()].lower() == v.lower(), k


def test_labels_match_web():
    if not os.path.exists(LABELS_TS):
        return _skip("không thấy web tại " + WEB)
    ts = open(LABELS_TS, encoding="utf-8").read()
    alert = dict(re.findall(r"^\s+([A-Z_]+): '([^']+)',?$", ts.split("SEVERITY_LABEL")[0], re.M))
    for k, v in alert.items():
        assert labels()["alert"][k]["label"] == v, (k, v)
    assert set(alert) == set(labels()["alert"])
    for st, lab in re.findall(r"^\s+(GOOD|BAD|AWAY|OFFLINE): \{ label: '([^']+)'", ts, re.M):
        assert labels()["state"][st]["label"] == lab, (st, lab)
    for k, v in re.findall(r"^\s+(LOW|MEDIUM|HIGH): '([^']+)'", ts, re.M):
        assert labels()["severity"][k] == v


def test_message_table_35():
    msg = {k: v["message"] for k, v in labels()["alert"].items()}
    assert "Ngồi thẳng, kéo vai ra sau nhé." in msg["NECK_TRUNK"]
    assert "{distanceCm}" in msg["TOO_CLOSE"] and "{limit}" in msg["TOO_CLOSE"]
    assert "{sittingMin" in msg["SIT_TOO_LONG"] and "6 m" in msg["EYE_BREAK"]


def test_notifier_uses_labels():
    from notifier import format_message
    t, b = format_message(dict(alertType="NECK_TRUNK", eventType="ALERT_STARTED"))
    assert t == "Cúi cổ, gù lưng" and "kéo vai ra sau nhé" in b
    t, b = format_message(dict(alertType="TOO_CLOSE", eventType="ALERT_REPEATED", level=2, snapshot={"distanceCm": 41}),
                          {"distance_on_cm": 50})
    assert t == "Ngồi quá gần màn hình (nhắc lần 2)" and "41 cm" in b and "50 cm" in b


def test_theme_qss_is_current():
    with open(os.path.join(UI_DIR, "theme.qss"), encoding="utf-8", newline="") as f:
        on_disk = f.read().replace("\r\n", "\n")
    assert on_disk == build_theme.TEMPLATE.format(**_vars()), "chạy lại: python ui/build_theme.py"


def _vars():
    t = tokens()
    c, f = t["colors"], t["font"]
    v = {k.replace("-", "_"): val for k, val in c.items()}
    v.update(family=f["family"], body=f["size"]["body"], note=f["size"]["note"], page_title=f["size"]["page-title"],
             section_title=f["size"]["section-title"], big_number=f["size"]["big-number"],
             panel=t["radius"]["panel"], control=t["radius"]["control"], icons="@ICONS@")
    return v


def test_plumb_line_states_and_theme_loads():
    from PySide6.QtWidgets import QApplication
    from ui.theme import apply_theme
    from ui.widgets import PlumbLine, plumb_state
    app = QApplication.instance() or QApplication([])
    assert apply_theme(app) == "Be Vietnam Pro"
    assert plumb_state("GOOD") == ("#0ca30c", 0, False)
    assert plumb_state("BAD") == ("#d03b3b", 14, False)
    assert plumb_state("AWAY")[2] is True and plumb_state("OFFLINE") == ("#8a8f98", 0, False)
    assert plumb_state("CALIBRATING")[2] is True
    p = PlumbLine(100)
    p.set_state("BAD")
    assert p.state() == "BAD"


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK ", fn.__name__)
    print(f"{len(fns)}/{len(fns)} test đạt")
