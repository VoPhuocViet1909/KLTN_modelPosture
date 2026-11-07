# Setup Kaggle: train Random Forest, giữ Transformer hiện có

Ngày chuẩn bị: 07/11/2026. **File upload chính: [kaggle_train_rf_v3.ipynb](kaggle_train_rf_v3.ipynb).**

Mục tiêu của lượt này là tạo model RF trên dữ liệu train cũ để sau đó so sánh với Transformer và luật góc trên video người mới. Notebook này chưa chạy phép so sánh cảnh báo; chưa cần quay/upload video test người mới.

## 1. Bạn cần chuẩn bị gì?

1. Dataset video train cũ trên Kaggle (cùng bản đã dùng trước đây), hoặc `dataset_windows.npz` của lần train cũ nếu còn.
2. Ba file tham chiếu **từ thư mục `posture_model/` đang dùng**:
   - `posture_config.json`
   - `posture_transformer.onnx`
   - `pose_landmarker_full.task`
3. Notebook `kaggle_train_rf_v3.ipynb` trong thư mục này.

Bản đóng gói tiện upload được tạo ở thư mục `upload/`: `posture-v3-reference.zip` chứa đúng ba file tham chiếu. Giải nén rồi upload ba file vào một dataset Kaggle riêng, đặt tên gợi ý `posture-v3-reference`, chọn quyền riêng tư phù hợp. Không đưa video người tham gia lên dataset công khai.

File Markdown bạn gửi ở Downloads đã được so hash với bản `training/posture_model_pipeline_mediapipe_rula.md`: cùng nội dung. Markdown mô tả quy trình; code chuẩn bị dữ liệu lấy từ notebook v3 đã lưu trong project, tránh chép những đoạn minh họa có ngưỡng khác nhau trong Markdown.

## 2. Đưa notebook lên Kaggle

1. Tạo/mở notebook Kaggle và dùng chức năng import/upload notebook `.ipynb`; chọn `kaggle_train_rf_v3.ipynb`.
2. Gắn dataset train cũ và dataset ba file tham chiếu vào notebook bằng khu vực **Input / Add Input** (tên nút có thể khác tùy giao diện).
3. Chọn CPU/không cần accelerator. RF và bước trích landmark này không cần GPU; bật GPU không tự làm RF dùng GPU.
4. Nếu notebook báo thiếu package, bật Internet rồi chạy ô thư viện. Notebook chỉ cài package còn thiếu, không ép nâng cấp cả môi trường.
5. Mở cây `/kaggle/input` để lấy đường dẫn thật; sửa ô **1. Cấu hình** trước khi chạy các ô còn lại.

Xem hướng dẫn nền tảng của [Kaggle Notebooks](https://www.kaggle.com/docs/notebooks) và [Kaggle Datasets](https://www.kaggle.com/docs/datasets). Đường dẫn mount là thông tin của từng dataset/session, không suy từ tên hiển thị.

## 3. Chọn đúng chế độ

### A. Còn dataset_windows.npz của lần train trước — ưu tiên cách này

Upload file đó thành dataset riêng, gắn vào notebook, rồi sửa:

```python
MODE = "npz"
ASSET_DIR = "/kaggle/input/duong-dan-dataset-tham-chieu"
DATASET_NPZ = "/kaggle/input/duong-dan-dataset-cu/dataset_windows.npz"
RUN_LOSO = True
```

Notebook bỏ qua trích landmark và tạo nhãn, đọc trực tiếp `X`, `Y`, `G`. File phải do pipeline cũ tạo, với `G` là chuỗi Unicode; không bật `allow_pickle=True` cho file không rõ nguồn để vượt qua lỗi đọc.

### B. Chỉ còn video train cũ — cách phù hợp nếu chưa lưu NPZ

```python
MODE = "video"
DATA_DIR = "/kaggle/input/datasets/vphcvit12a1/datakl/Video_TrainAI_KhoaLuan"
ASSET_DIR = "/kaggle/input/duong-dan-dataset-tham-chieu"
WORKERS = 2
RUN_LOSO = True
```

`DATA_DIR` trên được lấy từ notebook cũ; kiểm và sửa nếu Kaggle mount khác. Thư mục phải chứa các video tên `P01_S01_...`, `P02_...`, `P03_...`, gồm clip CALIBRATION/GOOD như lần trước. Không gắn video người mới vào train.

Notebook giữ cách chọn video, hiệu chỉnh và tạo cửa sổ của notebook gốc. Mỗi run có cache riêng. Việc chạy lại MediaPipe bằng môi trường mới **có thể tạo dữ liệu khác lần train Transformer trước**, kể cả khi dùng cùng video và asset. Nếu còn cache/môi trường lịch sử, nên lưu lại để đối chiếu. Đừng gọi dữ liệu dựng lại là “giống hệt” chỉ vì cùng 9.600 mẫu.

## 4. Chạy các ô theo thứ tự

| Ô/phần | Công việc | Bạn kiểm gì? |
| --- | --- | --- |
| 1 | Cấu hình, tìm asset, kiểm SHA-256 | Đường dẫn thật; đúng ba file của bản app hiện tại |
| 2 | Kiểm/cài package còn thiếu | Import thành công; ghi phiên bản |
| 3 | Ghi module đặc trưng nguyên bản | Không sửa góc/ngưỡng để ép khớp kết quả |
| 4 | Kiểm kê video hoặc nhận NPZ | Đúng train cũ; không có người mới trong train |
| 5 | Trích landmark | Chờ chạy hết video; lỗi video phải được xử lý |
| 6 | Tạo dataset | Xem số cửa sổ/BAD/người; bỏ qua nếu dùng NPZ |
| 7 | Ghi code RF và helper | Không có lệnh train/export Transformer |
| 8 | Kiểm dữ liệu | Khớp shape, số mẫu theo người và tỷ lệ BAD |
| 9 | RF LOSO tùy chọn + fit RF cuối | Có kết quả từng fold và file model cuối |
| 10 | Đóng ZIP | Có đường dẫn ZIP và xác nhận hash tham chiếu không đổi |

Sau khi sửa đường dẫn, có thể Run All. `RUN_LOSO=False` sẽ bỏ chẩn đoán LOSO để chỉ train RF cuối. Không dùng accuracy train của RF cuối để báo chất lượng trên người mới.

Các mốc đối chiếu trong config hiện hành:

| Dữ liệu | Số mẫu |
| --- | ---: |
| Tổng | 9.600 |
| P01 | 2.843 |
| P02 | 3.521 |
| P03 | 3.236 |
| BAD | 5.445 |

Notebook dùng 300 cây, `class_weight="balanced"`, seed 0, đầu vào 24 thống kê nối theo thứ tự mean(6), std(6), min(6), max(6). RF cuối fit trên toàn bộ dữ liệu cũ. Tham số bám notebook trước, không dò tham số trên video test.

## 5. Tải gì về?

Ô cuối tạo đường dẫn dạng:

```text
/kaggle/working/rf_run_<timestamp>/export_<timestamp>.zip
```

Tải qua liên kết của ô cuối hoặc lưu phiên bản notebook rồi lấy ZIP trong Output. Bên trong có:

- `posture_rf.joblib`: RF cuối, dùng cho **người mới**.
- `rf_metadata.json`: hash model/dataset/config, số mẫu, người train, tham số, phiên bản và kết quả RF LOSO nếu bật.
- `rf-requirements.txt`: phiên bản NumPy/SciPy/scikit-learn/joblib/threadpoolctl để chuẩn bị môi trường nạp RF.
- `dataset_windows.npz`: giữ lại để lần sau không phải dựng lại từ video.
- `reference_posture_config.json`, `posture_features.py`, `common.py`, `train_rf.py`, `environment.json`.
- Khi dựng từ video: thêm `video_manifest.json`, `frames_labeled.csv`, `windows_info.csv`.

ZIP không chứa video gốc, cache landmark hoặc model Transformer mới. Không chép toàn bộ ZIP đè lên `posture_model/`; lưu ở thư mục thí nghiệm riêng.

## 6. Các lỗi thường gặp

| Lỗi | Cách xử lý |
| --- | --- |
| `NameError: name 'digest' is not defined` ở ô kiểm kê (bản đầu) | Bản cập nhật cho ô kiểm kê tự định nghĩa hàm SHA-256 và import cần thiết. Với notebook đang mở, thêm hàm `digest` từ bản mới vào đầu ô kiểm kê rồi chạy lại ô đó. Nếu còn thiếu `MODE`/`DATA_DIR`/`RUN_DIR`, cần chạy ô cấu hình thành công; lỗi cũ có thể do bỏ qua ô, ô trước bị dừng hoặc restart session. Không cần chạy lại ô tạo run nếu các biến vẫn đầy đủ. |
| Không tìm thấy ASSET_DIR/DATA_DIR | Xem cây Input và copy đường dẫn thật; dataset có thể nằm dưới nhiều cấp thư mục. |
| Hash file tham chiếu khác | Upload lại đúng ba file từ app. Nếu chủ động đổi bản app, cần tái chuẩn bị notebook/hash và ghi rõ phiên bản; không sửa hash chỉ để bỏ lỗi. |
| Không có video đúng tên | Kiểm thư mục con và tên `Pxx_Sxx_...`; giữ nguồn train như trước. |
| Tên video trùng ở nhiều thư mục | Đối chiếu nguồn trước; notebook dừng để tránh hai video ghi vào cùng cache. |
| 9.600 mẫu hoặc số mẫu từng người không khớp | So dataset/version, clip thiếu/trùng, asset, MediaPipe và điều kiện baseline. Tìm NPZ/cache gốc nếu có; giữ log và số mới để điều tra. |
| Cùng số mẫu nhưng tỷ lệ BAD khác | Nhãn hoặc preprocessing đã khác; không tiếp tục coi đây là cùng bộ train. |
| Hết RAM khi trích video | Giảm WORKERS xuống 1; notebook train RF cần RAM cho dữ liệu và rừng cây, không giải quyết bằng bật GPU. |
| Cell trích bị ngắt | Trong cùng session, chạy lại cell đó để dùng lại cache run hiện tại; bắt đầu từ cell cấu hình tạo run mới. |
| Gói thư viện thiếu, cài thất bại | Bật Internet và kiểm log pip; không tiếp tục với import lỗi. Nếu Kaggle yêu cầu restart, chạy lại tuần tự từ cấu hình. |

## 7. Sau khi chạy xong mới làm bước so sánh cảnh báo

Gửi hoặc lưu lại ZIP cùng notebook có output. Bước tiếp theo mới là chạy RF, Transformer giữ nguyên và luật góc trên video liên tục của người mới; dùng nhãn chấm độc lập và cùng hậu xử lý. Code notebook này **chỉ hoàn thành khâu chuẩn bị RF**, không xuất số FP/giờ hay trễ cảnh báo giả lập.

Model `joblib` cần được nạp từ nguồn tin cậy và môi trường phù hợp; scikit-learn không hỗ trợ bảo đảm nạp model qua các phiên bản khác nhau. Xem [hướng dẫn lưu model](https://scikit-learn.org/stable/model_persistence.html) và [RandomForestClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html). Metadata/requirements giúp truy vết, không tự chứng minh độ chính xác.

**Phạm vi kiểm tại lúc bàn giao:** xem kết quả kiểm được ghi trong tiến độ dự án. Notebook không có output train thật sẵn; cần chạy trên tài khoản Kaggle và dataset của bạn để có model/kết quả.
