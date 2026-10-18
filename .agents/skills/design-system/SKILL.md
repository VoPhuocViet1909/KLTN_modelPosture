---
name: design-system
description: Ngôn ngữ thiết kế chung của KLTN web React và desktop PySide6. Đọc khi thiết kế, sửa hoặc review giao diện, bố cục, thành phần, biểu đồ, lời văn và luồng camera; giữ hai ứng dụng đồng bộ về nhận diện và ý nghĩa.
---

# Ngôn ngữ thiết kế KLTN

Phiên bản KLTN-DS-1, ngày 18/10/2026. Hướng người dùng đã chọn: **sáng, gọn, dễ dùng**.
Web phục vụ xem lại thói quen và quản lý; desktop phục vụ chọn camera, hiệu chỉnh và nhắc tư thế tại chỗ.
Cùng nhận diện, thuật ngữ và cách phản hồi; dùng tương tác phù hợp từng nền tảng, không ép cùng bố cục.

## Nguồn và cách áp dụng

- Skill này được lưu giống hệt tại `.agents/skills/design-system/` của cả hai repo.
  Khi sửa quy tắc, sửa cả hai bản và kiểm tra đồng bộ trước khi áp dụng UI.
- Đọc `../ui-ux-pro-max/SKILL.md` để tra cứu vấn đề cụ thể và `../ponytail/SKILL.md` khi viết code.
  Kết quả tra cứu là gợi ý; lựa chọn đã chốt của người dùng và quy tắc dự án được ưu tiên.
- Web: dùng React/Tailwind/shadcn đã cài. Desktop: dùng widget PySide6 hiện có;
  cơ sở dữ liệu UI UX Pro Max chưa có stack PySide6, chỉ áp dụng hướng dẫn UX chung.
- Token chạy thật: web `src/index.css`; desktop `posture_model/ui/design_tokens.json`.
  Nhãn: web `src/lib/labels.ts`; desktop `posture_model/ui/labels.json`.
  Không rải màu/nhãn riêng trong màn hình. Sửa token chung phải sửa cả hai bên.
- Desktop sinh `theme.qss` qua `posture_model/ui/build_theme.py`, không sửa tệp sinh bằng tay.
- Skill là quy tắc thiết kế, không phải bằng chứng đã triển khai. Tiến độ và giới hạn kiểm chứng
  ghi trong `kltn-project`/`team-sync`; không đưa báo cáo màn hình cũ vào quy tắc lâu dài.

## 1. Nhận diện

Nền trung tính hơi ấm, bề mặt trắng, viền mảnh, xanh lam cho thao tác chính.
Ưu tiên thứ bậc thông tin, khoảng trắng và chữ số dễ đọc. Không thêm gradient, kính mờ,
neon, hiệu ứng trang trí hay thư viện UI mới chỉ để thay hình thức.
Thước dọi tư thế là hình nhận diện: dùng ở đăng nhập, thương hiệu và trạng thái hiện tại;
không lặp ở mọi thẻ.

| Vai trò | Token | Giá trị |
| --- | --- | --- |
| Nền ứng dụng | surface | #f4f5f3 |
| Bề mặt nội dung | background, card | #ffffff |
| Chữ chính | foreground | #1c2433 |
| Chữ phụ | muted-foreground | #5b6472 |
| Thao tác chính | primary | #256abf |
| Chữ trên nút chính | primary-foreground | #ffffff |
| Vùng chọn | accent | #e8eef8 |
| Viền, viền ô nhập | border, input | #e1e4df, #d5d9d3 |
| Focus | ring | #2a78d6 |
| Lỗi, thao tác nguy hiểm | destructive | #d03b3b |
| Dữ liệu biểu đồ | chart-1…5 | #2a78d6, #86b6ef, #1c5cab, #cde2fb, #104281 |

Màu kết nối máy chủ dùng primary hoặc offline; không dùng xanh GOOD để nói đang đồng bộ.
Chưa có bảng màu tối được nghiệm thu; không tự bật dark mode hoặc đảo màu.

## 2. Chữ và nhịp bố cục

- Font chung **Be Vietnam Pro**, trọng lượng 400/500/600/700; dùng bản font sẵn có.
- Tiêu đề trang 24px/600; tiêu đề mục 16px/500–600; nội dung và ô nhập 14px;
  ghi chú 12px; số trọng tâm 48px/600. Chữ tiếng Việt đủ khoảng dòng, không cắt dấu.
- Chữ số thống kê dùng tabular. Một nhóm chỉ có một chỉ số lớn làm trọng tâm.
- Bước khoảng cách 4px; khoảng mục 32px; padding panel 24px, thu còn 16px ở vùng hẹp;
  khoảng nhãn–ô nhập 6–8px. Panel bo khoảng 11px, control 6px, không đổ bóng panel thường.
- Viết hoa kiểu câu. Không dùng viết hoa toàn bộ, chữ siêu nhỏ hoặc màu nhạt để tạo thứ bậc.

## 3. Ngữ nghĩa trạng thái và thuật ngữ

| Mã | Nhãn thống nhất | Màu icon | Icon Lucide |
| --- | --- | --- | --- |
| GOOD | Ngồi đúng | #0ca30c | CircleCheck |
| BAD | Đang ngồi sai | #d03b3b | TriangleAlert |
| AWAY | Vắng mặt | #c98500 | Moon |
| OFFLINE | Không kết nối | #8a8f98 | CircleOff |
| CALIBRATING | Đang hiệu chỉnh | Màu trung tính/primary | RotateCw |

CALIBRATING là trạng thái cục bộ desktop; không tự thêm vào hợp đồng realtime web.
Màu trạng thái chỉ tô icon/chấm/thước dọi, luôn kèm nhãn; chữ dùng foreground để dễ đọc.
GOOD/BAD không thay thế thành công/lỗi khi lưu cấu hình. AWAY không đồng nghĩa mất kết nối.
Kết nối camera, kết nối máy chủ và tình trạng tư thế phải có nhãn phân biệt.

| Khái niệm | Lời văn chung |
| --- | --- |
| Ứng dụng camera | Ứng dụng desktop |
| Camera nhìn nghiêng tai–vai–hông | Camera hông |
| Camera nhìn mặt và hai vai | Camera trước |
| Đo tư thế chuẩn | Hiệu chỉnh / Hiệu chỉnh lại |
| Xem ảnh thử thiết bị | Kiểm tra hình |
| Chạy tại máy, không gửi số liệu | Dùng không đăng nhập |
| NECK_TRUNK / SHOULDER_TILT | Cúi cổ, gù lưng / Lệch vai |
| TOO_CLOSE / SIT_TOO_LONG / EYE_BREAK | Ngồi quá gần màn hình / Ngồi quá lâu / Nghỉ mắt |
| LOW / MEDIUM / HIGH | Thấp / Vừa / Cao |

Nút nêu hành động: “Lưu cấu hình”, “Lưu và tiếp tục”; thông báo dùng cùng động từ: “Đã lưu cấu hình”.
Lỗi nêu sự cố và bước tiếp theo; không đẩy tên script, backend hay stack trace cho người dùng.
Dữ liệu trống khác lỗi, số 0 khác chưa đo: chưa đo dùng “Chưa đo” hoặc “—”, không thay bằng 0.

## 4. Thành phần và hành vi chung

- Mỗi khu vực tác vụ có một hành động chính; hành động phụ dùng viền hoặc liên kết.
  Nút xóa/khóa không đặt cạnh hành động chính mà thiếu phân biệt và xác nhận cần thiết.
- Ô nhập có nhãn hiển thị, mô tả nếu cần; placeholder không thay nhãn. Nhãn lỗi đặt gần ô,
  có văn bản, tập trung ô lỗi sau submit. Với form dài trên web, dùng tóm tắt lỗi có liên kết.
- Khi đang xử lý: tên nút cho biết việc đang làm, ngăn gửi trùng, giữ giá trị đã nhập;
  khi thất bại trả lại khả năng sửa/thử lại. Không treo UI trong lúc đọc camera/gọi mạng.
- Mục tiêu bấm chính và điều hướng ít nhất 44×44px logic; icon 16–20px, có tên truy cập
  nếu không có chữ. Không dựa vào hover để lộ thao tác bắt buộc.
- Tab tới mọi điều khiển theo thứ tự đọc; focus rõ và không bị header/footer che.
  Dialog dùng hành vi native/Radix: giữ focus, Escape khi có thể hủy, trả focus khi đóng.
- Không chỉ đổi màu để báo lỗi/chọn/trạng thái. Chữ thường tương phản ít nhất 4.5:1,
  icon/đường viền thiết yếu 3:1; trạng thái disabled không được hiểu là tác vụ đang chạy.
- Hover đổi màu 150ms, không làm xô bố cục. Thước dọi đổi góc 14° trong 600ms khi trạng thái đổi;
  tôn trọng giảm chuyển động. Không thêm chuyển động liên tục hoặc nhấp nháy.

## 5. Web

- Sidebar 240px khi vùng nhìn ≥1024px; nhỏ hơn dùng nút mở menu có tên, focus và đóng được bằng Escape.
  Menu đóng khi điều hướng. Giữ nguyên nhóm/quyền USER, ORG_ADMIN, SYS_ADMIN.
- Nội dung căn trái, tối đa 1024px; lề 32px trên màn rộng, 16px trên màn hẹp.
  Tiêu đề, mô tả ngắn và bộ lọc nằm trước nội dung; bộ lọc xuống hàng khi thiếu chỗ.
- Panel quan trọng nhất: tư thế hiện tại và số liệu khoảng thời gian đã chọn.
  Bảng rộng cuộn trong vùng bảng; toàn trang không tràn ngang. Có đường tắt đến nội dung chính.
- Form đăng nhập có mục đích rõ, lỗi dễ hiểu, autocomplete phù hợp và trạng thái gửi.
  Không hiển thị số liệu demo như số liệu thật để trang trông đầy hơn.
- API/auth/TanStack Query/Socket.IO giữ theo AGENTS của web; thiết kế không thay phân quyền.

## 6. Desktop

- Cửa sổ co giãn, có kích thước tối thiểu phù hợp; khi thiếu chiều cao cho phép cuộn nội dung.
  Không khóa 420×560 khiến chữ Windows 150–200% bị cắt. Native Qt xử lý DPI và bàn phím.
- Luồng chuẩn: chọn camera → kiểm tra hình → lưu → đăng nhập hoặc dùng cục bộ → ngồi thẳng hiệu chỉnh
  → theo dõi. Không thêm wizard bắt buộc làm mất luồng tiếp tục phiên hiện tại.
- Camera hông: ngang người khoảng 90°, thấy tai–vai–hông. Camera trước: thấy mặt và hai vai.
  Hiển thị vai trò cạnh ảnh, gợi ý đổi số thiết bị nếu chọn nhầm; không đoán camera theo chỉ số 0/1.
- Tùy chọn tắt camera trước có nhãn dễ hiểu; `-1` chỉ là giá trị nội bộ. Nói rõ khi tắt thì
  không đo lệch vai/khoảng cách. Ảnh kiểm tra là ảnh chụp, không gọi là video trực tiếp.
- Không lưu/gửi ảnh kiểm tra; không mở thiết bị ở UI thread; giữ giải phóng thiết bị, chặn đóng khi
  worker chưa dừng và giới hạn đổi máy chủ trong phiên đăng nhập theo code hiện có.
- Trang theo dõi ưu tiên tư thế + lời nhắc, sau đó thời gian ngồi/khoảng cách, rồi đồng bộ/tài khoản.
  Giữ tín hiệu controller, thu xuống khay khi đóng, hàng chờ gửi lại và hiệu chỉnh thật.

## 7. Biểu đồ và số liệu

Xu hướng dùng đường, so sánh dùng thanh ngang, thứ×giờ dùng heatmap một màu.
Điểm luôn 0–100; ngày thiếu dữ liệu là khoảng trống. Không cắt trục làm phóng đại thay đổi.
Không dùng màu GOOD/BAD tô chuỗi dữ liệu; biểu đồ có nhãn/tooltip đọc được và dữ liệu thay thế khi cần.
Bộ lọc chỉ ảnh hưởng vùng được mô tả, không tự đổi cửa sổ thời gian của trạng thái trực tiếp.

## 8. Cổng kiểm tra trước khi sửa và giao UI

Trước khi sửa: đọc màn hình và callers, xác định token/nhãn chung hay hành vi riêng nền tảng;
tra UI UX Pro Max theo một vấn đề cụ thể. Chốt vào skill khi đổi quy tắc, rồi mới sửa UI.
Không tạo abstraction hoặc dependency mới khi component/native widget hiện có giải quyết được.

Chạy kiểm đồng bộ từ một trong hai repo (Python 3, không thêm dependency):

```powershell
python .agents/skills/design-system/scripts/check_sync.py --web <dashboard-root> --desktop <desktop-root>
```

Kiểm web: build/lint; xem ở 375/768/1024/1440px, zoom 200%, Tab/Escape và giảm chuyển động;
thử dữ liệu thật/mock và phân biệt rõ. Kiểm desktop: Qt offscreen, cỡ cửa sổ nhỏ/lớn, chữ lớn,
login/setup/trạng thái/lỗi; webcam và exe thật là các bước riêng, không suy ra từ ảnh mock.
Chưa kiểm điều nào thì ghi rõ; không đánh dấu hoàn thành UI chỉ từ bản đặc tả này.

## Căn cứ tra cứu

Tra ngày 18/10/2026 trên UI UX Pro Max commit `56ea9cf` đã cài trong repo:
`minimal light dashboard --domain style` → Minimalism & Swiss Style;
`keyboard focus modal --domain ux` → Focus States;
`error summary validation --domain ux` → Focusable Error Summary/Error Messages;
`responsive navigation --stack react` → semantic HTML.
Nhận nguyên tắc tối giản, focus, lỗi theo trường và thành phần đúng ngữ nghĩa; giữ bảng màu,
font và bo góc KLTN, không sao chép nguyên palette/type của kết quả tìm kiếm.
