# Chẩn đoán hàng đợi và đồng bộ trên web

14/11/2026. Khi desktop đăng nhập và đang theo dõi với config sync, mở mục Cá nhân → Chẩn đoán trên dashboard để xem trạng thái camera, hàng đợi gửi dữ liệu, lần được nhận gần nhất và phiên bản cấu hình đã nạp.

`Sender` chỉ xuất counters/thời gian/code an toàn, không xuất payload, token, URL hoặc raw last_error. Metadata chỉ gửi sau khi ACK device-state xác nhận backend hỗ trợ diagnostics; server cũ vẫn nhận packet cũ, reconnect reset khả năng hỗ trợ. Chỉ có1 ACK callback đang chờ trên một connection, backend cũ không trả ACK không làm tích lũy callback. Nếu Outbox không đúng owner/server hiện tại thì không xuất metadata của hàng đợi đó.

- queued: chờ ghi vào SQLite; pending: đã lưu và chờ gửi; retrying: đã thử gửi nhưng còn chờ; dead: bị từ chối và không thử lại.
- acceptedSinceStart: số mục có ACK accepted từ lúc tạo Sender của phiên, không khẳng định Analytics đã lưu. Counter sent trong Outbox cũ giữ nguyên, có retention riêng; không dùng làm tổng trọn đời.
- lastAttemptMs: monotonic cho lần thử gửi; configFetchApplyMs: từ lúc bắt đầu GET đến lúc nạp thành công tại desktop. Không bao gồm thời gian chờ polling/push, không lấy chênh lệch hai đồng hồ làm độ trễ server→desktop. Từ chối cấu hình/thiếu mốc thì duration null.
- Dữ liệu quá hạn hoặc realtime ngắt không hiển thị như tình trạng hiện tại. Camera và đường gửi dữ liệu độc lập; camera lỗi chưa chứng minh API gửi lô cũng lỗi.

Không cần dependency hoặc DB migration mới. Hợp đồng và quyền owner-only trong [STEP15-DEVICE-DIAGNOSTICS.md](https://github.com/luongtan204/DoAnTotNghiep_BE/blob/main/docs/software-expansion-v1/STEP15-DEVICE-DIAGNOSTICS.md), API catalogue backend team-sync4.7. Web/desktop mới cần backend mới để có số liệu chẩn đoán, không cần đổi model/schema telemetry.

Kiểm local:27 direct scripts (bỏ bộ IoT pytest không đổi), check_config_sync đạt; test_diagnostics mới kiểm counters, ACK partial, mã lỗi không lộ dữ liệu, source mismatch, duration/legacy/callback generation và giới hạn callback. Sau bổ sung source guard đã kiểm lại diagnostics/telemetry_history/engine/config_snapshot/config_sync đạt. Qt offscreen/pose/mock network không phải webcam, máy thật, bản exe hoặc thử tải.
