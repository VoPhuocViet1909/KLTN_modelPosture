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
| `tests/` | pytest (28 test) |

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
- **C3 mô hình.** (a) tần suất dương của train theo nhóm tỷ lệ BAD của phút t; (b) Markov bậc 1 theo nhóm tỷ lệ BAD của phút (5 nhóm + X), xác suất ≥ 50% BAD trong 5 phút tính bằng liệt kê mọi đường đi; (c) logistic L2, `C = 1`, 23 đặc trưng; (d) GRU 1 lớp, 16 đơn vị trên chuỗi 10 × 13, Adam, early stopping theo validation; (e) logistic L2 (`C = 1`) **chỉ trên thời gian ngồi liên tục**, để tách phần đóng góp của riêng đặc trưng này (thêm ở protocol v2). Seed 0, PyTorch CPU 1 luồng.
- **C4 đánh giá.** LOSO theo người. **Chọn ngưỡng nhắc (protocol v2):** với (a), (b), (c), (e): LOSO *lồng* trong train fold — dự đoán ngoài lượt cho từng người train (mô hình fit trên các người train còn lại), chọn ngưỡng thấp nhất để nhắc nhầm/giờ trên các dự đoán đó ≤ 2, rồi **fit lại mô hình trên toàn bộ train fold** và áp ngưỡng lên người test. Với (d) GRU giữ cách cũ: tách 25% *người* trong train làm validation cho early stopping và chọn ngưỡng, GRU fit trên phần còn lại và không fit lại (không lồng vì chi phí huấn luyện và vì early stopping cần validation riêng). Hệ quả: (d) học trên ít dữ liệu hơn (a),(b),(c),(e) — cần nhớ khi so sánh. Luật nhắc: nhắc khi p ≥ ngưỡng, sau đó im ≥ 10 phút (theo phiên); nhắc nhầm = nhắc tại mốc y = 0. Giờ = tổng `presence_sec`/3600. Phút nhắc trước = từ mốc nhắc (y = 1) tới phút đầu tiên trong t+1..t+5 có BAD ≥ 50% phân loại được. CI 95% = bootstrap percentile **theo người** (2000 lần, seed 0); so với (a) bằng chênh lệch có CI trên cùng mẫu bootstrap.

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

Chạy 26/11/2026 trên commit ghi trong `run_meta.json` (`17df9f44`, protocol v2), bootstrap 2000 lần. Mỗi ô: giá trị [CI 95% bootstrap theo người].

**`simulate.py` chính (10 người)** — 3386 mốc, tỷ lệ dương 0.103, chạy 121.0 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU | (e) chỉ thời gian ngồi |
|---|---|---|---|---|---|
| PR-AUC | 0.119 [0.096; 0.146] | 0.107 [0.084; 0.134] | 0.150 [0.113; 0.185] | 0.157 [0.103; 0.217] | 0.173 [0.111; 0.240] |
| Brier | 0.092 [0.074; 0.107] | 0.092 [0.074; 0.108] | 0.093 [0.077; 0.108] | 0.092 [0.077; 0.108] | 0.090 [0.074; 0.106] |
| Độ nhạy @ngưỡng khóa | 0.160 [0.133; 0.192] | 0.175 [0.143; 0.207] | 0.393 [0.226; 0.574] | 0.315 [0.180; 0.458] | 0.562 [0.418; 0.708] |
| Nhắc nhầm/giờ | 1.712 [1.486; 1.919] | 2.226 [2.021; 2.416] | 1.975 [1.460; 2.482] | 1.910 [1.656; 2.147] | 1.989 [1.612; 2.384] |
| Phút nhắc trước | 1.200 [1.032; 1.414] | 1.235 [1.057; 1.467] | 1.615 [1.409; 1.765] | 1.643 [1.344; 2.000] | 1.655 [1.389; 1.848] |
| PR-AUC − (a) | — | -0.011 [-0.023; -0.003] | 0.031 [-0.001; 0.057] | 0.038 [-0.007; 0.090] | 0.054 [0.005; 0.110] |

**đối chứng: nhãn xáo trong người** — 3386 mốc, tỷ lệ dương 0.103, chạy 133.9 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU | (e) chỉ thời gian ngồi |
|---|---|---|---|---|---|
| PR-AUC | 0.083 [0.064; 0.107] | 0.088 [0.068; 0.113] | 0.101 [0.081; 0.126] | 0.089 [0.068; 0.112] | 0.079 [0.061; 0.106] |
| Brier | 0.093 [0.075; 0.108] | 0.094 [0.076; 0.109] | 0.096 [0.078; 0.111] | 0.095 [0.077; 0.110] | 0.093 [0.075; 0.108] |
| Độ nhạy @ngưỡng khóa | 0.034 [0.018; 0.049] | 0.100 [0.076; 0.124] | 0.172 [0.068; 0.339] | 0.097 [0.055; 0.144] | 0.192 [0.099; 0.298] |
| Nhắc nhầm/giờ | 1.159 [0.751; 1.558] | 2.397 [2.161; 2.650] | 1.910 [1.222; 2.776] | 2.120 [1.738; 2.508] | 1.264 [0.596; 2.045] |
| Phút nhắc trước | 3.000 [1.000; 4.000] | 2.385 [1.333; 3.267] | 3.000 [2.700; 3.333] | 3.571 [3.000; 4.000] | 2.167 [1.500; 2.500] |
| PR-AUC − (a) | — | 0.005 [0.000; 0.011] | 0.018 [0.010; 0.028] | 0.007 [0.001; 0.011] | -0.003 [-0.008; 0.001] |

**đối chứng công suất `--planted`** — 3994 mốc, tỷ lệ dương 0.040, chạy 185.7 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU | (e) chỉ thời gian ngồi |
|---|---|---|---|---|---|
| PR-AUC | 0.072 [0.048; 0.107] | 0.053 [0.038; 0.075] | 0.167 [0.115; 0.266] | 0.367 [0.209; 0.577] | 0.045 [0.039; 0.056] |
| Brier | 0.037 [0.033; 0.041] | 0.038 [0.034; 0.042] | 0.036 [0.031; 0.040] | 0.032 [0.024; 0.042] | 0.038 [0.034; 0.043] |
| Độ nhạy @ngưỡng khóa | 0.151 [0.092; 0.215] | 0.170 [0.103; 0.237] | 0.736 [0.606; 0.838] | 0.906 [0.833; 0.964] | 0.000 [0.000; 0.000] |
| Nhắc nhầm/giờ | 0.838 [0.650; 1.067] | 1.496 [1.221; 1.791] | 1.999 [1.711; 2.319] | 2.012 [1.739; 2.272] | 1.999 [1.830; 2.190] |
| Phút nhắc trước | 1.333 [1.062; 1.571] | 1.476 [1.222; 1.714] | 1.818 [1.555; 2.000] | 1.625 [1.244; 1.857] | — |
| PR-AUC − (a) | — | -0.020 [-0.035; -0.007] | 0.094 [0.060; 0.177] | 0.295 [0.124; 0.499] | -0.027 [-0.058; -0.004] |

**bộ giả của backend (7 người đủ mốc)** — 1330 mốc, tỷ lệ dương 0.143, chạy 25.3 s

| | (a) | (b) Markov | (c) Logistic | (d) GRU | (e) chỉ thời gian ngồi |
|---|---|---|---|---|---|
| PR-AUC | 0.255 [0.198; 0.376] | 0.216 [0.136; 0.333] | 0.335 [0.251; 0.821] | 0.167 [0.160; 0.285] | 0.094 [0.054; 0.212] |
| Brier | 0.100 [0.064; 0.178] | 0.184 [0.172; 0.212] | 0.201 [0.075; 0.352] | 0.264 [0.241; 0.283] | 0.128 [0.086; 0.229] |
| Độ nhạy @ngưỡng khóa | 0.989 [0.970; 1.000] | 0.284 [0.214; 0.472] | 0.858 [0.526; 1.000] | 0.489 [0.129; 0.874] | 0.347 [0.185; 0.505] |
| Nhắc nhầm/giờ | 2.096 [1.097; 3.019] | 1.088 [0.234; 2.433] | 2.096 [1.031; 3.149] | 2.217 [0.601; 4.043] | 1.451 [0.527; 2.433] |
| Phút nhắc trước | 1.279 [1.143; 1.467] | 1.438 [1.300; 1.543] | 1.472 [1.286; 1.600] | 1.381 [1.000; 1.706] | 1.526 [1.308; 1.690] |
| PR-AUC − (a) | — | -0.038 [-0.082; -0.006] | 0.081 [-0.037; 0.493] | -0.087 [-0.136; 0.028] | -0.161 [-0.219; -0.112] |


**Đọc các kết quả trên** (protocol v2; mọi số là kiểm code, không phải kết quả nghiên cứu):
- Bộ `simulate.py` chính: tín hiệu dự báo *có nhưng yếu* (khởi phát BAD hiếm; tỷ lệ dương tăng từ ~5% khi ngồi < 10 phút lên ~21% khi ngồi > 70 phút). Chỉ **(e)** (chỉ thời gian ngồi) hơn (a) với CI loại 0 (+0,054 [0,005; 0,110]); (c) +0,031 [−0,001; 0,057] và (d) +0,038 [−0,007; 0,090] có CI chứa 0. Tức là trên bộ này các mô hình đầy đủ **không hơn mốc đơn giản chỉ dùng thời gian ngồi**: 23 đặc trưng/GRU không thêm thông tin so với đặc trưng đã đưa vào mô phỏng, và với 10 người chỉ có (e) đủ ổn định. Tiêu chí "(c)/(d) hơn (a) rõ ràng" vẫn **không đạt** trên bộ chính. Không chỉnh mô phỏng cho đẹp.
- Đối chứng công suất `--planted` (BAD khởi phát xác định khi ngồi đủ T phút, T riêng từng người): (d) hơn (a) rõ (+0,295 [0,124; 0,499]), (c) +0,094 [0,060; 0,177]. (e) **không** hơn (a) (PR-AUC 0,045 ≈ tỷ lệ dương 0,040, độ nhạy 0) vì T khác nhau theo người nên quan hệ với thời gian ngồi không tuyến tính chung; điều này cho thấy (e) chỉ bắt được tín hiệu *đơn điệu*. Pipeline phát hiện được tín hiệu mạnh.
- Đối chứng xáo nhãn trong người: PR-AUC của cả 5 về 0,08–0,10, quanh tỷ lệ dương 0,103; chênh lệch với (a) nhỏ (≤ 0,018) dù vài CI loại 0. Mức lệch này đến từ LOSO (người test có tỷ lệ dương cao khiến mô hình train thấy tỷ lệ thấp hơn → (a) 0,083 < 0,103) và từ chia nhóm, không phải rò rỉ nhãn (nhãn đã xáo thì không mô hình nào có tín hiệu). Khi đọc dữ liệu thật, chênh lệch cỡ ±0,02 không nên coi là bằng chứng.
- Bộ `generate-research-pilot.py` (BAD tăng tuyến tính theo phút, quá nhỏ): chỉ dùng kiểm đọc file, quy tắc 3.1, phút thiếu, `model_version` khác; số liệu không có ý nghĩa dự báo.
- So với v1 (validation 25% người cho cả 4 mô hình, không fit lại): nhắc nhầm/giờ trên test của (a) và (c) gần như không đổi (v1: 1,65 và 2,04; v2: 1,71 và 1,98), tức đổi cách chọn ngưỡng không làm khác kết luận trên dữ liệu giả.

## 6. Quyết định (Việt đã xác nhận 26/11/2026)

Kế hoạch không nêu rõ; đã chọn phương án đơn giản và khóa trong `protocol.json`. Việt đã **xác nhận 1, 2, 3, 4, 5, 7, 8, 9**; **6 được đổi** (protocol v2, xem dưới). Mốc (e) thêm theo yêu cầu của Việt.
1. ✅ **Ngưỡng reset thời gian ngồi**: `away_sec ≥ 30` trong một phút. (Kế hoạch: "reset khi `away_sec` ≥ ngưỡng khóa".)
2. ✅ **Phút "quan sát được"** cho đặc trưng/trạng thái: phân loại được ≥ 30 s (cùng ngưỡng với điều kiện mốc).
3. ✅ **Phần thiếu tính cả thời gian rời ghế** (`60 − phân loại được`), nên mốc ngay trước/sau khi rời ghế thường bị bỏ. Nếu muốn dự báo cả "sắp rời ghế" thì phải đổi định nghĩa trong kế hoạch trước.
4. ✅ **Phút nhắc trước**: phút BAD đầu tiên = phút có BAD ≥ 50% phân loại được; nhắc mà y = 1 nhưng không có phút nào như vậy (BAD rải đều dưới 50%) bị bỏ khỏi trung bình (báo `lead_n`).
5. ✅ **Nhắc chỉ xét tại các mốc hợp lệ** (phút chủ yếu GOOD, đủ dữ liệu); phút khác không nhắc được. Nhắc nhầm/giờ tính theo `presence_sec` của mọi phút, nên là mức *tối thiểu* so với chạy thật trong Desktop.
6. **Ngưỡng nhắc** (ĐÃ ĐỔI ở protocol v2, sửa trước khi có dữ liệu thật, chỉ dựa trên kiểm code với dữ liệu giả): thấp nhất thỏa ≤ 2 nhắc nhầm/giờ; im 10 phút giữa hai lần nhắc. (a),(b),(c),(e): chọn trên dự đoán ngoài lượt của LOSO lồng trong train fold rồi fit lại trên toàn bộ train fold. (d) GRU: vẫn validation 25% người (early stopping + chọn ngưỡng), không fit lại. Bản v1 (validation 25% người cho cả 4 mô hình, không fit lại) đã bỏ.
7. ✅ **Mốc (a)** dùng tần suất dương theo 5 nhóm tỷ lệ BAD (không dùng tỷ lệ BAD thô). **Mốc (b)** là Markov bậc 1 trên 6 trạng thái; ước lượng xác suất "≥ 50% BAD" bằng tỷ lệ BAD trung bình của trạng thái (nên chỉ có 6 giá trị p khác nhau).
8. ✅ **Tham số (c)/(d)** (C = 1, 16 đơn vị GRU, lr 0,003…) khóa từ đầu, không dò. Muốn dò phải làm trong train fold và ghi lại.
9. ✅ `min_persons = 4`. Dưới mức này `evaluate.py` từ chối chạy.

## 7. Giới hạn

- Các mốc liền nhau trong một phiên tương quan mạnh; bootstrap theo người đã tính đến điều này nhưng với ít người CI sẽ rất rộng.
- Nhãn `y` suy từ chính phân loại của model v4 (RULA), nên đây là dự báo *nhãn của model*, không phải ngồi sai "thật".
- Chưa có dữ liệu thật; chưa hiệu chỉnh xác suất (calibration) ngoài việc vẽ biểu đồ.
