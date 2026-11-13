# KLTN_modelPosture

Bước 12/A5, nhánh `feat/workspace-profiles`: nút **Vị trí làm việc** tải hồ sơ trên web và đăng ký/gán đúng mã máy. **Áp dụng và hiệu chỉnh lại** chỉ dừng/mở phiên sau khi server xác nhận; dữ liệu chờ gửi vẫn giữ. Lựa chọn camera và bản ghi calibration nằm trong SQLite riêng theo API server/tài khoản/mã máy/vị trí. Góc baseline đã lưu không tự khôi phục; mỗi phiên đo lại. Web đổi hồ sơ thì app báo cần xác nhận; không âm thầm đổi baseline. GUI mới dùng hiệu chỉnh camera cục bộ ưu tiên hơn thiết lập cá nhân chung. Backend cần migration V5; chưa kiểm DB/webcam thật hoặc exe mới.

Bước 12/A2, nhánh `feat/notification-policy`: web Cấu hình có chính sách giờ yên lặng/tập trung/giãn cách và kênh PC. Desktop lấy bản có phiên bản mỗi 30 giây hoặc khi reconnect, hiển thị chính sách đã nạp và lúc hết tập trung. Chỉ chặn toast/bíp/popup; banner và telemetry vẫn hoạt động, không phát bù thông báo cũ. IoT dùng cấu hình riêng. Giải thích cảnh báo bổ sung dữ liệu đo hợp lệ, không suy nguyên nhân cụ thể từ nhãn nhị phân. Đã kiểm local/mock; chưa kiểm stack/webcam hoặc build exe mới.

A6, nhánh `feat/config-offline-history` (13/11/2026): app hiển thị phiên bản cấu hình đã nạp, lấy lại lúc kết nối lại và kiểm mỗi 30 giây. **Dữ liệu trên máy** mở lịch sử sự kiện/số liệu theo tài khoản và máy chủ, lọc/phân trang/xuất tóm tắt JSON. Dữ liệu cũ chưa rõ máy chủ cần xác nhận trước khi gửi; ID/payload được giữ nguyên. Xem [hướng dẫn cấu hình và dữ liệu trên máy](api_handover/config-offline-history.md). Đã kiểm local/mock, chưa nghiệm thu backend/webcam thật hoặc build exe mới.

Truyền hình lên dashboard, nhánh `feat/live-camera-setup` (13/11/2026): mở Thiết lập → Máy chủ video để lưu địa chỉ RTSP cho backend hiện tại; bật chia sẻ trong app, sao chép mã thiết bị hiển thị rồi dùng trên web. Cùng máy giữ `rtsp://127.0.0.1:8554`; khác máy cần MediaMTX/mạng được cấu hình trước. Xem [hướng dẫn camera](api_handover/live-camera.md). Mặc định không chia sẻ; không có video outbox hoặc ghi hình. Chưa đóng gói lại exe.

Nhánh `feat/device-observation` (A1, 13/11/2026) phân biệt hiệu chỉnh/chưa đủ mẫu/mất camera, gửi quan sát còn mới qua Socket.IO sẵn có và hiển thị UNKNOWN nếu quá 3 giây không nhận trạng thái engine. Kết nối lại vẫn hiệu chỉnh và giữ outbox như trước. Không đổi model hoặc telemetry v1.5; backend/web phải cùng hỗ trợ luồng mới. Có kiểm video giả, Qt offscreen và mock; chưa kiểm webcam, driver treo hoặc exe mới.

Nhánh `feat/software-expansion-m1`: thêm **Nghỉ và phản hồi**, hộp thư REST lưu riêng theo owner/server và timing tùy chọn (mặc định tắt). Đã kiểm local/mock/offscreen; chưa kiểm backend/webcam thật. Kế hoạch kiểm lại ở repo backend `docs/software-expansion-v1/RETEST-M1.md`.

Để kiểm mã mới, chạy source `posture_model/app.py` bằng môi trường Python đã cài requirements. File exe có sẵn và `MoUngDung.vbs` ưu tiên exe có thể vẫn là bản cũ; chưa đóng gói lại trong đợt này.

Bước 11/A6, nhánh `feat/local-command-history`: trong **Nghỉ và phản hồi → Xem lịch sử trên máy**, lọc thao tác chờ/đã gửi/bị từ chối/đã bỏ sau đối soát, xem chi tiết, thử gửi lệnh chờ và xuất toàn bộ lịch sử theo bộ lọc ra JSON. Dữ liệu giới hạn đúng tài khoản và máy chủ; file xuất chỉ gồm nghỉ/phản hồi lưu trên máy, không phải bản sao toàn bộ telemetry. Có kiểm SQLite/Qt offscreen; chưa nghiệm thu backend, webcam hoặc bản exe.

## Desktop App

Mở bằng nhấp đúp `MoUngDung.vbs`, hoặc `posture_model/dist/PostureMonitor/PostureMonitor.exe`
khi đã build. Lần đầu chọn camera và máy chủ trên giao diện; những lần sau app nhớ lựa chọn.
Xem [cách dùng/build](api_handover/desktop-app.md) và [kế hoạch tiếp theo](api_handover/desktop-next-steps.md).

## Camera trực tiếp

Ứng dụng hỗ trợ bật truyền hình side/front bằng `--stream-camera`; xem [hợp đồng video v1, cách chạy và phần chưa kiểm](api_handover/live-camera.md). Mặc định tắt, chỉ chủ tài khoản xem được, không ghi hình.
