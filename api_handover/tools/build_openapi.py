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
            "version": "1.1.0",
            "description": (
                "Hợp đồng API v1.1 giữa Desktop App (edge) và backend microservice.\n\n"
                "- Thời gian: ISO-8601 UTC (`...Z`). Body: JSON UTF-8.\n"
                "- Chống trùng: cùng `eventId` / `metricId` chỉ lưu 1 lần nhưng VẪN trả trong `accepted`.\n"
                "- Kiểm tra từng mục: mục sai schema vào `rejected`, các mục khác vẫn nhận.\n"
                "- `userId` lấy từ JWT (`sub`), không tin trường `userId` trong payload.\n"
                "- Trả lời trong 5 giây (app hết chờ sau 5 giây).\n\n"
                "Realtime (không mô tả được bằng OpenAPI): Socket.IO v4 tại `/socket.io/` qua Gateway (polling và "
                "WebSocket). Client gửi JWT trong `auth: {token}` lúc kết nối; sai / hết hạn token thì server từ chối "
                "(`connect_error` với message `unauthorized`), client lấy token mới rồi kết nối lại. Client không tự "
                "join room: server tự đưa socket vào room `user:{sub}` (và `org:{orgId}` nếu là MANAGER). "
                "Server phát 2 sự kiện: `config` (JSON theo schema `Config`, mỗi khi cấu hình đổi – app nhận) và "
                "`status` (`{userId, deviceId, state: GOOD|BAD|AWAY|OFFLINE, alertType, ts}` – Dashboard nhận)."),
        },
        "servers": [{"url": "http://127.0.0.1:8080", "description": "mock_server.py / máy dev"}],
        "tags": [{"name": "telemetry"}, {"name": "auth"}, {"name": "config"}, {"name": "system"}],
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
                "responses": {"200": {"description": "Đăng nhập thành công", "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/LoginResponse"}}}},
                    "401": err("Sai email hoặc mật khẩu")}}},
            "/api/v1/auth/refresh": {"post": {
                "tags": ["auth"], "summary": "Lấy access token mới (app chạy cả ngày)", "security": [],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["refreshToken"],
                    "properties": {"refreshToken": {"type": "string"}}}}}},
                "responses": {"200": {"description": "Token mới", "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/TokenPair"}}}},
                    "401": err("Refresh token sai hoặc hết hạn")}}},
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
                        "description": "Chỉ trả các khoá khác mặc định; app gộp với mặc định của nó.",
                        "responses": {"200": {"description": "Cấu hình", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Config"}}}}, "401": err("Chưa đăng nhập")}},
                "put": {"tags": ["config"], "summary": "Lưu cấu hình (từ Web Dashboard)",
                        "description": "Lưu xong backend đẩy sự kiện Socket.IO `config` tới room `user:{sub}` "
                                       "(qua topic Kafka `config.updates`).",
                        "requestBody": {"required": True, "content": {"application/json": {"schema": {
                            "$ref": "#/components/schemas/Config"}}}},
                        "responses": {"200": {"description": "Đã lưu", "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Config"}}}},
                            "400": err("Giá trị không hợp lệ"), "401": err("Chưa đăng nhập")}}},
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
                    "email": {"type": "string", "format": "email"}, "password": {"type": "string"},
                    "deviceId": {"type": "string"}, "deviceName": {"type": "string"}}},
                "TokenPair": {"type": "object", "required": ["accessToken", "refreshToken", "expiresIn"],
                              "properties": {"accessToken": {"type": "string"}, "refreshToken": {"type": "string"},
                                             "expiresIn": {"type": "integer", "description": "giây"}}},
                "LoginResponse": {"allOf": [{"$ref": "#/components/schemas/TokenPair"}, {
                    "type": "object", "required": ["user"], "properties": {"user": {
                        "type": "object", "required": ["id", "role"], "properties": {
                            "id": {"type": "string"}, "name": {"type": "string"},
                            "orgId": {"type": ["string", "null"]},
                            "role": {"enum": ["USER", "ORG_ADMIN", "SYS_ADMIN"]}}}}}]},
                "Error": {"type": "object", "properties": {"error": {}}},
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
