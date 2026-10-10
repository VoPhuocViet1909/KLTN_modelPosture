# Gói bàn giao API v1.0 – Desktop App → Backend

Thư mục này là **toàn bộ những gì backend cần** để làm phần nhận dữ liệu, không cần webcam hay chạy Desktop App.
Kế hoạch chi tiết, lộ trình và các câu hỏi cần chốt nằm trong tài liệu "Kế hoạch bàn giao API".

Chỉ cần Python 3.9+ (thư viện chuẩn) để chạy các script; `tools/build_openapi.py` cần thêm `pyyaml`.

## Có gì trong thư mục

| File | Dùng để |
| --- | --- |
| `openapi.yaml` | Đặc tả 5 endpoint (OpenAPI 3.1). Mở bằng https://editor.swagger.io hoặc import vào Postman; sinh DTO / controller bằng openapi-generator |
| `schemas/*.json` | **Nguồn chuẩn duy nhất** của dữ liệu: `event`, `metrics`, `batch`, `config` (JSON Schema 2020-12). Backend kiểm tra dữ liệu bằng chính các file này |
| `mock_server.py` + `schema.py` | Server giả chạy đúng hợp đồng – để đối chiếu hành vi |
| `contract_test.py` | 29 bài kiểm tra hợp đồng, chạy vào bất kỳ server nào. **Mốc M2 = đạt 100%** |
| `replay.py` | `seed`: sinh lịch sử nhiều ngày để làm Dashboard · `load`: kiểm thử tải N máy |
| `payloads.py` | Bộ sinh dữ liệu hợp lệ, dùng chung cho 2 script trên |
| `sample_data/p01_*.jsonl` | Dữ liệu THẬT từ app chạy trên video người tham gia P01 (9 sự kiện, 4 metrics) |
| `tools/build_openapi.py` | Sinh lại `openapi.yaml` khi sửa schema |

## Bắt đầu trong 5 phút

```bash
# 1. chạy server giả (bắt buộc đăng nhập như server thật)
python mock_server.py --require-login            # http://127.0.0.1:8080, tài khoản demo@kltn.local / 123456

# 2. chạy bộ kiểm tra hợp đồng vào server giả -> phải 29/29
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
| Xác thực | JWT trong `auth: {token}` lúc kết nối. Sai / hết hạn → `connect_error`, message `unauthorized`; client refresh token rồi kết nối lại |
| Room | Server tự join: `user:{sub}`; MANAGER thêm `org:{orgId}`. Client không gửi lệnh join |
| Sự kiện `config` | Server → app, JSON theo `config.schema.json`, mỗi khi Dashboard lưu cấu hình (nguồn: Kafka `config.updates`) |
| Sự kiện `status` | Server → Dashboard, `{userId, deviceId, state: GOOD \| BAD \| AWAY \| OFFLINE, alertType, ts}` |

Client Python (app): `python-socketio`, `sio.connect(base, auth={"token": jwt}, socketio_path="socket.io")`.
Client React: `io(base, { auth: { token } })`.

Phía backend dùng netty-socketio 2.0.14: cần kiểm tra server đọc được `auth` của gói CONNECT
(`HandshakeData.getAuthToken()`); nếu không được thì chốt lại cách gửi token trước khi làm client.

v1.0 → v1.1: chỉ đổi phần realtime (STOMP `/ws` → Socket.IO). REST và `schemas/*.json` giữ nguyên.
