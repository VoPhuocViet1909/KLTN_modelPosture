"""Lưu phiên đăng nhập trong Windows Credential Manager (qua thư viện keyring).

Chỉ lưu REFRESH TOKEN (+ email, địa chỉ máy chủ để biết token của ai/ở đâu). KHÔNG lưu mật khẩu, KHÔNG lưu access token.
Refresh token dùng một lần: mỗi lần máy chủ cấp cặp mới, update_refresh() ghi đè token mới.
Mọi lỗi keyring (không có kho khóa, bị từ chối...) trả về False/None để app vẫn chạy được (chỉ không nhớ phiên).
"""
import json
import threading

SERVICE = "KLTN Posture Monitor"
ENTRY = "session"


class CredentialStore:
    def __init__(self, backend=None):
        """backend: module/đối tượng có get_password/set_password/delete_password (mặc định: keyring)."""
        if backend is None:
            import keyring
            backend = keyring
        self._kr = backend
        self._lock = threading.Lock()

    def _read(self):
        try:
            raw = self._kr.get_password(SERVICE, ENTRY)
            data = json.loads(raw) if raw else None
        except Exception:
            return None
        if (isinstance(data, dict) and all(isinstance(data.get(k), str) and data[k]
                                           for k in ("baseUrl", "email", "refreshToken"))):
            return data
        return None

    def _write(self, data):
        try:
            self._kr.set_password(SERVICE, ENTRY, json.dumps(data, separators=(",", ":")))
            return True
        except Exception:
            return False

    def load(self):
        """{'baseUrl', 'email', 'refreshToken'} hoặc None."""
        with self._lock:
            return self._read()

    def save(self, base_url, email, refresh_token):
        with self._lock:
            return self._write(dict(baseUrl=base_url, email=email, refreshToken=refresh_token))

    def update_refresh(self, refresh_token):
        """Ghi đè refresh token mới (chỉ khi đang có phiên đã lưu)."""
        with self._lock:
            cur = self._read()
            if cur is None:
                return False
            cur["refreshToken"] = refresh_token
            return self._write(cur)

    def clear(self):
        with self._lock:
            try:
                self._kr.delete_password(SERVICE, ENTRY)
                return True
            except Exception:                    # không có mục để xóa cũng coi như đã sạch
                return self._read() is None
