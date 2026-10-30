# Giai đoạn 1 – Desktop App: cảnh báo, khoảng cách, thông báo

`realtime_posture.py` giữ nguyên làm bản cũ. Bản mới chạy bằng `realtime_app.py`.

## Cài đặt

```
pip install -r requirements.txt
```

Lần chạy đầu, app tự tải `face_landmarker.task` (để đo khoảng cách bằng mống mắt), giống `pose_landmarker_full.task`.

## Chạy

```
python realtime_app.py --side 1 --front 0                       # cam hông = webcam 1, cam laptop = webcam 0
python realtime_app.py --side http://192.168.1.5:8080/video --front 0   # điện thoại (IP Webcam) làm cam hông
python realtime_app.py --side-video hong.mp4 --no-gui           # chạy thử trên video, không mở cửa sổ
python realtime_app.py ... --log out/log.csv                    # ghi CSV từng mẫu (có thêm cột khoảng cách)
```

Phím `q` để thoát, `c` để hiệu chỉnh lại. Khi hiệu chỉnh, ngồi thẳng và nhìn màn hình 10 giây.

## Các file mới

| File | Việc |
| --- | --- |
| `alerts.py` | `AlertTracker` (ALERT_STARTED / REPEATED / RESOLVED + thời lượng), `PresenceTracker` (USER_AWAY / BACK), `Reminders` (SIT_TOO_LONG, EYE_BREAK), `EventLog` (ghi `out/events.jsonl`) |
| `distance.py` | Khoảng cách mắt–màn hình từ đường kính mống mắt (11,7 mm), dự phòng bằng khoảng cách 2 mắt |
| `distance_check.py` | Đo sai số khoảng cách ở các mốc 40–80 cm, ghi `distance_check.csv`, in MAE |
| `notifier.py` | Thông báo theo mức độ: LOW = banner + toast, MEDIUM = + bíp, HIGH = + hộp thoại |
| `app_config.py` | Đọc `app_config.json`, tự nạp lại khi file đổi (khoảng 2 giây) |
| `realtime_app.py` | Ghép tất cả lại |
| `tests/test_alerts.py` | 10 test cho logic cảnh báo: `python tests/test_alerts.py` |
| `build_exe.bat` | Đóng gói bằng PyInstaller thành `dist\PostureMonitor\PostureMonitor.exe` |

## Cấu hình (`app_config.json`, sửa khi app đang chạy được)

| Khoá | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `alert_sec` / `clear_sec` | 5 / 3 | BAD bao lâu thì cảnh báo, GOOD bao lâu thì coi là đã sửa |
| `repeat_sec` | 240 | Vẫn sai sau bao lâu thì nhắc lại, mức tăng dần LOW → MEDIUM → HIGH |
| `cooldown_sec` | 60 | Hai lần cảnh báo cùng loại gần nhau hơn mức này: vẫn ghi sự kiện nhưng không bật thông báo |
| `distance_on_cm` / `distance_off_cm` | 50 / 55 | Gần hơn 50 cm thì báo, xa hơn 55 cm mới hết báo |
| `calib_distance_cm` | null | Nếu lúc hiệu chỉnh ngồi đúng một khoảng cách đã đo bằng thước (ví dụ 60), app tính tiêu cự chính xác |
| `camera_focal_px` | null | Tiêu cự lấy từ `distance_check.py` (phím `f`) |
| `away_sec` | 30 | Mất người bao lâu thì coi là vắng mặt |
| `sit_limit_min` / `sit_repeat_min` | 30 / 10 | Nhắc đứng dậy |
| `eye_break_min` | 20 | Nhắc nghỉ mắt 20-20-20 |
| `notify_toast` / `notify_sound` / `notify_popup` | true | Bật / tắt từng kiểu thông báo |
| `p_bad_threshold`, `shoulder_tilt_on/off` | null | null = lấy từ `posture_config.json` |

## Sự kiện ghi ra (`out/events.jsonl`, đầu vào cho giai đoạn 2)

`SESSION_START`, `CALIBRATED`, `ALERT_STARTED`, `ALERT_REPEATED`, `ALERT_RESOLVED`, `USER_AWAY`, `USER_BACK`, `REMINDER`, `CONFIG_APPLIED`, `SESSION_END`. Mỗi dòng có `eventId`, `ts` (UTC), `sessionId`, `deviceId`, `alertType`, `severity`, `startedAt`, `endedAt`, `durationSec`, `snapshot` (pBad, góc, lệch vai, khoảng cách), `modelVersion`, `config`.

## Kết quả chạy thử trên video P01 (chỉ cam hông)

- FORWARD_HEAD_01 và LEAN_FORWARD_03: có cảnh báo, thời lượng ngồi sai lần lượt 30,3 s và 20,5 s; tự đóng cảnh báo khi ngồi thẳng lại.
- DISTRACTOR_STRETCH: P(BAD) lên 1,0 trong khoảng 1 giây nhưng không cảnh báo (debounce chặn đúng).
- LEAN_FORWARD_01 (thân ~14°, cổ ~12°): không cảnh báo, vì chính RULA nhóm B cũng chấm GOOD. Cần cân nhắc ngưỡng của teacher.
- Nhắc nghỉ mắt và nhắc đứng dậy bật đúng mốc (thử với 2 và 3 phút).

## Việc còn lại của giai đoạn 1 (cần làm trên máy có webcam)

- [ ] Chạy `distance_check.py`, đo ở 40 / 50 / 60 / 70 cm, lấy bảng sai số cho báo cáo
- [ ] Thử thông báo toast / bíp / hộp thoại trên Windows (`pip install plyer` cho toast)
- [ ] Chạy `build_exe.bat`, thử file .exe
- [ ] Màn hình đăng nhập: làm ở giai đoạn 3, khi đã có Auth Service
