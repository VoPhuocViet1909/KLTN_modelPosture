# C1–C4: dự báo tư thế 5 phút tới (pipeline, kiểm trên dữ liệu giả)

> **Mọi số liệu trong thư mục này và trong README là KIỂM CODE trên dữ liệu giả, không phải kết quả nghiên cứu.**
> Dữ liệu thật (`minutes.jsonl` + `sessions.jsonl` từ đợt thu) chưa có. Khi có, chạy ngay bằng các lệnh ở mục 3. C5 (tích hợp Desktop) chưa làm.

Câu hỏi: tại một phút đang *chủ yếu ngồi đúng*, trong 5 phút tới có sắp ngồi sai (≥ 50% thời gian phân loại được là BAD) không? Mục đích là nhắc *trước khi* ngồi sai.
Kế hoạch gốc: `GIT_backend/DoAnTotNghiep_BE/docs/ke-hoach-hoan-thien-kltn.md` mục 1 (#2), 3.1–3.2, 5.C, 9.

| File | Việc |
| --- | --- |
| `protocol.json` | **khóa** nhãn, đặc trưng, ngưỡng, tham số mô hình, bootstrap. Commit trước khi viết code đánh giá. Mọi script đọc từ đây |
| `data.py` | đọc + kiểm `minutes.jsonl`/`sessions.jsonl` theo hợp đồng 3.1–3.2 (không đọc DB/API) |
| `labels.py` | C1: nhãn `y`, lọc mốc, lý do bỏ |
| `features.py` | C2: đặc trưng từ 10 phút gần nhất (chỉ phút ≤ t) |
| `models.py` | C3: (a) giống phút hiện tại, (b) Markov, (c) logistic L2, (d) GRU |
| `evaluate.py` | C4: LOSO theo người, ngưỡng nhắc, chỉ số, bootstrap theo người, biểu đồ |
| `simulate.py` | dữ liệu giả có tín hiệu (Markov chuyển chế độ), seed cố định |
| `tests/` | pytest (24 test) |

## 1. Đầu vào

Chỉ hai file đúng hợp đồng (snake_case): `minutes.jsonl` (mỗi người, mỗi phiên, mỗi phút một dòng, kể cả phút `unknown`) và `sessions.jsonl`
(`participant, session_id, started_at, ended_at, duration_min, camera_setup, study_opt_in, ended_early, note`). `data.py` kiểm đúng quy tắc 3.1
(away + unknown + presence = 60 ± 1; tổng 6 lớp ≤ presence + 0,3; phút thiếu phải có dòng; `window_start` khớp `minute_idx`; chỉ nhận phiên
`study_opt_in`). Lớp null **không** bị đổi thành 0: `cls` là NaN, và phút đó có phân loại được = 0 nên bị coi là thiếu.
`window_sec` lấy từ `protocol.json` (60) vì `minutes.jsonl` không có cột này.

## 2. Protocol đã khóa (`protocol.json`)

- **C1 nhãn.** BAD = tổng 5 lớp xấu; phân loại được = tổng 6 lớp. Mốc t hợp lệ khi phút t chủ yếu GOOD (`good/phân loại được ≥ 0,5`) và phân loại được(t) ≥ 30 s.
  `y = 1` nếu Σ BAD(t+1..t+5) ≥ 50% Σ phân loại được(t+1..t+5). Bỏ mốc khi phần thiếu `Σ(60 − phân loại được)/(5·60)` của t+1..t+5 > 50%, hoặc cuối phiên (thiếu 5 phút sau). Không cắt ngang phiên. `evaluate.py` in số mốc, tỷ lệ dương theo người, số mốc bỏ theo lý do.
- **C2 đặc trưng** (23, chỉ phút ≤ t): tỷ trọng 6 lớp trên tổng phân loại được của các phút quan sát được; tỷ lệ BAD của từng phút trong 10 phút và độ dốc hồi quy tuyến tính; thời gian ngồi liên tục tới t (reset khi `away_sec ≥ 30`); số phút từ cảnh báo gần nhất (`alerts_total > 0`, tối đa 60); phút trong phiên; giờ trong ngày (sin/cos); tỷ lệ phút thiếu. Phút thiếu/trước đầu phiên được đánh dấu, tỷ lệ BAD thiếu thay bằng trung bình các phút quan sát được trong cửa sổ (chỉ quá khứ). Chuẩn hóa fit trên train của từng fold. Có test: đặc trưng tại t không đổi khi sửa dữ liệu sau t.
- **C3 mô hình.** (a) tần suất dương của train theo nhóm tỷ lệ BAD của phút t; (b) Markov bậc 1 theo nhóm tỷ lệ BAD của phút (5 nhóm + X), xác suất ≥ 50% BAD trong 5 phút tính bằng liệt kê mọi đường đi; (c) logistic L2, `C = 1`; (d) GRU 1 lớp, 16 đơn vị trên chuỗi 10 × 13, Adam, early stopping theo validation. Seed 0, PyTorch CPU 1 luồng.
- **C4 đánh giá.** LOSO theo người. Trong mỗi fold train, tách 25% *người* làm validation (early stopping của GRU + chọn ngưỡng của cả 4 mô hình), 4 mô hình fit trên phần còn lại (không fit lại). Ngưỡng nhắc = ngưỡng thấp nhất để nhắc nhầm/giờ trên validation ≤ 2, rồi áp nguyên lên người test. Luật nhắc: nhắc khi p ≥ ngưỡng, sau đó im ≥ 10 phút (theo phiên); nhắc nhầm = nhắc tại mốc y = 0. Giờ = tổng `presence_sec`/3600. Phút nhắc trước = từ mốc nhắc (y = 1) tới phút đầu tiên trong t+1..t+5 có BAD ≥ 50% phân loại được. CI 95% = bootstrap percentile **theo người** (2000 lần, seed 0); so với (a) bằng chênh lệch có CI trên cùng mẫu bootstrap.

## 3. Chạy

```
pip install numpy scikit-learn matplotlib torch    # torch bản CPU
python simulate.py D:\KLTN\forecast_data\sim_main                    # dữ liệu giả có tín hiệu
python simulate.py D:\KLTN\forecast_data\sim_planted --planted       # đối chứng công suất (không thực tế)
python <repo backend>\dev\generate-research-pilot.py D:\KLTN\forecast_data\pilot   # bộ giả của backend (chỉ chạy)

python evaluate.py --data D:\KLTN\forecast_data\sim_main --run sim_main
python evaluate.py --data D:\KLTN\forecast_data\sim_main --run sim_main_shuffle --shuffle-control   # đối chứng: xáo nhãn trong người
python -m pytest tests -q
```

Dữ liệu thật: `python evaluate.py --data <thư mục có minutes.jsonl, sessions.jsonl> --run thuc_te`. Cần ≥ 4 người (`min_persons`). Đầu ra `out/<run>/`:
`predictions.csv` (participant, session_id, minute_idx, y, p_a, p_b, p_c, p_d), `metrics.json`, `metrics.md`, `pr_curve.png`, `calibration.png`, `run_meta.json`
(SHA-256 `minutes.jsonl`/`sessions.jsonl`, SHA-256 `protocol.json`, commit, protocol đã commit/chưa sửa, phiên bản thư viện, thời gian chạy). `--boot-n` chỉ để chạy thử nhanh và bị ghi vào `run_meta` là đã ghi đè protocol.

## 4. Cách đọc kết quả

- **PR-AUC phải đọc cùng tỷ lệ dương** (một mô hình đoán bừa có PR-AUC ≈ tỷ lệ dương). Chênh lệch với (a) có CI chứa 0 thì chưa kết luận được mô hình nào hơn.
- Độ nhạy / nhắc nhầm/giờ / phút nhắc trước đều ở **ngưỡng đã khóa từ validation**; nhắc nhầm/giờ trên test có thể vượt mục tiêu 2 (ngưỡng chọn trên ít người).
- Nếu không mô hình nào hơn (a), vẫn là kết quả hợp lệ (kế hoạch mục 9).

## 5. Kết quả kiểm code trên dữ liệu giả (KHÔNG phải kết quả nghiên cứu)

Chạy 26/11/2026 trên commit ghi trong `run_meta.json`, bootstrap 2000 lần. PR-AUC [CI 95%], tỷ lệ dương trong ngoặc đầu dòng.

**`simulate.py` chính (10 người)** — 3386 mốc, tỷ lệ dương 0.103, chạy 28.2 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU |
|---|---|---|---|---|
| PR-AUC | 0.127 [0.106; 0.151] | 0.120 [0.097; 0.141] | 0.144 [0.107; 0.180] | 0.157 [0.103; 0.217] |
| Brier | 0.092 [0.074; 0.107] | 0.092 [0.074; 0.108] | 0.095 [0.079; 0.110] | 0.092 [0.077; 0.108] |
| Độ nhạy @ngưỡng khóa | 0.138 [0.102; 0.174] | 0.011 [0.000; 0.038] | 0.381 [0.248; 0.533] | 0.315 [0.180; 0.458] |
| Nhắc nhầm/giờ | 1.646 [1.392; 1.892] | 0.198 [0.000; 0.576] | 2.041 [1.470; 2.688] | 1.910 [1.656; 2.147] |
| Phút nhắc trước | 1.125 [1.000; 1.321] | 1.000 [1.000; 1.000] | 1.667 [1.333; 2.000] | 1.643 [1.344; 2.000] |
| PR-AUC − (a) | — | -0.007 [-0.020; 0.002] | 0.017 [-0.010; 0.048] | 0.030 [-0.012; 0.083] |

**đối chứng: nhãn xáo trong người** — 3386 mốc, tỷ lệ dương 0.103, chạy 29.7 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU |
|---|---|---|---|---|
| PR-AUC | 0.091 [0.071; 0.113] | 0.098 [0.076; 0.118] | 0.096 [0.080; 0.115] | 0.089 [0.068; 0.112] |
| Brier | 0.093 [0.075; 0.108] | 0.094 [0.076; 0.110] | 0.096 [0.078; 0.111] | 0.095 [0.077; 0.110] |
| Độ nhạy @ngưỡng khóa | 0.037 [0.026; 0.049] | 0.000 [0.000; 0.000] | 0.195 [0.078; 0.337] | 0.097 [0.055; 0.144] |
| Nhắc nhầm/giờ | 1.580 [1.288; 1.878] | 0.013 [0.000; 0.040] | 2.133 [1.455; 2.801] | 2.120 [1.738; 2.508] |
| Phút nhắc trước | 4.000 [4.000; 4.000] | — | 3.111 [2.667; 4.000] | 3.571 [3.000; 4.000] |
| PR-AUC − (a) | — | 0.007 [-0.002; 0.014] | 0.005 [-0.007; 0.014] | -0.002 [-0.017; 0.008] |

**đối chứng công suất `--planted`** — 3994 mốc, tỷ lệ dương 0.040, chạy 44.3 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU |
|---|---|---|---|---|
| PR-AUC | 0.081 [0.053; 0.118] | 0.058 [0.040; 0.082] | 0.148 [0.108; 0.231] | 0.367 [0.209; 0.577] |
| Brier | 0.037 [0.033; 0.041] | 0.038 [0.034; 0.042] | 0.037 [0.033; 0.041] | 0.032 [0.024; 0.042] |
| Độ nhạy @ngưỡng khóa | 0.151 [0.092; 0.215] | 0.088 [0.027; 0.171] | 0.711 [0.592; 0.826] | 0.906 [0.833; 0.964] |
| Nhắc nhầm/giờ | 0.838 [0.650; 1.067] | 1.044 [0.561; 1.510] | 2.063 [1.691; 2.513] | 2.012 [1.739; 2.272] |
| Phút nhắc trước | 1.333 [1.062; 1.571] | 1.500 [1.000; 1.917] | 1.923 [1.500; 2.167] | 1.625 [1.244; 1.857] |
| PR-AUC − (a) | — | -0.024 [-0.040; -0.009] | 0.067 [0.043; 0.126] | 0.286 [0.116; 0.490] |

**bộ giả của backend (8 người, 7 đủ mốc)** — 1330 mốc, tỷ lệ dương 0.143, chạy 15.7 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU |
|---|---|---|---|---|
| PR-AUC | 0.309 [0.219; 0.589] | 0.336 [0.197; 0.587] | 0.394 [0.299; 0.701] | 0.167 [0.160; 0.285] |
| Brier | 0.101 [0.064; 0.179] | 0.165 [0.132; 0.221] | 0.239 [0.102; 0.420] | 0.264 [0.241; 0.283] |
| Độ nhạy @ngưỡng khóa | 0.647 [0.262; 1.000] | 0.342 [0.183; 0.628] | 0.679 [0.261; 1.000] | 0.489 [0.129; 0.874] |
| Nhắc nhầm/giờ | 1.653 [0.580; 2.721] | 0.988 [0.282; 2.001] | 2.076 [0.682; 3.498] | 2.217 [0.601; 4.043] |
| Phút nhắc trước | 1.481 [1.294; 1.834] | 1.438 [1.333; 1.512] | 1.346 [1.129; 1.923] | 1.381 [1.000; 1.706] |
| PR-AUC − (a) | — | 0.026 [-0.092; 0.160] | 0.084 [-0.153; 0.396] | -0.142 [-0.356; 0.007] |


**Đọc các kết quả trên:**
- Bộ `simulate.py` chính: tín hiệu dự báo *có nhưng yếu* (khởi phát BAD là sự kiện hiếm; tỷ lệ dương tăng từ ~5% khi ngồi < 10 phút lên ~21% khi ngồi > 70 phút). (c)/(d) có PR-AUC cao hơn (a) nhưng CI của chênh lệch chứa 0, nên **tiêu chí "(c)/(d) hơn (a) rõ ràng" không đạt trên bộ này**. Đã tìm lỗi: đặc trưng đúng, riêng `sitting_min` có AP 0,19 (cao hơn logistic 23 đặc trưng với C đã khóa là 0,15), không có rò rỉ; nên đây là giới hạn của mô phỏng + 10 người + protocol khóa, không chỉnh mô phỏng cho đẹp.
- Bộ đối chứng công suất (`--planted`, BAD khởi phát xác định theo thời gian ngồi): (d) hơn (a) rõ, (c) hơn (a) có CI loại 0 → pipeline phát hiện được tín hiệu mạnh.
- Đối chứng xáo nhãn trong người: PR-AUC của cả 4 về quanh tỷ lệ dương → không có rò rỉ nhãn.
- Bộ `generate-research-pilot.py` (8 người, BAD tăng tuyến tính): chỉ dùng kiểm đọc file, quy tắc 3.1, phút thiếu, `model_version` khác; số liệu không có ý nghĩa dự báo.

## 6. Quyết định cần Việt xác nhận

Kế hoạch không nêu rõ; đã chọn phương án đơn giản và khóa trong `protocol.json`:
1. **Ngưỡng reset thời gian ngồi**: `away_sec ≥ 30` trong một phút. (Kế hoạch: "reset khi `away_sec` ≥ ngưỡng khóa".)
2. **Phút "quan sát được"** cho đặc trưng/trạng thái: phân loại được ≥ 30 s (cùng ngưỡng với điều kiện mốc).
3. **Phần thiếu tính cả thời gian rời ghế** (`60 − phân loại được`), nên mốc ngay trước/sau khi rời ghế thường bị bỏ. Nếu muốn dự báo cả "sắp rời ghế" thì phải đổi định nghĩa trong kế hoạch trước.
4. **Phút nhắc trước**: phút BAD đầu tiên = phút có BAD ≥ 50% phân loại được; nhắc mà y = 1 nhưng không có phút nào như vậy (BAD rải đều dưới 50%) bị bỏ khỏi trung bình (báo `lead_n`).
5. **Nhắc chỉ xét tại các mốc hợp lệ** (phút chủ yếu GOOD, đủ dữ liệu); phút khác không nhắc được. Nhắc nhầm/giờ tính theo `presence_sec` của mọi phút, nên là mức *tối thiểu* so với chạy thật trong Desktop.
6. **Ngưỡng nhắc**: thấp nhất thỏa ≤ 2 nhắc nhầm/giờ trên validation; im 10 phút giữa hai lần nhắc. Validation = 25% người, mô hình **không** fit lại trên cả train (giữ nhất quán giữa early stopping, chọn ngưỡng và dự đoán test). Với ít người, mất 25% dữ liệu train là cái giá.
7. **Mốc (a)** dùng tần suất dương theo 5 nhóm tỷ lệ BAD (không dùng tỷ lệ BAD thô). **Mốc (b)** là Markov bậc 1 trên 6 trạng thái; ước lượng xác suất "≥ 50% BAD" bằng tỷ lệ BAD trung bình của trạng thái (nên chỉ có 6 giá trị p khác nhau).
8. **Tham số (c)/(d)** (C = 1, 16 đơn vị GRU, lr 0,003…) khóa từ đầu, không dò. Muốn dò phải làm trong train fold và ghi lại.
9. `min_persons = 4`. Dưới mức này `evaluate.py` từ chối chạy.

## 7. Giới hạn

- Các mốc liền nhau trong một phiên tương quan mạnh; bootstrap theo người đã tính đến điều này nhưng với ít người CI sẽ rất rộng.
- Nhãn `y` suy từ chính phân loại của model v4 (RULA), nên đây là dự báo *nhãn của model*, không phải ngồi sai "thật".
- Chưa có dữ liệu thật; chưa hiệu chỉnh xác suất (calibration) ngoài việc vẽ biểu đồ.
