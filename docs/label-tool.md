# Công cụ chấm tay nhãn 6 lớp (A1)

Cập nhật 24/11/2026. Kế hoạch: `GIT_backend/DoAnTotNghiep_BE/docs/ke-hoach-hoan-thien-kltn.md` mục 5.A (A1).
Dùng để chấm nhãn thật cho video người mới, làm chuẩn đánh giá Transformer v4, RF và luật góc ở A2–A3.

## Quy ước

- Video chia thành các đoạn **2,0 giây** liên tiếp từ giây 0. Phần dư cuối video ngắn hơn 2 giây bị bỏ (hai người chấm
  thấy cùng danh sách đoạn, nên ghép cặp tính κ khớp từng đoạn).
- Nhãn: 6 lớp của model v4, tên IN HOA như `posture_config.json`: `GOOD`, `FORWARD_HEAD`, `LEAN_FORWARD`, `SLOUCH`,
  `LEAN_BACKWARD`, `NECK_EXTENSION`, và `UNCLEAR` (không nhìn rõ / không chắc).
- CSV: `video,t_start,t_end,label,rater`. `video` là tên file (không đường dẫn), nên hai người chấm hai bản sao cùng
  video ở thư mục khác nhau vẫn khớp. **Mỗi người chấm một file CSV riêng.**
- Chấm mù: công cụ không hiện dự đoán của model.
- Video thật và CSV nhãn thật **không commit** vào repo (mặc định ghi vào `posture_model/out/`, đã được bỏ qua).

## Chấm

```powershell
cd GIT_KLTN\posture_model
python -m labeling.app --rater A --video D:\video\nguoi01.mp4 D:\video\nguoi02.mp4
# mặc định ghi out\labels_A.csv; đổi bằng --out
```

| Phím | Việc |
| --- | --- |
| `1` … `6` | GOOD, FORWARD_HEAD, LEAN_FORWARD, SLOUCH, LEAN_BACKWARD, NECK_EXTENSION |
| `0` | UNCLEAR |
| Space | phát lại đoạn |
| ← / → | đoạn trước / sau, không đổi nhãn (có thể bỏ qua đoạn để chấm sau) |
| Backspace | bỏ nhãn của đoạn đang xem |
| `N` | tới đoạn chưa chấm kế tiếp |

Mỗi lần gán nhãn là ghi CSV ngay (ghi vào file tạm rồi đổi tên), nên tắt máy giữa chừng không mất phần đã chấm.
**Chấm tiếp:** chạy lại đúng lệnh, công cụ nhảy tới đoạn chưa chấm đầu tiên. Công cụ từ chối ghi vào CSV của người chấm khác
hoặc CSV có đoạn không thuộc các video đang mở (sai video). Đổi thứ tự video trong lệnh thì không sao vì ghép theo tên file và giây.

## Cohen's κ giữa hai người chấm

```powershell
python -m labeling.kappa out\labels_A.csv out\labels_B.csv [--include-unclear] [--json kappa.json]
```

- Ghép cặp theo (video, `t_start`); chỉ tính các đoạn cả hai đã chấm. Mặc định bỏ đoạn mà một trong hai chọn `UNCLEAR` và
  in số đoạn bị bỏ; `--include-unclear` coi `UNCLEAR` là lớp thứ 7.
- In số đoạn trùng, độ đồng thuận quan sát, kỳ vọng ngẫu nhiên, κ kèm khoảng 95% (xấp xỉ đơn giản) và ma trận nhầm lẫn.
  κ là NaN (JSON ghi `null`) khi hai người chỉ dùng đúng một lớp giống nhau hoặc không có đoạn trùng.
- Nhiều hơn hai người chấm thì tính mọi cặp. Gõ sai tên file thì báo lỗi, không im lặng.

## Test

```powershell
cd GIT_KLTN\posture_model
$env:PYTHONUTF8 = "1"; $env:QT_QPA_PLATFORM = "offscreen"
python tests\test_label_tool.py     # 11 test, video tự sinh bằng OpenCV
```

## Giới hạn

- Phím tắt và giao diện chưa thử với người chấm thật trên màn hình thật (chỉ offscreen, gửi phím bằng QTest).
- Đọc video bằng OpenCV: nhảy tới đoạn bằng số khung nên có thể lệch vài khung với video có khung chính thưa (GOP dài).
- Khoảng tin cậy của κ là xấp xỉ; báo cáo cuối nên bootstrap theo video nếu số đoạn ít.
