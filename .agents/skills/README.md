# Skill dùng chung cho web và desktop

Đã cài ngày 18/10/2026, giữ giấy phép MIT. Điều chỉnh tương thích Codex duy nhất:
bỏ khóa frontmatter `argument-hint` của Ponytail (validator Codex chưa hỗ trợ); nội dung hướng dẫn giữ nguyên.

| Skill | Nguồn | Commit đã ghim | Thư mục nguồn |
| --- | --- | --- | --- |
| UI UX Pro Max | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill | `56ea9cf174ed86786187daa9de0e6247cb0747e4` | `.claude/skills/ui-ux-pro-max` |
| Ponytail | https://github.com/DietrichGebert/ponytail | `09c434ab73ca43761c5d8b0c5d341926c2fba710` | `skills/ponytail` |

Hai repo Dashboard và Desktop App đều mang bản sao trong `.agents/skills/`, không cần cài global.
Commit cả thư mục này cùng `AGENTS.md` để người clone repo nhận đủ skill, dữ liệu, script và giấy phép.
Khi cập nhật, cập nhật cả hai repo cùng phiên bản và chạy lại kiểm tra; không tự lấy `main` mỗi lần dùng.
Codex có thể nạp skill từ lượt kế tiếp; `AGENTS.md` cũng chỉ đường đọc trực tiếp khi công cụ không tự phát hiện.

## Dùng UI UX Pro Max

Đọc `ui-ux-pro-max/SKILL.md`; chạy Python 3 từ gốc repo, không cần pip/npm:

```powershell
python .agents/skills/ui-ux-pro-max/scripts/search.py "keyboard focus modal" --domain ux
python .agents/skills/ui-ux-pro-max/scripts/search.py "health dashboard minimal light" --design-system -p KLTN
```

Thay `.agents/...` bằng đường dẫn tuyệt đối khi chạy từ thư mục khác.
Ví dụ `${CLAUDE_PLUGIN_ROOT}` trong hướng dẫn upstream là đường dẫn dành cho plugin Claude;
ở đây dùng trực tiếp đường dẫn `.agents/skills/ui-ux-pro-max/scripts/search.py`.
Không dùng `--persist` cho đến khi đã chọn và kiểm tra kết quả, để tránh ghi đè định hướng dự án.

Chuẩn KLTN-DS-1: đọc `.agents/skills/design-system/SKILL.md` trước khi sửa UI ở cả hai repo.
Bản skill và script kiểm đồng bộ phải giống nhau; chạy theo mục 8 trong skill trước khi sửa màn hình.
Web dùng React/Tailwind/shadcn hiện có.
Desktop: dùng PySide6 và token hiện có; chưa có stack PySide6 trong cơ sở dữ liệu skill, không chọn WPF/React thay thế.
Hướng chung đã chốt: **sáng, gọn, dễ dùng, tiếng Việt**. Gợi ý từ skill không tự động thay các quyết định này.

## Dùng Ponytail

Đọc `ponytail/SKILL.md`, hoặc yêu cầu AI: “Dùng Ponytail, sửa phần này với thay đổi nhỏ nhất”.
Đây là hướng dẫn cho AI, không có ứng dụng hoặc lệnh CLI cần cài thêm.
Giữ đủ chức năng được yêu cầu, validation, bảo mật, accessibility và kiểm chứng phù hợp.
