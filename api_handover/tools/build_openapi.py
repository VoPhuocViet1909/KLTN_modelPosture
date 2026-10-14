"""
Sinh openapi.yaml từ các file schemas/*.json (nguồn chuẩn duy nhất).
Sửa schema thì chạy lại:  python tools/build_openapi.py
"""
import copy
import json
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS = os.path.join(ROOT, "schemas")


def load(name):
    with open(os.path.join(SCHEMAS, f"{name}.schema.json"), encoding="utf-8") as f:
        s = json.load(f)
    for k in ("$schema", "$id", "version"):
        s.pop(k, None)
    return s


def fix_refs(node):
    if isinstance(node, dict):
        if node.get("$ref") == "event.schema.json":
            node["$ref"] = "#/components/schemas/Event"
        elif node.get("$ref") == "metrics.schema.json":
            node["$ref"] = "#/components/schemas/Metrics"
        for v in node.values():
            fix_refs(v)
    elif isinstance(node, list):
        for v in node:
            fix_refs(v)
    return node


def err(desc):
    return {"description": desc, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}


AUTH_401 = ("Thiếu / sai / hết hạn token (`AUTH_TOKEN_MISSING`, `AUTH_TOKEN_INVALID`, `AUTH_TOKEN_EXPIRED` "
            "từ Gateway).")
FORBIDDEN = "`AUTH_FORBIDDEN`: role không đủ quyền hoặc vi phạm quy tắc phạm vi"
NOT_FOUND = "`USER_NOT_FOUND`: không có user này, hoặc user thuộc tổ chức khác (với ORG_ADMIN)"
VALIDATION = "`VALIDATION_FAILED` (chi tiết theo trường trong `errors`) hoặc `MALFORMED_REQUEST`"
SCOPE = ("Phạm vi: ORG_ADMIN chỉ thấy và sửa user cùng tổ chức, user tổ chức khác trả 404; ORG_ADMIN không được "
         "gán role SYS_ADMIN và không được động vào tài khoản SYS_ADMIN; SYS_ADMIN thao tác được mọi user.")
SELF = "Admin không được tự đổi role hay tự khóa chính mình (403)."
RAISE = ("Nâng role chỉ có hiệu lực sau khi user đăng nhập lại (token cũ vẫn mang role cũ); hạ role có hiệu lực "
         "ngay với các API quản lý tài khoản.")
HISTORY_RANGE = [
    {"name": "from", "in": "query", "required": False,
     "description": "ISO-8601 có offset. Mặc định `to` − 7 ngày", "schema": {"type": "string", "format": "date-time"}},
    {"name": "to", "in": "query", "required": False,
     "description": "ISO-8601 có offset, không gồm mốc này. Mặc định: bây giờ. Khoảng tối đa 92 ngày",
     "schema": {"type": "string", "format": "date-time"}}]
HISTORY_PAGE = [
    {"name": "page", "in": "query", "required": False, "description": "Trang, bắt đầu từ 0 (tối đa 10000)",
     "schema": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0}},
    {"name": "size", "in": "query", "required": False, "description": "Số mục mỗi trang",
     "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}]
ALERT_TYPE = {"name": "alertType", "in": "query", "required": False, "description": "Chỉ lấy một loại cảnh báo",
              "schema": {"type": "string", "examples": ["NECK_TRUNK"]}}
HISTORY_400 = ("`VALIDATION_FAILED`: `from`/`to` sai định dạng, khoảng không dương hoặc quá 92 ngày, `alertType`, "
               "`page` hoặc `size` sai; trường sai nằm trong `errors`")
ENDED_WITH_SESSION = ("Cảnh báo không có `ALERT_RESOLVED` (app tắt giữa chừng) kết thúc cùng phiên: `endedAt` là lúc "
                      "phiên kết thúc, `endReason` là `SESSION_END` hoặc `SESSION_TIMEOUT`.")
STATS_400 = "`VALIDATION_FAILED`: `from`/`to` sai định dạng, khoảng không dương hoặc quá 92 ngày; trường sai trong `errors`"
STATS_HOW = ("Tính từ metrics 60 giây: `meanScore` = trung bình `postureScore` có trọng số `presenceSec` (bỏ phút "
             "`postureScore` null; null nếu không có phút nào), `badMinutes` = Σ (1 − goodRatio) × presenceSec / 60, "
             "`presenceMinutes` = Σ presenceSec / 60, `alerts` = tổng `alertCount` theo loại. Lọc theo `windowStart` "
             "trong `[from, to)`.")
USER_ID = {"name": "id", "in": "path", "required": True, "description": "Id người dùng (UUID)",
           "schema": {"type": "string", "format": "uuid"}}


def main():
    event, metrics, batch, config = (load(n) for n in ("event", "metrics", "batch", "config"))
    batch = fix_refs(copy.deepcopy(batch))
    ex_event = {"eventId": "c287daa7-782b-4824-8bc0-bfbdb83c2d34", "eventType": "ALERT_RESOLVED", "userId": None,
                "deviceId": "dev_e5e61fb5d685", "sessionId": "s_6d0be9bf308a", "ts": "2026-10-03T16:11:38.617Z",
                "alertType": "NECK_TRUNK", "severity": "LOW", "level": 1, "startedAt": "2026-10-03T16:11:05.283Z",
                "endedAt": "2026-10-03T16:11:35.614Z", "durationSec": 30.3, "reason": "CORRECTED",
                "snapshot": {"pBad": 0.0, "neck": 8.88, "trunk": -2.59, "headPitch": 4.94, "rulaB": 0,
                             "tiltRel": None, "distanceCm": None},
                "modelVersion": "v3", "appVersion": "1.0.0",
                "config": {"alertSec": 5, "clearSec": 3, "repeatSec": 240}}
    ex_metric = {"metricId": "162a41cd-b6e4-588b-bf0d-23c7314276e5", "userId": None, "deviceId": "dev_e5e61fb5d685",
                 "sessionId": "s_6d0be9bf308a", "windowStart": "2026-10-03T16:11:00Z", "windowSec": 60,
                 "coveredSec": 60.0, "samples": 599, "presenceSec": 60.0, "goodRatio": 0.327, "pBadMean": 0.59,
                 "neckMean": 22.5, "neckMax": 35.09, "trunkMean": 3.35, "trunkMax": 16.39, "headPitchMean": 12.27,
                 "tiltRelMean": None, "tiltAbsMax": None, "shoulderBadRatio": None, "distanceMeanCm": None,
                 "distanceMinCm": None, "tooCloseRatio": None, "alertCount": {"NECK_TRUNK": 2},
                 "postureScore": 23, "modelVersion": "v3", "appVersion": "1.0.0"}
    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "Posture Monitor – API giữa Desktop App và Backend",
            "version": "1.5.0",
            "description": (
                "Thay đổi v1.5: thêm lịch sử cảnh báo (alert-service): `GET /alerts/me`, `GET /alerts/me/sessions`, "
                "`GET /alerts/org` (ORG_ADMIN), và thống kê cho Dashboard (analytics-service): "
                "`GET /stats/me/summary`, `/stats/me/timeseries`, `/stats/me/heatmap`, `/stats/org/summary` "
                "(ORG_ADMIN). Mốc thời gian trong query string phải mã hoá URL (`+07:00` -> `%2B07:00`). Phiên không có `SESSION_END` tự đóng sau 3 phút không có dữ liệu "
                "(`endReason` `TIMEOUT`) và mở lại nếu dữ liệu mới hơn đến muộn.\n\n"
                "Thay đổi v1.4: thêm `GET/PUT /config/org` cho ORG_ADMIN; `GET /config/me`, phản hồi PUT và sự kiện "
                "Socket.IO `config` trả cấu hình hiệu lực sau khi gộp tổ chức rồi cá nhân. Notification đã gửi "
                "sự kiện `status` từ telemetry.\n\n"
                "Thay đổi v1.3: `PUT /config/me` ghi rõ là thay toàn bộ cấu hình và các quy tắc kiểm tra (khoá lạ, `api_token`/`api_base_url` bị từ chối, `user_id` bị bỏ qua, kiểm chéo khoảng cách và nghiêng vai), 400 trả `VALIDATION_FAILED` theo trường; Socket.IO: kết nối không gửi token bị từ chối sau vài giây, server ngắt khi token hết hạn, sự kiện `config` là toàn bộ cấu hình; `status` chưa có ở backend.\n\n"
                "Thay đổi v1.2: thêm `GET /auth/me`, `POST /auth/logout`, các endpoint quản lý tài khoản `/users` và "
                "`GET /auth/.well-known/jwks.json`; body lỗi `Error` đổi thành `{code, message, traceId, errors}`; "
                "`login`/`refresh` thêm mã 400 và 500; thêm bảng mã lỗi; `MANAGER` -> `ORG_ADMIN`.\n\n"
                "Hợp đồng API v1.5 giữa Desktop App (edge), Web Dashboard và backend microservice.\n\n"
                "- Thời gian: ISO-8601 UTC (`...Z`). Body: JSON UTF-8.\n"
                "- Chống trùng: cùng `eventId` / `metricId` chỉ lưu 1 lần nhưng VẪN trả trong `accepted`.\n"
                "- Kiểm tra từng mục: mục sai schema vào `rejected`, các mục khác vẫn nhận.\n"
                "- `userId` lấy từ JWT (`sub`), không tin trường `userId` trong payload.\n"
                "- Trả lời trong 5 giây (app hết chờ sau 5 giây).\n\n"
                "Realtime (không mô tả được bằng OpenAPI): Socket.IO v4 tại `/socket.io/` qua Gateway (polling và WebSocket).\n"
                "- Xác thực: client gửi JWT trong `auth: {token}` lúc kết nối. Token thiếu, sai hoặc hết hạn thì server từ "
                "chối bằng `connect_error` với message đúng `unauthorized` (không nêu lý do). Kết nối không gửi `auth` bị "
                "từ chối sau tối đa vài giây (mặc định 5 giây) và trong lúc chờ không nhận sự kiện nào. Khi auth-service "
                "chưa sẵn sàng cũng nhận `unauthorized`: client thử lại sau.\n"
                "- Hết hạn: server tự ngắt kết nối đúng lúc token hết hạn (`exp`); client lấy token mới bằng `refresh` "
                "rồi TỰ kết nối lại (thư viện client không tự kết nối lại khi chính server ngắt).\n"
                "- Room: client không tự join. Server đưa socket vào `user:{sub}` (Desktop App và Dashboard của cùng "
                "user dùng chung) và thêm `org:{orgId}` nếu là ORG_ADMIN có tổ chức; mọi lệnh client gửi lên bị bỏ qua.\n"
                "- Sự kiện `config`: TOÀN BỘ cấu hình hiệu lực của user (JSON theo schema `Config`, giống `GET /config/me`, "
                "không phải phần thay đổi), gửi tới `user:{sub}` sau mỗi lần `PUT /config/me` hoặc `PUT /config/org` "
                "ảnh hưởng tới user, thường trong "
                "vài giây. Server không gửi lại bản cũ hơn bản đã gửi; sự kiện có thể trễ hoặc bị lỡ khi mất kết nối nên "
                "app vẫn gọi `GET /config/me` lúc khởi động.\n"
                "- Sự kiện `status` từ telemetry: `{userId, deviceId, state: "
                "GOOD|BAD|AWAY|OFFLINE, alertType, ts}` cho Dashboard.\n\n"
                "Body lỗi chung: `{code, message, traceId, errors[{field, message}]}`; `errors` rỗng khi lỗi không "
                "gắn với trường nào. Chỉ dùng `code` để rẽ nhánh, `message` chỉ để hiển thị. Mã lỗi:\n\n"
                "| `code` | HTTP | Ý nghĩa |\n| --- | --- | --- |\n"
                "| `AUTH_TOKEN_MISSING` | 401 | Gateway: không có `Authorization: Bearer` |\n"
                "| `AUTH_TOKEN_INVALID` | 401 | Gateway: token sai chữ ký, sai issuer hoặc sai định dạng |\n"
                "| `AUTH_TOKEN_EXPIRED` | 401 | Gateway: token hết hạn – dùng `refresh` rồi gửi lại |\n"
                "| `AUTH_IDENTITY_MISSING` | 401 | Dịch vụ không xác định được người gọi (không còn tồn tại hoặc bị khóa) |\n"
                "| `AUTH_INVALID_CREDENTIALS` | 401 | Sai email hoặc mật khẩu, hoặc tài khoản bị khóa (không phân biệt) |\n"
                "| `AUTH_INVALID_REFRESH_TOKEN` | 401 | Refresh token không có, hết hạn hoặc đã dùng / đã thu hồi |\n"
                "| `AUTH_FORBIDDEN` | 403 | Thiếu quyền hoặc vi phạm quy tắc phạm vi (không nói rõ lý do) |\n"
                "| `USER_NOT_FOUND` | 404 | Không có user này (kể cả user của tổ chức khác) |\n"
                "| `USER_EMAIL_TAKEN` | 409 | Email đã được dùng (không phân biệt hoa thường) |\n"
                "| `VALIDATION_FAILED` | 400 | Sai ràng buộc; chi tiết theo trường trong `errors` |\n"
                "| `MALFORMED_REQUEST` | 400 | Body không phải JSON hợp lệ |\n"
                "| `INTERNAL_ERROR` | 500 | Lỗi bất ngờ phía server |\n"
                "| `HTTP_<mã>` | 4xx | Lỗi khung chung, ví dụ `HTTP_405`, `HTTP_415` |\n\n"
                "Các endpoint khác (telemetry, config, alerts) có thể trả thêm mã riêng, mô tả ở từng endpoint. "
                "`503 AUTH_UNAVAILABLE` do Gateway trả khi tạm thời không lấy được khóa kiểm token."),
        },
        "servers": [{"url": "http://127.0.0.1:8080", "description": "mock_server.py / máy dev"}],
        "tags": [{"name": "telemetry"}, {"name": "auth"}, {"name": "users"}, {"name": "config"}, {"name": "alerts"}, {"name": "stats"}, {"name": "system"}],
        "paths": {
            "/api/v1/health": {"get": {
                "tags": ["system"], "summary": "Kiểm tra server sống", "security": [],
                "description": "App gọi mỗi 15 giây khi đang mất kết nối để biết lúc nào gửi bù.",
                "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {
                    "type": "object", "required": ["status"], "properties": {"status": {"const": "UP"}}}}}}}}},
            "/api/v1/auth/login": {"post": {
                "tags": ["auth"], "summary": "Đăng nhập trên Desktop App", "security": [],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/LoginRequest"}}}},
                "description": "Không cần token. Access token sống 15 phút (`expiresIn` = 900 giây); refresh token "
                               "dùng một lần. Tài khoản bị khóa nhận cùng lỗi với sai mật khẩu.",
                "responses": {"200": {"description": "Đăng nhập thành công", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/LoginResponse"}}}},
                    "400": err("`VALIDATION_FAILED` (email sai định dạng, thiếu trường, quá dài) hoặc "
                               "`MALFORMED_REQUEST`"),
                    "401": err("`AUTH_INVALID_CREDENTIALS`: sai email hoặc mật khẩu, hoặc tài khoản bị khóa"),
                    "500": err("`INTERNAL_ERROR`")}}},
            "/api/v1/auth/refresh": {"post": {
                "tags": ["auth"], "summary": "Lấy access token mới (app chạy cả ngày)", "security": [],
                "description": "Không cần token. Refresh token xoay vòng: token vừa gửi bị thu hồi, dùng lại sẽ "
                               "nhận 401. Khóa user hoặc đổi role cũng thu hồi mọi refresh token của user đó.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["refreshToken"],
                    "properties": {"refreshToken": {"type": "string", "maxLength": 512}}}}}},
                "responses": {"200": {"description": "Token mới", "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/TokenPair"}}}},
                    "400": err("`VALIDATION_FAILED` hoặc `MALFORMED_REQUEST`"),
                    "401": err("`AUTH_INVALID_REFRESH_TOKEN`: token sai, hết hạn, đã dùng hoặc đã bị thu hồi"),
                    "500": err("`INTERNAL_ERROR`")}}},
            "/api/v1/auth/.well-known/jwks.json": {"get": {
                "tags": ["auth"], "summary": "Khóa công khai để kiểm access token (JWK Set)", "security": [],
                "description": "Không cần token. Chỉ chứa khóa công khai RS256; Gateway dùng để kiểm chữ ký. "
                               "Cache được 5 phút.",
                "responses": {"200": {"description": "JWK Set", "content": {"application/json": {"schema": {
                    "type": "object", "required": ["keys"], "properties": {"keys": {
                        "type": "array", "items": {"type": "object"}}}}}}}}}},
            "/api/v1/auth/me": {"get": {
                "tags": ["auth"], "summary": "Thông tin người dùng đang đăng nhập",
                "description": "Quyền: `PROFILE_READ` (mọi role). Đọc từ cơ sở dữ liệu nên `role`, `orgId`, `enabled` "
                               "luôn mới nhất, dù token được cấp trước đó.",
                "responses": {"200": {"description": "Người gọi", "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/UserAccount"}}}},
                    "401": err(AUTH_401 + " Hoặc `AUTH_IDENTITY_MISSING` nếu user không còn hoặc bị khóa.")}}},
            "/api/v1/auth/logout": {"post": {
                "tags": ["auth"], "summary": "Đăng xuất: thu hồi một refresh token",
                "description": "Quyền: `SESSION_LOGOUT` (mọi role). Chỉ thu hồi nếu refresh token thuộc người gọi. "
                               "Luôn trả 204, kể cả token không tồn tại hoặc của người khác (không lộ thông tin). "
                               "Access token hiện tại vẫn dùng được đến khi hết hạn (15 phút); app nên xóa token cục bộ.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/LogoutRequest"}}}},
                "responses": {"204": {"description": "Đã xử lý"},
                              "400": err("`VALIDATION_FAILED` (thiếu `refreshToken`) hoặc `MALFORMED_REQUEST`"),
                              "401": err(AUTH_401)}}},
            "/api/v1/users": {
                "get": {"tags": ["users"], "summary": "Danh sách người dùng (có phân trang)",
                        "description": "Quyền: `USER_READ` (ORG_ADMIN, SYS_ADMIN). " + SCOPE +
                                       " ORG_ADMIN không thuộc tổ chức nào nhận 403. Sắp xếp theo thời điểm tạo, "
                                       "cũ trước.",
                        "parameters": [
                            {"name": "page", "in": "query", "required": False, "description": "Trang, bắt đầu từ 0",
                             "schema": {"type": "integer", "minimum": 0, "default": 0}},
                            {"name": "size", "in": "query", "required": False, "description": "Số mục mỗi trang",
                             "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}],
                        "responses": {"200": {"description": "Một trang user", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/UserPage"}}}},
                            "400": err("`VALIDATION_FAILED`: `page` < 0 hoặc `size` ngoài 1..100"),
                            "401": err(AUTH_401), "403": err(FORBIDDEN)}},
                "post": {"tags": ["users"], "summary": "Tạo người dùng",
                         "description": "Quyền: `USER_CREATE` (ORG_ADMIN, SYS_ADMIN). ORG_ADMIN luôn tạo trong tổ chức "
                                        "của mình (bỏ qua `orgId` trong body) và không được tạo SYS_ADMIN. "
                                        "SYS_ADMIN tự chọn `orgId` (có thể null). Không trả mật khẩu hay hash.",
                         "requestBody": {"required": True, "content": {"application/json": {"schema": {
                             "$ref": "#/components/schemas/CreateUserRequest"}}}},
                         "responses": {"201": {"description": "Đã tạo", "content": {"application/json": {
                             "schema": {"$ref": "#/components/schemas/UserAccount"}}}},
                             "400": err(VALIDATION), "401": err(AUTH_401), "403": err(FORBIDDEN),
                             "409": err("`USER_EMAIL_TAKEN`: email đã được dùng")}}},
            "/api/v1/users/{id}": {"get": {
                "tags": ["users"], "summary": "Chi tiết một người dùng",
                "description": "Quyền: `USER_READ` (ORG_ADMIN, SYS_ADMIN). " + SCOPE,
                "parameters": [USER_ID],
                "responses": {"200": {"description": "User", "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/UserAccount"}}}},
                    "401": err(AUTH_401), "403": err(FORBIDDEN), "404": err(NOT_FOUND)}}},
            "/api/v1/users/{id}/role": {"patch": {
                "tags": ["users"], "summary": "Đổi role người dùng",
                "description": "Quyền: `USER_ASSIGN_ROLE` (ORG_ADMIN, SYS_ADMIN). " + SCOPE + " " + SELF + " "
                               "Đổi sang role khác sẽ thu hồi mọi refresh token của user. " + RAISE,
                "parameters": [USER_ID],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/ChangeRoleRequest"}}}},
                "responses": {"200": {"description": "User sau khi đổi", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/UserAccount"}}}},
                    "400": err(VALIDATION), "401": err(AUTH_401), "403": err(FORBIDDEN),
                    "404": err(NOT_FOUND)}}},
            "/api/v1/users/{id}/status": {"patch": {
                "tags": ["users"], "summary": "Khóa / mở khóa người dùng",
                "description": "Quyền: `USER_UPDATE_STATUS` (ORG_ADMIN, SYS_ADMIN). " + SCOPE + " " + SELF + " "
                               "Khóa (`enabled=false`) thu hồi mọi refresh token của user; mở khóa không khôi phục "
                               "chúng. Access token đã cấp vẫn dùng được với các dịch vụ khác đến khi hết hạn "
                               "(15 phút); các API quản lý tài khoản kiểm lại cơ sở dữ liệu nên có hiệu lực ngay.",
                "parameters": [USER_ID],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/ChangeStatusRequest"}}}},
                "responses": {"200": {"description": "User sau khi đổi", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/UserAccount"}}}},
                    "400": err(VALIDATION), "401": err(AUTH_401), "403": err(FORBIDDEN),
                    "404": err(NOT_FOUND)}}},
            "/api/v1/telemetry/batch": {"post": {
                "tags": ["telemetry"], "summary": "Nhận một lô sự kiện + metrics từ Desktop App",
                "description": "App gửi mỗi 5 giây (sự kiện khẩn gửi ngay), tối đa 100 mục / lô. "
                               "Backend kiểm tra schema rồi đẩy vào Kafka, không xử lý nặng trong request.",
                "parameters": [{"name": "X-Device-Id", "in": "header", "required": False,
                                "schema": {"type": "string"}}],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Batch"},
                    "example": {"schemaVersion": "1.0", "deviceId": "dev_e5e61fb5d685",
                                "sentAt": "2026-10-03T16:11:40.120Z", "events": [ex_event], "metrics": [ex_metric]}}}},
                "responses": {
                    "200": {"description": "Đã nhận lô (kể cả khi có mục bị từ chối)", "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/BatchResult"}}}},
                    "400": err("Body sai cấu trúc chung (không phải JSON, thiếu deviceId...) – app sẽ thử lại"),
                    "401": err("Thiếu / sai / hết hạn JWT – app giữ dữ liệu, chờ đăng nhập lại"),
                    "413": err("Lô quá 500 sự kiện hoặc 500 metrics – app tự chia nhỏ"),
                    "429": err("Quá giới hạn tần suất – app thử lại với backoff"),
                    "503": err("Server quá tải / bảo trì – app thử lại với backoff")}}},
            "/api/v1/config/me": {
                "get": {"tags": ["config"], "summary": "Cấu hình của người dùng hiện tại",
                        "description": "Cấu hình hiệu lực của người gọi: khoá tổ chức, sau đó khoá cá nhân ghi đè. "
                                       "Chưa có cả hai thì trả `{}`; app vẫn gộp với mặc định của nó. "
                                       "Lần GET đăng ký user với orgId trong Config để nhận cập nhật tổ chức.",
                        "responses": {"200": {"description": "Cấu hình", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Config"}}}},
                            "400": err("VALIDATION_FAILED: tùy chỉnh cá nhân cũ xung đột khi chuyển tổ chức; PUT hợp lệ để sửa"),
                            "401": err("Chưa đăng nhập / token hết hạn")}},
                "put": {"tags": ["config"], "summary": "Lưu cấu hình (từ Web Dashboard)",
                        "description": (
                            "Body là TẤT CẢ các khoá người dùng muốn khác mặc định và THAY THẾ toàn bộ bản cũ: "
                            "khoá không gửi trở về cấu hình tổ chức hoặc mặc định app, `{}` xoá hết tuỳ chỉnh "
                            "cá nhân. Trả 200 với cấu hình hiệu lực.\n\n"
                            "Kiểm tra (sai thì 400 `VALIDATION_FAILED` với `errors[{field, message}]`, không trả lại "
                            "giá trị bị từ chối, không lưu gì):\n"
                            "1. Kiểu và min/max theo schema `Config` (`null` chỉ ở khoá cho phép).\n"
                            "2. `api_token`, `api_base_url` là cấu hình riêng trên máy: gửi lên bị từ chối.\n"
                            "3. `user_id` bị bỏ qua (không lưu, không báo lỗi).\n"
                            "4. Khoá không có trong schema `Config` bị từ chối.\n"
                            "5. Kiểm tra trên cấu hình hiệu lực sau khi gộp tổ chức và cá nhân: "
                            "`distance_off_cm >= distance_on_cm`; `shoulder_tilt_off <= shoulder_tilt_on` "
                            "(khi cả hai khác null). Với khoảng cách, khóa vắng mặt dùng mặc định app 50/55 cm "
                            "để kiểm tra. Nếu xung đột, không lưu và không phát sự kiện.\n\n"
                            "Body không phải JSON: 400 `MALFORMED_REQUEST`. Lưu xong backend đẩy sự kiện Socket.IO "
                            "`config` (toàn bộ cấu hình hiệu lực) tới room `user:{sub}`."),
                        "requestBody": {"required": True, "content": {"application/json": {"schema": {
                            "$ref": "#/components/schemas/Config"}}}},
                        "responses": {"200": {"description": "Đã lưu", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Config"}}}},
                            "400": err("`VALIDATION_FAILED` (chi tiết theo trường) hoặc `MALFORMED_REQUEST`"),
                            "401": err("Chưa đăng nhập / token hết hạn")}}},
            "/api/v1/config/org": {
                "get": {"tags": ["config"], "summary": "Cấu hình lưu cho tổ chức của người gọi",
                        "description": "Chỉ ORG_ADMIN có orgId. Trả các khoá tổ chức đã lưu, hoặc `{}`.",
                        "responses": {"200": {"description": "Các khoá tổ chức đã lưu", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Config"}}}},
                            "401": err("Chưa đăng nhập / token hết hạn"), "403": err(FORBIDDEN)}},
                "put": {"tags": ["config"], "summary": "Thay toàn bộ cấu hình tổ chức",
                        "description": "Chỉ ORG_ADMIN có orgId. Body thay toàn bộ các khoá tổ chức; `{}` xoá hết. "
                                       "Kiểm tra như PUT /config/me, cấm thêm các khoá hiệu chỉnh riêng từng máy: "
                                       "calib_distance_cm, camera_focal_px, camera_hfov_deg, calib_sec. "
                                       "Nếu cấu hình hiệu lực của bất kỳ thành viên đã biết nào có cặp ngưỡng sai, "
                                       "từ chối toàn bộ giao dịch với 400 VALIDATION_FAILED. "
                                       "Trả các khoá tổ chức đã lưu. Sau commit, Config phát một event cấu hình "
                                       "hiệu lực cho mỗi thành viên đã gọi Config; user khác nhận giá trị mới "
                                       "khi gọi GET /config/me.",
                        "requestBody": {"required": True, "content": {"application/json": {"schema": {
                            "$ref": "#/components/schemas/Config"}}}},
                        "responses": {"200": {"description": "Các khoá tổ chức đã lưu", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Config"}}}},
                            "400": err(VALIDATION), "401": err("Chưa đăng nhập / token hết hạn"),
                            "403": err(FORBIDDEN)}},
            },
            "/api/v1/alerts/me": {"get": {
                "tags": ["alerts"], "summary": "Lịch sử cảnh báo của người gọi",
                "description": "Mọi role. Các lần cảnh báo (mỗi cặp ALERT_STARTED…ALERT_RESOLVED là một mục) "
                               "bắt đầu trong khoảng `[from, to)`, mới nhất trước. " + ENDED_WITH_SESSION,
                "parameters": HISTORY_RANGE + [ALERT_TYPE] + HISTORY_PAGE,
                "responses": {"200": {"description": "Một trang cảnh báo", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertPage"}}}},
                    "400": err(HISTORY_400), "401": err(AUTH_401)}}},
            "/api/v1/alerts/me/sessions": {"get": {
                "tags": ["alerts"], "summary": "Các phiên làm việc của người gọi",
                "description": "Mọi role. Phiên giao với khoảng `[from, to)`, mới nhất trước, kèm số cảnh báo. "
                               "Phiên đóng bằng `SESSION_END` từ app, hoặc `TIMEOUT` khi 3 phút không có dữ liệu "
                               "(app bị tắt, máy ngủ). Phiên `TIMEOUT` mở lại nếu sau đó đến dữ liệu mới hơn "
                               "(app gửi bù khi có mạng lại).",
                "parameters": HISTORY_RANGE + HISTORY_PAGE,
                "responses": {"200": {"description": "Một trang phiên", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertSessionPage"}}}},
                    "400": err(HISTORY_400), "401": err(AUTH_401)}}},
            "/api/v1/alerts/org": {"get": {
                "tags": ["alerts"], "summary": "Lịch sử cảnh báo của cả tổ chức",
                "description": "Chỉ ORG_ADMIN có orgId. Như `GET /alerts/me` nhưng gồm mọi thành viên; tổ chức "
                               "của một phiên lấy theo `orgId` trong dữ liệu app gửi. " + ENDED_WITH_SESSION,
                "parameters": HISTORY_RANGE + [ALERT_TYPE] + HISTORY_PAGE,
                "responses": {"200": {"description": "Một trang cảnh báo", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/AlertPage"}}}},
                    "400": err(HISTORY_400), "401": err(AUTH_401), "403": err(FORBIDDEN)}}},
            "/api/v1/stats/me/summary": {"get": {
                "tags": ["stats"], "summary": "Tổng hợp tư thế của người gọi trong một khoảng",
                "description": "Mọi role. " + STATS_HOW,
                "parameters": HISTORY_RANGE,
                "responses": {"200": {"description": "Tổng hợp", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/StatsSummary"}}}},
                    "400": err(STATS_400), "401": err(AUTH_401)}}},
            "/api/v1/stats/me/timeseries": {"get": {
                "tags": ["stats"], "summary": "Chuỗi thời gian theo giờ hoặc theo ngày",
                "description": "Mọi role. Mỗi phần tử là một khung có dữ liệu (khung không có metrics thì không có "
                               "phần tử), sắp theo `start` tăng dần. `hour`: khung giờ UTC. `day`: ngày theo giờ "
                               "Việt Nam (UTC+7), `start` là 00:00 giờ Việt Nam viết theo UTC, ví dụ "
                               "`2026-10-13T17:00:00Z` là ngày 14/10. " + STATS_HOW,
                "parameters": HISTORY_RANGE + [
                    {"name": "bucket", "in": "query", "required": False, "description": "Độ rộng khung",
                     "schema": {"type": "string", "enum": ["hour", "day"], "default": "day"}}],
                "responses": {"200": {"description": "Các khung có dữ liệu", "content": {"application/json": {
                    "schema": {"type": "array", "items": {"$ref": "#/components/schemas/StatsBucket"}}}}},
                    "400": err(STATS_400 + "; `bucket` khác `hour`/`day`"), "401": err(AUTH_401)}}},
            "/api/v1/stats/me/heatmap": {"get": {
                "tags": ["stats"], "summary": "Heatmap điểm tư thế theo thứ và giờ",
                "description": "Mọi role. Luôn đủ 168 ô (7 thứ × 24 giờ, giờ Việt Nam), thứ tự thứ 1..7 rồi giờ "
                               "0..23; ô không có dữ liệu có `meanScore` null. Lấy `weeks` tuần tính tới hiện tại.",
                "parameters": [{"name": "weeks", "in": "query", "required": False, "description": "Số tuần",
                                "schema": {"type": "integer", "minimum": 1, "maximum": 12, "default": 4}}],
                "responses": {"200": {"description": "168 ô", "content": {"application/json": {"schema": {
                    "type": "array", "minItems": 168, "maxItems": 168,
                    "items": {"$ref": "#/components/schemas/HeatmapCell"}}}}},
                    "400": err("`VALIDATION_FAILED`: `weeks` không phải số nguyên 1..12"), "401": err(AUTH_401)}}},
            "/api/v1/stats/org/summary": {"get": {
                "tags": ["stats"], "summary": "Tổng hợp tư thế của cả tổ chức",
                "description": "Chỉ ORG_ADMIN có orgId. Như `/stats/me/summary` nhưng gộp mọi thành viên. " + STATS_HOW,
                "parameters": HISTORY_RANGE,
                "responses": {"200": {"description": "Tổng hợp", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/StatsSummary"}}}},
                    "400": err(STATS_400), "401": err(AUTH_401), "403": err(FORBIDDEN)}}},
        },
        "components": {
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
            "schemas": {
                "Event": event, "Metrics": metrics, "Batch": batch, "Config": config,
                "BatchResult": {"type": "object", "required": ["accepted", "rejected"], "properties": {
                    "accepted": {"type": "array", "items": {"type": "string"},
                                 "description": "id đã lưu, kể cả id trùng đã lưu trước đó"},
                    "rejected": {"type": "array", "items": {"type": "object", "required": ["id", "reason"],
                                 "properties": {"id": {"type": ["string", "null"]}, "reason": {"type": "string"}}},
                                 "description": "id sai schema – app KHÔNG gửi lại"},
                    "duplicates": {"type": "integer", "minimum": 0}}},
                "LoginRequest": {"type": "object", "required": ["email", "password"], "properties": {
                    "email": {"type": "string", "format": "email", "maxLength": 254},
                    "password": {"type": "string", "maxLength": 200},
                    "deviceId": {"type": "string", "maxLength": 128},
                    "deviceName": {"type": "string", "maxLength": 200}}},
                "TokenPair": {"type": "object", "required": ["accessToken", "refreshToken", "expiresIn"],
                              "properties": {"accessToken": {"type": "string"}, "refreshToken": {"type": "string"},
                                             "expiresIn": {"type": "integer", "description": "giây"}}},
                "LoginResponse": {"allOf": [{"$ref": "#/components/schemas/TokenPair"}, {
                    "type": "object", "required": ["user"], "properties": {"user": {
                        "type": "object", "required": ["id", "role"], "properties": {
                            "id": {"type": "string"}, "name": {"type": "string"},
                            "orgId": {"type": ["string", "null"]},
                            "role": {"enum": ["USER", "ORG_ADMIN", "SYS_ADMIN"]}}}}}]},
                "Error": {"type": "object", "required": ["code", "message", "errors"], "properties": {
                    "code": {"type": "string", "description": "mã ổn định cho máy xử lý, xem bảng mã lỗi ở đầu tài liệu"},
                    "message": {"type": "string", "description": "câu hiển thị, không dùng để rẽ nhánh logic"},
                    "traceId": {"type": ["string", "null"], "description": "mã vết của request, dùng để tra log"},
                    "errors": {"type": "array", "items": {"$ref": "#/components/schemas/FieldProblem"},
                               "description": "lỗi theo từng trường; rỗng nếu lỗi không gắn với trường"}}},
                "FieldProblem": {"type": "object", "required": ["field", "message"], "properties": {
                    "field": {"type": "string", "description": "tên trường sai"},
                    "message": {"type": "string", "description": "lý do; không bao giờ chứa giá trị đã gửi"}}},
                "UserAccount": {"type": "object", "required": ["id", "email", "role", "enabled"], "properties": {
                    "id": {"type": "string", "description": "UUID; bằng `sub` của access token"},
                    "email": {"type": "string"},
                    "name": {"type": ["string", "null"]},
                    "role": {"enum": ["USER", "ORG_ADMIN", "SYS_ADMIN"]},
                    "orgId": {"type": ["string", "null"], "description": "null nếu user không thuộc tổ chức nào"},
                    "enabled": {"type": "boolean", "description": "false = tài khoản bị khóa"}}},
                "UserPage": {"type": "object", "required": ["items", "page", "size", "total"], "properties": {
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/UserAccount"}},
                    "page": {"type": "integer", "description": "trang, bắt đầu từ 0"},
                    "size": {"type": "integer", "description": "kích thước trang yêu cầu (tối đa 100)"},
                    "total": {"type": "integer", "description": "tổng số user người gọi được thấy"}}},
                "CreateUserRequest": {"type": "object", "required": ["email", "password", "role"], "properties": {
                    "email": {"type": "string", "format": "email", "maxLength": 254,
                              "description": "duy nhất, không phân biệt hoa thường"},
                    "password": {"type": "string", "minLength": 8, "maxLength": 200,
                                 "description": "8 ký tự – tối đa 72 byte UTF-8 (giới hạn của BCrypt); "
                                                "quá 72 byte trả 400"},
                    "name": {"type": "string", "maxLength": 200},
                    "role": {"enum": ["USER", "ORG_ADMIN", "SYS_ADMIN"],
                             "description": "ORG_ADMIN không được gán SYS_ADMIN"},
                    "orgId": {"type": ["string", "null"], "format": "uuid",
                              "description": "bị bỏ qua nếu người gọi là ORG_ADMIN (luôn là tổ chức của họ)"}}},
                "ChangeRoleRequest": {"type": "object", "required": ["role"], "properties": {
                    "role": {"enum": ["USER", "ORG_ADMIN", "SYS_ADMIN"]}}},
                "ChangeStatusRequest": {"type": "object", "required": ["enabled"], "properties": {
                    "enabled": {"type": "boolean", "description": "false = khóa và thu hồi mọi refresh token"}}},
                "AlertItem": {"type": "object", "required": [
                    "userId", "deviceId", "sessionId", "alertType", "startedAt", "repeatCount", "open"], "properties": {
                    "userId": {"type": "string", "format": "uuid"},
                    "deviceId": {"type": "string"},
                    "sessionId": {"type": "string"},
                    "alertType": {"type": "string", "description": "như `alertType` của sự kiện, ví dụ `NECK_TRUNK`"},
                    "severity": {"type": ["string", "null"], "enum": ["LOW", "MEDIUM", "HIGH", None],
                                 "description": "mức mới nhất đã nhận"},
                    "startedAt": {"type": "string", "format": "date-time"},
                    "endedAt": {"type": ["string", "null"], "format": "date-time",
                                "description": "null khi còn đang mở"},
                    "durationSec": {"type": ["integer", "null"], "description": "endedAt − startedAt, giây"},
                    "endReason": {"type": ["string", "null"], "description": (
                        "`reason` của ALERT_RESOLVED (`CORRECTED`, `AWAY`, `RECALIBRATE`, `SESSION_END`, `RESET`), "
                        "hoặc `SESSION_END` / `SESSION_TIMEOUT` khi cảnh báo kết thúc cùng phiên; null khi còn mở")},
                    "repeatCount": {"type": "integer", "minimum": 0, "description": "số lần ALERT_REPEATED"},
                    "open": {"type": "boolean", "description": "true khi cả cảnh báo và phiên còn mở"}}},
                "AlertPage": {"type": "object", "required": ["items", "page", "size", "total"], "properties": {
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/AlertItem"}},
                    "page": {"type": "integer"}, "size": {"type": "integer"},
                    "total": {"type": "integer", "description": "tổng số mục khớp bộ lọc"}}},
                "AlertSession": {"type": "object", "required": [
                    "deviceId", "sessionId", "lastSeenAt", "open", "alertCount"], "properties": {
                    "deviceId": {"type": "string"},
                    "sessionId": {"type": "string"},
                    "startedAt": {"type": ["string", "null"], "format": "date-time",
                                  "description": "null khi chưa nhận SESSION_START"},
                    "endedAt": {"type": ["string", "null"], "format": "date-time"},
                    "endReason": {"type": ["string", "null"], "enum": ["SESSION_END", "TIMEOUT", None]},
                    "lastSeenAt": {"type": "string", "format": "date-time",
                                   "description": "thời điểm (theo `ts` của app) của dữ liệu mới nhất"},
                    "open": {"type": "boolean"},
                    "alertCount": {"type": "integer", "minimum": 0}}},
                "AlertSessionPage": {"type": "object", "required": ["items", "page", "size", "total"], "properties": {
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/AlertSession"}},
                    "page": {"type": "integer"}, "size": {"type": "integer"},
                    "total": {"type": "integer"}}},
                "StatsSummary": {"type": "object", "required": [
                    "meanScore", "badMinutes", "presenceMinutes", "alerts"], "properties": {
                    "meanScore": {"type": ["number", "null"], "minimum": 0, "maximum": 100,
                                  "description": "điểm tư thế trung bình 0–100; null khi không có dữ liệu"},
                    "badMinutes": {"type": "number", "minimum": 0, "description": "số phút ngồi sai"},
                    "presenceMinutes": {"type": "number", "minimum": 0, "description": "số phút có người"},
                    "alerts": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0},
                               "description": "số lần cảnh báo theo loại, ví dụ `{\"NECK_TRUNK\": 3}`"}}},
                "StatsBucket": {"allOf": [{"type": "object", "required": ["start"], "properties": {
                    "start": {"type": "string", "format": "date-time", "description": "đầu khung (UTC)"}}},
                    {"$ref": "#/components/schemas/StatsSummary"}]},
                "HeatmapCell": {"type": "object", "required": ["weekday", "hour", "meanScore"], "properties": {
                    "weekday": {"type": "integer", "minimum": 1, "maximum": 7, "description": "1 = thứ Hai … 7 = Chủ nhật"},
                    "hour": {"type": "integer", "minimum": 0, "maximum": 23, "description": "giờ Việt Nam"},
                    "meanScore": {"type": ["number", "null"], "minimum": 0, "maximum": 100}}},
                "LogoutRequest": {"type": "object", "required": ["refreshToken"], "properties": {
                    "refreshToken": {"type": "string", "maxLength": 512}}},
            },
        },
        "security": [{"bearerAuth": []}],
    }
    out = os.path.join(ROOT, "openapi.yaml")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# SINH TỰ ĐỘNG từ schemas/*.json bằng tools/build_openapi.py – đừng sửa tay\n")
        yaml.safe_dump(spec, f, allow_unicode=True, sort_keys=False, width=110)
    print("->", out)


if __name__ == "__main__":
    main()
