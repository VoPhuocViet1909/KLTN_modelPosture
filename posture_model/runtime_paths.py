"""Mutable configuration and outbox directory. A portable without a marker keeps its original layout."""
import os
import sys
from pathlib import Path


def data_directory():
    if not getattr(sys, 'frozen', False):
        return Path(__file__).resolve().parent
    folder = Path(sys.executable).resolve().parent
    marker = folder / 'posture-data.path'
    if not marker.is_file():
        return folder
    destination = Path(marker.read_text(encoding='utf-8-sig').strip())
    if not destination.is_absolute() or not destination.is_dir():
        raise RuntimeError('Không tìm thấy thư mục dữ liệu đã chọn khi cài đặt.')
    return destination
