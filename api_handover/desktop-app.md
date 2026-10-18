# Desktop App có giao diện (PySide6) — cách chạy, cấu trúc, phiên bản

Cập nhật 18/10/2026. Kế hoạch: `TaiLieu/KeHoach_DesktopApp.md`; ngôn ngữ thiết kế: `TaiLieu/KeHoach_NgonNguThietKe.md`.
Tiến độ ghi ở `DoAnTotNghiep_BE/.codex/skills/kltn-project/SKILL.md`. Không đổi API/backend.

## Chạy

Người dùng: nhấp đúp **`MoUngDung.vbs`** ở gốc repo (dùng venv local), hoặc mở
**`posture_model/dist/PostureMonitor/PostureMonitor.exe`** sau khi đóng gói; giữ nguyên cả thư mục portable.
Không cần nhập tham số mỗi lần. Lần đầu app hiện **Thiết lập camera / máy chủ**: chọn số webcam,
bấm **Kiểm tra hình**, lưu; app nhớ bằng QSettings của tài khoản Windows. Camera trước `-1` là tắt.
Đổi camera bằng nút thiết lập ngay trong app; đổi máy chủ cần đăng xuất trước.
Ảnh kiểm tra là ảnh tĩnh, không lưu/gửi; không tự nhận diện camera nào đặt hông.

Kế hoạch và tiêu chí nghiệm thu còn lại: [desktop-next-steps.md](desktop-next-steps.md).

Lệnh dưới đây dành cho phát triển/ghi đè lựa chọn đã nhớ:

```powershell
python -m venv .venv                       # trong thư mục KLTN_modelPosture; không cài vào Python toàn máy
.venv\Scripts\python -m pip install -r posture_model/requirements.txt
.venv\Scripts\python posture_model/app.py --side 1 --front 0      # giao diện
.venv\Scripts\python posture_model/realtime_app.py --side 1 --front 0   # CLI cũ (cửa sổ OpenCV), vẫn dùng được
```

Cửa sổ chính (~420×560) không hiện camera; nút **Xem camera** mở khung hình có vẽ khung xương (hình không lưu, không gửi).
Cửa sổ camera (`ui/camera_view.py`, mặc định 960×560) co hai hình vừa vùng hiển thị, giữ tỉ lệ, thấy trọn khung gốc (không cắt trái/phải); đủ rộng thì xếp ngang,
hẹp thì xếp dọc, co lại khi đổi kích thước (`layout_rects`, `FitView`). Trước đây ghép 2 hình thành ảnh ~1070 px trong QLabel ~560 px nên chỉ thấy phần giữa
(camera hông mất bên trái, camera laptop mất bên phải). Test: `python posture_model/tests/test_camera_view.py` (hình hiển thị chứa đủ 4 góc của khung gốc ở nhiều cỡ cửa sổ).
Đóng cửa sổ = thu xuống khay; menu khay: **Mở**, **Hiệu chỉnh lại**, **Thoát**. Chọn camera tạm bằng `--side`, `--front`
(`--side-video`, `--front-video` để chạy thử trên video). Ngưỡng cảnh báo chỉ sửa trên web, app chỉ nhận và hiển thị.

### Build portable cho Windows

Trong venv dự án có đủ `requirements.txt`, cài công cụ build `pyinstaller==6.22.3`, rồi chạy `posture_model/build_exe.bat`.
Script đóng gói `app.py` bằng `--windowed`, gồm model, schema, Qt UI/font/icon và backend Windows keyring.
Không đưa cấu hình local có token hoặc dữ liệu runtime vào gói. Bản portable chưa có installer/updater.
PyInstaller 6.22.3 đã đối chiếu metadata PyPI ngày 18/10/2026 (Python >=3.8,<3.16, hỗ trợ Python 3.11;
GPLv2-or-later với ngoại lệ phân phối ứng dụng); đây là dependency build, không phải runtime mới của app.
Nguồn: https://pypi.org/pypi/pyinstaller/6.22.3/json, https://pyinstaller.org/en/stable/usage.html;
QSettings dùng API Qt có sẵn: https://doc.qt.io/qtforpython-6/PySide6/QtCore/QSettings.html.

Kiểm 18/10/2026: build portable thành công (~433 MiB), mở `.exe` hiện màn **Thiết lập Posture Monitor**
trên Windows, tiến trình phản hồi; đã tạo shortcut Desktop trên máy phát triển. Không kèm cấu hình/token/outbox/log.
`test_setup.py` đạt (validate/lưu lựa chọn/preview nền/giải phóng camera/đổi camera/hủy), login 9/9,
engine 4/4, calibration 16/16 đạt. Qt E2E bằng video/landmark giả: CALIBRATING→GOOD→BAD→GOOD,
nhịp UI tối đa 47 ms. Tokens/labels được đối chiếu trực tiếp với repo `FE/KLTN_dashboard`, đạt.
Chưa nghiệm thu webcam thật, thay camera trong phiên gửi telemetry thật, inference từ `.exe`,
hoặc máy Windows chưa cài Python. Kết quả mở màn setup không thay cho các phép kiểm này.

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

Quy ước góc (`frame_angles`): thân (trunk) dương khi nghiêng ra trước, âm khi ngả sau; `neck` thô = góc(vai→tai so với đứng) − trunk;
**góc đầu so với phương thẳng đứng = neck + trunk** (vector vai→tai so với phương thẳng đứng, không trừ thân).

| Kiểm tra (mã lỗi) | Điều kiện đạt (trung vị cửa sổ hiệu chỉnh) | Khóa cấu hình (`app_config.json`) |
| --- | --- | --- |
| Thấy người ở cam hông (`SIDE_NOT_VISIBLE`) | tai–vai–hông (visibility ≥ 0,5) ở ≥ 80% số khung, tối thiểu 10 khung | `calib_visible_ratio` = 0.8 |
| Lưng thẳng (`BACK_NOT_STRAIGHT`) | góc thân từ −20° đến +10° (+ = nghiêng ra trước) | `calib_min_trunk_deg` = −20, `calib_max_trunk_deg` = 10 |
| Cổ thẳng (`NECK_NOT_STRAIGHT`) | góc **đầu so với phương thẳng đứng** từ 0° đến +30° (+ = đầu ra trước vai) | `calib_min_neck_deg` = 0, `calib_max_neck_deg` = 30 |
| Ngồi yên (`MOVING_TOO_MUCH`) | độ lệch chuẩn góc cổ và góc thân ≤ 5° | `calib_still_deg` = 5.0 |
| Thấy hai vai (`SHOULDERS_NOT_VISIBLE`), nếu cam laptop bật | `shoulder_tilt` hợp lệ ở ≥ 50% số khung | `calib_front_ratio` = 0.5 |
| Khoảng cách (`TOO_CLOSE`), nếu đo được | khoảng cách mắt–màn hình ≥ `distance_on_cm` (không đo được thì không chặn) | `distance_on_cm` (đã có) |

### Vì sao "Cổ thẳng" không còn dùng `neck` thô / điểm RULA tuyệt đối (sửa 18/10/2026)

Bản đầu so điểm RULA (cổ ≤ 20°) với `neck` thô và báo `NECK_NOT_STRAIGHT` (+27°) cho người ngồi thẳng, tựa lưng nhẹ. Hai nguyên nhân:
1. điểm tai của MediaPipe luôn nằm trước vai nên góc thô lúc ngồi chuẩn đã ~15–27° (không phải ~0°);
2. ngả lưng (trunk âm) làm `neck` = đầu − thân tăng dù đầu vẫn thẳng (đầu 20°, ngả 12° → neck 32°).

RULA lúc chạy dùng góc **đã trừ baseline** nên không gặp lỗi này; chỉ bước kiểm hiệu chỉnh (chưa có baseline) cần ngưỡng tuyệt đối, và
ngưỡng đó phải lấy từ dữ liệu. `calib_max_score` (dùng chung) đã bỏ, thay bằng `calib_max_neck_deg` và `calib_max_trunk_deg`
(+ hai cận dưới `calib_min_*`); khóa `calib_max_score` cũ trong `app_config.json` bị bỏ qua.

### Nguồn số liệu của ngưỡng (tính ngày 18/10/2026, chạy lại bằng `python posture_model/calib_threshold_stats.py`)

`posture_model/frames_labeled.csv` (58.461 khung, 3 người, 6 phiên) **đã trừ baseline** (trung vị khung GOOD ≈ 0°) nên chỉ cho độ lệch so với
chuẩn của chính người đó, không cho góc thô tuyệt đối. Góc thô khung GOOD được **tái dựng** = góc đã trừ baseline của khung GOOD + baseline thô
của đúng phiên. Baseline thô lấy từ hai nguồn có thật:

- output notebook Kaggle `ChayKaggle/notebook067dc83140.ipynb` (cell 10), 7 nhóm (người × phiên × độ phân giải): (neck, trunk) = (37,0; −15,6), (25,0; −3,4),
  (23,0; −7,3), (22,8; −1,5), (17,5; −1,3), (22,8; −1,0), (19,4; −0,4) → **đầu so với đứng** = 21,4 / 21,6 / 15,7 / 21,3 / 16,2 / 21,8 / 19,0;
- hai baseline ngồi chuẩn chạy thật: `api_handover/sample_data/p01_events.jsonl` (neck 24,6; trunk −5,8 → đầu 18,8°) và lần chạy của chủ dự án
  18/10 khi ngồi thẳng tựa lưng nhẹ (neck 26,8; trunk +0,9 → đầu 27,7°). Lần chạy 18/10 đầu tiên (neck 44,7; trunk −9,8 → đầu 34,9°) không dùng vì chưa biết tư thế lúc đó.

| Đại lượng (góc thô, độ) | Tập | p50 | p90 | p95 | p99 |
| --- | --- | --- | --- | --- | --- |
| Đầu so với phương thẳng đứng, khung GOOD | dataset (6 phiên, 12.789 khung) | 19,1 | 23,5 | 25,3 | 27,9 |
| Đầu so với phương thẳng đứng, khung GOOD | dataset + 2 baseline chạy thật (34.729 khung) | 20,8 | 28,9 | **31,2** | 34,8 |
| `neck` thô (vai→tai − thân), khung GOOD | dataset | 22,7 | 34,4 | 36,7 | 40,0 |
| Thân thô, khung GOOD | dataset | −3,2 | 1,2 | 3,5 | 4,8 |

Độ lệch so với chuẩn của chính người đó (từ `frames_labeled.csv` gốc, khung GOOD): đầu p95 6,2°, thân p95 4,8°; baseline 6 phiên khác nhau tới 15,7–21,8° nên không thể dùng "gần 0°".

- **`calib_max_neck_deg` = 30:** p95 khung GOOD = 31,2° làm tròn xuống bội 5°. Ngưỡng này đủ rộng cho ngồi chuẩn đã đo 27,7°. Chỉ dùng dataset thì p95 = 25,3° và sẽ loại nhầm ca 27,7°.
  Khung BAD tái dựng vượt 30°: FORWARD_HEAD 91,6%, LEAN_FORWARD 87,3%, SLOUCH 75,4% (SLOUCH chủ yếu là gù thân nên do kiểm lưng bắt).
- **`calib_min_neck_deg` = 0:** tai không ra sau vai (GOOD p0,1 = 4,5°).
- **`calib_min_trunk_deg` = −20:** khung GOOD thô < −15°: 10,6% (chủ yếu phiên P01_S01 tựa lưng, baseline −15,6°) nên ngưỡng −15° cũ loại nhầm người tựa lưng; < −20°: 0,11%.
  Khung LEAN_BACKWARD thô < −20°: 89,9%.
- **`calib_max_trunk_deg` = 10 (đổi từ 20 theo chính số liệu này):** khung GOOD thô > 10°: chỉ 0,02% (> 20°: 0%; p99 thân thô GOOD 4,8°; baseline thân thô lớn nhất đã đo +0,9°).
  Ở ngưỡng 20° có 73% khung SLOUCH và 38,4% khung LEAN_FORWARD lọt qua; ở 10° chỉ còn 20,5% SLOUCH và 1,4% LEAN_FORWARD lọt. Nếu người dùng thật hay bị loại nhầm thì nới bằng `calib_max_trunk_deg`.
- **Hạn chế:** chỉ 3 người, 6 phiên dataset + 2 baseline chạy thật; baseline P01_S01 có hai độ phân giải nhưng đầu so với đứng gần như nhau (21,4 và 21,6). Các ngưỡng cần chỉnh lại khi có thêm người.

### Còn lại

- Lưng/cổ/ngồi yên chỉ được đánh giá khi cam hông thấy người đủ (ngược lại chỉ báo "không thấy người", tránh kết luận bậy từ dữ liệu thiếu).
- Các khóa `calib_*` **chỉ ở máy**: `apply_remote` từ chối nếu máy chủ gửi, và `config.schema.json` (3 bản sao theo team-sync mục 2.5) **không đổi**;
  giá trị sai kiểu/ngoài khoảng bị bỏ qua, dùng mặc định.
- `CALIBRATION_FAILED {reasons:[{code, message}], checks:{mã: true/false/null}, details:{mã: "số đo + ngưỡng"}}` ghi vào `events.jsonl` và phát cho giao diện, nhưng
  `Sender` **không gửi** lên backend (không thuộc 10 loại event của ingestion, gửi sẽ bị đánh dấu `dead`).
- **Chẩn đoán:** mỗi lần kiểm xong engine in ra console số đo và ngưỡng từng mục (cả khi đạt), ví dụ
  `[KHÔNG ĐẠT] Cổ thẳng: đầu +45.0° so với phương thẳng đứng (cho phép +0° … +30°; + = đầu ra trước vai); cổ so với thân +45.0° (chỉ để tham khảo)`.
- Engine: `on_state` có thêm `calib` (`stage` = `measuring`/`failed`, `checks`, `reasons`, `retryLeft`, `frontAvailable`, `frontSkipped`)
  và `frontSkipped`; `engine.request_skip_front()` bỏ qua cam laptop (không đo lệch vai và khoảng cách; `request_recalibrate()` bật lại).
- Giao diện (`ui/calibration_view.py`): hướng dẫn "Ngồi thẳng lưng, mắt nhìn màn hình, đặt tay lên đùi hoặc bàn, không gõ phím trong 10 giây",
  danh sách kiểm tra cập nhật nửa giây một lần (✓ đạt / ✗ chưa đạt / vòng đứt nét = đang kiểm tra; luôn có icon + chữ), khi không đạt hiện lý do cụ thể
  + "Làm lại sau N giây", nút **Hiệu chỉnh lại** (cũng ở menu khay) và **Bỏ qua camera laptop** (chỉ hiện khi cam laptop mở); đã bỏ qua thì cửa sổ chính ghi rõ
  "Đang chạy không đo lệch vai và khoảng cách".
- Kiểm thử: `python posture_model/tests/test_calibration.py` (16 ca: đạt, ngồi thẳng tựa lưng 10–15° tai trước vai 20° phải đạt, cúi đầu 45° bị bắt, gù lưng, ngả sau/ngửa đầu,
  cử động nhiều, không thấy người, thiếu vai, quá gần, ngưỡng cấu hình, chẩn đoán, engine bắt gù rồi cho đạt, không lưu baseline nếu không bao giờ đạt, bỏ qua cam laptop);
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
# Chia sẻ camera từ giao diện (18/10/2026)

Ở bản nguồn `feat/desktop-camera-sharing`, đăng nhập và hoàn tất hiệu chỉnh, sau đó mở
**Chia sẻ camera lên web**, chọn **Camera hông** hoặc **Camera trước**, bấm **Bật chia sẻ**.
Camera trước chỉ chọn được khi đang hoạt động. Nếu chưa tìm thấy FFmpeg, chọn tệp
`ffmpeg.exe` đã chuẩn bị trên máy; app nhớ đường dẫn, không nhớ lựa chọn bật chia sẻ.

Đăng nhập Dashboard cùng tài khoản → Tổng quan → Camera của bạn → chọn đúng thiết bị/góc
→ **Xem camera**. Chỉ phát một góc mỗi lần; bấm **Dừng chia sẻ** trước khi đổi góc.
Dừng chia sẻ vẫn giữ giám sát, đăng nhập và outbox. Thu cửa sổ xuống khay vẫn chia sẻ;
đăng xuất, đổi thiết lập camera hoặc thoát app dừng publisher. Phiên mới mặc định không chia sẻ.
Lỗi truyền hình không làm dừng phân tích tư thế. Không ghi hình, không âm thanh.

Tái sử dụng media-token/RTSP hiện có, không thay API hay telemetry. CLI vẫn dùng
`--stream-camera side|front`. Chưa đóng gói lại portable cho tính năng này; webcam/front/LAN
cần nghiệm thu riêng. Kiểm giả lập runnable: `python posture_model/tests/test_camera_sharing.py`.

