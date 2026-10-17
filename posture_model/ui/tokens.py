"""Đọc design_tokens.json và labels.json (nguồn chép từ web, xem trường _source trong từng file)."""
import functools
import json
import os
import sys

UI_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):                      # PyInstaller: dữ liệu nằm cạnh bản giải nén
    UI_DIR = os.path.join(getattr(sys, "_MEIPASS", UI_DIR), "ui")


@functools.lru_cache(maxsize=None)
def _load(name):
    with open(os.path.join(UI_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def tokens():
    return _load("design_tokens.json")


def labels():
    return _load("labels.json")


def color(name):
    return tokens()["colors"][name]


def status_color(state):
    return tokens()["status"][state]


def state_label(state):
    return labels()["state"][state]["label"]


def alert_info(alert_type):
    """{'label', 'message', 'group', 'icon'}; loại lạ thì hiện nguyên mã."""
    return labels()["alert"].get(alert_type) or {
        "label": alert_type or "Cảnh báo", "message": "Hãy điều chỉnh tư thế.", "group": "posture",
        "icon": "triangle-alert"}
