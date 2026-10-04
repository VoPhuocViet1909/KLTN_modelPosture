"""Kiểm tra camera trước khi chạy realtime_posture.py
  python test_cam.py                                  # dò webcam số 0..9, in kết quả rồi cho xem từng cam
  python test_cam.py 1                                # xem riêng cam số 1
  python test_cam.py http://192.168.1.5:8080/video    # xem thử stream điện thoại (app IP Webcam)
Trong cửa sổ hình: nhấn phím bất kỳ để sang cam tiếp theo. Thoát ngay: Ctrl+C ở PowerShell."""
import os, sys, time
os.environ["OPENCV_LOG_LEVEL"] = "OFF"          # tắt cảnh báo của OpenCV cho dễ đọc
import cv2


def open_cam(s):
    """Webcam số: thử DirectShow, MSMF, mặc định. Link: mở thẳng. Trả (cap, tên backend, khung đầu)."""
    apis = [("stream", cv2.CAP_ANY)] if isinstance(s, str) else \
           [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("FFMPEG", cv2.CAP_FFMPEG), ("AUTO", cv2.CAP_ANY)]
    for name, api in apis:
        cap = cv2.VideoCapture(s, api)
        if cap.isOpened():
            for _ in range(20):                  # cam vừa bật thường trả vài khung rỗng
                ok, fr = cap.read()
                if ok and fr is not None:
                    return cap, name, fr
                time.sleep(0.1)
        cap.release()
    return None, None, None


srcs = [int(a) if a.isdigit() else a for a in sys.argv[1:]] or list(range(10))
found = []
print("Đang dò camera ...")
for s in srcs:
    cap, api, fr = open_cam(s)
    if cap is None:
        print(f"  Cam {s}: không mở được")
        continue
    dark = fr.mean() < 8
    print(f"  Cam {s}: OK {fr.shape[1]}x{fr.shape[0]} ({api})" + ("  <-- HÌNH ĐEN (cam ảo chưa nhận điện thoại?)" if dark else ""))
    found.append(s); cap.release()
if not found:
    print("Không thấy camera nào."); sys.exit()
print("\nXem từng cam: nhấn phím bất kỳ trong cửa sổ hình để sang cam tiếp theo.")
for s in found:
    cap, api, _ = open_cam(s)
    if cap is None:
        continue
    while True:
        ok, fr = cap.read()
        if ok:
            cv2.putText(fr, f"cam {s} ({api}) - nhan phim bat ky", (20, 50), 0, 1.2, (0, 0, 255), 3)
            cv2.imshow("test cam", fr)
        if cv2.waitKey(30) != -1:
            break
    cap.release()
cv2.destroyAllWindows()
