"""Memory-only login and serialized, single-use refresh for edge workers."""
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class AuthError(ValueError):
    """Messages must be safe for logs and the SQLite outbox.

    kind (để giao diện nói đúng chuyện gì xảy ra, không đổi message):
      invalid     máy chủ từ chối (sai email/mật khẩu hoặc refresh token hết hạn/đã dùng)  - HTTP 401
      inactive    tổ chức tạm ngưng / không được phép                                      - HTTP 403
      unreachable không kết nối được máy chủ (mạng, sai địa chỉ, quá thời gian)
      server      máy chủ lỗi hoặc trả dữ liệu không hợp lệ                                - HTTP 5xx / sai định dạng
      config      địa chỉ máy chủ (api_base_url) thiếu hoặc không hợp lệ
      rejected    mặc định / lỗi khác
    """

    def __init__(self, message="", kind="rejected"):
        super().__init__(message)
        self.kind = kind


def _http_kind(error):
    """HTTPError -> kind. 403 hoặc code ORGANIZATION_INACTIVE = tổ chức tạm ngưng; chỉ đọc trường `code` của body lỗi."""
    code = ""
    try:
        code = str(json.loads(error.read(4096)).get("code", ""))
    except Exception:
        pass
    if error.code == 403 or code.startswith("ORGANIZATION_"):
        return "inactive"
    if error.code == 401:
        return "invalid"
    return "server" if error.code >= 500 else "rejected"


class ApiSession:
    def __init__(self, base_url, email, password, on_tokens=None):
        self._init_common(base_url, on_tokens)
        if not email or not password:
            raise AuthError("Email and password are required")
        self.email = email
        self._update(self._exchange("login", dict(email=email, password=password)), login=True)

    def _init_common(self, base_url, on_tokens=None):
        base = urllib.parse.urlsplit(base_url or "")
        if (base.scheme not in ("https", "http") or not base.hostname or base.username or base.password
                or base.query or base.fragment or base.path not in ("", "/")
                or (base.scheme == "http" and base.hostname not in ("localhost", "127.0.0.1", "::1"))):
            raise AuthError("Login requires HTTPS or loopback HTTP, without URL credentials/path", "config")
        self.base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener(NoRedirect)
        self._refresh = None
        self._access = None
        self._expires = 0
        self.on_tokens = on_tokens          # gọi (refresh_token) mỗi lần máy chủ cấp cặp token mới (xoay vòng)
        self.lost_kind = None               # kind của lần làm mới thất bại cuối (None = phiên còn dùng được)
        self.user_id = self.email = self.name = self.role = self.org_id = None

    @classmethod
    def resume(cls, base_url, refresh_token, on_tokens=None):
        """Mở lại phiên từ refresh token đã lưu (keyring): làm mới rồi đọc /auth/me. Không cần mật khẩu."""
        self = cls.__new__(cls)
        self._init_common(base_url, on_tokens)
        if not isinstance(refresh_token, str) or not refresh_token:
            raise AuthError("Missing stored session", "invalid")
        self._update(self._exchange("refresh", {"refreshToken": refresh_token}))
        me = self._me()
        try:
            self.user_id = str(uuid.UUID(me["id"]))
            self.email, self.name = me.get("email"), me.get("name")
            self.role, self.org_id = me.get("role"), me.get("orgId")
        except (KeyError, TypeError, ValueError, AttributeError):
            self._refresh = None
            raise AuthError("Invalid authentication response; sign in again", "server") from None
        return self

    @property
    def lost(self):
        """Phiên không làm mới được nữa (hết hạn/bị thu hồi/lỗi làm mới): phải đăng nhập lại."""
        return self._refresh is None

    @property
    def refresh_token(self):
        return self._refresh

    def _exchange(self, action, payload, bearer=None):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        request = urllib.request.Request(self.base_url + "/api/v1/auth/" + action,
                data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=5) as response:
                raw = response.read(65536)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            kind = _http_kind(e)
            e.close()
            raise AuthError("Authentication unavailable or rejected; sign in again", kind) from None
        except ValueError:
            raise AuthError("Authentication unavailable or rejected; sign in again", "server") from None
        except OSError:
            raise AuthError("Authentication unavailable or rejected; sign in again", "unreachable") from None

    def _me(self):
        request = urllib.request.Request(self.base_url + "/api/v1/auth/me", headers={
            "Authorization": "Bearer " + self._access}, method="GET")
        try:
            with self._opener.open(request, timeout=5) as response:
                return json.loads(response.read(65536))
        except urllib.error.HTTPError as e:
            kind = _http_kind(e)
            e.close()
            self._refresh = None
            raise AuthError("Authentication unavailable or rejected; sign in again", kind) from None
        except (OSError, ValueError):
            self._refresh = None
            raise AuthError("Authentication unavailable or rejected; sign in again", "unreachable") from None

    def _update(self, result, login=False):
        try:
            access, refresh, ttl = result["accessToken"], result["refreshToken"], result["expiresIn"]
            if (not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
                    or any(not 33 <= ord(c) <= 126 for c in access + refresh)
                    or isinstance(ttl, bool) or not isinstance(ttl, (float, int)) or not math.isfinite(ttl) or ttl <= 0):
                raise ValueError()
            if login:
                user = result["user"]
                self.user_id = str(uuid.UUID(user["id"]))
                self.name, self.role, self.org_id = user.get("name"), user.get("role"), user.get("orgId")
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AuthError("Invalid authentication response; sign in again", "server") from None
        self._access, self._refresh = access, refresh
        self._expires = time.monotonic() + ttl - min(30, ttl / 10)
        self.lost_kind = None
        if self.on_tokens is not None:
            try:
                self.on_tokens(refresh)
            except Exception:               # lưu token lỗi không được làm hỏng phiên đang chạy
                pass

    def token(self, rejected=None):
        with self._lock:
            if self._refresh is None:
                raise AuthError("Session unavailable; sign in again (outbox retained)", self.lost_kind or "rejected")
            if time.monotonic() >= self._expires or (rejected is not None and rejected == self._access):
                refresh, self._refresh = self._refresh, None
                # ponytail: uncertain refresh outcomes require login; no replay of a single-use token.
                try:
                    self._update(self._exchange("refresh", {"refreshToken": refresh}))
                except AuthError as e:
                    self.lost_kind = e.kind
                    raise
            return self._access

    def logout(self):
        """Thu hồi phiên trên máy chủ (POST /auth/logout, luôn 204) rồi xóa token khỏi RAM. True nếu máy chủ đã nhận.
        Token truy cập hết hạn thì làm mới trước để lệnh đăng xuất được xác thực."""
        try:
            access = self.token()
        except AuthError:
            access = None
        with self._lock:
            refresh, self._refresh, self._access = self._refresh, None, None
            self.lost_kind = "invalid"
        if not (access and refresh):
            return False
        try:
            self._exchange("logout", {"refreshToken": refresh}, bearer=access)
            return True
        except AuthError:
            return False

    def credentials(self, base_url):
        if (base_url or "").rstrip("/") != self.base_url:
            raise AuthError("API address changed; sign in again")
        return self.base_url, self.token()

    def open(self, request, timeout=5):
        # Only explicitly allowed safe-to-replay operations use this helper.
        if (request.full_url, request.get_method()) not in (
                (self.base_url + "/api/v1/telemetry/batch", "POST"),
                (self.base_url + "/api/v1/auth/media-token", "POST"),
                (self.base_url + "/api/v1/config/me", "GET")):
            raise AuthError("Authenticated request outside session scope")
        token = self.token()
        request.add_header("Authorization", "Bearer " + token)
        try:
            return self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
            error.close()
        request.add_header("Authorization", "Bearer " + self.token(rejected=token))
        return self._opener.open(request, timeout=timeout)
