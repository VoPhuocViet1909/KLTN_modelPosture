# Kế hoạch hoàn thiện Desktop App

Cập nhật 18/10/2026. Điểm xuất phát: main `5914849`, đối chiếu mã trong `posture_model/`.
Nguồn: [bàn giao desktop](desktop-app.md), [hợp đồng camera](live-camera.md),
[tiến độ chung](https://github.com/luongtan204/DoAnTotNghiep_BE/blob/main/.codex/skills/kltn-project/SKILL.md)
và [câu hỏi API](https://github.com/luongtan204/DoAnTotNghiep_BE/blob/main/.codex/skills/team-sync/SKILL.md).
Đã đọc `KeHoach_NgonNguThietKe.md` ngày 18/10 và đối chiếu design system trong repo Dashboard.
File `TaiLieu/KeHoach_DesktopApp.md` được bàn giao dẫn đến nhưng chưa có trong bản checkout/local;
không coi kế hoạch này là bản sao của tài liệu còn thiếu đó.

## Trải nghiệm sử dụng

1. Mở `PostureMonitor.exe` bằng nhấp đúp, không có cửa sổ CMD.
2. Lần đầu: chọn camera hông và camera trước (hoặc tắt camera trước), bấm **Kiểm tra hình**.
   Đặt camera hông nhìn ngang tai–vai–hông; camera trước thấy hai vai. Ảnh kiểm tra chỉ nằm trong RAM.
3. Nhập địa chỉ backend một lần, **Lưu và tiếp tục**. Thiết lập cục bộ được Windows nhớ cho tài khoản hiện tại.
4. Đăng nhập hoặc dùng chế độ cục bộ, ngồi thẳng giữ yên để app hiệu chỉnh; lỗi hiệu chỉnh có hướng dẫn sẵn.
5. Những lần sau mở app là dùng lựa chọn đã lưu; phiên đăng nhập được keyring khôi phục nếu người dùng bật ghi nhớ.
6. Nút **Thiết lập camera / máy chủ** cho phép đổi camera: app dừng engine, trả camera,
   xem ảnh kiểm tra rồi chạy lại và hiệu chỉnh. Chỉ đổi máy chủ khi đã đăng xuất.
7. Đóng cửa sổ thu xuống khay; chọn **Thoát** ở menu khay để dừng ứng dụng.

## Thứ tự thực hiện và điều kiện đạt

| Ưu tiên | Việc | Hiện trạng và điều kiện nghiệm thu |
| --- | --- | --- |
| 1 — phần việc hiện tại | Mở bằng nhấp đúp, chọn camera, ghi nhớ thiết lập | Thêm setup Qt, ảnh kiểm tra chạy nền, QSettings, launcher `MoUngDung.vbs`; sửa build sang `app.py` windowed. Test camera giả xác nhận validate, trả camera kể cả khi lỗi, lưu lựa chọn và đổi camera khi đang dùng. Bản `.exe` phải được kiểm chạy riêng; không suy ra từ build thành công. |
| 2 | Nghiệm thu với người thật | Hai camera đúng góc → hiệu chỉnh thành công → GOOD/BAD/AWAY; gù trong lúc hiệu chỉnh phải bị từ chối; ảnh camera đủ khung, UI không đơ. Thử ít nhất ba người, ghi camera/ánh sáng/ngưỡng và trường hợp sai. Chưa nghiệm thu; dữ liệu giả không thay thế bước này. |
| 3 | Hoàn thiện thiết lập và phục hồi lỗi | Kiểm rút/cắm lại webcam, camera bận/mất quyền; tên thiết bị và tự tìm camera nếu người dùng vẫn khó chọn theo số. Hiện cho nhập số 0–99 và kiểm bằng ảnh; không đoán vai trò camera chỉ từ tên thiết bị. Đồng bộ lựa chọn với thiết bị thay đổi là phần tiếp theo. |
| 4 | Rà cảnh báo (GĐ 4) và cài đặt (GĐ 6) | Banner/toast/sound/popup đã có mã. Kiểm thực từng mức, không phát dồn; kiểm giới hạn nhắc, tạm dừng, khả năng dùng bàn phím và độ hiển thị ở DPI 125–150%. Ngưỡng cảnh báo vẫn quản lý trên web, tránh thêm nguồn cấu hình cạnh tranh. GĐ 5 thiết lập lần đầu mới được bổ sung trong phần việc hiện tại. |
| 5 | Kiểm độ ổn định S1–S6 | Theo checklist backend: mất mạng thật/gửi bù, bỏ lỡ config/reconnect, TTL 900 giây thật, camera trước, hai máy/LAN, soak/FPS/latency/CPU/RAM. Giữ ID khi gửi lại; không mất hoặc lẫn dữ liệu tài khoản. Chưa chạy trong phần việc này. |
| 6 | Bản phát hành cho máy khác | Dùng cả thư mục portable `dist/PostureMonitor`, chạy trên Windows chưa cài Python và đường dẫn có dấu/khoảng trắng. Kiểm ONNX/MediaPipe, Qt, keyring và quyền ghi dữ liệu. Sau đó mới làm bộ cài/shortcut/uninstall; chuyển dữ liệu người dùng vào AppData trước khi cài vào Program Files. Chưa chứng nhận máy sạch. |
| 7 | Tích hợp và bàn giao | Web/desktop cùng tài khoản thấy đúng cảnh báo, lịch sử và cấu hình. Chốt các câu hỏi `CALIBRATING`/độ trễ BAD, org ngưng và config override với chủ API. Sau nghiệm thu mới đánh dấu hoàn tất, ghi commit + bằng chứng vào tiến độ chung. |

## Phạm vi bản đầu

Giữ PySide6, engine và API hiện có; không thêm framework giao diện. Bản đầu dùng webcam đánh số,
ảnh kiểm tra tĩnh và gói portable. Camera IP/video vẫn có thể dùng tham số CLI cũ; màn setup mới chỉ dành cho webcam.
Không lưu mật khẩu/token trong thiết lập hoặc bản phát hành. Không kèm `app_config.json`, outbox hay log của máy build.
Không coi bản portable là bộ cài đã nghiệm thu trên máy khác.
