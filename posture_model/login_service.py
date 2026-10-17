"""Đăng nhập / mở lại phiên / đăng xuất cho giao diện, không phụ thuộc Qt (dễ kiểm thử).

Lỗi trả về là câu tiếng Việt nói rõ chuyện gì xảy ra và cách xử lý (theo design system, mục 6 Lời văn).
Backend không phân biệt "sai mật khẩu" với "tổ chức tạm ngưng" ở login/refresh (cùng 401, xem team-sync mục 6),
nên chỉ báo "tổ chức tạm ngưng" khi máy chủ trả 403 / mã ORGANIZATION_*.
"""
import urllib.parse

from api_session import ApiSession, AuthError

MSG_INVALID_LOGIN = "Email hoặc mật khẩu không đúng. Kiểm tra lại rồi thử đăng nhập lần nữa."
MSG_INACTIVE = "Tổ chức của bạn đang tạm ngưng truy cập. Liên hệ quản lý tổ chức để được mở lại."
MSG_SERVER = "Máy chủ đang gặp sự cố. Thử lại sau ít phút."
MSG_NO_URL = "Chưa cấu hình địa chỉ máy chủ. Đặt api_base_url trong app_config.json hoặc chạy với --api-base-url."
MSG_BAD_URL = ("Địa chỉ máy chủ không hợp lệ (cần https://…, hoặc http://localhost cho máy thử). "
               "Sửa api_base_url trong app_config.json.")
MSG_EXPIRED = "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại."
MSG_LOST_INVALID = "Phiên đăng nhập đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại; dữ liệu chưa gửi vẫn được giữ trên máy."
MSG_LOST_NETWORK = ("Không làm mới được phiên đăng nhập vì mất kết nối. Hãy đăng nhập lại khi có mạng; "
                    "dữ liệu chưa gửi vẫn được giữ trên máy.")


def _host(base_url):
    return urllib.parse.urlsplit(base_url or "").netloc or (base_url or "")


def describe(error, base_url, context="login"):
    """AuthError -> câu thông báo tiếng Việt. context: login | resume | runtime."""
    kind = getattr(error, "kind", "rejected")
    if kind == "config":
        return MSG_NO_URL if not base_url else MSG_BAD_URL
    if kind == "inactive":
        return MSG_INACTIVE
    if kind == "unreachable":
        if context == "runtime":
            return MSG_LOST_NETWORK
        return f"Không kết nối được máy chủ ({_host(base_url)}). Kiểm tra mạng hoặc địa chỉ máy chủ rồi thử lại."
    if kind == "server":
        return MSG_SERVER
    if kind == "invalid":
        return {"login": MSG_INVALID_LOGIN, "resume": MSG_EXPIRED, "runtime": MSG_LOST_INVALID}[context]
    return MSG_INVALID_LOGIN if context == "login" else MSG_EXPIRED


def login(base_url, email, password, store=None, remember=False):
    """Đăng nhập. Thành công -> ApiSession. Ghi nhớ: lưu refresh token vào keyring và cập nhật mỗi lần token xoay vòng.
    Không ghi nhớ: xóa phiên cũ trong keyring (để lần mở sau không tự vào bằng tài khoản khác)."""
    if not base_url:
        raise AuthError("No API base URL", "config")
    if not email or not password:
        raise AuthError("Email and password are required", "invalid")
    on_tokens = store.update_refresh if (store and remember) else None
    auth = ApiSession(base_url, email.strip(), password, on_tokens=on_tokens)
    if store is not None:
        if remember:
            store.save(auth.base_url, email.strip(), auth.refresh_token)
        else:
            store.clear()
    return auth


def resume(base_url, store):
    """Mở lại phiên đã nhớ. Trả (ApiSession | None, thông báo | None, đã xóa phiên?).
    Không có phiên lưu cho địa chỉ này -> (None, None, False). Token bị từ chối -> xóa khỏi keyring.
    Lỗi mạng/máy chủ -> giữ token (chưa chắc hỏng), để người dùng thử lại."""
    saved = store.load() if store else None
    if not saved or not base_url or saved["baseUrl"].rstrip("/") != base_url.rstrip("/"):
        return None, None, False
    try:
        return ApiSession.resume(base_url, saved["refreshToken"], on_tokens=store.update_refresh), None, False
    except AuthError as e:
        if e.kind in ("invalid", "inactive"):
            store.clear()
            return None, describe(e, base_url, "resume"), True
        return None, describe(e, base_url, "resume"), False


def logout(auth, store=None):
    """Đăng xuất: thu hồi phiên trên máy chủ rồi xóa keyring. Luôn xóa keyring dù máy chủ không trả lời.
    Trả True nếu máy chủ đã thu hồi."""
    ok = False
    try:
        ok = auth.logout() if auth is not None else False
    finally:
        if store is not None:
            store.clear()
    return ok
