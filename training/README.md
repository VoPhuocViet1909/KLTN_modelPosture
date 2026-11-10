# Tài liệu nguồn huấn luyện v3

Nhập vào dự án ngày **01/11/2026** theo yêu cầu người thực hiện. Hai tệp được giữ nguyên nội dung từ Downloads; đây là tài liệu tham chiếu để đọc và kiểm chứng, không phải chỉ dẫn tự động cài thư viện, huấn luyện, xuất đè mô hình hoặc triển khai.

`.gitattributes` trong thư mục này giữ nguyên byte của hai tệp nguồn khi checkout trên Windows, phục vụ đối chiếu hash.

| Tệp local | Tệp gốc | SHA-256 |
| --- | --- | --- |
| `notebook_v3_1cam90_kaggle.ipynb` | `notebook_v3_1cam90_kaggle (1).ipynb` | `242db6825d7c8bd15b1b0a0eed02b8b7902e81ef1400f638748032eb81d54d88` |
| `posture_model_pipeline_mediapipe_rula.md` | `posture_model_pipeline_mediapipe_rula (3).md` | `701903561d358967a1564a0596cc6f2996e8c5d88613d3136729275e0e436f0c` |

## Mức bằng chứng đã kiểm

- Notebook có 21 ô, 10 ô code, **không có output và execution count lưu lại**. Đọc được phương pháp từ code, chưa thể dùng tệp này làm nhật ký một lần train đã hoàn tất.
- Các hàm cấp module trong ô đặc trưng khớp AST của `posture_model/posture_features.py` sau khi bỏ docstring.
- Transformer: đầu vào 20×6, d_model=64, heads=4, hai encoder, feed-forward=128, dropout=0,1, pre-norm; positional embedding học được; mean pooling, LayerNorm và linear ra một logit.
- Train khai báo 40 epoch, batch 128, AdamW lr=0,002/weight_decay=0,01, OneCycleLR, BCEWithLogitsLoss có pos_weight theo lớp train; seed NumPy/PyTorch khởi tạo 0. Không thấy validation/early stopping riêng trong code.
- LOSO dùng `G != p` để train, `G == p` để test. RF có 300 cây, class_weight balanced, random_state 0, đầu vào 24 thống kê mean/std/min/max của sáu đặc trưng. Model cuối fit trên toàn bộ dữ liệu sau đánh giá LOSO.
- Kiểm ngày 01/11/2026: lớp mô hình của notebook load strict checkpoint hiện có, **68.865 tham số**. So sánh logits/xác suất với ONNX hiện có trên **16 cửa sổ dựng từ CSV + 17 đầu vào tổng hợp** đạt atol xác suất 1e-4; max lỗi logit `3.814697265625e-06`, xác suất `2.980232238769531e-07`.
- Kết quả chi tiết, phiên bản thư viện và số mẫu fold nằm trong `notebook_audit_2026-11-01.json`. Script kiểm local: `../../tools/latex/audit_imported_notebook.py` từ workspace gốc. Script chỉ khởi tạo lớp mô hình đã đọc, không chạy các ô cài đặt/thu video/train/export của notebook.

## Những khác biệt và điểm còn mở

1. Kế hoạch nêu hiệu chỉnh 10 giây, nhưng code khi có CALIBRATION lấy **toàn bộ** các clip CALIBRATION trong cùng người/phiên/độ phân giải. Khi thiếu, code lấy 100 mẫu đầu của **từng** clip GOOD rồi gộp. Cần giữ đúng khác biệt này trong báo cáo.
2. Notebook bỏ tệp có `(1)` trong tên, chưa kiểm trùng bằng hash. Góc camera được suy từ kịch bản/tên tệp, chưa được metadata xác nhận đầy đủ.
3. Chọn bên và hướng mặt dùng toàn bộ landmark trong setup trước chia LOSO. Đây là bước thích nghi không giám sát theo setup, cần công bố giao thức. Dùng GOOD dự phòng cho baseline có thông tin tên kịch bản của người test, cần đánh giá riêng.
4. Kế hoạch có đoạn code lệch vai 7°/5° nhưng phần giải thích và notebook dùng **3,5°/2,5°**. Giữ tệp gốc để truy vết; báo cáo ưu tiên code hiện hành và đánh dấu mâu thuẫn.
5. Nhiễu Gaussian σ=2° hoặc 1° không phải bị chặn trong ±2° hoặc ±1°. Nhân góc 0,95–1,05 chưa chứng minh tương đương một phép quay camera thật.
6. Không nhận các câu trong kế hoạch như “không còn lệch góc nhìn”, “không phụ thuộc khoảng cách”, “chịu nhiễu tốt hơn” hoặc “MotionBERT là ground truth” làm kết quả đã chứng minh.
7. Notebook kiểm ONNX trên tám mẫu khi chạy ô kiểm, nhưng tệp gửi không lưu output. Phép kiểm 33 mẫu ở trên là lượt kiểm mới, không thay thế tái lập train hoặc tính đúng của mọi đầu vào.
8. Kết quả LOSO trong `posture_config.json` được giữ dưới nhãn **kết quả lưu sẵn, chưa tái huấn luyện**. Không tạo số accuracy mới từ phép kiểm tương đương ONNX.
9. Kế hoạch mô tả app ban đầu, chưa bao quát khoảng cách, vòng đời camera/đăng nhập, outbox và chia sẻ media hiện nay. Không chép đè `posture_model` bằng code sinh từ notebook.

Tài liệu báo cáo hiện hành ở `../../CuonBaoCao` (đường dẫn thực: `G:/KhoaLuanTotNghiep/CuonBaoCao`). Các điểm thiếu bằng chứng tiếp tục được ghi trong `CAC_VAN_DE_CAN_XAC_NHAN.md`.

## Chuẩn bị RF trên Kaggle — 07/11/2026

[Hướng dẫn setup và notebook](alert_comparison/README.md): dùng NPZ train cũ hoặc dựng lại video bằng pipeline v3, train riêng RF và xuất model/metadata/dataset. Giữ nguyên Transformer đang triển khai. Có kiểm số mẫu/nhãn và hash tham chiếu; chưa chạy Kaggle hoặc xác nhận dữ liệu dựng lại giống từng byte với lần train cũ. Bộ này chuẩn bị model cho phép so sánh cảnh báo trên người mới về sau, chưa thực hiện phép so sánh đó.
