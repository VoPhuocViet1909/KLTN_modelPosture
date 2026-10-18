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

## Đăng nhập (giai đoạn 3)

```powershell
.venv\Scripts\python posture_model/app.py --side 1 --front 0 --api-base-url http://localhost:8080
```

- Mở app → màn **Đăng nhập** (email, mật khẩu, "Ghi nhớ đăng nhập", "Dùng không đăng nhập"). Địa chỉ backend lấy từ `api_base_url`
  trong `app_config.json` (hoặc `--api-base-url`, chỉ trong RAM). Dùng lại `api_session.py`; sau đăng nhập tự bật config sync.
- **Ghi nhớ:** chỉ lưu **refresh token** (+ email, địa chỉ máy chủ) vào Windows Credential Manager qua `keyring`
  (`WinVaultKeyring`, mục `KLTN Posture Monitor / session`). Không lưu mật khẩu, không lưu access token. Refresh token dùng một lần,
  nên mỗi lần máy chủ cấp cặp mới app ghi đè token mới. Mở app lần sau: tự làm mới phiên rồi vào thẳng.
- **Lỗi tiếng Việt:** sai email/mật khẩu · tổ chức tạm ngưng (chỉ khi máy chủ trả 403/`ORGANIZATION_*`; hiện login/refresh vẫn trả
  401 chung nên chưa phân biệt được, xem team-sync mục 6) · không kết nối được máy chủ · máy chủ lỗi · thiếu/sai `api_base_url`.
- **Đăng xuất** (menu khay): dừng engine (gửi nốt lô cuối) → `POST /auth/logout` → xóa keyring → về màn đăng nhập. Dữ liệu chưa gửi
  vẫn ở outbox. Mỗi tài khoản một outbox riêng `out/outbox-<userId>.db` (trừ khi truyền `--outbox`), để dữ liệu người này không chặn người kia.
- **Hết phiên** (refresh bị từ chối/thu hồi/mất kết nối lúc làm mới): về màn đăng nhập kèm thông báo; token hỏng bị xóa khỏi keyring.
- **Dùng không đăng nhập:** chỉ nhắc tại chỗ; không ghi outbox, không gửi, không config sync. Menu khay có "Đăng nhập…" để quay lại.
- Không nhớ đăng nhập → thoát app thì gọi `/auth/logout` để thu hồi phiên.

Kiểm với backend thật: `python posture_model/ui/login_e2e.py login|resume|lost <thư mục>` (cần `DEMO_PW`, backend `docker compose up -d`
với `AUTH_SEED_DEMO=true`); logic có kiểm thử riêng không cần mạng: `python posture_model/tests/test_login.py`.

## Hiệu chỉnh có kiểm hợp lệ

Trước đây chỉ cần cam hông thấy người ≥ 10 khung là lưu baseline, nên người gù lưng/ngồi lệch lúc hiệu chỉnh bị lấy tư thế sai làm chuẩn.
Nay hết `calib_sec` (10 giây) engine gọi `calibration.evaluate` trên **góc thô** (chưa trừ baseline, từ `sequence_angles`). Không đạt thì
**không lưu baseline**, phát `CALIBRATION_FAILED`, chờ 3 giây rồi tự đo lại; đạt mới phát `CALIBRATED` như cũ.

Quy ước góc (`frame_angles`): thân (trunk) dương khi nghiêng ra trước, âm khi ngả sau; cổ (neck) là góc so với thân, dương khi cúi, âm khi ngửa.
So bằng đúng hàm của teacher RULA nhóm B (`score_neck`, `score_trunk`): điểm 1 = thẳng, 2 = ≤ 20°, ≥ 3 = sai.

| Kiểm tra (mã lỗi) | Điều kiện đạt | Khóa cấu hình (`app_config.json`) |
| --- | --- | --- |
| Thấy người ở cam hông (`SIDE_NOT_VISIBLE`) | tai–vai–hông (visibility ≥ 0,5) ở ≥ 80% số khung, tối thiểu 10 khung | `calib_visible_ratio` = 0.8 |
| Lưng thẳng (`BACK_NOT_STRAIGHT`) | trung vị góc thân: điểm ≤ 2 (≤ 20°) và không ngả sau quá 15° (`LEAN_BACK_TOL` của teacher) | `calib_max_score` = 2 |
| Cổ thẳng (`NECK_NOT_STRAIGHT`) | trung vị góc cổ: điểm ≤ 2 (−15° … 20°; ngửa quá 15° là điểm 4) | `calib_max_score` = 2 |
| Ngồi yên (`MOVING_TOO_MUCH`) | độ lệch chuẩn góc cổ và góc thân ≤ 5° | `calib_still_deg` = 5.0 |
| Thấy hai vai (`SHOULDERS_NOT_VISIBLE`), nếu cam laptop bật | `shoulder_tilt` hợp lệ ở ≥ 50% số khung | `calib_front_ratio` = 0.5 |
| Khoảng cách (`TOO_CLOSE`), nếu đo được | khoảng cách mắt–màn hình ≥ `distance_on_cm` (không đo được thì không chặn) | `distance_on_cm` (đã có) |

- Lưng/cổ/ngồi yên chỉ được đánh giá khi cam hông thấy người đủ (ngược lại chỉ báo "không thấy người", tránh kết luận bậy từ dữ liệu thiếu).
- Các khóa `calib_*` mới **chỉ ở máy**: `apply_remote` từ chối nếu máy chủ gửi, và `config.schema.json` (3 bản sao theo team-sync mục 2.5) **không đổi**;
  giá trị sai kiểu/ngoài khoảng bị bỏ qua, dùng mặc định.
- `CALIBRATION_FAILED {reasons:[{code, message}], checks:{mã: true/false/null}}` ghi vào `events.jsonl` và phát cho giao diện, nhưng
  `Sender` **không gửi** lên backend (không thuộc 10 loại event của ingestion, gửi sẽ bị đánh dấu `dead`). CLI `realtime_app.py` in lý do ra console.
- Engine: `on_state` có thêm `calib` (`stage` = `measuring`/`failed`, `checks`, `reasons`, `retryLeft`, `frontAvailable`, `frontSkipped`)
  và `frontSkipped`; `engine.request_skip_front()` bỏ qua cam laptop (không đo lệch vai và khoảng cách; `request_recalibrate()` bật lại).
- Giao diện (`ui/calibration_view.py`): hướng dẫn "Ngồi thẳng lưng, mắt nhìn màn hình, đặt tay lên đùi hoặc bàn, không gõ phím trong 10 giây",
  danh sách kiểm tra cập nhật nửa giây một lần (✓ đạt / ✗ chưa đạt / vòng đứt nét = đang kiểm tra; luôn có icon + chữ), khi không đạt hiện lý do cụ thể
  + "Làm lại sau N giây", nút **Hiệu chỉnh lại** (cũng ở menu khay) và **Bỏ qua camera laptop** (chỉ hiện khi cam laptop mở); đã bỏ qua thì cửa sổ chính ghi rõ
  "Đang chạy không đo lệch vai và khoảng cách".
- Kiểm thử: `python posture_model/tests/test_calibration.py` (đạt, gù lưng, cúi cổ, ngả sau/ngửa cổ, cử động nhiều, không thấy người, thiếu vai, quá gần,
  ngưỡng cấu hình, engine bắt gù rồi cho đạt khi ngồi thẳng, engine không lưu baseline nếu không bao giờ đạt, bỏ qua cam laptop);
  `python posture_model/ui/calib_e2e.py gu|vai <thư mục>` chụp màn hình qua đường ống Qt đầy đủ.

## Cấu trúc

| Đường dẫn (`posture_model/`) | Việc |
| --- | --- |
| `engine.py` | `PostureEngine`: toàn bộ vòng lặp camera → model → cảnh báo → outbox (tách từ `realtime_app.py`, logic giữ nguyên). `EngineListener` phát khung hình (chỉ khi `want_frames`), trạng thái GOOD/BAD/AWAY/CALIBRATING, cảnh báo, metrics, tình trạng gửi, cấu hình mới. |
| `realtime_app.py` | CLI cũ chạy bằng lõi mới (`--login`, `--sync-config`, `--no-gui`… giữ nguyên). |
| `app.py`, `ui/controller.py` | Điểm vào Qt; engine chạy trong `QThread`, nói chuyện với giao diện bằng signal (`ui/bridge.py`). |
| `ui/design_tokens.json`, `ui/theme.qss` | Màu, trạng thái, bo góc, cỡ chữ chép từ `GIT_frontend/src/index.css` + design-system (ghi nguồn trong file). `theme.qss` sinh bằng `python ui/build_theme.py`. |
| `ui/labels.json` | Tên trạng thái/cảnh báo khớp `GIT_frontend/src/lib/labels.ts`; lời nhắc theo bảng 3.5 kế hoạch ngôn ngữ. `notifier.py` đọc file này. |
| `credentials.py`, `login_service.py`, `ui/login_view.py` | Kho khóa (keyring), logic đăng nhập/mở lại phiên/đăng xuất + thông báo lỗi tiếng Việt, màn đăng nhập. `api_session.py` được mở rộng tương thích: `AuthError.kind`, `ApiSession.resume/logout/lost`, callback khi token xoay vòng. |
| `calibration.py`, `ui/calibration_view.py` | Kiểm hợp lệ hiệu chỉnh (ngưỡng `calib_*`) và màn hiệu chỉnh. |
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
| keyring | **25.7.0** (phát hành 16/11/2025) | Bản stable mới nhất trên PyPI và GitHub release (`v25.7.0`); `requires_python >=3.9`; MIT; trên Windows dùng backend `WinVaultKeyring` (Credential Manager) qua `pywin32-ctypes`, không cần cài thêm. Credential Manager giới hạn 2560 byte mỗi mục; refresh token của backend dài 43 ký tự nên đủ chỗ. Rủi ro: máy không có kho khóa → app vẫn chạy nhưng không nhớ được đăng nhập. | [PyPI metadata 25.7.0](https://pypi.org/pypi/keyring/25.7.0/json), [release v25.7.0](https://github.com/jaraco/keyring/releases/tag/v25.7.0), [kho mã](https://github.com/jaraco/keyring) |
| Be Vietnam Pro | bản trong `google/fonts` (OFL) | Font duy nhất của web; Regular/Medium/SemiBold/Bold; kèm `OFL.txt` | [google/fonts ofl/bevietnampro](https://github.com/google/fonts/tree/main/ofl/bevietnampro) |
| Lucide icons | SVG từ `lucide-icons/lucide` (ISC), bản mới nhất 1.59.0 | Cùng bộ icon với web (`lucide-react`) | [lucide-icons/lucide](https://github.com/lucide-icons/lucide), [license](https://github.com/lucide-icons/lucide/blob/main/LICENSE) |

Dữ kiện lấy từ nguồn ở trên; "bản stable mới nhất" và nhận định rủi ro là đánh giá của người làm. Kết quả chạy thật ở máy
phát triển: Python 3.11.9, Windows 11, mediapipe 1.1.1, onnxruntime 1.31.0, opencv-python 5.0.0.93, numpy 2.4.6.
