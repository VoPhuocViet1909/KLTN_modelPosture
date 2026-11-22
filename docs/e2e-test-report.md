# Báo cáo chạy thử E2E toàn hệ thống (backend thật)

Ngày chạy: 22/11/2026. Phạm vi: Desktop App → Backend (Gateway `:8080`) → Web Dashboard + Mobile App, với backend Docker thật,
chưa kiểm ESP32/IoT. Người chạy: Việt (thao tác trước camera/iPhone) cùng Claude Code (điều tra, sửa, kiểm).

Bản gốc của tài khoản thử, mật khẩu và token không nằm trong báo cáo hay repo.

## Tóm tắt

| Bước | Nội dung | Kết quả |
| --- | --- | --- |
| B0 | Backend lên, 47 bài hợp đồng, seed dữ liệu | **ĐẠT** |
| B1 | Desktop → Backend (outbox, DB, hiệu chỉnh) | **ĐẠT có lỗi đã sửa** (2 lỗi tích hợp, 1 điều kiện môi trường) |
| B2 | Dashboard (realtime, lịch sử, thống kê, chẩn đoán, đổi cấu hình, ack) | **ĐẠT** sau 2 bản sửa |
| B3 | Mobile (kết nối backend, Socket.IO) | **ĐẠT** phần kết nối; thông báo "ngồi sai" **HOÃN – kiểm sau** |
| B4 | Mất kết nối (tắt Gateway ~2 phút) | **HOÃN – kiểm sau** |
| B5 | Cấu hình tổ chức (ORG_ADMIN) | **HOÃN – kiểm sau** |
| — | ESP32 / IoT | **Để sau** (chưa kiểm) |

## Chi tiết từng bước

### B0. Backend: ĐẠT
- `docker compose up --build -d`: 17 container. Eureka có 8 service UP, `/actuator/health` của 9 service UP (discovery nghe cổng 8761),
  `/api/v1/health` trả `{"status":"UP"}`, Socket.IO polling trả `0{`.
- Tạo tổ chức "E2E Test Org" và 3 tài khoản cùng tổ chức bằng SYS_ADMIN seed: `e2e.user` (USER), `e2e.orgadmin` (ORG_ADMIN), `e2e.seed` (USER, chỉ để seed).
- `contract_test.py`: **47/47** trước và sau bản sửa backend ([bản rút gọn](e2e-evidence/b0-contract-test-47-47.json); bản gốc có JWT nên không commit).
- `replay.py seed` vào `e2e.seed`: 17.531 mục, 0 bị từ chối; sau đó 10 ngày dữ liệu, 1.055 cảnh báo.
- Ghi nhận môi trường: sau khi stack lên, login trả `503` khoảng 1 phút (Eureka chưa phân phối route) → đã sửa ở backend (xem lỗi L3).
  `contract_test.py` trên console Windows cần `PYTHONUTF8=1` (nếu không bị `UnicodeEncodeError` cp1252).

### B1. Desktop → Backend: ĐẠT, có lỗi đã sửa
Bằng chứng:
- Outbox `out/e2e/outbox.db`: **93 mục, 93 đã gửi, 0 chờ, 0 bị từ chối**.
- Timescale: 33 dòng `analytics.posture_metrics` của `e2e.user` (03:58 → 06:29 UTC).
- Dashboard "Chẩn đoán" ([ảnh](e2e-evidence/b2-chan-doan-thiet-bi.png)): thiết bị Desktop "Đã nhận xác nhận gửi", hàng đợi 0, cấu hình v2 đã nạp.
- `status` realtime qua Socket.IO: GOOD ↔ BAD với `alertType` đúng (TOO_CLOSE, NECK_TRUNK, SHOULDER_TILT).

Ghi nhận về dữ liệu: metrics v1.5 **không có trường tỉ lệ theo lớp tư thế** (`postureClass` của model v4 chỉ dùng trong UI/engine, không truyền lên),
nên chưa "lưu đúng postureClass" trong DB vì schema hiện tại không có chỗ cho nó. Chưa phải lỗi; ghi lại vì tính năng sau này cần.

Hiệu chỉnh thất bại liên tục (L4): xem bên dưới.

### B2. Dashboard: ĐẠT sau sửa
Kiểm bằng Chrome headless (Playwright) trên giao diện thật, tài khoản `e2e.user`, Desktop đang chạy:
- Thẻ "Tư thế lúc này" hiện **"Đang hiệu chỉnh"** khi Desktop hiệu chỉnh ([ảnh](e2e-evidence/b2-tong-quan-dang-hieu-chinh.png)); thời gian có mặt "29 phút".
- Lịch sử cảnh báo, thống kê/tiến độ, chẩn đoán thiết bị: [lịch sử](e2e-evidence/b2-lich-su-canh-bao.png), [tiến bộ](e2e-evidence/b2-theo-doi-tien-bo.png), [chẩn đoán](e2e-evidence/b2-chan-doan-thiet-bi.png). Không có lỗi console.
- **Đổi cấu hình cá nhân**: đổi "Chờ trước khi cảnh báo" 7 → 9 trên Dashboard. Sau khoảng 4 giây ack hiện "Đã nạp cấu hình hiện tại v3"
  ([trước](e2e-evidence/b2-dong-bo-cau-hinh-truoc.png), [sau](e2e-evidence/b2-dong-bo-cau-hinh-sau.png)); Desktop ghi `CONFIG_APPLIED` lúc 06:34:29Z với `alert_sec=9`.
- `npm test` 3/3, `npm run build`, `npm run lint` đạt.

### B3. Mobile
- `node dev/check-backend.mjs` qua IP LAN `192.168.1.16:8080`: **9/9 đạt** (login, refresh, token cũ bị từ chối, `/auth/me`, `/stats/me/summary`, Socket.IO có/không token, logout).
  Dòng INFO: Socket.IO nhận kết nối khi `Origin` lạ (`http://evil.example`) với token đúng; app di động không gửi Origin nên hành vi này phục vụ Mobile, nhưng cần cân nhắc khi triển khai thật.
- Metro chạy, iPhone `192.168.1.7` kết nối cổng 8081 và 8080.
- **Thông báo "ngồi sai": HOÃN – kiểm sau.** Đã điều tra phía code: luật `evaluateStatus` đúng với dữ liệu `status` thật. Đã thêm khối chẩn đoán dev-only
  (quyền, công tắc, số gói `status`, lý do báo/không báo, nút "Gửi thông báo thử") để kiểm trên iPhone. Còn cần người cầm iPhone;
  công cụ `fire_alert` (bắn cảnh báo qua ingestion, không cần ngồi sai) đã dùng thử, backend phát `status` BAD/TOO_CLOSE đúng.

### B4. Mất kết nối: HOÃN – kiểm sau
Chưa chạy. Cần Desktop đang chạy có camera hông hoạt động (Iriun) trong lúc tắt Gateway ~2 phút.

### B5. Cấu hình tổ chức: HOÃN – kiểm sau
Chưa chạy (cần ORG_ADMIN trên Dashboard, Desktop và Mobile cùng mở).

## Danh sách lỗi và bản sửa

| # | Lỗi | Nguyên nhân gốc | Sửa ở | Bản sửa |
| --- | --- | --- | --- | --- |
| L1 | Dashboard "Chưa đủ dữ liệu" mãi dù Desktop đang gửi | Desktop gửi `sessionId` dạng `s_<hex12>` trong `device-state`; backend đòi UUID → `OBSERVATION_INVALID` | Desktop | `observation.session_uuid` (UUID v5 cố định theo phiên) – [#32](https://github.com/VoPhuocViet1909/KLTN_modelPosture/pull/32) |
| L2 | Vẫn "Chưa đủ dữ liệu" sau L1 | netty-socketio đặt `NON_NULL` toàn server, bỏ khóa null (`diagnostics.oldestPendingAt`, `lastFailureCode`, `config.appliedAt`); web yêu cầu đủ khóa | Backend + Web | Backend `ObservationWire` giữ null riêng event này ([PR #85](https://github.com/luongtan204/DoAnTotNghiep_BE/pull/85)); Web `restoreObservation` làm lớp phòng thủ ([PR #23](https://github.com/VoPhuocViet1909/KLTN_dashboard/pull/23)) |
| L3 | Login `503` ~1 phút sau `docker compose up` | Eureka đăng ký chậm (mặc định 40 s/30 s) và Gateway không chờ service | Backend | Healthcheck mọi service, `depends_on: service_healthy`, rút thời gian Eureka; `docker compose up -d --wait gateway` (cold start 98 s, login 401 ngay) – PR #85 |
| L4 | Hiệu chỉnh thất bại liên tục | Camera hông chỉ số 1 là **Iriun Webcam** trả khung đen hoàn toàn (độ sáng 0,0) khi app Iriun trên điện thoại chưa phát; thông báo cũ "0% số khung" khó hiểu. Phụ: ngồi quá gần (44–48 cm < 48 cm), cử động nhiều | Desktop | Lý do mới `SIDE_NO_SIGNAL` ("Camera hông không có tín hiệu (hình đen)…"), 17/17 test hiệu chỉnh – [#32](https://github.com/VoPhuocViet1909/KLTN_modelPosture/pull/32) |
| L5 | "Thời gian có mặt 0 giờ" khi thực tế 21,5 phút | Tổng quan làm tròn theo giờ | Web | `formatMinutes` – PR #23 |
| L6 | Desktop tự đăng nhập nhầm tài khoản demo; "Outbox belongs to another server or owner" | Phiên cũ trong Credential Manager; outbox gắn với chủ cũ | Quy trình | Hướng dẫn tắt phiên + thư mục outbox riêng theo lần chạy (không sửa code) |
| L7 | Truy vấn `/stats/me/*` đầu tiên ngay sau khởi động lạnh có lúc `503` vài giây | Analytics đang làm nóng/rebalance consumer (quan sát với tài khoản có nhiều dữ liệu); sau đó 0,05 giây | Backend | **Chưa xử lý**, ghi nhận |

Lỗi môi trường khác: lệnh PowerShell (`$env:`, `New-NetFirewallRule`) dán vào CMD; firewall cần cổng 8081 (Metro) ngoài 8080.

## Các PR

| Repo | PR | Nội dung |
| --- | --- | --- |
| KLTN_BE (backend) | [#85](https://github.com/luongtan204/DoAnTotNghiep_BE/pull/85) | `ObservationWire`, healthcheck Compose, team-sync (backend do Việt phụ trách) |
| KLTN_dashboard | [#23](https://github.com/VoPhuocViet1909/KLTN_dashboard/pull/23) | khôi phục khóa null, thời gian có mặt theo phút |
| KLTN_modelPosture | [#32](https://github.com/VoPhuocViet1909/KLTN_modelPosture/pull/32) | `session_uuid`, `SIDE_NO_SIGNAL`, báo cáo này |
| KLTN_mobile | [#4](https://github.com/VoPhuocViet1909/KLTN_mobile/pull/4) | luật `explainStatus`, khối chẩn đoán thông báo (dev-only) |

## Chưa kiểm
- B4 (mất kết nối, outbox bù, không trùng bản ghi), B5 (cấu hình tổ chức), thông báo "ngồi sai" trên iPhone.
- Trạng thái GOOD/BAD thật trước webcam trong lần chạy cuối (camera hông Iriun không phát hình).
- Truy vấn thống kê ngay sau khởi động lạnh (L7).
- ESP32 / IoT.
- Chưa kiểm tải, độ bền kéo dài, triển khai ngoài máy local.
