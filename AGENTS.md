# Hướng dẫn AI cho Desktop App

Đọc tiến độ và quy tắc dự án tại repo backend:
https://github.com/luongtan204/DoAnTotNghiep_BE/tree/main/.codex/skills
Trong workspace này: `../BE/DoAnTotNghiep_BE/.codex/skills/{kltn-project,team-sync}/SKILL.md`.

- Trước khi thiết kế/sửa giao diện: đọc `.agents/skills/design-system/SKILL.md` (KLTN-DS-1 dùng chung
  với web), sau đó tra `.agents/skills/ui-ux-pro-max/SKILL.md` theo vấn đề cụ thể.
  Khi đổi quy tắc/token/nhãn chung, đồng bộ hai repo và chạy `design-system/scripts/check_sync.py` trước khi sửa UI.
  Hướng đã chọn: sáng, gọn, dễ dùng, tiếng Việt. Dùng PySide6 hiện có; không đổi sang webview.
  Giữ màu/font ở `posture_model/ui/design_tokens.json`, nhãn ở `ui/labels.json` đồng bộ web.
  Sinh QSS bằng `posture_model/ui/build_theme.py`, không sửa tay `theme.qss`.
  Skill chưa có stack PySide6: dùng hướng dẫn UX chung, đối chiếu widget Qt thực tế.
- Viết/sửa/review code: đọc `.agents/skills/ponytail/SKILL.md`; thay đổi ít nhất nhưng giải quyết đủ yêu cầu.
  Không bỏ validation, bảo mật, accessibility, hiệu chỉnh camera hoặc xử lý tránh mất dữ liệu.
- Giữ vòng đời camera, luồng worker/UI, tín hiệu controller, khay hệ thống và hộp thư SQLite.
  Không tự thay hợp đồng API, model hoặc ngưỡng hiệu chỉnh khi chỉ sửa giao diện.
- Chạy kiểm thử phù hợp; phân biệt Qt offscreen/video giả với kiểm chứng webcam và bản exe thật.
- Nguồn, phiên bản và cách chạy skill ở `.agents/skills/README.md`. Giữ các skill trong Git để chia sẻ.
