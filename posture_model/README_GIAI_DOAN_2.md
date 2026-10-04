# Giai đoạn 2 – Gửi dữ liệu

Luồng dữ liệu:

```
vòng lặp camera ──(không chờ)──► hàng đợi ──► thread Sender ──► Outbox SQLite ──► POST theo lô ──► server
        │                                                          (out/outbox.db)
        └─► MetricsAggregator (mỗi 60 s) ──► metrics ──┘
```

## Các file mới

| File | Việc |
| --- | --- |
| `schemas/event.schema.json` | Schema sự kiện (10 loại, có ràng buộc riêng cho từng loại) |
| `schemas/metrics.schema.json` | Schema metrics 60 giây |
| `schemas/batch.schema.json` | Body của `POST /api/v1/telemetry/batch` |
| `schemas/config.schema.json` | Cấu hình server đẩy xuống app; `app_config.json` sai giá trị bị từ chối |
| `schema.py` | Kiểm tra theo schema, không cần cài thêm thư viện |
| `outbox.py` | Outbox SQLite: ghi đĩa trước, gửi sau; chống trùng theo id; backoff 2, 4, 8 … 300 s |
| `sender.py` | Thread Sender: lô 5 s / 100 mục, sự kiện khẩn gửi ngay, tự gửi bù khi có mạng lại |
| `metrics.py` | Gộp metrics 60 s (chạy trong app, hoặc chạy riêng trên `log.csv`) |
| `mock_server.py` | Server giả đúng API để thử khi chưa có backend Spring |
| `tests/test_phase2.py` | 7 test: schema, outbox, gửi / mất mạng / có mạng lại, sai token, metrics |

Backend Spring ở giai đoạn 3 dùng lại chính các file trong `schemas/`, nên app và server luôn khớp nhau.

## Thử nhanh trên máy

Terminal 1, chạy server giả:
```
python mock_server.py --token abc123
```

Terminal 2: thêm vào `app_config.json` (sửa được cả khi app đang chạy):
```json
"api_base_url": "http://127.0.0.1:8080",
"api_token": "abc123"
```
rồi chạy app:
```
python realtime_app.py --side 1 --front 0
```

Góc phải dưới cửa sổ app hiện `server online, 0 cho gui`. Terminal 1 in ra từng lô nhận được. Dữ liệu server nhận nằm trong `mock_data/events.jsonl` và `mock_data/metrics.jsonl`; xem tổng hợp tại http://127.0.0.1:8080/api/v1/stats.

**Thử mất mạng:** tắt terminal 1 (Ctrl+C). App hiện `server MAT KET NOI, n cho gui` và vẫn chạy bình thường. Bật lại `mock_server.py`: trong khoảng 15 giây app tự gửi bù, số chờ gửi về 0, không có bản trùng. Muốn thử mạng chập chờn thì dùng `python mock_server.py --fail-rate 0.3`.

`api_base_url` để null thì app chỉ lưu outbox (chế độ offline). Lúc có server thì dữ liệu cũ được gửi lên.

## API (hợp đồng cho giai đoạn 3)

| | |
| --- | --- |
| `POST /api/v1/telemetry/batch` | Header `Authorization: Bearer <token>`, body theo `batch.schema.json` |
| Trả về 200 | `{"accepted": [id...], "rejected": [{"id", "reason"}], "duplicates": n}` |
| 401 / 403 | Giữ dữ liệu, thử lại sau (sai token không làm mất dữ liệu) |
| 413 | App tự chia nhỏ lô |
| 429 / 5xx / mất mạng | Giữ trong outbox, backoff, hỏi `/api/v1/health` mỗi 15 s |
| `GET /api/v1/health` | `{"status": "UP"}` |

Sự kiện khẩn, gửi ngay không chờ lô: `ALERT_STARTED`, `ALERT_REPEATED`, `ALERT_RESOLVED`, `USER_AWAY`, `USER_BACK`.

## Metrics 60 giây

Cửa sổ căn theo phút đồng hồ (14:20:00, 14:21:00 …). `metricId = uuid5(sessionId + windowStart)`, nên gửi lại vẫn trùng id và server tự bỏ. Mọi tỉ lệ tính theo thời gian, chỉ trong lúc có người.

| Trường | Ý nghĩa |
| --- | --- |
| `coveredSec`, `presenceSec`, `samples` | Thời gian có dữ liệu, thời gian có người, số mẫu |
| `goodRatio`, `pBadMean` | Tỉ lệ thời gian cổ/thân GOOD, P(BAD) trung bình |
| `neckMean/Max`, `trunkMean/Max`, `headPitchMean` | Góc (độ, so với lúc hiệu chỉnh) |
| `tiltRelMean`, `tiltAbsMax`, `shoulderBadRatio` | Lệch vai |
| `distanceMeanCm`, `distanceMinCm`, `tooCloseRatio` | Khoảng cách mắt–màn hình |
| `alertCount` | Số lần bật cảnh báo / nhắc nhở theo loại |
| `postureScore` | 0–100, công thức bên dưới |

Công thức điểm:

```
postureScore = 100 × trung bình có trọng số các nhánh đang có dữ liệu
                 (cổ/thân: goodRatio × 0.6, lệch vai: (1 − shoulderBadRatio) × 0.2,
                  khoảng cách: (1 − tooCloseRatio) × 0.2)
               − 5 × số lần bật cảnh báo tư thế trong phút, kẹp trong [0, 100]
```

Khi có người dưới 10% thời gian của cửa sổ thì `postureScore = null`.

Gộp từ file `log.csv` có sẵn (ví dụ để làm dataset cho báo cáo):
```
python metrics.py out/log.csv --start 2026-10-03T14:00:00+07:00 --out out/metrics_from_log.csv
```

## Kết quả kiểm thử

- `python tests/test_phase2.py`: 7/7 đạt. `python tests/test_alerts.py`: 10/10 đạt.
- Chạy app trên video P01 (khoảng 3 phút), gửi tới `mock_server.py --fail-rate 0.3`: 13/13 mục tới server (9 sự kiện, 4 metrics), không trùng, không mất, dù khoảng 30% request bị lỗi 503.
