"""Nền dùng chung của pipeline D1–D3: import (không chép) các phần của `training/forecast/`.

Tái dùng từ forecast: đọc/kiểm minutes.jsonl + sessions.jsonl (`data`), phân loại được/BAD (thuộc tính của `Session`),
thời gian ngồi liên tục, phút quan sát được (`features.minute_table`), bootstrap theo người (`boot`), hash/commit (`protocol`).
`training/forecast` được NỐI VÀO CUỐI sys.path nên các module của fatigue (tên khác: `fat_protocol`, `blocks`, ...) không che chúng.
"""
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FORECAST = HERE.parent / "forecast"
if str(FORECAST) not in sys.path:
    sys.path.append(str(FORECAST))

import boot as BT              # noqa: E402,F401  (forecast)
import data as D               # noqa: E402,F401  (forecast)
import features as FE          # noqa: E402,F401  (forecast)
import protocol as PF          # noqa: E402,F401  (forecast: hash/commit + protocol của forecast)

PROTOCOL_PATH = HERE / "protocol.json"


def load_protocol(path=PROTOCOL_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def forecast_protocol():
    """Protocol của forecast: nguồn của away_reset_sec và các tham số quan sát được dùng trong `minute_table`."""
    return PF.load()


def truncate(s, m):
    """Session chỉ gồm m phút đầu (sao chép mảng). Mọi đặc trưng D3 tính trên bản cắt này nên KHÔNG thể dùng dữ liệu sau phút m."""
    m = min(m, s.n)
    return dataclasses.replace(
        s, n=m, window_start=list(s.window_start[:m]), covered=s.covered[:m].copy(), presence=s.presence[:m].copy(),
        away=s.away[:m].copy(), unknown=s.unknown[:m].copy(), cls=s.cls[:m].copy(), alerts=s.alerts[:m].copy(),
        model_version=list(s.model_version[:m]))


def block_permuted(s, order, B):
    """Session với thứ tự các khối (mỗi khối B phút) đổi theo `order`; phút dư cuối giữ nguyên chỗ; window_start (giờ thật) giữ nguyên."""
    nb = len(order)
    idx = np.concatenate([np.arange(k * B, (k + 1) * B) for k in order] + [np.arange(nb * B, s.n)]).astype(int)
    return dataclasses.replace(
        s, covered=s.covered[idx], presence=s.presence[idx], away=s.away[idx], unknown=s.unknown[idx], cls=s.cls[idx],
        alerts=s.alerts[idx], model_version=[s.model_version[i] for i in idx])
