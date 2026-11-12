# KLTN_modelPosture

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
