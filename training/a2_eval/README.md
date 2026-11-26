# A2–A3: đánh giá Transformer v4, Random Forest và luật góc trên người mới

Pipeline chạy ba cách trên cùng video cam hông 90°, so với nhãn chấm tay (công cụ A1), rồi tính chỉ số và khoảng tin cậy.
**Trạng thái:** pipeline đã dựng và kiểm bằng code; **chưa có video người mới**, nên chưa có kết quả đánh giá thật.
Kết quả chạy thử trên P01 (đã nằm trong tập train) chỉ là kiểm code, không dùng làm số liệu báo cáo.

| File | Việc |
| --- | --- |
| `build_v4_dataset.py` | dựng lại bộ cửa sổ v4 tại máy từ video SIDE (P01–P03) đúng quy trình notebook v4 |
| `compare_v4_reference.py` | đối chiếu bộ vừa dựng với `windows_info_v4.csv` và `posture_config.json` |
| `train_rf_v4.py` | LOSO + fit Random Forest v4, so LOSO với `loso_random_forest` trong config |
| `evaluate.py` | chạy Transformer / RF / luật góc trên video, quy về đoạn 2 s, xuất `predictions.csv`, `alerts.csv`, `run_meta.json` |
| `metrics.py` | chỉ số mức đoạn + mức cảnh báo + bootstrap theo người |
| `pipeline.py`, `common.py` | lõi dùng chung (import code của app, không chép) |
| `tests/` | pytest, dữ liệu tự sinh |

## 1. Chuẩn bị video người mới

- Cam hông đặt 90° (ngang vai, như lúc quay train), một người một buổi, tên file bắt đầu bằng mã người, ví dụ
  `P11_nguoi_dung.mp4` (mã `P\d+` dùng làm đơn vị bootstrap; không có mã thì lấy cả tên file).
- **15 giây ngồi chuẩn ở đầu video** (tựa lưng, nhìn giữa màn hình, giữ yên) rồi làm việc tự nhiên 20–30 phút. Mặc định
  hiệu chỉnh lấy giây 3–18 của chính video; muốn hiệu chỉnh bằng clip riêng thì dùng manifest (mục 3).
- Một người nên có ít nhất vài đợt ngồi sai thật (cúi, gù, ngả sau) lẫn đoạn ngồi tốt, nếu không recall/cảnh báo nhầm không có mẫu.
- Không cần ghi nhãn lúc quay. Người chấm không được xem dự đoán của model.

## 2. Chấm nhãn tay bằng `labeling.app` (A1)

Chạy trong `posture_model/`, mỗi người chấm một file CSV riêng:

```
cd posture_model
python -m labeling.app --rater A --video D:\video\P11_nguoi_dung.mp4 --out out\labels_A.csv
```

Phím 1–6 = GOOD, FORWARD_HEAD, LEAN_FORWARD, SLOUCH, LEAN_BACKWARD, NECK_EXTENSION; 0 = UNCLEAR. CSV: `video,t_start,t_end,label,rater`
(đoạn 2 s từ 0, phần dư < 2 s bị bỏ, cùng quy tắc với `evaluate.py`). Hai người chấm thì tính κ bằng `python -m labeling.kappa`.

## 3. Chạy

Chạy trong `training/a2_eval/` (cần `pip install -r ../../posture_model/requirements.txt scikit-learn==1.9.1`).

```
# một lần: dựng dataset v4 tại máy, đối chiếu, train RF
python build_v4_dataset.py            # cần D:\KLTN\video_kaggle_v4; ra work/ (NPZ, windows_info.csv)
python compare_v4_reference.py        # in tỷ lệ khớp; lệch thì DỪNG và báo, không sửa code cho khớp
python train_rf_v4.py                 # ra models/posture_rf_v4.joblib + .meta.json (SHA-256 mọi đầu vào)

# mỗi lần đánh giá
python evaluate.py --videos D:\video\P11_nguoi_dung.mp4 D:\video\P12_nguoi_dung.mp4 --labels ..\..\posture_model\out\labels_A.csv --run lan1
python metrics.py --run out\lan1
```

Manifest (khi cần clip hiệu chỉnh riêng hoặc khoảng khác): CSV `video,person,calib_video,calib_start,calib_end`, cột sau `video`
có thể để trống; dùng `--manifest manifest.csv`. Nhiều người chấm thì thêm `--rater A`.

Đầu ra `out/<run>/`: `predictions.csv` (video, person, t_start, t_end, true_label, transformer, rf, rule, `*_bad`, `*_bad_filtered`,
coverage), `alerts.csv` (method, video, person, t_on, t_off, class, started_at, notify, end_reason), `run_meta.json`
(SHA-256 ONNX/RF/config/video/nhãn, phiên bản thư viện, tham số, hiệu chỉnh từng video), `metrics.json`, `metrics.md`.

## 4. Quy tắc khóa tham số (không dò trên dữ liệu đánh giá)

- Ngưỡng và bộ lọc lấy từ app: `posture_config.json` (`threshold` 0,5, `class_rule`, `window` 20, `fps` 10) và
  `app_config.DEFAULTS` (hysteresis 0,1, `alert_sec` 5, `clear_sec` 3, `repeat_sec`, `cooldown_sec`). Median 5 kết quả giống `engine.py`.
- Đặc trưng, hiệu chỉnh, nhãn teacher, `pick_posture_class`, `AlertTracker` được **import** từ `posture_model/`. Chỉ nhãn lớp phụ
  theo khung (`frame_class`) nằm ở `common.py`, vì app không có và notebook v4 định nghĩa nó.
- Cả ba cách đi qua cùng cửa sổ trượt bước 1 khung (như app), cùng median + hysteresis + `AlertTracker`, cùng
  `pick_posture_class` trên trung bình 5 cửa sổ (Transformer, RF và luật góc đều dùng cách này cho công bằng).
- RF fit lại tại máy theo notebook (2 rừng × 300 cây, `class_weight="balanced"`, seed 0, 24 thống kê); **không phải** model Kaggle.
  Không đổi `engine.py`, `alerts.py`, ONNX, `posture_config.json`.
- Model, NPZ, video, CSV nhãn, kết quả chạy đều nằm trong `.gitignore`: không commit.

## 5. Quy về đoạn 2 giây

Đoạn `t_start = 0, 2, 4, …` (`labeling.session.segments_for`, phần dư < 2 s bỏ). Cửa sổ thuộc đoạn khi **tâm cửa sổ**
(giữa khung đầu và khung cuối) rơi trong `[t_start, t_end)`.

- `*_bad` (thô): 1 nếu ≥ 50% cửa sổ hợp lệ trong đoạn có P(BAD) ≥ ngưỡng (đúng quy tắc `y = pbad ≥ 0,5` của notebook).
- Lớp của đoạn: GOOD nếu `*_bad` = 0; ngược lại là lớp xấu xuất hiện nhiều nhất trong các cửa sổ BAD (hòa → lớp đứng trước
  trong danh sách lớp). Lớp từng cửa sổ = `pick_posture_class` trên trung bình 5 cửa sổ gần nhất.
- `*_bad_filtered`: 1 nếu ≥ 50% cửa sổ có trạng thái sau lọc rõ ràng (GOOD/BAD/CANH BAO, bỏ trạng thái "…") là BAD; rỗng nếu không có.
- Luật góc: `p_bad` = tỉ lệ khung BAD theo `rula_frame_label`; xác suất lớp = tần suất lớp phụ của các khung BAD. Khác lúc train:
  cửa sổ nhãn lẫn không bị loại, lớp lấy theo số đông thay vì ngưỡng 70%, vì lúc chạy phải có đáp án.
- Cửa sổ hợp lệ: ≥ 80% khung có cổ/thân hữu hạn và không phi lý (`quality.angles_ok`), hông hiện rõ (vis ≥ 0,3). Đoạn có < 50% cửa sổ
  hợp lệ (hoặc không cửa sổ nào) là `NO_POSE`, không tính vào điểm. Giây đầu video chưa đủ 20 khung nên chưa có cửa sổ.

## 6. Chỉ số

Mức đoạn (bỏ `UNCLEAR`, `NO_POSE`, đoạn chưa có nhãn; in số bỏ): accuracy, macro-F1 6 lớp (trung bình F1 các lớp có trong nhãn tay),
ma trận nhầm lẫn (hàng = nhãn tay), F1 lớp BAD (BAD thật = nhãn tay khác GOOD).

Mức cảnh báo (trạng thái sau lọc, từ `alerts.csv`): cảnh báo nhầm/giờ (cảnh báo bật trong đoạn nhãn GOOD ÷ số giờ đã chấm),
recall theo đợt ngồi sai (chuỗi đoạn BAD liên tiếp dài ≥ `alert_sec` của app; GOOD/UNCLEAR/NO_POSE cắt đợt), độ trễ từ đầu đợt tới
lúc bật (0 nếu đã bật sẵn). Mọi cảnh báo `ALERT_STARTED` đều tính, kể cả khi `notify=False` (đang trong cooldown).

Khoảng tin cậy 95%: bootstrap percentile **theo người** (lấy mẫu có hoàn lại các người, gộp, tính lại), 2000 lần, seed 0. Dưới 2 người thì
không có khoảng tin cậy. Với ít người, khoảng sẽ rộng; đó là thông tin thật.

## 7. Giới hạn đã biết

- **RF 6 lớp không tái lập được số LOSO trong `posture_config.json`** (kiểm 26/11/2026). Dataset dựng lại khớp 99,58% (3944 so với 3950 cửa sổ),
  LOSO GOOD/BAD khớp trong 0,0015, nhưng `acc_cls`/`macro_f1` lệch tới 0,06/0,18 (P01 macro-F1 0,777 so với 0,958; P03 0,803 so với 0,889).
  `train_rf_v4.py` đã đối chiếu từng điểm với ô 12 notebook (hai RF riêng, 24 thống kê, 300 cây, balanced, seed 0, cách tính acc_cls/macro_f1)
  và không có khác biệt. Lỗi tập trung ở lớp biên/ít mẫu (LEAN_BACKWARD↔NECK_EXTENSION, FORWARD_HEAD, LEAN_FORWARD↔SLOUCH).
  Nguyên nhân chưa rõ. Model RF được ghi bằng `--export-anyway`, `posture_rf_v4.meta.json` có `loso_exported_despite_mismatch: true`.
  Khi báo cáo, **không** trích số RF 6 lớp từ config như thể đã tái lập; dùng số của lần chạy `evaluate.py`/`metrics.py`.

- Tập train v4 chỉ có 3 người; LOSO trong config là số liệu nội bộ, không thay cho đánh giá người mới.
- `mediapipe` trên máy có thể khác bản Kaggle (config ghi 1.2.3), landmark lệch nhẹ; số khớp được báo ở `compare_v4_reference.py`.
- Tâm cửa sổ quyết định đoạn nhưng trạng thái sau lọc có độ trễ (median + debounce), nên `*_bad_filtered` chậm hơn nhãn tay vài giây là hành vi thật của app.
