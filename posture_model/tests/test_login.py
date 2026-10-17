"""Kiểm thử đăng nhập / ghi nhớ phiên / đăng xuất với máy chủ giả (loopback) + kho khóa giả:  python tests/test_login.py"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import login_service  # noqa: E402
from api_session import ApiSession, AuthError  # noqa: E402
from credentials import ENTRY, SERVICE, CredentialStore  # noqa: E402

UID = "11111111-2222-3333-4444-555555555555"


class FakeKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, s, u): return self.data.get((s, u))
    def set_password(self, s, u, p): self.data[(s, u)] = p
    def delete_password(self, s, u):
        if (s, u) not in self.data:
            raise KeyError("no entry")
        del self.data[(s, u)]


class Backend:
    """Máy chủ auth giả: refresh token dùng một lần, logout thu hồi."""

    def __init__(self):
        self.n = 0
        self.valid = {}                  # refresh -> True
        self.mode = None                 # None | '403' | '500'
        self.logouts, self.password = 0, "mat-khau-dung"
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def pair(self):
        self.n += 1
        r = f"refresh-{self.n}"
        self.valid[r] = True
        return {"accessToken": f"access-{self.n}", "refreshToken": r, "expiresIn": 900}

    def _handler(self):
        be = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _send(self, code, body=None):
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path.endswith("/auth/me") and self.headers.get("Authorization", "").startswith("Bearer access-"):
                    return self._send(200, {"id": UID, "email": "demo@kltn.local", "name": "Demo", "role": "USER",
                                            "orgId": None, "enabled": True})
                self._send(401, {"code": "AUTH_TOKEN_INVALID"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                act = self.path.rsplit("/", 1)[-1]
                if be.mode == "500":
                    return self._send(503, {"code": "AUTH_UNAVAILABLE"})
                if act == "login":
                    if be.mode == "403":
                        return self._send(403, {"code": "ORGANIZATION_INACTIVE"})
                    if body.get("password") != be.password:
                        return self._send(401, {"code": "AUTH_INVALID_CREDENTIALS"})
                    return self._send(200, dict(be.pair(), user={"id": UID, "name": "Demo", "orgId": None, "role": "USER"}))
                if act == "refresh":
                    if be.valid.pop(body.get("refreshToken"), None):
                        return self._send(200, be.pair())
                    return self._send(401, {"code": "AUTH_INVALID_REFRESH_TOKEN"})
                if act == "logout":
                    be.logouts += 1
                    be.valid.pop(body.get("refreshToken"), None)
                    return self._send(204)
                self._send(404)
        return H


def test_login_errors_in_vietnamese():
    be, store = Backend(), CredentialStore(FakeKeyring())
    try:
        login_service.login(be.url, "demo@kltn.local", "sai", store)
        assert False
    except AuthError as e:
        assert e.kind == "invalid" and "không đúng" in login_service.describe(e, be.url)
    be.mode = "403"
    try:
        login_service.login(be.url, "demo@kltn.local", be.password, store)
        assert False
    except AuthError as e:
        assert e.kind == "inactive" and "tạm ngưng" in login_service.describe(e, be.url)
    be.mode = "500"
    try:
        login_service.login(be.url, "demo@kltn.local", be.password, store)
        assert False
    except AuthError as e:
        assert e.kind == "server" and "sự cố" in login_service.describe(e, be.url)
    be.srv.shutdown()
    be.srv.server_close()
    try:
        login_service.login(be.url, "demo@kltn.local", be.password, store)
        assert False
    except AuthError as e:
        msg = login_service.describe(e, be.url)
        assert e.kind == "unreachable" and "Không kết nối được máy chủ" in msg and "127.0.0.1" in msg
    for url, text in ((None, "Chưa cấu hình"), ("ftp://x", "không hợp lệ"), ("http://example.com", "không hợp lệ")):
        try:
            login_service.login(url, "a@b.c", "x", store)
            assert False
        except AuthError as e:
            assert e.kind == "config" and text in login_service.describe(e, url)
    assert store.load() is None


def test_remember_stores_only_refresh_token_and_follows_rotation():
    be, kr = Backend(), FakeKeyring()
    store = CredentialStore(kr)
    auth = login_service.login(be.url, "demo@kltn.local", be.password, store, remember=True)
    raw = kr.data[(SERVICE, ENTRY)]
    assert json.loads(raw) == {"baseUrl": be.url, "email": "demo@kltn.local", "refreshToken": auth.refresh_token}
    assert be.password not in raw and "access-" not in raw
    old = auth.refresh_token
    auth._expires = 0                                   # ép hết hạn -> làm mới -> token xoay vòng
    auth.token()
    assert auth.refresh_token != old and store.load()["refreshToken"] == auth.refresh_token
    be.srv.shutdown()


def test_no_remember_clears_previous_session():
    be, kr = Backend(), FakeKeyring()
    store = CredentialStore(kr)
    login_service.login(be.url, "demo@kltn.local", be.password, store, remember=True)
    assert store.load()
    a2 = login_service.login(be.url, "demo@kltn.local", be.password, store, remember=False)
    assert store.load() is None and a2.on_tokens is None
    be.srv.shutdown()


def test_resume_ok_then_consumed_token_clears_store():
    be, kr = Backend(), FakeKeyring()
    store = CredentialStore(kr)
    login_service.login(be.url, "demo@kltn.local", be.password, store, remember=True)
    auth, msg, cleared = login_service.resume(be.url, store)
    assert auth is not None and msg is None and not cleared
    assert auth.user_id == UID and auth.email == "demo@kltn.local" and auth.name == "Demo"
    assert store.load()["refreshToken"] == auth.refresh_token          # token mới đã được lưu
    be.valid.clear()                                                   # máy chủ thu hồi mọi phiên
    auth2, msg2, cleared2 = login_service.resume(be.url, store)
    assert auth2 is None and "hết hạn" in msg2 and cleared2 and store.load() is None
    assert login_service.resume(be.url, store) == (None, None, False)  # không còn gì để mở lại
    be.srv.shutdown()


def test_resume_network_error_keeps_token():
    be, kr = Backend(), FakeKeyring()
    store = CredentialStore(kr)
    login_service.login(be.url, "demo@kltn.local", be.password, store, remember=True)
    be.srv.shutdown()
    be.srv.server_close()
    auth, msg, cleared = login_service.resume(be.url, store)
    assert auth is None and "Không kết nối được máy chủ" in msg and not cleared and store.load() is not None


def test_resume_ignores_session_of_another_server():
    be, kr = Backend(), FakeKeyring()
    store = CredentialStore(kr)
    login_service.login(be.url, "demo@kltn.local", be.password, store, remember=True)
    assert login_service.resume("http://localhost:1", store) == (None, None, False) and store.load()
    be.srv.shutdown()


def test_logout_revokes_and_clears_even_with_expired_access():
    be, kr = Backend(), FakeKeyring()
    store = CredentialStore(kr)
    auth = login_service.login(be.url, "demo@kltn.local", be.password, store, remember=True)
    auth._expires = 0                                   # access hết hạn: logout phải làm mới trước rồi mới thu hồi
    assert login_service.logout(auth, store) is True
    assert be.logouts == 1 and not be.valid and store.load() is None and auth.lost
    try:
        auth.token()
        assert False
    except AuthError:
        pass
    be.srv.shutdown()


def test_session_lost_flag_when_refresh_rejected():
    be = Backend()
    auth = ApiSession(be.url, "demo@kltn.local", be.password)
    assert not auth.lost
    be.valid.clear()
    auth._expires = 0
    try:
        auth.token()
        assert False
    except AuthError as e:
        assert e.kind == "invalid"
    assert auth.lost and auth.lost_kind == "invalid"
    assert "hết hạn hoặc bị thu hồi" in login_service.describe(AuthError("", auth.lost_kind), be.url, "runtime")
    be.srv.shutdown()


def test_store_survives_keyring_failures():
    class Broken:
        def get_password(self, *a): raise RuntimeError("no keyring")
        set_password = delete_password = get_password
    s = CredentialStore(Broken())
    assert s.load() is None and s.save("http://x", "a@b.c", "r") is False and s.update_refresh("r") is False
    assert s.clear() is False or s.clear() is True


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK ", fn.__name__)
    print(f"{len(fns)}/{len(fns)} test đạt")
