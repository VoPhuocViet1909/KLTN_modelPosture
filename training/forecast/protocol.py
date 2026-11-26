"""Đọc protocol.json (nguồn tham số duy nhất) và ghi dấu: hash, đã commit chưa."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "protocol.json"


def load(path=PROTOCOL_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def protocol_hash(path=PROTOCOL_PATH):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()   # bất biến CRLF/LF


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def git_info(path=PROTOCOL_PATH):
    """commit hiện tại + protocol.json đã được commit và không bị sửa so với HEAD chưa."""
    rel = Path(path).resolve()
    tracked = _git("ls-files", "--error-unmatch", str(rel)) is not None
    changed = subprocess.run(["git", "-C", str(HERE), "diff", "--ignore-cr-at-eol", "--quiet", "HEAD", "--", str(rel)],
                             capture_output=True).returncode != 0 if tracked else None
    return dict(commit=_git("rev-parse", "HEAD"), protocol_tracked=tracked, protocol_modified_since_commit=changed,
                code_dirty=bool(_git("status", "--porcelain", "--", str(HERE))))
