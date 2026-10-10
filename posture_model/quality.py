"""
Lọc giá trị phi lý trước khi cảnh báo, gộp metrics và gửi lên server.

Ngưỡng lấy từ dữ liệu (frames_labeled.csv 58.292 khung, out/log.csv 8.053 mẫu webcam 04/10):
- Góc cổ / thân / cúi đầu sau hiệu chỉnh: 99,9% mẫu nằm trong khoảng ±90°. Ngoài khoảng này
  là MediaPipe bắt sai điểm khớp (ví dụ neck 188°, headPitch −152° trong log 04/10).
- Khoảng cách mắt – màn hình: 99% mẫu dưới 140 cm; 20–150 cm khớp khoảng hiệu chỉnh trong
  config.schema.json. Ngoài khoảng này là đo sai (ví dụ 1055 cm).
- Cửa sổ metrics phủ dưới 5 giây và không có cảnh báo thì không gửi (vài mẫu, số liệu nhiễu).

Mẫu bị loại được coi như "không thấy người" ở khung đó, không bị kẹp về biên.
"""
import math

ANGLE_LIMIT_DEG = 90.0
ANGLE_KEYS = ("neck", "trunk", "head_pitch")
DIST_MIN_CM, DIST_MAX_CM = 20.0, 150.0
MIN_WINDOW_SEC = 5.0


def _finite(x):
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def angle_ok(x):
    """Một góc đã hiệu chỉnh (độ). NaN / None -> False."""
    return _finite(x) and abs(x) <= ANGLE_LIMIT_DEG


def angles_ok(ang):
    """dict {neck, trunk, head_pitch}: False khi có góc VƯỢT ±90°. Góc thiếu (NaN) không tính là sai -
    khung thiếu góc vẫn xử lý như trước (mô hình nhận 0)."""
    vals = [ang.get(k) for k in ANGLE_KEYS]
    return all(abs(float(v)) <= ANGLE_LIMIT_DEG for v in vals if v is not None and math.isfinite(float(v)))


def dist_ok(cm):
    return _finite(cm) and DIST_MIN_CM <= cm <= DIST_MAX_CM
