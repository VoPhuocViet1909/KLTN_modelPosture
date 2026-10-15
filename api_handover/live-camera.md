# Video trực tiếp v1 — bổ sung độc lập với telemetry v1.5

Quyết định ngày 15/10/2026: [tài liệu kiến trúc/hợp đồng/cách chạy/giới hạn tại BE nhánh triển khai](https://github.com/luongtan204/DoAnTotNghiep_BE/blob/feat/live-camera/docs/live-camera.md). **BE PR [#33](https://github.com/luongtan204/DoAnTotNghiep_BE/pull/33) đang mở**, chưa có camera trên BE main do kiểm thử Config còn lỗi chập chờn. Cần dùng BE nhánh đó để chạy luồng đã kiểm; sau khi merge, nguồn cập nhật là [docs/live-camera.md trên main](https://github.com/luongtan204/DoAnTotNghiep_BE/blob/main/docs/live-camera.md). Edge PR #4 đã merge `2874c29` nhưng streaming vẫn tắt mặc định. Hợp đồng OpenAPI v1.5 và batch/config/status không đổi; video không đi qua Socket.IO hoặc outbox.

## Chạy edge

Cần BE có Auth media-token và MediaMTX 1.21.2, FFmpeg **9.0.2** có libx264, môi trường Python hiện có của app. Không thêm dependency Python. FFmpeg Windows essentials lấy từ Gyan (provider được FFmpeg giới thiệu), không dùng nightly; kiểm `ffmpeg -version`, release/checksum được ghi ở tài liệu BE. Binary ngoài Git; chưa đóng gói vào app.

```powershell
python posture_model/realtime_app.py --side 1 --front 0 --stream-camera side --ffmpeg <absolute-path-to-ffmpeg>
```

- Không có `--stream-camera` thì không gửi video. Chọn side/front; front phải mở được. Chỉ một camera mỗi process; lấy từ capture sẵn có, trước overlay, không âm thanh.
- Cấu hình cũ `api_base_url` là gốc Gateway, `api_token` là JWT của user sở hữu camera. Không commit token. Khi token API hết hạn (mặc định 15 phút), cập nhật token trong cấu hình để hot reload; chưa có login/refresh tự động.
- `--stream-rtsp-base rtsp://127.0.0.1:8554` mặc định. Thiết bị khác máy cần BE cấu hình LAN/VPN, ICE/origin/firewall theo tài liệu; loopback không nhận thiết bị từ xa. Không mở plaintext local ra Internet.
- Mở `http://localhost:8080/camera.html`, nhập API token cùng user, deviceId in lúc bật streaming/metadata, camera đã chọn. Media server localhost mặc định `http://127.0.0.1:8889`.

## Hợp đồng

Publisher gọi `POST {api_base_url}/api/v1/auth/media-token`, Bearer API JWT, body `{"deviceId":"dev_example","camera":"side","action":"publish"}`. Response `{"token":"<media-JWT>","expiresIn":120,"path":"camera/<callerUUID>/dev_example/side","action":"publish"}`, no-store. Viewer dùng action read. Owner do Auth lấy từ caller, không từ user_id cấu hình; ORG_ADMIN/SYS_ADMIN cũng chỉ camera của chính mình. Device ID regex `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`. API lỗi chuẩn BE, media lỗi RTSP/WHEP riêng.

JWT media: RS256, audience posture-media, một exact path/action, TTL 120 giây, không role/orgId; không dùng cho REST/Socket.IO. FFmpeg publish tới `{rtsp-base}/{grant.path}?token={media-JWT}`. Không đặt API JWT vào URL/argv. Media JWT ngắn hạn vẫn có trong argv FFmpeg: người có quyền inspect process đọc được; không log/debug argv hay FFmpeg stderr.

`live_stream.py`: 640×360, tối đa 15 FPS, H.264 baseline/yuv420p, no B-frame, 600 kbit/s mục tiêu, GOP 30, ultrafast/zerolatency, một encoder thread. `deque(maxlen=1)` giữ frame mới nhất, bỏ frame cũ, không gửi bù video; submit chỉ resize/copy, mạng/pipe ở worker. Một frame queue 691.200 byte, còn frame đang ghi và buffers encoder/process, không phải tổng RAM. HTTP timeout 5 giây, lỗi retry 5 giây; encoder bị kill trước hạn token để cả pipe kẹt cũng hữu hạn. Stop clear queue/kill/join; Python process exit cleanup qua atexit.

**Thu hồi chưa cứng:** MediaMTX kiểm JWT khi mở kết nối; chưa tự kick kết nối đang mở khi hết hạn hoặc khóa user. Client chuẩn đóng/cấp lại khoảng 105 giây, có thể gián đoạn; client tùy ý có thể giữ kết nối cũ. Không coi TTL là thu hồi tức thời. Không có recording/chia sẻ/bật camera từ xa.

## Kiểm chứng và phần thiếu

```powershell
python posture_model/check_live_stream.py --ffmpeg <path>
python posture_model/check_live_stream.py --ffmpeg <path> --integration --seconds 125
```

Integration đọc `API_EMAIL/API_PASSWORD` từ environment và BE/media localhost; chỉ gửi synthetic frames. Kiểm queue một frame/copy, publisher edge thật → MediaMTX → giải mã frame, token API/anonymous/sai device/sai action bị từ chối, stop không còn thread/process. `--seconds 125` kiểm đọc lại sau chu kỳ cấp lại token. Tại BE, `node dev/verify-camera.mjs` kiểm trình duyệt thật qua WHEP/ICE/H.264 và nút Dừng. Kết quả cuối và full reactor ghi trong tài liệu/PR/skill tiến độ BE.

Chưa kiểm webcam vật lý/toàn bộ inference cùng telemetry/Socket.IO, LAN/NAT/TLS/TURN, chậm/mất mạng dài, FPS/CPU/RAM edge/soak/multi-viewer, thu hồi cứng và refresh API tự động. Không suy ra app camera đã kiểm hoàn chỉnh từ synthetic publisher. Thay đổi frame size phải đổi cả command FFmpeg và bộ đệm đầu vào; đổi quyền/path/TTL phải đồng bộ Auth, MediaMTX, publisher, viewer, docs và test.
