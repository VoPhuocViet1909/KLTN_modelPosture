# Gói bàn giao API v1.5 – Desktop App → Backend

Thư mục này là **toàn bộ những gì backend cần** để làm phần nhận dữ liệu, không cần webcam hay chạy Desktop App.
Kế hoạch chi tiết, lộ trình và các câu hỏi cần chốt nằm trong tài liệu "Kế hoạch bàn giao API".

Chỉ cần Python 3.9+ (thư viện chuẩn) để chạy các script; `tools/build_openapi.py` cần thêm `pyyaml`.

## Có gì trong thư mục

| File | Dùng để |
| --- | --- |
| `openapi.yaml` | Đặc tả OpenAPI 3.1 v1.5: auth, quản lý tài khoản, telemetry, config cá nhân/tổ chức, lịch sử cảnh báo, thống kê Dashboard, health. Mở bằng https://editor.swagger.io hoặc import vào Postman; sinh DTO / controller bằng openapi-generator |
| `schemas/*.json` | **Nguồn chuẩn duy nhất** của dữ liệu: `event`, `metrics`, `batch`, `config` (JSON Schema 2020-12). Backend kiểm tra dữ liệu bằng chính các file này |
| `mock_server.py` + `schema.py` + `history.py` | Server giả chạy đúng hợp đồng – để đối chiếu hành vi; có cả `/alerts/*` và `/stats/*` tính từ dữ liệu đã nhận (Dashboard dùng thử được khi chưa có backend). `python test_history.py`: 4 test |
| `contract_test.py` | 47 bài kiểm tra hợp đồng, chạy vào bất kỳ server nào. **Mốc M2 = đạt 100%** |
| `replay.py` | `seed`: sinh lịch sử nhiều ngày để làm Dashboard · `load`: kiểm thử tải N máy |
| `payloads.py` | Bộ sinh dữ liệu hợp lệ, dùng chung cho 2 script trên |
| `sample_data/p01_*.jsonl` | Dữ liệu THẬT từ app chạy trên video người tham gia P01 (9 sự kiện, 4 metrics) |
| `tools/build_openapi.py` | Sinh lại `openapi.yaml` khi sửa schema |

## Bắt đầu trong 5 phút

```bash
# 1. chạy server giả (bắt buộc đăng nhập như server thật)
python mock_server.py --require-login            # http://127.0.0.1:8080, tài khoản demo@kltn.local / 123456

# 2. chạy bộ kiểm tra hợp đồng vào server giả -> phải 47/47
python contract_test.py --base http://127.0.0.1:8080 --email demo@kltn.local --password 123456

# 3. khi server Spring của bạn chạy: đổi --base, sửa tới khi đạt 100%
python contract_test.py --base http://localhost:8080 --email <user> --password <pass> --report report.json
python contract_test.py --base ... --token <JWT> --only health batch errors   # chưa làm xong auth / config
```

## Sinh dữ liệu để làm Dashboard

```bash
python replay.py seed --base http://localhost:8080 --email <user> --password <pass> --devices 5 --days 14
```

Mỗi máy, mỗi ngày làm việc (08:30–17:30, nghỉ trưa) có khoảng 480 metrics, 20–30 cặp cảnh báo, nhắc nghỉ mắt,
vắng mặt giờ trưa, đầu / cuối phiên. Điểm tư thế giảm dần về chiều (8h ≈ 92 → 16h ≈ 63), nên heatmap và biểu đồ
có hình dạng thật. Cùng `--seed` thì sinh ra cùng dữ liệu.

## Kiểm thử tải (chương đánh giá)

```bash
python replay.py load --base ... --token <JWT> --devices 100  --duration 120 --interval 5 --out load_100.csv
python replay.py load --base ... --token <JWT> --devices 500  --duration 120 --interval 5 --out load_500.csv
python replay.py load --base ... --token <JWT> --devices 1000 --duration 120 --interval 5 --workers 128 --out load_1000.csv
```

In ra request/s, mục/s, độ trễ p50 / p95 / p99, lỗi theo mã; file CSV ghi từng request để vẽ biểu đồ.
`--interval 60` là nhịp thật của app (1 lô / phút / máy); `--interval 5` dồn tải gấp 12 lần.
Kết hợp Prometheus + Grafana phía server để có thêm consumer lag của Kafka.

## Quy tắc bắt buộc phía backend (tóm tắt – chi tiết trong openapi.yaml)

1. **Chống trùng theo id**: cùng `eventId` / `metricId` chỉ lưu 1 lần nhưng **vẫn trả trong `accepted`**
   (app gửi lại khi mất mạng; nếu không trả `accepted` app sẽ gửi mãi).
2. **Kiểm tra từng mục**: mục sai schema vào `rejected` kèm `reason`, các mục khác vẫn nhận, vẫn trả 200.
3. **`userId` lấy từ JWT** (`sub`), không tin trường `userId` trong payload (có thể null).
4. **Không giả định thứ tự**: dữ liệu gửi bù đến muộn – sắp theo `ts` / `windowStart`.
5. **Trả lời < 5 giây**: kiểm tra schema rồi đẩy Kafka, không xử lý nặng trong request.
6. Mã lỗi: 400 body sai cấu trúc · 401 JWT · 413 quá 500 mục · 429 rate limit · 503 quá tải.
7. Mỗi `ALERT_STARTED` có đúng một `ALERT_RESOLVED` cùng `sessionId` + `alertType` + `startedAt` → ghép cặp theo 3 trường này.
8. App tắt đột ngột thì không có `SESSION_END`: coi phiên đã kết thúc khi quá 3 phút không có metrics.

Định tuyến Kafka gợi ý (key = `deviceId`):

| Topic | Nội dung |
| --- | --- |
| `posture.alerts` | `ALERT_STARTED`, `ALERT_REPEATED`, `ALERT_RESOLVED`, `REMINDER` |
| `posture.metrics` | metrics 60 giây |
| `session.events` | `SESSION_START`, `SESSION_END`, `CALIBRATED`, `USER_AWAY`, `USER_BACK`, `CONFIG_APPLIED` |

## Kiểm tra schema trong Spring Boot

```xml
<dependency>
  <groupId>com.networknt</groupId>
  <artifactId>json-schema-validator</artifactId>
  <version><!-- bản 1.5 trở lên --></version>
</dependency>
```

```java
JsonSchemaFactory f = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);
JsonSchema eventSchema = f.getSchema(getClass().getResourceAsStream("/schemas/event.schema.json"));
Set<ValidationMessage> errors = eventSchema.validate(eventJsonNode);   // rỗng = hợp lệ
```

Chép thư mục `schemas/` vào `src/main/resources/schemas/` của Ingestion Service và Config Service.

## Thay đổi hợp đồng

Hợp đồng do phía Desktop App giữ. Muốn đổi / thêm trường: sửa `schemas/*.json` → chạy
`python tools/build_openapi.py` → chạy lại `contract_test.py` vào mock → báo bên kia. Thay đổi làm hỏng
tương thích (đổi tên, xoá trường, thêm trường bắt buộc) thì tăng `schemaVersion`.

## Realtime: Socket.IO (từ v1.1, thay STOMP `/ws`)

Chưa có trong mock.

| Mục | Quy ước |
| --- | --- |
| Địa chỉ | `http://<gateway>/socket.io/`, Socket.IO v4 (Engine.IO 4), polling và WebSocket |
| Xác thực | JWT trong `auth: {token}` lúc kết nối. Thiếu / sai / hết hạn → `connect_error`, message đúng `unauthorized` (không nêu lý do). Không gửi `auth` → bị từ chối sau tối đa vài giây (mặc định 5 giây), trong lúc chờ không nhận gì. Auth-service chưa sẵn sàng cũng là `unauthorized`: thử lại sau |
| Hết hạn token | Server tự ngắt kết nối đúng lúc `exp`. Client gọi `refresh` rồi **tự** kết nối lại (thư viện client không tự kết nối lại khi chính server ngắt) |
| Room | Server tự join: `user:{sub}` (app và Dashboard của cùng user dùng chung); ORG_ADMIN có tổ chức thêm `org:{orgId}`. Client không gửi lệnh join (gửi cũng bị bỏ qua) |
| Sự kiện `config` | Server → app và Dashboard, **toàn bộ** cấu hình đã lưu (JSON theo `config.schema.json`, giống `GET /config/me`, không phải phần thay đổi), sau mỗi `PUT /config/me` thành công, thường trong vài giây. Không bao giờ gửi bản cũ hơn bản đã gửi; có thể trễ hoặc lỡ khi mất kết nối nên app vẫn `GET /config/me` lúc khởi động |
| Sự kiện `status` | **Chưa có ở backend.** Dự kiến: server → Dashboard, `{userId, deviceId, state: GOOD \| BAD \| AWAY \| OFFLINE, alertType, ts}`; mô tả chi tiết khi làm |

Client Python (app): `python-socketio`, `sio.connect(base, auth={"token": jwt}, socketio_path="socket.io")`.
Client React: `io(base, { auth: { token } })`.

Phía backend (notification-service, netty-socketio 2.0.14) đã kiểm bằng client Socket.IO v4 thật: server đọc được
`auth` của gói CONNECT và trả đúng `connect_error` `unauthorized`.

v1.0 → v1.1: chỉ đổi phần realtime (STOMP `/ws` → Socket.IO). REST và `schemas/*.json` giữ nguyên.

## v1.1 → v1.2: endpoint auth và quản lý tài khoản

`openapi.yaml` thêm (nguồn đối chiếu: tài liệu OpenAPI do auth-service thật sinh ra):

| Endpoint | Quyền | Dùng cho |
| --- | --- | --- |
| `GET /api/v1/auth/me` | mọi role | thông tin người đang đăng nhập |
| `POST /api/v1/auth/logout` | mọi role | thu hồi một refresh token (luôn 204) |
| `GET /api/v1/auth/.well-known/jwks.json` | không cần token | khóa công khai kiểm token (Gateway dùng) |
| `GET`, `POST /api/v1/users` | ORG_ADMIN, SYS_ADMIN | danh sách (phân trang, `size` tối đa 100) và tạo user |
| `GET /api/v1/users/{id}` | ORG_ADMIN, SYS_ADMIN | chi tiết user |
| `PATCH /api/v1/users/{id}/role` | ORG_ADMIN, SYS_ADMIN | đổi role |
| `PATCH /api/v1/users/{id}/status` | ORG_ADMIN, SYS_ADMIN | khóa / mở khóa |

Quy tắc phạm vi: ORG_ADMIN chỉ thấy và sửa user cùng tổ chức (tổ chức khác trả 404), không gán được SYS_ADMIN và
không động vào tài khoản SYS_ADMIN; admin không tự đổi role hay tự khóa mình; khóa user hoặc đổi role thu hồi mọi
refresh token của user; nâng role chỉ có hiệu lực sau khi user đăng nhập lại.

Các chỗ hợp đồng cũ đã sửa cho khớp backend:

- Body lỗi `Error` từ `{error}` thành `{code, message, traceId, errors[{field, message}]}`; thêm bảng mã lỗi.
- `login` và `refresh` thêm 400 (`VALIDATION_FAILED`, `MALFORMED_REQUEST`) và 500; thêm ràng buộc `maxLength`
  (`email` 254, `password` 200, `deviceId` 128, `deviceName` 200, `refreshToken` 512).
- Mô tả Socket.IO: `MANAGER` đổi thành `ORG_ADMIN` (role thật trong token).

**`mock_server.py` CHƯA mô phỏng** `GET /auth/me`, `POST /auth/logout` và các endpoint `/users`. Frontend cần
backend thật (auth-service qua Gateway; bật `SWAGGER_ENABLED=true` để thử trên Swagger UI) để thử các API này.
`contract_test.py` cũng chưa kiểm chúng.

## v1.4 → v1.5: lịch sử cảnh báo

Thêm 3 endpoint của alert-service (không đổi `schemas/*.json`, không đổi gì phía app):

| Endpoint | Quyền | Trả về |
| --- | --- | --- |
| `GET /api/v1/alerts/me?from&to&alertType&page&size` | mọi role | các lần cảnh báo của người gọi, mới nhất trước |
| `GET /api/v1/alerts/me/sessions?from&to&page&size` | mọi role | các phiên làm việc, kèm `alertCount` |
| `GET /api/v1/alerts/org?from&to&alertType&page&size` | ORG_ADMIN có `orgId` | các lần cảnh báo của mọi thành viên |

- Danh sách dạng `{items, page, size, total}` như `/users`; `size` 1–100 (mặc định 20); `from`/`to` mặc định 7 ngày gần nhất, tối đa 92 ngày.
- Mỗi lần cảnh báo: `{userId, deviceId, sessionId, alertType, severity, startedAt, endedAt, durationSec, endReason, repeatCount, open}`. Cảnh báo không có `ALERT_RESOLVED` (app tắt giữa chừng) kết thúc cùng phiên với `endReason` `SESSION_END` hoặc `SESSION_TIMEOUT`.
- **Phiên tự đóng:** app không gửi được `SESSION_END` khi bị tắt đột ngột, nên backend đóng phiên sau 3 phút không có dữ liệu (`endReason` `TIMEOUT`, `endedAt` = lúc có dữ liệu cuối). Nếu app chỉ mất mạng rồi gửi bù dữ liệu mới hơn, phiên mở lại. App không cần làm gì thêm.
- Lỗi: 400 `VALIDATION_FAILED` (trường sai trong `errors`), 401, 403 `AUTH_FORBIDDEN` với `/org`.

Thống kê cho Dashboard (analytics-service), cùng tham số `from` / `to`:

| Endpoint | Quyền | Trả về |
| --- | --- | --- |
| `GET /api/v1/stats/me/summary?from&to` | mọi role | `{meanScore, badMinutes, presenceMinutes, alerts}` |
| `GET /api/v1/stats/me/timeseries?from&to&bucket=hour\|day` | mọi role | mảng `{start, meanScore, badMinutes, presenceMinutes, alerts}`, chỉ khung có dữ liệu |
| `GET /api/v1/stats/me/heatmap?weeks=1..12` | mọi role | đúng 168 ô `{weekday 1..7, hour 0..23, meanScore}` |
| `GET /api/v1/stats/org/summary?from&to` | ORG_ADMIN có `orgId` | như summary, gộp cả tổ chức |

- `meanScore` là trung bình `postureScore` có trọng số theo `presenceSec` (null khi không có dữ liệu); `badMinutes` = Σ(1 − goodRatio) × presenceSec / 60.
- Ngày (`bucket=day`) và heatmap tính theo **giờ Việt Nam**: `start` `2026-10-13T17:00:00Z` là ngày 14/10.
- Mốc thời gian trong query string phải mã hoá URL: `+07:00` viết `%2B07:00` (dùng `encodeURIComponent` / `URLSearchParams`), nếu không dấu `+` thành dấu cách và bị 400.

**Server giả và bộ kiểm tra:** `mock_server.py` trả được cả 7 endpoint trên, tính lại từ dữ liệu đã nhận theo cùng quy tắc với backend (đã đối chiếu với câu SQL của analytics-service). Thêm tài khoản `admin@kltn.local` / `123456` (ORG_ADMIN, cùng tổ chức với `demo@kltn.local`) để thử `/org`. Lỗi của các endpoint mới dùng body chuẩn `{code, message, traceId, errors}`. `contract_test.py` thêm nhóm `history` (18 bài); với backend thật nhóm này chờ tối đa 20 giây cho dữ liệu đi qua Kafka. Tài khoản kiểm tra không phải USER thì thêm `--not-user` để bỏ 2 bài 403.

## v1.3 → v1.4: cấu hình tổ chức

- `GET /api/v1/config/me` và phản hồi `PUT /api/v1/config/me` trả các khóa hiệu lực: tổ chức trước, cá nhân ghi đè; `{}` khi chưa có khóa nào. Sự kiện Socket.IO `config` dùng cùng giá trị hiệu lực.
- `GET/PUT /api/v1/config/org` chỉ dành cho `ORG_ADMIN` có `orgId`; `PUT` thay toàn bộ khóa tổ chức. Các khóa hiệu chỉnh riêng thiết bị bị từ chối.
- Khi ghi ở bất kỳ tầng nào, backend kiểm tra cặp ngưỡng sau khi gộp. Nếu một thành viên đã biết có cấu hình hiệu lực sai, từ chối toàn bộ giao dịch bằng 400 `VALIDATION_FAILED`; không lưu một phía và không phát sự kiện. App cũng từ chối file cấu hình có cặp ngưỡng sai, giữ cấu hình đang chạy.
- Với cặp khoảng cách, backend kiểm cả giá trị mặc định của app (`distance_on_cm=50`, `distance_off_cm=55`) nếu khóa chưa được ghi đè. Vì vậy tổ chức chỉ đặt `distance_on_cm=70` sẽ bị từ chối; cần đặt `distance_off_cm` hợp lệ cùng lúc.
- Nếu người dùng được chuyển sang tổ chức có ngưỡng xung đột với tùy chỉnh cá nhân cũ, `GET /config/me` trả 400 `VALIDATION_FAILED` thay vì trả cấu hình sai; `PUT /config/me` với cặp ngưỡng hợp lệ (hoặc `{}` để bỏ tùy chỉnh) sẽ khôi phục truy cập.
- Fanout hiện đến các thành viên đã gọi Config. Thành viên chưa từng gọi Config nhận giá trị tổ chức ở lần `GET /config/me` đầu; cần sự kiện thành viên từ Auth để fanout đầy đủ.

## v1.2 → v1.3: config và Socket.IO theo backend thật

Không thêm hay xoá endpoint, không đổi `schemas/*.json`. Chỉ ghi rõ hành vi backend đang chạy:

- `PUT /api/v1/config/me` **thay toàn bộ** cấu hình: body là tất cả các khoá muốn khác mặc định; khoá không gửi trở
  về mặc định; `{}` xoá hết tuỳ chỉnh. `GET` chưa lưu gì trả `{}`.
- Kiểm tra của `PUT` (sai thì 400 `VALIDATION_FAILED` với `errors[{field, message}]`, không lưu gì):
  kiểu và min/max theo `config.schema.json`; `api_token`, `api_base_url` bị từ chối (chỉ là cấu hình trên máy);
  `user_id` bị bỏ qua; khoá không có trong schema bị từ chối; khi body có đủ cặp thì
  `distance_off_cm >= distance_on_cm` và `shoulder_tilt_off <= shoulder_tilt_on` (khi cả hai khác null).
  Body không phải JSON: 400 `MALFORMED_REQUEST`.
- Socket.IO: không gửi token bị từ chối sau vài giây; server ngắt khi token hết hạn và client tự kết nối lại sau
  khi `refresh`; sự kiện `config` là toàn bộ cấu hình; `status` chưa có ở backend.

`config.schema.json` cố ý KHÔNG thêm `additionalProperties: false`: file này còn là schema của `app_config.json`
trên Desktop App (bản sao trong `posture_model/schemas/`), nên quy tắc "khoá lạ bị từ chối" chỉ áp dụng ở
`PUT /config/me` của backend.

**`mock_server.py` lỏng hơn backend:** `PUT /config/me` của mock chỉ kiểm theo schema (không từ chối `api_token`,
`api_base_url`, khoá lạ, không kiểm chéo) và vẫn trả lỗi dạng cũ `{error}`; mock chưa có Socket.IO.
`contract_test.py` nhóm `config` vẫn đúng với cả mock và backend.
