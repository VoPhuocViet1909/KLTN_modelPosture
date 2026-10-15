# Video trực tiếp v1 — bổ sung độc lập với telemetry v1.5

Cập nhật ngày 15/10/2026: **BE PR [#33](https://github.com/luongtan204/DoAnTotNghiep_BE/pull/33) đã merge main `ca32f7d`** sau Config PR #41/#42 và full reactor 315/315 (0 failure/error/skipped). Nguồn kiến trúc/hợp đồng/cách chạy/giới hạn: [docs/live-camera.md trên BE main](https://github.com/luongtan204/DoAnTotNghiep_BE/blob/main/docs/live-camera.md); danh mục API hiện hành là team-sync mục 4. Edge PR #4 đã merge `2874c29`, streaming tắt mặc định. OpenAPI v1.5 đóng băng để hồi quy, batch/config/status không đổi; video không đi qua Socket.IO hoặc outbox.

Nguồn hình là capture trong **ứng dụng `KLTN_modelPosture/realtime_app.py`**, chủ dự án đã xác nhận. Publisher chạy cùng ứng dụng edge; BE không mở camera riêng. Chạy edge và BE cùng máy qua loopback chỉ chứng minh tích hợp phần mềm, chưa chứng minh mạng hai thiết bị.

## Chạy edge

Cần BE có Auth media-token và MediaMTX 1.21.2, FFmpeg **9.0.2** có libx264, môi trường Python hiện có của app. Không thêm dependency Python. FFmpeg Windows essentials lấy từ Gyan (provider được FFmpeg giới thiệu), không dùng nightly; kiểm `ffmpeg -version`, release/checksum được ghi ở tài liệu BE. Binary ngoài Git; chưa đóng gói vào app.

```powershell
python -X utf8 posture_model/realtime_app.py --side 1 --front 0 --stream-camera side --ffmpeg <absolute-path-to-ffmpeg>
```

- Không có `--stream-camera` thì không gửi video. Chọn side/front; front phải mở được. Chỉ một camera mỗi process; lấy từ capture sẵn có, trước overlay, không âm thanh.
- Cấu hình cũ `api_base_url` là gốc Gateway, `api_token` là JWT của user sở hữu camera. Không commit token. Chế độ thủ công vẫn hot reload token; dùng `--login` để đăng nhập và refresh tự động như mô tả dưới đây.
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

Đã chạy toàn ứng dụng side/capture/inference/telemetry cùng LivePublisher 135 giây: browser decode 640×360 ở giây 25 và 121 qua chu kỳ media token, stop đạt; 5 event + 3 metric đều gửi (8 sent/0 pending/0 dead), Socket.IO observer nhận OFFLINE của đúng device sau kết thúc phiên. Kiểm bằng publisher ứng dụng đang chạy: ở BE đặt `CAMERA_DEVICE_ID` và tùy chọn `CAMERA_NAME=side|front` rồi chạy `node dev/verify-camera.mjs`; script không phát synthetic khi có device này.

Chưa kiểm front, hai máy/LAN/NAT/TLS/TURN, chậm/mất mạng dài, FPS/CPU/RAM edge/soak/multi-viewer, thu hồi cứng và xử lý status trong chính Python app. Config Socket.IO đã có với `--sync-config`; API refresh tự động đã có ở chế độ `--login`; media grant vẫn được cấp lại độc lập. Không suy ra nghiệm thu thiết bị từ xa từ kiểm loopback. Thay đổi frame size phải đổi cả command FFmpeg và bộ đệm đầu vào; đổi quyền/path/TTL phải đồng bộ Auth, MediaMTX, publisher, viewer, docs và test.

## Đăng nhập và refresh API (15/10/2026)

Thêm `--login` vào lệnh chạy; đặt `api_base_url` trong config, nhập email và mật khẩu tại prompt (mật khẩu ẩn). Login chạy trước khi mở capture. `userId` của event/metric lấy từ tài khoản đăng nhập; `api_token`/`user_id` trong config không thay thế danh tính phiên này. Không thêm dependency hoặc đổi phiên bản.

```powershell
python -X utf8 posture_model/realtime_app.py --login --side 1 --front 0 --stream-camera side --ffmpeg <path>
python -X utf8 posture_model/check_api_session.py
```

API URL phải HTTPS, hoặc HTTP loopback khi kiểm local; không có credentials/path/query. Login/refresh/Bearer không đi theo redirect. Đổi API URL khi hot reload yêu cầu đăng nhập lại; không chuyển token sang máy chủ khác. Mỗi tài khoản dùng `--outbox` riêng: batch có dữ liệu chờ của user khác hoặc userId trống bị giữ lại, không gửi dưới tài khoản mới. Không xóa SQLite để xử lý lỗi xác thực; đăng nhập đúng tài khoản để gửi bù.

Access/refresh token chỉ trong RAM; không lưu mật khẩu, không ghi token vào config/log/SQLite. Telemetry và publisher dùng chung khóa refresh: làm mới trước hạn (tối đa 30 giây), hoặc một lần khi REST trả 401; refresh token xoay vòng chỉ dùng một lần. Chỉ tự phát lại hai request hiện có: batch với cùng eventId/metricId chống trùng tại BE và cấp media grant không thay đổi trạng thái nghiệp vụ. Không có retry ghi chung cho API khác.

Nếu refresh bị từ chối, mất mạng hoặc mất response sau khi máy chủ đã xoay token, phiên dừng refresh và yêu cầu khởi động lại app với `--login`; outbox giữ pending. Đây là giới hạn có chủ đích để không dùng lại token một lần hoặc giữ mật khẩu nhằm login ngầm. Chưa lưu phiên bằng OS credential store, chưa có màn hình login hoặc nút logout/re-login trong app; session phía BE hết hạn theo chính sách Auth. Mất mạng khi gửi batch vẫn backoff/gửi bù như trước. Khi thoát, chờ Sender hoàn tất trước khi đóng SQLite; chỉ thử thêm một batch, dữ liệu còn lại ở đĩa. Check giữ request đang chạy đã xác nhận stop chờ worker; chưa đo thời gian thoát khi mạng chậm kéo dài.

Kiểm chứng: check stdlib đạt refresh đồng thời 24 lời gọi/12 thread chỉ một refresh, xoay token lần kế tiếp, 401 retry một lần, refresh bị thu hồi/mất response không replay, outbox pending và chặn đổi origin/redirect/đổi user; test_phase2 7/7, test_alerts 10/10, bounded queue check đạt. Toàn app `--login` side chạy 40 giây qua Gateway/BE thật; ép thời hạn nội bộ phiên về 0 để thực sự gọi refresh (không đổi TTL BE), browser decode 640×360 và Dừng đạt, app exit 0, outbox 2 sent/0 pending/0 dead. Bằng chứng local ngoài Git: `tools/camera-check/edge-login-vh4t94tj`. Chưa đợi hết 900 giây thực, chưa kiểm hai máy/LAN/front hoặc refresh với BE outage thật.

Nguồn chính thức kiểm HTTP 200 ngày 15/10/2026: Python 3.11 [urllib.request](https://docs.python.org/3.11/library/urllib.request.html), [threading](https://docs.python.org/3.11/library/threading.html), [getpass](https://docs.python.org/3.11/library/getpass.html). Dùng stdlib trong runtime hiện có, không thay version; hợp đồng Auth theo team-sync mục 4.1.

## Đồng bộ cấu hình máy chủ (15/10/2026)

Cài `python -m pip install -r posture_model/requirements.txt`, rồi thêm `--login --sync-config` vào lệnh chạy. Opt-in, không tự bật khi chỉ truyền hình. Worker lấy `GET /api/v1/config/me` lúc khởi động, sau mỗi reconnect và khi Socket.IO báo `config`; dùng WebSocket qua Gateway, JWT trong auth CONNECT, không trong URL. Không bật polling, logger hoặc redirect WebSocket. Sau khi server ngắt do JWT hết hạn, vòng reconnect lấy token mới từ phiên dùng chung; chưa đợi 900 giây thật để kiểm việc này.

Push chỉ đánh thức worker để GET bản hiện hành, tránh ghi đè snapshot mới bằng push cũ khi hai nguồn đến lệch nhau. Một snapshot mới nhất chờ trong RAM; camera áp dụng ở lượt kiểm config mỗi ~2 giây, phát `CONFIG_APPLIED` qua telemetry. Toàn bộ snapshot thay overlay trước đó; khóa bị bỏ quay về file local/mặc định model. Overlay ưu tiên hơn local, không ghi vào file và không lưu qua restart. Khi lỗi mạng, giữ cấu hình hợp lệ gần nhất và retry 5 giây; chưa có cache cấu hình máy chủ trên đĩa.

Validate schema, khóa lạ, số không hữu hạn và cặp ngưỡng trước khi áp dụng; từ chối `api_base_url`, `api_token`, `user_id` từ server. File local vẫn hot reload; khi phối hợp local/remote làm cặp ngưỡng sai, giữ bản hợp lệ trước đó. Edge không xử lý sự kiện `status` dành cho Dashboard. Không đổi hợp đồng BE; nguồn team-sync mục 4.4/4.7.

```powershell
python -X utf8 posture_model/check_config_sync.py
# Tài khoản test không thuộc org; credentials cấp qua environment, không đặt trong argv.
python -X utf8 posture_model/check_config_sync.py --integration
```

Check local đạt thay toàn bộ/reset/local reload/validation/không ghi file; integration Gateway thật đạt startup GET, nhận config Socket.IO, khôi phục cập nhật bị lỡ và GET sau reconnect, hoàn nguyên config user. Toàn app `--login --sync-config` side 40 giây: push `alert_sec=23` tạo `CONFIG_APPLIED`, video browser 640×360/stop đạt, exit 0, outbox 4 sent/0 pending/0 dead; config test đã hoàn nguyên. Bằng chứng local `tools/camera-check/edge-config-gldslqpl`. Auth check/phase2 7/7/alerts 10/10 đạt. Chưa kiểm front, hai máy/LAN, mất mạng dài, CPU/RAM/FPS/latency hoặc soak; không coi bài 40 giây là nghiệm thu tải.

Dependency được chọn theo research-tech-stack ngày 15/10/2026: `python-socketio[client]==5.17.0` stable phát hành 14/09/2026, MIT, Python >=3.8; Python 3.11 hiện tại đáp ứng cả bidict >=3.11. Thư viện chính thức hỗ trợ Socket.IO 3/4, Engine.IO 4; tránh tự viết giao thức. Nguồn maintainer HTTP 200: [ma trận tương thích](https://raw.githubusercontent.com/miguelgrinberg/python-socketio/main/docs/intro.rst), [client](https://raw.githubusercontent.com/miguelgrinberg/python-socketio/main/docs/client.rst), [release metadata](https://pypi.org/pypi/python-socketio/5.17.0/json). ReadTheDocs trả 403 trong lần kiểm nên đối chiếu mã nguồn tài liệu maintainer. Không thay dependency cũ của app hoặc BE; chỉ cài vào venv kiểm ngoài Git.

Các version được resolver cài mới trong venv; metadata maintainer PyPI đều HTTP 200 ngày 15/10, stable mới nhất lúc kiểm:

| Thành phần | Version kiểm | Giấy phép | Nguồn |
| --- | --- | --- | --- |
| python-socketio | 5.17.0 | MIT | [metadata](https://pypi.org/pypi/python-socketio/5.17.0/json) |
| python-engineio | 4.14.0 | MIT | [metadata](https://pypi.org/pypi/python-engineio/4.14.0/json) |
| websocket-client | 1.9.2 | Apache-2.0 | [metadata](https://pypi.org/pypi/websocket-client/1.9.2/json) |
| bidict | 0.24.1 | MPL-2.0 | [metadata](https://pypi.org/pypi/bidict/0.24.1/json) |
| requests | 2.34.2 | Apache-2.0 | [metadata](https://pypi.org/pypi/requests/2.34.2/json) |
| simple-websocket | 1.1.0 | MIT (classifier package) | [metadata](https://pypi.org/pypi/simple-websocket/1.1.0/json) |
| charset-normalizer | 3.5.2 | MIT | [metadata](https://pypi.org/pypi/charset-normalizer/3.5.2/json) |
| idna | 3.20 | BSD-3-Clause | [metadata](https://pypi.org/pypi/idna/3.20/json) |
| urllib3 | 2.8.0 | MIT | [metadata](https://pypi.org/pypi/urllib3/2.8.0/json) |
| wsproto | 1.3.2 | MIT | [metadata](https://pypi.org/pypi/wsproto/1.3.2/json) |
| h11 | 0.16.0 | MIT | [metadata](https://pypi.org/pypi/h11/0.16.0/json) |

Resolution/import và kiểm tích hợp đạt. `pip check` của venv dùng system-site-packages còn báo xung đột có sẵn: torch 2.14.0 cần setuptools >=77.0.3 nhưng đang 65.5.0; chưa sửa môi trường torch ngoài phạm vi, không tuyên bố toàn venv sạch. Manifest ghim dependency trực tiếp Socket.IO; chưa khóa toàn bộ dependency/transitive hoặc đóng gói app.

Kiểm gửi bù bổ sung: tiêm URLError tại HTTP opener của client (không dừng BE/mạng thật), hai event giữ nguyên ID/pending trong SQLite; phục hồi opener và gửi qua Gateway thật đạt 2 sent/0 pending/dead. Lượt shell thiếu `-X utf8` lỗi khi in tiếng Việt, chạy lại với UTF-8 đạt; không thay runtime/version.
