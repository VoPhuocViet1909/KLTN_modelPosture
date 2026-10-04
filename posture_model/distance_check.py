"""
Đo sai số khoảng cách mắt – màn hình (dùng cho chương Đánh giá).

  python distance_check.py                      # cam laptop = webcam 0, tiêu cự ước theo HFOV 63°
  python distance_check.py --cam 0 --hfov 70
  python distance_check.py --focal 620          # nếu đã biết tiêu cự (px) từ lần hiệu chỉnh trước

Cách làm: dùng thước đo khoảng cách từ mắt tới mặt màn hình (camera), ngồi đúng ở mỗi mốc rồi nhấn phím:
  4 = 40 cm, 5 = 50 cm, 6 = 60 cm, 7 = 70 cm, 8 = 80 cm   (mỗi lần nhấn lấy trung vị 3 giây gần nhất)
  f = dùng mốc vừa đo để tính lại tiêu cự (hiệu chỉnh 1 điểm) và in ra
  q = thoát, ghi kết quả ra distance_check.csv (thật, đo, sai số cm, sai số %)
"""
import argparse
import collections
import csv
import os
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
import cv2
import numpy as np

from distance import EyeDistance, IRIS_MM, IPD_MM
from realtime_posture import PoseDetector

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="0")
    ap.add_argument("--hfov", type=float, default=63.0)
    ap.add_argument("--focal", type=float, default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "distance_check.csv"))
    a = ap.parse_args()

    cam = int(a.cam) if a.cam.isdigit() else a.cam
    cap = cv2.VideoCapture(cam, cv2.CAP_DSHOW) if isinstance(cam, int) and os.name == "nt" else cv2.VideoCapture(cam)
    if not cap.isOpened():
        raise SystemExit("Không mở được camera")
    ed = EyeDistance(os.path.join(HERE, "face_landmarker.task"), hfov_deg=a.hfov)
    ed.focal = a.focal
    pose = PoseDetector(os.path.join(HERE, "pose_landmarker_full.task"))
    hist = collections.deque()          # (t, px, kind)
    rows, t0 = [], time.time()

    while True:
        ok, fr = cap.read()
        if not ok:
            time.sleep(0.03)
            continue
        now = time.time() - t0
        ts = int(now * 1000)
        L, _ = pose(fr, ts) if ed.det is None else (None, None)
        px, kind = ed.measure(fr, ts, L)
        if kind:
            hist.append((now, px, kind))
        while hist and now - hist[0][0] > 3:
            hist.popleft()
        w = fr.shape[1]
        cm_now = ed.to_cm(px, kind, w)
        cv2.rectangle(fr, (0, 0), (w, 70), (30, 30, 30), -1)
        txt = f"{cm_now:5.1f} cm ({kind})" if np.isfinite(cm_now) else "khong thay mat"
        cv2.putText(fr, txt, (15, 45), 0, 1.1, (0, 255, 255), 3)
        f_used = ed.focal or ed.default_focal(w)
        cv2.putText(fr, f"f={f_used:.0f}px  4..8 = moc 40..80cm, f = hieu chinh, q = thoat", (15, fr.shape[0] - 15),
                    0, 0.55, (255, 255, 255), 2)
        cv2.imshow("Kiem tra khoang cach", fr)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if ord("4") <= k <= ord("8") and hist:
            true_cm = (k - ord("0")) * 10
            kinds = [h[2] for h in hist]
            kd = max(set(kinds), key=kinds.count)
            med_px = float(np.median([h[1] for h in hist if h[2] == kd]))
            meas = ed.to_cm(med_px, kd, w)
            rows.append(dict(true_cm=true_cm, measured_cm=round(meas, 1), err_cm=round(meas - true_cm, 1),
                             err_pct=round(100 * (meas - true_cm) / true_cm, 1), method=kd,
                             size_px=round(med_px, 2), focal_px=round(f_used, 1)))
            print(rows[-1])
        if k == ord("f") and rows:
            r = rows[-1]
            ed.focal = r["true_cm"] * 10 * r["size_px"] / (IRIS_MM if r["method"] == "iris" else IPD_MM)
            print(f"Tiêu cự mới: {ed.focal:.1f} px (dùng --focal {ed.focal:.0f} hoặc calib_distance_cm trong app_config.json)")

    cap.release()
    cv2.destroyAllWindows()
    if rows:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        errs = np.array([abs(r["err_cm"]) for r in rows])
        print(f"Đã ghi {a.out}. MAE = {errs.mean():.1f} cm, sai số lớn nhất = {errs.max():.1f} cm")


if __name__ == "__main__":
    main()
