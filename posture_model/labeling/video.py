"""Đọc video cho công cụ chấm tay: thời lượng và các khung của một đoạn."""
import cv2


class VideoError(ValueError):
    pass


def probe(path):
    """-> (fps, duration_sec). Ném VideoError nếu không mở được hoặc không biết thời lượng."""
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoError(f"Không mở được video: {path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    finally:
        cap.release()
    if fps <= 0 or frames <= 0:
        raise VideoError(f"Video không cho biết FPS hoặc số khung: {path}")
    return float(fps), frames / fps


def read_segment(path, t_start, t_end):
    """Các khung BGR của [t_start, t_end). Nạp cả đoạn vào RAM (2 giây ~ 60 khung). Trả (khung, fps)."""
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise VideoError(f"Không mở được video: {path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        first, last = int(round(t_start * fps)), int(round(t_end * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        frames = []
        for _ in range(last - first):
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        return frames, fps
    finally:
        cap.release()
