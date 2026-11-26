# D1–D3: xu hướng BAD trong buổi, thời điểm xuống sức (onset), dự báo onset từ 30 phút đầu

> **Mọi số liệu trong thư mục này và trong README là KIỂM CODE trên dữ liệu giả, không phải kết quả nghiên cứu.**
> Dữ liệu thật (`minutes.jsonl` + `sessions.jsonl` từ đợt thu) chưa có. Khi có, chạy ngay bằng lệnh ở mục 3.
> Onset là mức *nhóm/người* của dữ liệu thu, không phải chẩn đoán xuống sức của từng người.

Kế hoạch gốc: `GIT_backend/DoAnTotNghiep_BE/docs/ke-hoach-hoan-thien-kltn.md` mục 1 (#3), 3.1–3.2, 5.D, 9, 10.
Làm theo cách của `training/forecast/` (protocol khóa trước, kiểm trên dữ liệu giả, báo trung thực).

| File | Việc |
| --- | --- |
| `protocol.json` | **khóa** khối, điều kiện phiên, onset, cửa sổ nhắc đúng lúc, mô hình, bootstrap. Commit riêng (1d72ce5) trước mọi code đánh giá |
| `common.py` | nối `training/forecast` vào `sys.path` và import: đọc/kiểm dữ liệu (`data`), thời gian ngồi liên tục (`features.minute_table`), bootstrap theo người (`boot`), hash/commit (`protocol`) |
| `blocks.py` | khối 10 phút, phiên đủ điều kiện, mức đầu buổi, onset, đối chứng xáo khối |
| `trend.py` | D1: MixedLM/GEE, `curves.json` |
| `survival.py` | D2: Kaplan–Meier, phân bố onset theo người; C-index |
| `d3.py` | D3: đặc trưng 30 phút đầu, hazard rời rạc, m0/m1/m2, LOSO, chỉ số, bootstrap |
| `evaluate.py` | chạy D1–D3, xuất file và hình |
| `tests/` | pytest (30 test) |

Tái dùng từ forecast bằng import (không chép): `data.load` (đọc + kiểm hợp đồng 3.1–3.2), `Session.classified/bad`, `features.minute_table`
(thời gian ngồi liên tục, `away_reset_sec` lấy từ `forecast/protocol.json`), `boot.resample_people`/`percentile_ci` (bootstrap theo người; tách ra
từ `forecast/evaluate.py`, kết quả của forecast không đổi), `protocol.git_info`/`protocol_hash`. Thêm cờ `--planted-fatigue` vào `forecast/simulate.py`
(mặc định tắt; khi tắt `minutes.jsonl`/`sessions.jsonl` giống hệt trước, có test).

## 1. Đầu vào

Chỉ `minutes.jsonl` + `sessions.jsonl` đúng hợp đồng 3.1–3.2 (snake_case); `forecast/data.py` kiểm quy tắc 3.1 và chỉ nhận phiên `study_opt_in`. Không đọc DB/API.

## 2. Protocol đã khóa (`protocol.json`, version 2; v1 ở commit 1d72ce5)

- **Khối**: 10 phút liên tiếp không chồng lấn, chỉ lấy khối đủ 10 phút (phần dư cuối phiên bị bỏ). `bad_rate = Σ BAD / Σ phân loại được` (BAD = 5 lớp xấu, phân loại được = 6 lớp). Khối **thiếu** khi Σ phân loại được < 50% × 10 × 60 s (đúng 50% không thiếu).
- **Phiên đủ điều kiện**: ≥ 60 phút, ≥ 4 khối không thiếu, và có mức đầu buổi.
- **Mức đầu buổi** = Σ BAD / Σ phân loại được của các khối *không thiếu* trong 20 phút đầu.
- **Onset** = phút bắt đầu của khối đầu tiên (từ khối 2) mà `bad_rate ≥ mức đầu buổi + 0,15` và giữ ≥ 2 khối liên tiếp (khối thiếu làm đứt chuỗi; đúng bằng ngưỡng vẫn tính). Không có = **kiểm duyệt** tại cuối khối đủ cuối cùng.
- **Mốc so sánh**: nhắc nghỉ ở phút 50. **Nhắc đúng lúc**: `onset − 15 ≤ r ≤ onset`; `r > onset` = trễ; `r < onset − 15` = sớm quá; không nhắc = bỏ lỡ.
- **D1**: `bad_rate ~ thời gian (giờ, điểm giữa khối)`, MixedLM với hệ số chặn + độ dốc ngẫu nhiên theo người, chỉ khối không thiếu của phiên đủ điều kiện. `MixedLM` không hỗ trợ trọng số nên mô hình chính **không** trọng số; không hội tụ/sai số không hữu hạn thì dùng GEE (Gaussian, exchangeable theo người, trọng số `classified_sec`) và ghi lại; GEE có trọng số luôn được báo thêm như phân tích độ nhạy. Trục phụ: thời gian ngồi liên tục (giờ) tại cuối khối.
- **D3**: từ 30 phút đầu; chỉ phiên đủ điều kiện có onset ≥ 30 hoặc kiểm duyệt (onset < 30 báo riêng, không so sánh, không train). Đặc trưng (15): mức BAD 3 khối đầu, độ dốc theo khối, tỷ trọng 6 lớp, thời gian ngồi liên tục dài nhất, số cảnh báo, tỷ lệ phút thiếu, giờ trong ngày (sin/cos), tính trên bản **cắt** 30 phút đầu (`common.truncate`) nên không thể dùng dữ liệu sau phút 29 (có test).
  (m0) luôn nhắc phút 50. (m1) trung vị onset của train (Kaplan–Meier, kể cả kiểm duyệt); không xuống tới 0,5 thì không nhắc. (m2) hazard rời rạc theo khối 10 phút: logistic L2 (`C=1`) trên 15 đặc trưng + chỉ số khối (số), phiên onset đóng góp các khối từ khối 3 tới khối onset (nhãn 1 ở khối onset), phiên kiểm duyệt đóng góp tới khối đủ cuối cùng với nhãn 0; phút nhắc = đầu khối đầu tiên có xác suất tích lũy ≥ 0,5 trừ lề 5 phút, không sớm hơn phút 30; không tới 0,5 thì không nhắc.
  LOSO theo người, bootstrap theo người (2000 lần, seed 0), so m1/m2 với m0 bằng chênh lệch có CI. C-index (Harrell, tính cả phiên kiểm duyệt) dùng hazard tích lũy làm rủi ro của m2; m0 và m1 không dùng thông tin phiên nên C-index = 0,5 theo cấu trúc. MAE chỉ tính phiên có nhắc nên luôn được báo cùng tỷ lệ không nhắc.

## 3. Chạy

```
pip install numpy scipy scikit-learn matplotlib statsmodels pandas
python ..\forecast\simulate.py D:\KLTN\forecast_data\sim_main                       # dữ liệu giả có tín hiệu
python ..\forecast\simulate.py D:\KLTN\forecast_data\sim_fatigue --planted-fatigue  # đối chứng công suất cho D (không thực tế)

python evaluate.py --data D:\KLTN\forecast_data\sim_main --run sim_main
python evaluate.py --data D:\KLTN\forecast_data\sim_main --run sim_main_shuffle_blocks --shuffle-control            # đối chứng: xáo thứ tự khối trong phiên
python evaluate.py --data D:\KLTN\forecast_data\sim_main --run sim_main_shuffle_minutes --shuffle-minutes-control   # đối chứng: xáo thứ tự phút trong phiên
python -m pytest tests -q
```

Dữ liệu thật: `python evaluate.py --data <thư mục có minutes.jsonl, sessions.jsonl> --run thuc_te` (cần ≥ 4 người có phiên so sánh, `min_persons`).
Đầu ra `out/<run>/`: `blocks.csv` (participant, session_id, block_idx, block_start_min, bad_rate, classified_sec, missing), `curves.json`, `sessions.csv`
(participant, session_id, onset, censored, r_m0, r_m1, r_m2, r_m3, eligible, group, n_min), `metrics.json`, `metrics.md`, `curves.png`, `km.png`, `run_meta.json`
(SHA-256 dữ liệu, SHA-256 protocol fatigue và forecast, commit, protocol đã commit/chưa sửa, phiên bản thư viện, thời gian chạy). `--boot-n` chỉ để chạy thử nhanh và bị ghi vào `run_meta`.

## 4. Định dạng `curves.json` (cho Dashboard H3 của Tân)

```json
{
  "version": 1, "block_min": 10,
  "unit": "fraction (0..1) = Σ BAD / Σ phân loại được của khối",
  "only": "phiên đủ điều kiện, khối không thiếu",
  "participants": {"P04": {"n_sessions": 4, "blocks": [
      {"block_idx": 0, "start_min": 0, "mean_bad_rate": 0.081, "n_sessions": 4, "classified_sec": 2310.0}, "..."]}},
  "overall": {"n_sessions": 40, "blocks": ["... cùng dạng, gộp mọi người ..."]}
}
```
`mean_bad_rate` gộp các phiên của người đó theo trọng số phân loại được; khối chỉ có mặt khi ít nhất một phiên có khối đó không thiếu. Mã người là mã giả (`participant`), không phải userId.

## 5. Kết quả kiểm code trên dữ liệu giả (KHÔNG phải kết quả nghiên cứu)

Chạy 26/11/2026 trên commit `07d5fbdd` (protocol v2 chưa sửa, code sạch), bootstrap 2000 lần; mỗi ô: giá trị [CI 95% bootstrap theo người]. Ba cột cuối: chênh lệch so với m0 có CI.

**1. `simulate.py` chính (10 người × 4 phiên)** — chạy 5.2 s. Phiên 40: đủ điều kiện 40, onset 23, kiểm duyệt 17; onset < 30 phút (báo riêng, không so sánh): 5.

- D1 độ dốc theo thời gian trong buổi: 5.49 [1.41; 9.57] (mixedlm) điểm % BAD/giờ; GEE có trọng số 5.60 [1.65; 9.56]. Trục phụ (thời gian ngồi liên tục): 13.35 [9.15; 17.54] (mixedlm).
- D2: KM trung vị = 70.0 phút (None = đường cong không xuống tới 0,5); trung vị onset theo người: 50.0 phút, 10 người có onset.

| D3 | m0: nhắc phút 50 | m1: trung vị onset (KM) | m2: hazard rời rạc | m3: hazard gọn | m1 − m0 | m2 − m0 | m3 − m0 |
|---|---|---|---|---|---|---|---|
| Nhắc đúng lúc | 0.333 [0.167; 0.450] | 0.056 [0.000; 0.222] | 0.222 [0.042; 0.467] | 0.111 [0.000; 0.211] | -0.278 [-0.435; +0.000] | -0.111 [-0.316; +0.143] | -0.222 [-0.364; -0.083] |
| Nhắc trễ | 0.333 [0.174; 0.571] | 0.222 [0.045; 0.571] | 0.444 [0.227; 0.667] | 0.500 [0.235; 0.800] | -0.111 [-0.250; +0.125] | +0.111 [-0.133; +0.348] | +0.167 [-0.100; +0.421] |
| Sớm quá (> 15 phút) | 0.333 [0.167; 0.500] | 0.000 [0.000; 0.000] | 0.222 [0.000; 0.455] | 0.111 [0.000; 0.294] | -0.333 [-0.500; -0.167] | -0.111 [-0.259; +0.111] | -0.222 [-0.391; +0.000] |
| Không nhắc | 0.000 [0.000; 0.000] | 0.722 [0.300; 0.920] | 0.111 [0.000; 0.296] | 0.278 [0.000; 0.500] | +0.722 [+0.300; +0.920] | +0.111 [+0.000; +0.296] | +0.278 [+0.000; +0.500] |
| MAE phút (phiên có nhắc; kèm % không nhắc) | 15.556 [11.875; 20.000] (không nhắc 0%) | 38.000 [21.429; 50.000] (không nhắc 72%) | 30.625 [20.907; 45.911] (không nhắc 11%) | 18.846 [13.667; 27.500] (không nhắc 28%) | +22.444 [+3.333; +35.240] | +15.069 [+5.624; +28.574] | +3.291 [+0.178; +7.541] |
| C-index | 0.500 [0.500; 0.500] | 0.500 [0.500; 0.500] | 0.623 [0.474; 0.790] | 0.643 [0.510; 0.797] | +0.000 [+0.000; +0.000] | +0.123 [-0.026; +0.290] | +0.143 [+0.010; +0.297] |
| Nhắc/giờ | 0.489 [0.472; 0.508] | 0.266 [0.108; 0.435] | 0.350 [0.250; 0.437] | 0.308 [0.224; 0.399] | -0.224 [-0.375; -0.061] | -0.140 [-0.249; -0.047] | -0.182 [-0.262; -0.097] |

**2. Đối chứng: xáo thứ tự các **khối** trong từng phiên (cùng dữ liệu bộ 1)** — chạy 4.7 s. Phiên 40: đủ điều kiện 40, onset 10, kiểm duyệt 30; onset < 30 phút (báo riêng, không so sánh): 2.

- D1 độ dốc theo thời gian trong buổi: 0.19 [-1.79; 2.16] (gee_weighted (MixedLM không hội tụ)) điểm % BAD/giờ; GEE có trọng số 0.19 [-1.79; 2.16]. Trục phụ (thời gian ngồi liên tục): 2.04 [0.08; 3.99] (gee_weighted (MixedLM không hội tụ)).
- D2: KM trung vị = None phút (None = đường cong không xuống tới 0,5); trung vị onset theo người: 80.0 phút, 7 người có onset.

| D3 | m0: nhắc phút 50 | m1: trung vị onset (KM) | m2: hazard rời rạc | m3: hazard gọn | m1 − m0 | m2 − m0 | m3 − m0 |
|---|---|---|---|---|---|---|---|
| Nhắc đúng lúc | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] |
| Nhắc trễ | 0.250 [0.000; 0.667] | 0.000 [0.000; 0.000] | 0.125 [0.000; 0.500] | 0.500 [0.167; 1.000] | -0.250 [-0.667; +0.000] | -0.125 [-0.444; +0.000] | +0.250 [+0.000; +0.556] |
| Sớm quá (> 15 phút) | 0.750 [0.333; 1.000] | 0.000 [0.000; 0.000] | 0.125 [0.000; 0.333] | 0.000 [0.000; 0.000] | -0.750 [-1.000; -0.333] | -0.625 [-0.917; -0.250] | -0.750 [-1.000; -0.333] |
| Không nhắc | 0.000 [0.000; 0.000] | 1.000 [1.000; 1.000] | 0.750 [0.429; 1.000] | 0.500 [0.000; 0.833] | +1.000 [+1.000; +1.000] | +0.750 [+0.429; +1.000] | +0.500 [+0.000; +0.833] |
| MAE phút (phiên có nhắc; kèm % không nhắc) | 31.250 [20.000; 40.000] (không nhắc 0%) | — (không nhắc 100%) | 92.500 [80.000; 105.000] (không nhắc 75%) | 62.500 [15.000; 95.000] (không nhắc 50%) | — | +61.250 [+40.000; +83.750] | +31.250 [-25.250; +71.667] |
| C-index | 0.500 [0.500; 0.500] | 0.500 [0.500; 0.500] | 0.498 [0.292; 0.689] | 0.673 [0.450; 0.860] | +0.000 [+0.000; +0.000] | -0.002 [-0.208; +0.189] | +0.173 [-0.050; +0.360] |
| Nhắc/giờ | 0.487 [0.470; 0.504] | 0.000 [0.000; 0.000] | 0.141 [0.054; 0.230] | 0.141 [0.048; 0.255] | -0.487 [-0.504; -0.470] | -0.346 [-0.434; -0.256] | -0.346 [-0.437; -0.241] |

**3. Đối chứng thứ 5: xáo thứ tự các **phút** trong từng phiên (cùng dữ liệu bộ 1)** — chạy 4.2 s. Phiên 40: đủ điều kiện 40, onset 4, kiểm duyệt 36; onset < 30 phút (báo riêng, không so sánh): 0.

- D1 độ dốc theo thời gian trong buổi: -0.66 [-2.23; 0.91] (mixedlm) điểm % BAD/giờ; GEE có trọng số -0.79 [-2.06; 0.48]. Trục phụ (thời gian ngồi liên tục): 0.79 [-2.34; 3.92] (mixedlm).
- D2: KM trung vị = None phút (None = đường cong không xuống tới 0,5); trung vị onset theo người: 60.0 phút, 3 người có onset.

| D3 | m0: nhắc phút 50 | m1: trung vị onset (KM) | m2: hazard rời rạc | m3: hazard gọn | m1 − m0 | m2 − m0 | m3 − m0 |
|---|---|---|---|---|---|---|---|
| Nhắc đúng lúc | 0.250 [0.000; 1.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | -0.250 [-1.000; +0.000] | -0.250 [-1.000; +0.000] | -0.250 [-1.000; +0.000] |
| Nhắc trễ | 0.250 [0.000; 0.500] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | -0.250 [-0.500; +0.000] | -0.250 [-0.500; +0.000] | -0.250 [-0.500; +0.000] |
| Sớm quá (> 15 phút) | 0.500 [0.000; 1.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | -0.500 [-1.000; +0.000] | -0.500 [-1.000; +0.000] | -0.500 [-1.000; +0.000] |
| Không nhắc | 0.000 [0.000; 0.000] | 1.000 [1.000; 1.000] | 1.000 [1.000; 1.000] | 1.000 [1.000; 1.000] | +1.000 [+1.000; +1.000] | +1.000 [+1.000; +1.000] | +1.000 [+1.000; +1.000] |
| MAE phút (phiên có nhắc; kèm % không nhắc) | 20.000 [0.000; 30.000] (không nhắc 0%) | — (không nhắc 100%) | — (không nhắc 100%) | — (không nhắc 100%) | — | — | — |
| C-index | 0.500 [0.500; 0.500] | 0.500 [0.500; 0.500] | 0.527 [0.128; 0.821] | 0.360 [0.104; 0.718] | +0.000 [+0.000; +0.000] | +0.027 [-0.372; +0.321] | -0.140 [-0.396; +0.218] |
| Nhắc/giờ | 0.484 [0.468; 0.501] | 0.000 [0.000; 0.000] | 0.024 [0.000; 0.050] | 0.000 [0.000; 0.000] | -0.484 [-0.501; -0.468] | -0.460 [-0.496; -0.420] | -0.484 [-0.501; -0.468] |

**4. Đối chứng công suất `simulate.py --planted-fatigue`** — chạy 7.7 s. Phiên 40: đủ điều kiện 40, onset 40, kiểm duyệt 0; onset < 30 phút (báo riêng, không so sánh): 0.

- D1 độ dốc theo thời gian trong buổi: 30.39 [23.21; 37.57] (mixedlm) điểm % BAD/giờ; GEE có trọng số 29.76 [24.16; 35.35]. Trục phụ (thời gian ngồi liên tục): 13.09 [9.01; 17.17] (mixedlm).
- D2: KM trung vị = 40.0 phút (None = đường cong không xuống tới 0,5); trung vị onset theo người: 40.0 phút, 10 người có onset.

| D3 | m0: nhắc phút 50 | m1: trung vị onset (KM) | m2: hazard rời rạc | m3: hazard gọn | m1 − m0 | m2 − m0 | m3 − m0 |
|---|---|---|---|---|---|---|---|
| Nhắc đúng lúc | 0.200 [0.000; 0.400] | 0.450 [0.275; 0.625] | 0.825 [0.725; 0.925] | 0.825 [0.725; 0.925] | +0.250 [+0.050; +0.450] | +0.625 [+0.400; +0.825] | +0.625 [+0.400; +0.825] |
| Nhắc trễ | 0.650 [0.350; 0.900] | 0.375 [0.175; 0.600] | 0.125 [0.050; 0.200] | 0.125 [0.050; 0.200] | -0.275 [-0.450; -0.100] | -0.525 [-0.800; -0.225] | -0.525 [-0.800; -0.225] |
| Sớm quá (> 15 phút) | 0.150 [0.000; 0.351] | 0.175 [0.000; 0.400] | 0.050 [0.000; 0.150] | 0.050 [0.000; 0.150] | +0.025 [+0.000; +0.075] | -0.100 [-0.200; +0.000] | -0.100 [-0.200; +0.000] |
| Không nhắc | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] |
| MAE phút (phiên có nhắc; kèm % không nhắc) | 14.000 [10.500; 17.750] (không nhắc 0%) | 11.000 [6.000; 17.250] (không nhắc 0%) | 5.875 [3.625; 8.625] (không nhắc 0%) | 5.750 [3.125; 8.750] (không nhắc 0%) | -3.000 [-8.000; +3.000] | -8.125 [-12.000; -4.375] | -8.250 [-12.875; -3.500] |
| C-index | 0.500 [0.500; 0.500] | 0.500 [0.500; 0.500] | 0.897 [0.787; 0.954] | 0.931 [0.848; 0.972] | +0.000 [+0.000; +0.000] | +0.397 [+0.287; +0.454] | +0.431 [+0.348; +0.472] |
| Nhắc/giờ | 0.501 [0.482; 0.522] | 0.501 [0.482; 0.522] | 0.501 [0.482; 0.522] | 0.501 [0.482; 0.522] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] |

**5. Bộ giả của backend (`generate-research-pilot.py`, chỉ kiểm đọc file)** — chạy 4.5 s. Phiên 32: đủ điều kiện 21, onset 21, kiểm duyệt 0, loại {'không có mức đầu buổi': 7, 'phiên ngắn hơn min_session_min': 4}; onset < 30 phút (báo riêng, không so sánh): 0.

- D1 độ dốc theo thời gian trong buổi: 19.69 [18.82; 20.55] (mixedlm) điểm % BAD/giờ; GEE có trọng số 19.79 [19.13; 20.45]. Trục phụ (thời gian ngồi liên tục): 53.76 [43.33; 64.20] (mixedlm).
- D2: KM trung vị = 50.0 phút (None = đường cong không xuống tới 0,5); trung vị onset theo người: 50.0 phút, 8 người có onset.

| D3 | m0: nhắc phút 50 | m1: trung vị onset (KM) | m2: hazard rời rạc | m3: hazard gọn | m1 − m0 | m2 − m0 | m3 − m0 |
|---|---|---|---|---|---|---|---|
| Nhắc đúng lúc | 0.857 [0.727; 0.957] | 0.857 [0.727; 0.957] | 0.619 [0.368; 0.850] | 0.810 [0.600; 0.957] | +0.000 [+0.000; +0.000] | -0.238 [-0.500; -0.043] | -0.048 [-0.158; +0.000] |
| Nhắc trễ | 0.143 [0.043; 0.273] | 0.143 [0.043; 0.273] | 0.286 [0.091; 0.524] | 0.190 [0.043; 0.400] | +0.000 [+0.000; +0.000] | +0.143 [+0.000; +0.350] | +0.048 [+0.000; +0.158] |
| Sớm quá (> 15 phút) | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.095 [0.000; 0.316] | 0.000 [0.000; 0.000] | +0.000 [+0.000; +0.000] | +0.095 [+0.000; +0.316] | +0.000 [+0.000; +0.000] |
| Không nhắc | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | 0.000 [0.000; 0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] |
| MAE phút (phiên có nhắc; kèm % không nhắc) | 3.810 [1.905; 5.789] (không nhắc 0%) | 3.810 [1.905; 5.789] (không nhắc 0%) | 9.762 [5.909; 14.500] (không nhắc 0%) | 6.905 [5.435; 9.000] (không nhắc 0%) | +0.000 [+0.000; +0.000] | +5.952 [+3.182; +9.446] | +3.095 [+1.818; +4.474] |
| C-index | 0.500 [0.500; 0.500] | 0.500 [0.500; 0.500] | 0.370 [0.116; 0.704] | 0.521 [0.217; 0.798] | +0.000 [+0.000; +0.000] | -0.130 [-0.384; +0.204] | +0.021 [-0.283; +0.298] |
| Nhắc/giờ | 0.462 [0.462; 0.462] | 0.462 [0.462; 0.462] | 0.462 [0.462; 0.462] | 0.462 [0.462; 0.462] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] | +0.000 [+0.000; +0.000] |

**Đọc các kết quả trên:**
- **Bộ 1 (`simulate.py` chính)**: D1 cho độ dốc dương rõ (≈ +5,5 điểm %/giờ, CI loại 0), đúng chiều mô phỏng. D3: **m2 không hơn m0** (đúng lúc −0,111 [−0,316; +0,143]). **m3** cải thiện thứ hạng nhưng không cải thiện thời điểm: C-index 0,643 [0,51; 0,80], hơn m0 +0,143 [+0,01; +0,30] (CI sát biên 0), nhưng nhắc đúng lúc **kém** m0 (−0,222 [−0,36; −0,08]) và MAE lớn hơn (+3,3 phút [+0,2; +7,5]), 28% phiên không được nhắc. Chỉ 35 phiên so sánh (18 có onset), nhiều chỉ số cùng lúc, nên không kết luận m3 tốt hơn m2 hay m0.
- **Bộ 2 (xáo khối)**: độ dốc D1 về ≈ 0 (+0,19 [−1,79; +2,16]; MixedLM không hội tụ nên dùng GEE) và D3 không hơn m0 (đúng lúc 0 ở cả bốn; C-index m2 0,498 [0,29; 0,69], m3 0,673 [0,45; 0,86], chênh lệch với m0 CI chứa 0). Trục phụ cho +2,04 [+0,08; +3,99], sát biên.
- **Bộ 3 (xáo phút) — kiểm giả thuyết về trục phụ ở bộ 2**: **cả hai trục về ≈ 0**: trục thời gian −0,66 [−2,23; +0,91], trục thời gian ngồi liên tục +0,79 [−2,34; +3,92] (GEE có trọng số +0,64 [−1,60; +2,88]). Vậy +2,04 ở bộ 2 là do xáo *khối* giữ nguyên cấu trúc trong khối (các phút rời ghế nằm cùng khối) nên không trung hòa hoàn toàn trục này; xáo *phút* thì có. Đây là kiểm chứng sau khi giả thuyết được nêu, không phải điều chỉnh để khớp. D3 ở bộ này suy biến (chỉ 4/40 phiên có onset; m1, m2, m3 đều không nhắc phiên nào) nên không đọc gì từ đó.
- **Bộ 4 (`--planted-fatigue`, đối chứng công suất)**: m2 và m3 cùng hơn m0 rõ, CI loại 0: đúng lúc +0,625 [+0,400; +0,825] cho cả hai; MAE −8,1 và −8,3 phút; C-index m2 0,897 [0,787; 0,954], m3 0,931 [0,85; 0,97]. Pipeline phát hiện được tín hiệu mạnh, và 3 đặc trưng của m3 đủ cho tín hiệu này. Bản đầu của cờ này từng thất bại (m2 đúng lúc 0,235 so với 0,471) do thiết kế đối chứng kém (onset dồn quanh phút 50, nhiễu lớn); đã tìm lỗi code trước (không có), chỉ cờ mới được thiết kế lại.
- **Bộ 5 (backend)**: chỉ kiểm đọc file; 11/32 phiên bị loại đúng quy tắc (7 không có mức đầu buổi vì khối thiếu, 4 phiên ngắn < 60 phút). Onset đều ở phút 50 theo cách sinh nên m0 gần như hoàn hảo; số liệu không có ý nghĩa dự báo. GEE có trọng số của trục phụ không tính được CI (dữ liệu quá đều).
- Thời gian chạy mỗi bộ 4–8 giây (kể cả bootstrap 2000 lần).

## 6. Quyết định (Việt đã xác nhận 8 quyết định đầu ngày 26/11/2026; 9–10 thêm ở protocol v2, cần xác nhận)

Kế hoạch/prompt không nêu rõ; đã chọn phương án đơn giản và khóa trong `protocol.json`:
1. ✅ **Δ = 0,15, ≥ 2 khối liên tiếp, 2 khối đầu làm mức đầu buổi** (theo đề xuất). Khối thiếu làm đứt chuỗi onset; đúng bằng baseline + Δ vẫn tính.
2. ✅ **Onset đo ở khối** (bước 10 phút) và cần khối kế tiếp để xác nhận, nên khối cuối cao một mình không tạo onset; kiểm duyệt đặt tại cuối khối đủ cuối cùng.
3. ✅ **Phiên onset < 30 phút** (chỉ có thể là phút 20) báo riêng, loại khỏi so sánh *và khỏi train* (khớp tình huống nhắc tại phút 30).
4. ✅ **m1 không nhắc** khi KM không xuống tới 0,5; **m2 không nhắc** khi xác suất tích lũy không tới 0,5 trong lưới tới khối 14 (phút 150). Hai trường hợp này tính vào "không nhắc/bỏ lỡ" nên MAE (chỉ phiên có nhắc) khó so sánh giữa các phương pháp.
5. ✅ **Lề 5 phút và ngưỡng 0,5** (khóa theo prompt) chưa được tối ưu; muốn dò phải làm trong train fold và ghi lại.
6. ✅ **MixedLM không trọng số** (thư viện không hỗ trợ), GEE có trọng số làm độ nhạy; chỉ khối không thiếu vào mô hình.
7. ✅ **C-index của m0/m1 = 0,5 theo cấu trúc** (không dùng thông tin phiên); C-index chỉ để đánh giá m2.
8. ✅ **Nhắc/giờ** = số phiên được nhắc / tổng số giờ phiên (tối đa một nhắc mỗi phiên); không tính nhắc lặp.
9. **m3 dùng đúng 3 đặc trưng** (mức BAD 2 khối đầu = `bad_b0`, `bad_b1`; độ dốc BAD phút 0–29 = `bad_slope`, hồi quy theo 3 khối đầu) + chỉ số khối, theo yêu cầu; không dò tập đặc trưng khác.
10. **Đối chứng xáo phút** dùng một hoán vị ngẫu nhiên các phút của từng phiên (seed cố định theo `protocol.controls.shuffle_minutes_seed` và chỉ số phiên); giờ thật (`window_start`) giữ nguyên.

## 7. Giới hạn

- Onset chỉ có độ phân giải 10 phút và cửa sổ đúng lúc rộng 15 phút; m0 (phút 50) có thể "đúng lúc" chỉ vì trùng mốc phổ biến của dữ liệu.
- Phiên của cùng một người tương quan; bootstrap theo người đã tính đến, nhưng với ít người CI sẽ rộng.
- Mô hình hazard có 16 hệ số trên vài chục phiên: dễ quá khớp; chưa có dữ liệu thật để biết.
- Chưa tích hợp vào Desktop/Dashboard; `curves.json` chưa được Tân dùng thử.
