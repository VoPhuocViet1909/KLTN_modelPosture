# Chế độ tham gia nghiên cứu và thẻ hỏi phút 120

Cập nhật 24/11/2026. Quy tắc nghiệp vụ: `GIT_backend/DoAnTotNghiep_BE/docs/ke-hoach-hoan-thien-kltn.md` mục 3.3 và 5.B.

## Dữ liệu gửi khi bật

- Metrics 60 giây (như bình thường) và câu trả lời khảo sát. **Không gửi video hay ảnh.**
- Mặc định **tắt**. Bật trong Thiết lập → "Tham gia nghiên cứu", nhập mã dạng `P04`.
- Lưu theo (máy chủ, tài khoản) trong `out/research/research-<hash>.db`. Đổi tài khoản hoặc máy chủ thì cờ không theo sang.
- Cần đăng nhập. Chế độ "Dùng không đăng nhập" không có mục này.

## Thẻ hỏi

- Đầu mỗi phiên quyết định mời bằng xác suất `invite_prob` (mặc định 0,5). Tối đa 1 lần mời/người/ngày (giờ Việt Nam).
- Tới 7200 giây kể từ đầu phiên (đồng hồ thật, không trừ lúc rời ghế) hiện thẻ không chặn. Đang rời ghế thì chờ có người lại.
  Hạn 10 phút từ lúc thẻ hiện.
- Bản ghi (`survey` trong outbox) gửi `POST /api/v1/research/me/surveys/{sessionId}` theo hợp đồng mục 4.12. Mã nghiên cứu vẫn giữ cục bộ. Giây lẻ ở outbox được làm tròn xuống khi gửi.
  Chưa có thì bản ghi nằm yên trong outbox (không thành `dead`) và gửi bù khi backend có.
- Schema: `posture_model/schemas/survey.schema.json`.

## Giới hạn đã biết

- **Khung đứng:** camera trả mãi một khung cũ chỉ bị coi là mất tín hiệu sau khi khung trùng y hệt liên tục ≥ 2 giây,
  nên mỗi lần camera treo tối đa 2 giây đầu vẫn được tính vào `coveredSec`, `presenceSec` và `postureClassSeconds`.
  Việt chốt 24/11/2026: giữ nguyên, không bù ngược.
- Khung chỉ lệch 1 mức xám ở một pixel vẫn là khung sống (không bị coi là đứng).
- Cửa sổ dưới 5 giây không có cảnh báo không gửi; app bị kill đột ngột mất cửa sổ đang dở (ra dòng `unknown` khi xuất).
- Backend nhận giờ hiện thẻ thực tế. Nếu người dùng quay lại muộn, thời hạn vẫn là 10 phút từ lúc thẻ hiện. Bản ghi cũ thiếu cấu hình camera được gửi với `cameraSetup=unknown`.

## Tự thử bằng tay (không chờ 2 giờ)

Biến môi trường chỉ để thử (đặt trước khi chạy app):

| Biến | Ý nghĩa | Mặc định |
| --- | --- | --- |
| `KLTN_RESEARCH_ASK_SEC` | giây từ đầu phiên tới lúc hiện thẻ | 7200 |
| `KLTN_RESEARCH_INVITE_PROB` | xác suất mời, thắng giá trị lưu trong CSDL | 0,5 |
| `KLTN_RESEARCH_IGNORE_DAILY_LIMIT` | `1` = bỏ giới hạn 1 lần/ngày để thử lặp lại | tắt |

Ví dụ (PowerShell), mock server cổng 8080, thẻ hiện sau 60 giây:

```powershell
# cửa sổ 1
cd GIT_KLTN\api_handover
python mock_server.py --require-login          # tài khoản demo@kltn.local / 123456

# cửa sổ 2
cd GIT_KLTN\posture_model
$env:KLTN_RESEARCH_ASK_SEC = "60"
$env:KLTN_RESEARCH_INVITE_PROB = "1"
$env:KLTN_RESEARCH_IGNORE_DAILY_LIMIT = "1"
python app.py --side 1 --front 0               # hoặc --side-video hong.mp4 --front -1
```

Đăng nhập, mở Thiết lập, bật “Tham gia nghiên cứu”, nhập `P04` và lưu. Desktop bắt đầu phiên mới.
Biến môi trường ở trên rút ngắn thời gian để xem thẻ trên UI. API khảo sát chỉ chấp nhận các mốc hợp lệ
từ giây 7200. Dùng đồng hồ giả trong bài kiểm tự động hoặc tham gia phiên thật để kiểm cả gửi và đọc lại.

## Test tự động

```powershell
cd GIT_KLTN\posture_model
$env:PYTHONUTF8 = "1"; $env:QT_QPA_PLATFORM = "offscreen"
python tests\test_metrics_window.py     # B2: rời ghế, mất/đứng khung, tắt giữa phút, ranh giới phiên
python tests\test_research.py           # B1, B3, B4: cờ theo tài khoản, thẻ, hết hạn, kill/mở lại, mất mạng, trùng
```
