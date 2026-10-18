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
| 3 | Hoàn thiện thiết lập và phục hồi lỗi | Đã bổ sung báo lỗi mở/mất hình cả hai camera, nút Kết nối lại / chọn camera dùng lại setup, giữ đăng nhập/outbox và hiệu chỉnh lại; kiểm giả lập đạt (chi tiết dưới). Còn kiểm rút/cắm thật, camera bận/mất quyền và driver treo. Hiện chọn số 0–99 và kiểm bằng ảnh; chỉ thêm tên thiết bị/tự tìm nếu thử người dùng cho thấy cần. |
| 4 | Rà cảnh báo (GĐ 4) và cài đặt (GĐ 6) | Banner/toast/sound/popup đã có mã. Kiểm thực từng mức, không phát dồn; kiểm giới hạn nhắc, tạm dừng, khả năng dùng bàn phím và độ hiển thị ở DPI 125–150%. Ngưỡng cảnh báo vẫn quản lý trên web, tránh thêm nguồn cấu hình cạnh tranh. GĐ 5 thiết lập lần đầu mới được bổ sung trong phần việc hiện tại. |
| 5 | Kiểm độ ổn định S1–S6 | Theo checklist backend: mất mạng thật/gửi bù, bỏ lỡ config/reconnect, TTL 900 giây thật, camera trước, hai máy/LAN, soak/FPS/latency/CPU/RAM. Giữ ID khi gửi lại; không mất hoặc lẫn dữ liệu tài khoản. Chưa chạy trong phần việc này. |
| 6 | Bản phát hành cho máy khác | Dùng cả thư mục portable `dist/PostureMonitor`, chạy trên Windows chưa cài Python và đường dẫn có dấu/khoảng trắng. Kiểm ONNX/MediaPipe, Qt, keyring và quyền ghi dữ liệu. Sau đó mới làm bộ cài/shortcut/uninstall; chuyển dữ liệu người dùng vào AppData trước khi cài vào Program Files. Chưa chứng nhận máy sạch. |
| 7 | Tích hợp và bàn giao | Web/desktop cùng tài khoản thấy đúng cảnh báo, lịch sử và cấu hình. Chốt các câu hỏi `CALIBRATING`/độ trễ BAD, org ngưng và config override với chủ API. Sau nghiệm thu mới đánh dấu hoàn tất, ghi commit + bằng chứng vào tiến độ chung. |

## Phạm vi bản đầu

Giữ PySide6, engine và API hiện có; không thêm framework giao diện. Bản đầu dùng webcam đánh số,
ảnh kiểm tra tĩnh và gói portable. Camera IP/video vẫn có thể dùng tham số CLI cũ; màn setup mới chỉ dành cho webcam.
Không lưu mật khẩu/token trong thiết lập hoặc bản phát hành. Không kèm `app_config.json`, outbox hay log của máy build.
Không coi bản portable là bộ cài đã nghiệm thu trên máy khác.

## Phục hồi camera — 18/10/2026

Nhánh `fix/desktop-camera-recovery` từ `23526af`. Camera hông hoặc camera trước đã chọn mà không mở
được sẽ báo lỗi cụ thể; camera trước không còn bị bỏ qua âm thầm. Trong phiên webcam, mất hình liên tục
ít nhất 3 giây sẽ kết thúc phiên, trả thiết bị và giữ dữ liệu chờ gửi. Một khung lỗi tạm thời vẫn được thử tiếp.
Thông báo lỗi được giữ sau khi engine dừng; cửa sổ ảnh cũ và cảnh báo cục bộ được đóng/ẩn.

Cắm lại thiết bị, đóng ứng dụng đang giữ camera hoặc kiểm tra quyền camera Windows, rồi chọn
**Kết nối lại / chọn camera** → **Kiểm tra hình** → **Lưu và tiếp tục**. Nếu không dùng camera trước,
tắt nó rõ ràng trong setup. Luồng hiện có giữ tài khoản đang đăng nhập, khóa địa chỉ máy chủ trong phiên,
chờ engine trả thiết bị trước khi mở setup và khởi động phiên mới để hiệu chỉnh lại.

Kiểm không cần webcam: engine 6/6 (gồm lỗi mở camera trước, mất hình hai vai trò, lỗi thoáng qua,
giải phóng thiết bị, SESSION_END, chạy lại và giữ nguyên ID/payload outbox); setup offscreen đạt
(giữ lý do lỗi sau finished, phục hồi cùng phiên đăng nhập và khóa máy chủ).
Hồi quy: calibration 16/16, login 9/9, assets 6/6, camera view 5/5, alerts 10/10,
quality 3/3, phase2 7/7, layout đạt.

Giới hạn: bộ đếm mất hình chỉ chạy khi driver trả về từ `read()`; chưa xử lý driver treo bên trong
lệnh đọc/mở. Chưa kiểm rút/cắm, quyền/bận bằng webcam thật, người thật, gửi thật sau phục hồi,
bản exe mới hoặc máy sạch. Chưa thêm tự chọn thiết bị để tránh chọn nhầm vai trò camera.
# Ưu tiên báo cáo ngày 18/10/2026

Theo yêu cầu người dùng, hoàn thiện luồng chức năng chính trước; đóng gói exe/installer,
updater và triển khai để sau. Bản nguồn `feat/desktop-camera-sharing` bổ sung bật/dừng
chia sẻ hông/trước trên GUI, mặc định tắt, giữ giám sát khi dừng truyền hình và dọn publisher
khi đăng xuất. Kiểm runnable ở `posture_model/tests/test_camera_sharing.py`.
Tiếp theo nghiệm thu webcam/người thật, camera trước và kênh thông báo Windows;
không suy kết quả video/landmark giả thành độ chính xác thực tế.

## Kiểm tự động cho demo — 18/10/2026

`python posture_model/tests/test_demo_reliability.py` kiểm xác nhận telemetry phải đủ ID,
không mất dữ liệu khi phản hồi thiếu/sai; định tuyến LOW/MEDIUM/HIGH và các cờ notify;
mỗi lúc một popup, đóng rồi mở lại được; dừng/đăng xuất/kết thúc phiên dọn popup/banner,
không phát cảnh báo đang chờ khi đã về đăng nhập hoặc đang rời phiên.

Kiểm native Windows đã gọi toast/âm thanh qua luồng thông báo và mở popup Qt thật;
đóng/mở lại rồi về đăng nhập dọn sạch, nhịp UI tối đa 47 ms. Windows báo có khay và hỗ trợ
toast. Đây là bằng chứng gọi API/hiển thị popup, chưa thay xác nhận nghe âm thanh/nhìn toast
trong Windows Notification Center hoặc khi bật Do Not Disturb.

Người dùng chọn tự thử webcam sau. Khi thử: đặt hai camera đúng góc, ngồi thẳng hiệu chỉnh;
cúi/gù, nghiêng vai, tiến gần màn hình rồi ngồi đúng lại; rời ghế để kiểm AWAY; thử rút/cắm
camera và Kết nối lại. Trên Dashboard cùng tài khoản thử từng góc. Ghi kết quả thực tế,
không đánh dấu độ chính xác mô hình từ landmark/video giả. Đóng gói vẫn để sau.

Tích hợp local thật với hai video/landmark giả đã đạt: GUI chọn Camera trước → Dashboard
decode 640×360; đo khoảng cách bằng nhánh IPD và phát SHOULDER_TILT/TOO_CLOSE;
dừng container Gateway rồi bật lại giữ/gửi bù 3 mục đúng ID/payload; refresh xoay token thật;
thu hồi refresh token ở server đưa app về đăng nhập, giữ 3 mục rồi gửi đủ sau đăng nhập lại.
Lượt cuối outbox 15 sent/0 pending/0 dead, fixture user đã khóa và Gateway được phục hồi.
Đây là lỗi dịch vụ thật, không phải rút cáp mạng; ép hạn client để kiểm refresh, chưa chờ TTL 900 giây.
