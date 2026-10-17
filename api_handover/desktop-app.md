# Desktop App có giao diện (PySide6) — cách chạy, cấu trúc, phiên bản

Cập nhật 18/10/2026. Kế hoạch: `TaiLieu/KeHoach_DesktopApp.md`; ngôn ngữ thiết kế: `TaiLieu/KeHoach_NgonNguThietKe.md`.
Tiến độ ghi ở `DoAnTotNghiep_BE/.codex/skills/kltn-project/SKILL.md`. Không đổi API/backend.

## Chạy

```powershell
python -m venv .venv                       # trong thư mục KLTN_modelPosture; không cài vào Python toàn máy
.venv\Scripts\python -m pip install -r posture_model/requirements.txt
.venv\Scripts\python posture_model/app.py --side 1 --front 0      # giao diện
.venv\Scripts\python posture_model/realtime_app.py --side 1 --front 0   # CLI cũ (cửa sổ OpenCV), vẫn dùng được
```

Cửa sổ chính (~420×560) không hiện camera; nút **Xem camera** mở khung hình có vẽ khung xương (hình không lưu, không gửi).
Đóng cửa sổ = thu xuống khay; menu khay: **Mở**, **Hiệu chỉnh lại**, **Thoát**. Chọn camera tạm bằng `--side`, `--front`
(`--side-video`, `--front-video` để chạy thử trên video). Ngưỡng cảnh báo chỉ sửa trên web, app chỉ nhận và hiển thị.

## Cấu trúc

| Đường dẫn (`posture_model/`) | Việc |
| --- | --- |
| `engine.py` | `PostureEngine`: toàn bộ vòng lặp camera → model → cảnh báo → outbox (tách từ `realtime_app.py`, logic giữ nguyên). `EngineListener` phát khung hình (chỉ khi `want_frames`), trạng thái GOOD/BAD/AWAY/CALIBRATING, cảnh báo, metrics, tình trạng gửi, cấu hình mới. |
| `realtime_app.py` | CLI cũ chạy bằng lõi mới (`--login`, `--sync-config`, `--no-gui`… giữ nguyên). |
| `app.py`, `ui/controller.py` | Điểm vào Qt; engine chạy trong `QThread`, nói chuyện với giao diện bằng signal (`ui/bridge.py`). |
| `ui/design_tokens.json`, `ui/theme.qss` | Màu, trạng thái, bo góc, cỡ chữ chép từ `GIT_frontend/src/index.css` + design-system (ghi nguồn trong file). `theme.qss` sinh bằng `python ui/build_theme.py`. |
| `ui/labels.json` | Tên trạng thái/cảnh báo khớp `GIT_frontend/src/lib/labels.ts`; lời nhắc theo bảng 3.5 kế hoạch ngôn ngữ. `notifier.py` đọc file này. |
| `ui/fonts/`, `ui/icons/` | Be Vietnam Pro (OFL, Google Fonts) và icon Lucide (ISC) dạng SVG. |

## Kiểm thử

```powershell
python posture_model/tests/test_engine.py        # lõi: video trắng + landmark giả, GOOD→BAD→GOOD, stop/recalibrate
python posture_model/tests/test_ui_assets.py     # tokens/labels khớp web, theme.qss mới, thước dọi
python posture_model/ui/e2e_check.py <thư mục>   # cả đường ống Qt tốc độ thực + ảnh chụp + đo độ đơ giao diện
python posture_model/ui/screenshots.py <thư mục> # ảnh cửa sổ ở từng trạng thái
```

## Phiên bản đã chọn (kiểm ngày 18/10/2026)

| Thành phần | Chọn | Lý do và tương thích | Nguồn chính thức |
| --- | --- | --- | --- |
| PySide6 (Qt for Python) | **6.12.0** (phát hành 08/10/2026) | Bản stable mới nhất trên PyPI (không phải RC/preview); `requires_python >=3.10,<3.16`, máy dùng Python 3.11.9; wheel `win_amd64` có sẵn; giấy phép `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` (dùng cho đồ án theo LGPL). Bản trước: 6.11.2 (18/08/2026), cùng dòng 6.x. Rủi ro: bản `.0` mới ra 10 ngày; nếu gặp lỗi có thể lùi về 6.11.2 (cùng API đang dùng). | [PyPI metadata 6.12.0](https://pypi.org/pypi/PySide6/6.12.0/json), [danh sách bản](https://pypi.org/pypi/PySide6/json), [tài liệu](https://doc.qt.io/qtforpython-6/), [kho mã](https://code.qt.io/cgit/pyside/pyside-setup.git/) |
| Be Vietnam Pro | bản trong `google/fonts` (OFL) | Font duy nhất của web; Regular/Medium/SemiBold/Bold; kèm `OFL.txt` | [google/fonts ofl/bevietnampro](https://github.com/google/fonts/tree/main/ofl/bevietnampro) |
| Lucide icons | SVG từ `lucide-icons/lucide` (ISC), bản mới nhất 1.59.0 | Cùng bộ icon với web (`lucide-react`) | [lucide-icons/lucide](https://github.com/lucide-icons/lucide), [license](https://github.com/lucide-icons/lucide/blob/main/LICENSE) |

Dữ kiện lấy từ nguồn ở trên; "bản stable mới nhất" và nhận định rủi ro là đánh giá của người làm. Kết quả chạy thật ở máy
phát triển: Python 3.11.9, Windows 11, mediapipe 1.1.1, onnxruntime 1.31.0, opencv-python 5.0.0.93, numpy 2.4.6.
