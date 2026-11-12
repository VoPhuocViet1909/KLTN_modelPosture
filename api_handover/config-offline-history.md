# Cấu hình phiên bản và dữ liệu trên máy

13/11/2026 — Tân, nhánh `feat/config-offline-history`. Chạy source Python; exe hiện có chưa được build lại. Backend và dashboard phải có tính năng tương ứng trên cùng nhánh. Không cần thay model.

1. Đăng nhập và mở phiên theo dõi. Phía dưới trạng thái kết nối, app hiển thị phiên bản cấu hình đã nạp. Web → Cấu hình → Đồng bộ cấu hình hiển thị server đang lưu và xác nhận từng desktop.
2. Sau khi lưu trên web, app lấy cấu hình qua `GET /api/v1/config/me/snapshot`. Startup, reconnect và sự kiện `config` đều kích hoạt GET; mỗi 30 giây kiểm lại để phục hồi khi bỏ lỡ push. Engine kiểm tra và áp dụng trước khi xác nhận. Cùng phiên bản số nhưng khác `revision` vẫn cần đồng bộ.
3. Mất mạng: app giữ cấu hình hợp lệ trong RAM và tiếp tục ghi hàng đợi. Kết nối lại lấy cấu hình hiện tại và gửi bù theo ID cũ. Không có đăng nhập offline hay cache cấu hình qua lần khởi động mới trong phần này.
4. Nút **Dữ liệu trên máy** xem tóm tắt sự kiện/số liệu của phiên đã đăng nhập. Chọn Chờ gửi / Đã gửi / Bị từ chối, mỗi trang 25 mục. **Tải lại** đọc SQLite, không gửi mạng. Dữ liệu đã gửi có thể bị dọn sau 7 ngày; đây không phải lịch sử đầy đủ trên server.
5. **Xuất tóm tắt JSON** xuất tất cả trang theo bộ lọc, gồm ID/loại/thời gian/trạng thái/số lần thử lỗi; không xuất payload hoặc nội dung lỗi. File ghi nguyên tử trên luồng nền. Không chọn file outbox hoặc các file `-wal`, `-shm`, `-journal` làm đích.

## Nguồn dữ liệu cũ

Outbox mới dùng tên hash theo URL API và user ID. Cùng user ID trên backend khác dùng file khác. DB được ràng buộc owner/server trước khi enqueue/gửi; Sender kiểm lại nguồn trước mỗi HTTP batch. Không đổi ID hoặc payload đang chờ.

Nếu chỉ có `outbox-<userId>.db` từ bản cũ, app hỏi gắn với máy chủ đang đăng nhập; mặc định **Không**. Chỉ chọn **Có** khi biết đúng nguồn. App kiểm mọi payload thuộc đúng user trước khi gắn. Chọn Không giữ file cũ nguyên trạng và dùng file mới; dữ liệu cũ không nằm trong màn lịch sử của phiên mới và không tự gửi. Outbox cũ đã có nguồn khác được giữ riêng, không cho gắn lại. File `outbox.db` ẩn danh không được tự nhận về tài khoản.

Với `--outbox` tự chọn, file rỗng được gắn tự động; file đã gắn sai nguồn hoặc có dữ liệu cũ chưa xác nhận bị từ chối. Dùng đường dẫn mới cho nguồn mới; không tự sửa metadata SQLite để vượt kiểm tra.

## Tương thích và kiểm chứng

Backend cũ chỉ khi trả 404 cho snapshot mới dùng GET `/config/me`; hiển thị chưa xác nhận được phiên bản và không phát APPLIED có phiên bản. Lỗi 401/503/JSON sai không fallback. Cấu hình không hợp lệ bị từ chối, giữ bản đang dùng. `config` trong `device-state` là xác nhận của ứng dụng; khi socket mất/hết hạn hoặc phiên dừng, web không coi xác nhận cũ là còn hiệu lực. Không phải chứng thực phần cứng.

Đã kiểm worker startup/reconnect/poll, rollback phiên bản, khác revision, fallback; SQLite restart/owner/server/legacy consent; phân trang và xuất file nguyên tử; Qt và browser giả lập. Chưa kiểm giao dịch PostgreSQL thật, Redis, Gateway, webcam hoặc exe. Không mở Docker.
