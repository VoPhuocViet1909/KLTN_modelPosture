# Pipeline xây dựng `posture_model` (MediaPipe Pose + RULA nhóm B)

> Tài liệu tham chiếu để so sánh với hướng **MotionBERT**.
> Bối cảnh: giám sát tư thế ngồi làm việc máy tính, chạy trên thiết bị biên (CPU), cảnh báo thời gian thực.
> Code đi kèm: notebook **v3** (`posture_features.py`, `realtime_posture.py`).

---

## 0. Tổng quan

```
TRAIN (1 cam hông 90°)
Video 90° → MediaPipe → Lọc nhiễu → Góc cổ/thân → RULA nhóm B (teacher)
→ GOOD/BAD + lọc sát ngưỡng → Cửa sổ 2s → Transformer → Đánh giá → ONNX

INFERENCE (2 cam)
Cam hông 90° → MediaPipe → Student ONNX       → GOOD/BAD (cổ, thân)
Cam laptop   → MediaPipe → Công thức lệch vai → SHOULDER_TILT
→ Gộp theo thời gian + median filter + debounce → Cảnh báo
```

| Thành phần | Lựa chọn |
|---|---|
| Pose estimator | MediaPipe Pose Landmarker (BlazePose full, 33 landmark 2D + world landmark 3D) |
| Camera khi train | **1 cam hông 90°** (đo cổ, thân) |
| Camera khi inference | **Cam hông 90°** (cùng vị trí lúc train) + **cam laptop chính diện** (chỉ đo lệch vai) |
| Teacher | RULA **nhóm B** (cổ, thân, chân) + 1 luật bổ sung (ngả sau); bỏ nhóm A, điểm cơ và điểm lực |
| Student | Transformer nhỏ trên chuỗi góc khớp (2 s @ 10 fps) |
| Lệch vai | **Công thức hình học + ngưỡng** trên cam laptop, **không train** |
| Nhãn của student | Nhị phân GOOD/BAD (nhãn phụ nếu cần: SLOUCH, LEAN_FORWARD, FORWARD_HEAD, LEAN_BACKWARD) |

**Vì sao chia như vậy**
- Cam hông 90° là góc đo cổ và thân chính xác nhất. Đặt cam chạy thật **cùng góc 90° như lúc train** thì không còn lệch góc nhìn giữa train và inference, nên không cần augmentation phối cảnh hay tập test góc khác.
- Cam hông không thấy được hai vai (hai vai chồng lên nhau), còn cam laptop chính diện thấy rõ. Lệch vai là một góc hình học đơn giản, đặt ngưỡng trực tiếp là đủ, không cần mô hình học.
- Hai nhánh chạy độc lập, chỉ gộp kết quả theo thời gian, nên **không cần đồng bộ từng frame** giữa 2 cam.

---

## 1. Thu thập dữ liệu

**Quy mô mục tiêu:** 10 người × 3 phiên (hiện có P01–P03, mỗi người 2 phiên). Mỗi phiên quay đủ các tư thế đúng và sai, kèm các động tác gây nhiễu (vươn vai, uống nước, nghe điện thoại, nhặt đồ, quay đầu).

**Bố trí camera**

| Cam | Vị trí | Dùng cho |
|---|---|---|
| Cam hông | Ngang vai, vuông góc 90° với mặt phẳng dọc của người ngồi, cách khoảng 1.5–2 m, thấy rõ từ hông đến đầu | Train (teacher + student) **và** chạy thật |
| Cam laptop | Chính diện, trên màn hình, thấy rõ hai vai | Chỉ lúc chạy thật (lệch vai) + vài clip để kiểm tra công thức |

**Kịch bản mỗi phiên (cam hông):** `CALIBRATION` (ngồi chuẩn 10 s), `GOOD`, `NATURAL`, `FORWARD_HEAD`, `LEAN_FORWARD`, `LEAN_BACKWARD`, `SLOUCH`, `DISTRACTOR_*`.

**Kịch bản cam laptop (không train):** `CALIBRATION` chính diện (ngồi chuẩn 10 s), `SHOULDER_TILT` nghiêng trái / phải ở vài mức. Hiện chỉ có `P01_S01_SHOULDER_TILT_01/02` và chưa có clip CALIBRATION chính diện; nên quay bổ sung để chọn ngưỡng và báo cáo độ chính xác của công thức.

**Quy tắc quay**
- FPS cố định (khuyến nghị 30 fps). Ghi lại độ phân giải.
- Ánh sáng đều, áo không trùng màu ghế hoặc nền.
- Tên file: `P<người>_S<phiên>_<KỊCH_BẢN>_<số>.mp4`. Lưu metadata: `subject_id, session_id, cam_id, angle_deg, fps, w, h`.
- Một phiên mà quay ở 2 setup khác nhau (khác độ phân giải / vị trí cam) sẽ được hiệu chuẩn riêng từng setup.

**Chia tập dữ liệu theo người, không chia theo frame**, để tránh rò rỉ dữ liệu. Với ít người như hiện tại dùng **Leave-One-Subject-Out (LOSO)**; khi đủ 10 người có thể chia `train 6 / val 2 / test 2`.

---

## 2. Trích xuất keypoint (MediaPipe Pose)

```python
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
det = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
    base_options=mpt.BaseOptions(model_asset_path="pose_landmarker_full.task"),
    running_mode=vision.RunningMode.VIDEO, num_poses=1))
r = det.detect_for_video(mp_image, timestamp_ms)
lm  = r.pose_landmarks[0]        # 2D chuẩn hóa (x,y ∈ [0,1]) + visibility
wlm = r.pose_world_landmarks[0]  # 3D đơn vị mét, gốc tại tâm hông
```

- Lấy mẫu **~10 fps** (bỏ bớt frame), ảnh thu nhỏ ½ để chạy nhanh. Lúc chạy thật cũng lấy mẫu 10 fps cho khớp với lúc train.
- **Lưu mỗi video:** `lm (T,33,3)` pixel x, y, visibility; `world (T,33,3)`; `t`; `fps`; `wh` → file `.npz`.

**Landmark sử dụng**

| Bộ phận | Chỉ số MediaPipe | Dùng cho |
|---|---|---|
| Mũi | 0 | Hướng mặt (cam hông) |
| Mắt trái / phải | 2 / 5 | Góc cúi mặt (cam hông) |
| Tai trái / phải | 7 / 8 | Góc cổ (cam hông) |
| Vai trái / phải | 11 / 12 | Cổ, thân (cam hông); **lệch vai (cam laptop)** |
| Hông trái / phải | 23 / 24 | Thân (cam hông) |

---

## 3. Tiền xử lý và lọc nhiễu

1. **Đổi sang pixel trước khi tính góc** (bắt buộc, nếu không tỉ lệ khung hình làm sai góc): `X = x·W`, `Y = y·H`.
2. **Chọn bên gần camera** (cam hông): ưu tiên world z (bên có z nhỏ hơn gần cam hơn), dự phòng bằng visibility tai + vai + hông. Chọn chung cho cả một setup.
3. **Hướng mặt:** dấu của `x_mũi − x_tai` → `f = ±1`, để góc "gập ra trước" luôn dương dù người quay mặt sang trái hay phải ảnh.
4. **Khung thiếu điểm:** thiếu tai / vai / hông thì góc = NaN; cửa sổ có < 80% khung hợp lệ hoặc visibility hông trung bình < 0.3 thì bỏ.
5. **Làm mượt lúc chạy thật:** median 5 kết quả gần nhất cho cả xác suất BAD và góc lệch vai (mục 11).
6. **Trục y ảnh hướng xuống.** Góc so với phương thẳng đứng dùng vector hướng lên `(0, −1)`.

---

## 4. Tính góc

### 4.1 Góc cổ, thân, cúi đầu (cam hông 90°)

```python
def _ang(v, f):
    """Góc (độ) của vector v so với phương thẳng đứng hướng LÊN, dương khi nghiêng về phía mặt."""
    return math.degrees(math.atan2(v[0] * f, -v[1]))

trunk      = _ang(S - H, f)                 # thân so với phương đứng (+ gập trước, − ngả sau)
neck       = _ang(Ea - S, f) - trunk        # cổ so với trục thân (đúng định nghĩa RULA)
head_pitch = atan2(y_mắt − y_tai, (x_mắt − x_tai)·f)   # cúi mặt (+ = mắt thấp hơn tai)
```

`S` vai, `H` hông, `Ea` tai ở bên gần camera (tọa độ pixel).

> **Lưu ý về cổ:** MediaPipe không có khớp đốt sống cổ (C7) hay đỉnh đầu. Vector `vai → tai` là xấp xỉ; ở tư thế ngồi thẳng góc này lệch sẵn 15–35° tùy người, nên **bắt buộc hiệu chuẩn baseline** theo từng người (mục 6.2). Góc cúi mặt `head_pitch` bổ sung cho kiểu gù mà chỉ cúi mặt, đường tai–vai ít thay đổi.

### 4.2 Công thức lệch vai (cam laptop, chỉ dùng lúc inference, không train)

```
Đường vai: từ vai bên TRÁI ẢNH → vai bên PHẢI ẢNH (pixel)
tilt      = atan2(dy, dx)                    (độ; ~0° khi vai cân)
tilt_rel  = tilt − baseline_tilt             (baseline = trung vị lúc hiệu chuẩn)
tilt_med  = median 5 giá trị tilt_rel gần nhất
LỆCH VAI  ⇔ |tilt_med| > 3,5°   ;   HẾT LỆCH ⇔ |tilt_med| < 2,5°
→ debounce: lệch liên tục ≥ 5 s mới cảnh báo, cân lại ≥ 3 s mới tắt
```

```python
SHOULDER_TILT_ON, SHOULDER_TILT_OFF, MIN_SHOULDER_VIS = 7.0, 5.0, 0.5

def shoulder_tilt(p):
    """p: (33,3) pixel x,y,vis từ cam CHÍNH DIỆN -> góc đường vai so với phương ngang (độ)."""
    L, R = p[11], p[12]
    if min(L[2], R[2]) < MIN_SHOULDER_VIS:      # vai bị che / ra khỏi khung -> bỏ khung
        return np.nan
    dx, dy = R[0] - L[0], R[1] - L[1]
    if dx < 0:                                  # ảnh lật gương (selfie) vẫn ra cùng độ lớn
        dx, dy = -dx, -dy
    return math.degrees(math.atan2(dy, dx))
```

- **Trừ baseline** loại bỏ việc cam laptop đặt hơi nghiêng và vai lệch bẩm sinh của từng người.
- **Ngưỡng trễ 3,5°/2,5°** tránh cảnh báo bật tắt liên tục khi góc dao động quanh ngưỡng.
- Ngưỡng 3,5° là do đề tài tự chọn (RULA chỉ định nghĩa "thân nghiêng sang bên" dạng có/không). Chọn từ chạy thử trên `P01_S01_SHOULDER_TILT_01/02`: đoạn nghiêng vai chủ ý chỉ lệch khoảng 4–5°, còn khi ngồi thẳng góc dao động khoảng ±2°; ngưỡng 7° ban đầu bỏ sót gần hết. Mới có 1 người nên cần tinh chỉnh lại trên thêm clip SHOULDER_TILT có nhãn tay (mục 10).
- Vươn vai, với tay sang bên cũng làm nghiêng vai trong thời gian ngắn; debounce 5 s lọc phần lớn các trường hợp này.

---

## 5. RULA nhóm B (Cổ – Thân – Chân)

*(Theo McAtamney & Corlett, 1993, Applied Ergonomics 24(2): 91–99)*

### 5.0 Vì sao chỉ dùng nhóm B

- Mục tiêu đề tài là **cột sống và thị lực**. Nhóm B (cổ, thân) phản ánh trực tiếp các lỗi gù lưng, đầu đưa ra trước và rướn người.
- Nhóm A (cánh tay, cẳng tay, cổ tay, xoay cổ tay) gần như cố định khi ngồi gõ phím, nên ít giúp phân biệt GOOD với BAD.
- MediaPipe Pose **không đo tin cậy** được cổ tay và độ xoay cổ tay. Nếu giữ nhóm A, phần lớn điểm A sẽ là giá trị giả định.

**Hệ quả cần ghi trong khóa luận**

- Table C cần cả điểm A lẫn điểm B. Bỏ nhóm A nghĩa là **không còn Grand score và Action level chuẩn** của RULA. Điểm teacher là **điểm Cổ–Thân–Chân lấy từ Table B**, thang 1–9.
- Gọi phương pháp là **"RULA nhóm B"** hoặc **"RULA rút gọn Neck–Trunk–Leg"**, không gọi là RULA đầy đủ.
- Cam hông 90° không thấy xoay và nghiêng sang bên, nên teacher **không dùng cờ điều chỉnh** (mục 6.1).
- Lệch vai **không** nằm trong teacher; nó là **luật bổ sung ngoài RULA**, đo bằng cam laptop (mục 4.2).

### 5.1 Cổ (Neck, đo so với thân)

| Góc | Điểm |
|---|---|
| Gập 0°–10° | 1 |
| Gập 10°–20° | 2 |
| Gập > 20° | 3 |
| Ngửa ra sau (extension) | 4 |

Điều chỉnh theo RULA: xoay cổ **+1**, nghiêng cổ sang bên **+1**. *(Cam hông không đo được, mặc định 0.)*

### 5.2 Thân (Trunk)

| Góc | Điểm |
|---|---|
| Ngồi thẳng có tựa tốt, góc hông–thân ≥ 90° (≈ 0°) | 1 |
| Gập 0°–20° | 2 |
| Gập 20°–60° | 3 |
| Gập > 60° | 4 |

Điều chỉnh theo RULA: xoay thân **+1**, nghiêng thân sang bên **+1**. *(Cam hông không đo được, mặc định 0.)*

> RULA không phạt việc ngả lưng ra sau khi ngồi (ngả có tựa vẫn được 1 điểm). Vì vậy LEAN_BACKWARD dùng một **luật bổ sung ngoài RULA** (mục 5.5).

### 5.3 Chân (Legs)

Chân được đỡ và cân bằng: **1**. Không được đỡ: **2**. Với người ngồi làm việc, mặc định là **1**.

### 5.4 Table B

Hàng là điểm Neck; cột là Trunk 1–6 × Legs 1–2.

| Neck | T1 L1 | T1 L2 | T2 L1 | T2 L2 | T3 L1 | T3 L2 | T4 L1 | T4 L2 | T5 L1 | T5 L2 | T6 L1 | T6 L2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 3 | 2 | 3 | 3 | 4 | 5 | 5 | 6 | 6 | 7 | 7 |
| 2 | 2 | 3 | 2 | 3 | 4 | 5 | 5 | 5 | 6 | 7 | 7 | 7 |
| 3 | 3 | 3 | 3 | 4 | 4 | 5 | 5 | 6 | 6 | 7 | 7 | 7 |
| 4 | 5 | 5 | 5 | 6 | 6 | 7 | 7 | 7 | 7 | 7 | 8 | 8 |
| 5 | 7 | 7 | 7 | 7 | 7 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |
| 6 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 9 | 9 | 9 | 9 | 9 |

Bản gốc cộng thêm điểm cơ và lực vào kết quả Table B. Đề tài đã bỏ hai điểm này, nên **Điểm nhóm B = giá trị tra Table B**.

### 5.5 Từ điểm nhóm B sang nhãn GOOD/BAD

Khi chân = 1 và không có cờ điều chỉnh, Table B rút gọn thành:

| Neck \ Trunk | 1 (≤ 5°*) | 2 (5–20°) | 3 (20–60°) | 4 (> 60°) |
|---|---|---|---|---|
| 1 (≤ 10°) | 1 | 2 | 3 | 5 |
| 2 (10–20°) | 2 | 2 | 4 | 5 |
| 3 (> 20°) | 3 | 3 | 4 | 5 |
| 4 (ngửa > 15°*) | 5 | 5 | 6 | 7 |

\* Góc so với baseline. Hai dung sai do đề tài đặt để chống nhiễu: thân lệch ≤ 5° vẫn tính là thẳng; cổ chỉ tính *ngửa* khi ngửa hơn baseline > 15° (nếu không, vài độ nhiễu làm điểm cổ nhảy thẳng từ 1 lên 4).

| Điểm nhóm B | Nhãn | Ý nghĩa |
|---|---|---|
| 1–2 | **GOOD** | Cổ và thân gần trung tính (gập ≤ 20°) |
| ≥ 3 | **BAD** | Có ít nhất một lỗi rõ: cổ gập > 20°, thân gập > 20°, hoặc cổ ngửa |

**Luật bổ sung ngoài RULA (trong teacher):** thân ngả sau quá 15° so với baseline → BAD (LEAN_BACKWARD).

**Góc cổ dùng để chấm:** `max(neck, head_pitch)`, tức lấy giá trị lớn hơn giữa góc tai–vai so với thân và góc cúi mặt.

**Vì sao chọn ngưỡng 3:** chỉ cần cổ gập > 20° (FORWARD_HEAD) hoặc thân gập > 20° (LEAN_FORWARD) là điểm B đã bằng 3. Nếu đặt ngưỡng ở 4, mô hình sẽ bỏ sót đúng hai lỗi chính mà đề tài nhắm tới.

### 5.6 Code RULA nhóm B

```python
TABLE_B = {  # neck -> [T1L1, T1L2, T2L1, T2L2, ..., T6L1, T6L2]
 1:[1,3,2,3,3,4,5,5,6,6,7,7], 2:[2,3,2,3,4,5,5,5,6,7,7,7],
 3:[3,3,3,4,4,5,5,6,6,7,7,7], 4:[5,5,5,6,6,7,7,7,7,7,8,8],
 5:[7,7,7,7,7,8,8,8,8,8,8,8], 6:[8,8,8,8,8,8,8,9,9,9,9,9],
}
BAD_SCORE, NEUTRAL_TOL, NECK_EXT_TOL, LEAN_BACK_TOL = 3, 5.0, 15.0, 15.0

def score_neck(a):
    if a < -NECK_EXT_TOL: return 4
    if a <= 10:           return 1
    if a <= 20:           return 2
    return 3

def score_trunk(a):
    if a <= NEUTRAL_TOL: return 1          # thẳng, hoặc ngả sau có tựa
    if a <= 20:          return 2
    if a <= 60:          return 3
    return 4

def group_b_score(neck, trunk, legs=1):
    return TABLE_B[score_neck(neck)][(score_trunk(trunk) - 1) * 2 + (legs - 1)]

def b_label(neck, trunk):                   # 0 = GOOD, 1 = BAD
    return int(group_b_score(neck, trunk) >= BAD_SCORE or trunk < -LEAN_BACK_TOL)
```

---

## 6. Áp dụng RULA nhóm B cho bài toán ngồi máy tính (teacher)

### 6.1 Ánh xạ thành phần nhóm B sang dữ liệu đo được

| Thành phần | Nguồn | Cách lấy | Độ tin cậy |
|---|---|---|---|
| Neck | Cam hông 90° | `max(neck_rel, head_pitch_rel)` | Tốt sau hiệu chuẩn |
| Neck side-bend / twist | — | Cam hông không thấy, mặc định **0** | — |
| Trunk | Cam hông 90° | `trunk_rel = trunk − baseline` | Tốt sau hiệu chuẩn |
| Trunk side-bend | — | Mặc định **0** trong teacher; lệch vai do cam laptop bắt riêng (mục 4.2) | — |
| Trunk twist | — | Mặc định **0** | — |
| Legs | Mặc định | **1** (ngồi, chân chạm sàn) | Giả định |
| Muscle use / Force | **Bỏ** | Ngồi tĩnh nên giá trị như nhau, không giúp phân biệt GOOD/BAD | — |

### 6.2 Hiệu chuẩn theo người (baseline)

Cho người dùng ngồi đúng chuẩn 10 giây, lấy **trung vị** làm baseline:
- **Lúc train:** clip `CALIBRATION` của cam hông → `neck`, `trunk`, `head_pitch`. Thiếu clip này thì lấy 10 s đầu các clip GOOD. Hiệu chuẩn riêng cho từng *(người, phiên, độ phân giải)*.
- **Lúc chạy thật:** 10 s đầu (hoặc khi bấm `c`) → baseline cổ / thân / cúi đầu từ cam hông **và** baseline lệch vai từ cam laptop, cùng một lúc.

```
neck_rel  = neck  − baseline_neck
trunk_rel = trunk − baseline_trunk
tilt_rel  = tilt  − baseline_tilt
```

Cách này loại bỏ sai lệch do vị trí camera, camera hơi nghiêng, vai lệch bẩm sinh và việc dùng tai thay cho đỉnh đầu.

### 6.3 Gán nhãn và lọc frame sát ngưỡng

Thay vì liệt kê thủ công các ngưỡng, kiểm tra trực tiếp: **dịch góc cổ/thân ±2° mà nhãn đổi thì frame đó nằm sát ngưỡng ("không ổn định").** Cửa sổ có > 40% khung không ổn định bị bỏ khỏi tập train.

```python
def rula_frame_label(neck_rel, trunk_rel, head_pitch_rel, margin=2.0):
    n = max(neck_rel, head_pitch_rel)
    lab = b_label(n, trunk_rel)
    stable = all(b_label(n + dn, trunk_rel + dt) == lab
                 for dn in (-margin, margin) for dt in (-margin, margin))
    return lab, stable
```

**Nhãn phụ** (nếu cần đa lớp), suy ra từ thành phần gây điểm cao nhất:
- `neck > 20°` và thân thẳng → FORWARD_HEAD
- `trunk_rel > 20°` → LEAN_FORWARD
- thân gập kèm cổ gập → SLOUCH
- `trunk_rel < −15°` → LEAN_BACKWARD *(luật bổ sung, không thuộc RULA)*

**Kiểm tra chéo:** lấy ngẫu nhiên khoảng 5% cửa sổ, cho người xem lại để đo độ khớp giữa teacher và người (Cohen's κ). Báo cáo số này trong khóa luận.

---

## 7. Tạo cửa sổ thời gian (windowing)

- Cửa sổ **2 s = 20 khung @ 10 fps**, bước nhảy **0,5 s** (5 khung).
- Nhãn cửa sổ là **đa số** nhãn khung. **Bỏ** cửa sổ khi:
  - thiếu điểm: < 80% khung có đủ cổ + thân, hoặc visibility hông trung bình < 0.3;
  - nhãn lẫn: tỉ lệ BAD nằm trong (20%, 80%);
  - sát ngưỡng: < 60% khung ổn định.
- Giữ cả các clip DISTRACTOR / NATURAL (nhãn vẫn do teacher chấm) để student thấy các động tác nhiễu.
- Clip SHOULDER_TILT (cam laptop) **không** đưa vào tập train.

**Đầu vào của student** (mỗi khung):

| Nhóm | Đặc trưng |
|---|---|
| Góc (đã trừ baseline, chia 30°) | `neck`, `trunk`, `head_pitch` |
| Chất lượng | `vis_ear`, `vis_shoulder`, `vis_hip` |

NaN → 0. Kích thước tensor: `[B, T=20, F=6]`.

> Student học trên **góc khớp**, không học trên tọa độ thô, nên không phụ thuộc vị trí người trong khung hình hay khoảng cách tới cam.

---

## 8. Vị trí cam hông lúc chạy thật

Vì train bằng cam 90° nên khi chạy thật **cũng đặt cam hông ở 90°**, ngang vai, thấy rõ từ hông đến đầu. Khi đó không có lệch góc nhìn giữa train và inference.

Sai số còn lại chỉ là đặt cam lệch vài độ, hiệu chuẩn chưa chuẩn và nhiễu MediaPipe. Student được augmentation đúng cho các sai số này:

| Augmentation | Mô phỏng |
|---|---|
| Nhân góc với hệ số 0.95–1.05 | Đặt cam lệch vài độ so với 90° |
| Cộng hằng số ±2° (σ) vào góc đã hiệu chuẩn | Sai số baseline |
| Cộng nhiễu ±1° (σ) từng khung | Rung landmark |
| Xóa ngẫu nhiên 5% khung | Mất phát hiện |

> **Nếu bàn làm việc không đặt được cam 90°** (sát tường, lưng ghế hay màn hình che hông), phải đặt lệch (vd 70°): khi đó cần thêm augmentation co góc mạnh hơn (0.88–1.05 hoặc xoay world landmark rồi chiếu lại 2D) và **bắt buộc** quay một tập test ở đúng góc đó, có nhãn từ teacher chạy đồng thời trên cam 90°.

---

## 9. Mô hình student (Transformer)

```
Input [B, 20, 6]
  → Linear(6 → 64) + positional embedding (học được)
  → TransformerEncoder × 2 (d_model=64, heads=4, ff=128, dropout=0.1, pre-norm)
  → Mean pooling theo thời gian → LayerNorm
  → Linear(64 → 1) → logit BAD
```

| Siêu tham số | Giá trị |
|---|---|
| Optimizer | AdamW, lr 2e-3, weight decay 1e-2 |
| Scheduler | OneCycle, 40 epoch |
| Loss | BCEWithLogits, `pos_weight` theo tỉ lệ lớp |
| Batch | 128 |
| Augment | Mục 8 |
| Ngưỡng | P(BAD) ≥ 0.5 |

**Baseline để so sánh** (để chứng minh Transformer có giá trị):
1. **Rule-based RULA nhóm B** trực tiếp trên góc (không học). Phải so với **nhãn người** (vì nhãn train do chính luật này sinh ra).
2. **Random Forest** trên thống kê cửa sổ (mean, std, min, max của các đặc trưng). Notebook v3 đã chạy LOSO cùng Transformer.
3. **Transformer**.

> Nhãn train do teacher RULA sinh ra, nên Transformer thực chất học **xấp xỉ RULA nhóm B theo chuỗi thời gian** và chịu nhiễu tốt hơn. Giá trị của nó nằm ở độ ổn định theo thời gian và khả năng bỏ qua động tác nhiễu, cần chứng minh bằng số cảnh báo giả (mục 10).

---

## 10. Đánh giá

| Nhóm | Chỉ số |
|---|---|
| Độ chính xác góc | MAE (độ) của góc cổ, thân (cam hông) và góc lệch vai (cam laptop) so với ground truth (marker màu trên da) |
| Teacher | Cohen's κ giữa nhãn RULA nhóm B và nhãn người |
| Phân loại (student) | Accuracy, κ, độ nhạy BAD, độ đặc hiệu GOOD, **F1 lớp BAD**, ROC-AUC, confusion matrix — theo **LOSO** |
| Lệch vai (luật) | Precision / Recall phát hiện SHOULDER_TILT trên clip cam laptop có đánh dấu tay; số lần báo nhầm trên clip GOOD/NATURAL |
| Thực tế | **Số cảnh báo giả mỗi giờ** (trên đoạn DISTRACTOR/NATURAL), độ trễ phát hiện (giây) |
| Hiệu năng | FPS end-to-end **khi chạy 2 cam**, % CPU, RAM, ms/inference (ONNX trên CPU) |

---

## 11. Triển khai trong Desktop App

```
Cam hông 90° → MediaPipe (lấy mẫu 10 fps) → góc − baseline → buffer vòng 20 khung
   → mỗi khung mới: student ONNX → P(BAD) → median 5 giá trị
   → BAD nếu ≥ 0.6, GOOD nếu ≤ 0.4 (vùng giữa giữ nguyên)  ─┐
                                                            ├→ debounce riêng từng nhánh:
Cam laptop → MediaPipe (≤ 10 fps) → tilt − baseline         │   BAD liên tục ≥ 5 s → CẢNH BÁO
   → median 5 giá trị → lệch nếu > 3,5°, cân nếu < 2,5°  ───────┘   GOOD liên tục ≥ 3 s → tắt
                                                                cooldown 60 s giữa 2 cảnh báo cùng loại
   → cảnh báo theo loại: POSTURE_BAD (cổ/thân) / SHOULDER_TILT (lệch vai)
   → gửi telemetry (timestamp, nhãn, P(BAD), góc cổ/thân, tilt_rel) lên message broker
```

- Script: `python realtime_posture.py --side 1 --front 0` (cam hông = webcam 1, cam laptop = webcam 0); `--front -1` để tắt nhánh lệch vai; `--side-video/--front-video` để chạy thử trên 2 video quay cùng lúc. Phím `c` hiệu chuẩn lại.
- Hai nhánh chạy độc lập, mất cam laptop thì nhánh cổ/thân vẫn chạy.
- **Tải CPU:** MediaPipe trên 2 luồng video nặng gần gấp đôi; cả hai đều chỉ lấy mẫu 10 fps để giảm tải. Cần đo FPS / % CPU thật trên máy mục tiêu.
- Export: `torch.onnx.export` → `onnxruntime` CPU.
- Chỉ gửi **góc và nhãn** lên server, không gửi ảnh (đảm bảo quyền riêng tư).

---

## 12. So sánh với hướng MotionBERT

| Tiêu chí | MediaPipe Pose + RULA (tài liệu này) | MotionBERT |
|---|---|---|
| Bản chất | Detector 2D/3D theo từng frame, 33 landmark | Mô hình nâng chuỗi 2D lên 3D (2D→3D lifting); **cần** một detector 2D phía trước (vd HRNet/ViTPose qua MMPose) |
| Bộ khớp | 33 điểm, có tai, mắt, ngón tay; **không có** cột sống/cổ riêng | 17 khớp chuẩn Human3.6M, **có** Spine, Thorax, Neck, Head nên đo cổ và thân tự nhiên hơn |
| Đầu ra 3D | World landmark (giả 3D, độ sâu kém tin cậy) | 3D tốt hơn rõ rệt, nhất quán theo thời gian |
| Độ trễ | Gần thời gian thực trên CPU | Cần một chuỗi frame đầu vào (độ trễ theo cửa sổ), thường cần GPU |
| Phụ thuộc góc camera | Cao (góc 2D), giải quyết bằng đặt cam 90° + hiệu chuẩn | Thấp hơn nhờ 3D, góc đo ít phụ thuộc vị trí cam |
| Số cam cần | 2 (hông + laptop) | Có thể 1 cam (3D cho cả cổ/thân lẫn lệch vai) |
| Triển khai biên | Dễ (pip, chạy CPU) | Nặng; cần thêm detector 2D, khó đóng gói vào Desktop App |
| Phù hợp | Ứng dụng thời gian thực cho người dùng | Phân tích offline, sinh nhãn hoặc ground truth chất lượng cao |

### Cách so sánh công bằng giữa hai hướng

1. **Cùng dữ liệu, cùng split** theo người (LOSO), cùng tập test.
2. **Cùng teacher:** áp dụng **cùng RULA nhóm B ở mục 5** (cùng ngưỡng, cùng dung sai, cùng luật LEAN_BACKWARD) lên góc của mỗi bên. Với MotionBERT: thân = Pelvis→Thorax so với phương thẳng đứng; cổ = Thorax→Head so với trục thân. Cả hai bên đều bỏ nhóm A.
3. **Cùng cách đo lệch vai:** cùng định nghĩa, cùng ngưỡng 3,5°/2,5° và cùng debounce. MotionBERT có thể tính trên 3D: góc giữa đường LShoulder–RShoulder và mặt phẳng ngang.
4. **Cùng ground truth góc:** marker màu trên da, so MAE từng góc.
5. **Báo cáo đủ bộ chỉ số ở mục 10**, đặc biệt **FPS và CPU trên cùng một máy**. Đây là điểm quyết định cho ứng dụng biên.
6. Kết luận theo **trade-off**: độ chính xác góc so với chi phí tính toán, độ trễ và số cam cần dùng.

---

## 13. Checklist

- [ ] Quay đủ người × phiên bằng **cam hông 90°**, mỗi phiên có clip CALIBRATION
- [ ] Quay clip cam laptop: CALIBRATION chính diện + SHOULDER_TILT (trái/phải, vài mức)
- [ ] Trích xuất keypoint (~10 fps), lưu kèm metadata và world landmark
- [ ] Tính góc cổ / thân / cúi đầu, hiệu chuẩn baseline theo (người, phiên, setup)
- [ ] Chấm RULA nhóm B + luật ngả sau, lọc khung sát ngưỡng, cắt cửa sổ 2 s / 0,5 s
- [ ] Kiểm tra chéo teacher với người (κ)
- [ ] Train Transformer + Random Forest, đánh giá LOSO
- [ ] Kiểm tra công thức lệch vai, chọn ngưỡng trên clip SHOULDER_TILT có nhãn tay
- [ ] Export ONNX, chạy realtime 2 cam, đo FPS / CPU và số cảnh báo giả mỗi giờ
- [ ] So sánh với MotionBERT theo mục 12

---

**Tài liệu tham khảo**
- McAtamney, L., & Corlett, E. N. (1993). RULA: a survey method for the investigation of work-related upper limb disorders. *Applied Ergonomics*, 24(2), 91–99.
- Bazarevsky, V. et al. (2020). BlazePose: On-device Real-time Body Pose Tracking. arXiv:2006.10204.
- Zhu, W. et al. (2023). MotionBERT: A Unified Perspective on Learning Human Motion Representations. ICCV 2023.
