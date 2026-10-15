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
    """Messages must be safe for logs and the SQLite outbox."""


class ApiSession:
    def __init__(self, base_url, email, password):
        base = urllib.parse.urlsplit(base_url or "")
        if (base.scheme not in ("https", "http") or not base.hostname or base.username or base.password
                or base.query or base.fragment or base.path not in ("", "/")
                or (base.scheme == "http" and base.hostname not in ("localhost", "127.0.0.1", "::1"))):
            raise AuthError("Login requires HTTPS or loopback HTTP, without URL credentials/path")
        if not email or not password:
            raise AuthError("Email and password are required")
        self.base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener(NoRedirect)
        self._refresh = None
        self._access = None
        self._expires = 0
        self._update(self._exchange("login", dict(email=email, password=password)), login=True)

    def _exchange(self, action, payload):
        request = urllib.request.Request(self.base_url + "/api/v1/auth/" + action,
                data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._opener.open(request, timeout=5) as response:
                return json.loads(response.read(65536))
        except (OSError, ValueError):
            raise AuthError("Authentication unavailable or rejected; sign in again") from None

    def _update(self, result, login=False):
        try:
            access, refresh, ttl = result["accessToken"], result["refreshToken"], result["expiresIn"]
            if (not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
                    or any(not 33 <= ord(c) <= 126 for c in access + refresh)
                    or isinstance(ttl, bool) or not isinstance(ttl, (float, int)) or not math.isfinite(ttl) or ttl <= 0):
                raise ValueError()
            if login:
                self.user_id = str(uuid.UUID(result["user"]["id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AuthError("Invalid authentication response; sign in again") from None
        self._access, self._refresh = access, refresh
        self._expires = time.monotonic() + ttl - min(30, ttl / 10)

    def token(self, rejected=None):
        with self._lock:
            if self._refresh is None:
                raise AuthError("Session unavailable; sign in again (outbox retained)")
            if time.monotonic() >= self._expires or (rejected is not None and rejected == self._access):
                refresh, self._refresh = self._refresh, None
                # ponytail: uncertain refresh outcomes require login; no replay of a single-use token.
                self._update(self._exchange("refresh", {"refreshToken": refresh}))
            return self._access

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
