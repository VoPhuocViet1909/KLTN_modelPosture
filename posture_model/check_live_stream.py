"""python posture_model/check_live_stream.py --ffmpeg PATH [--integration]

Integration requires API_EMAIL/API_PASSWORD env vars and running BE/media on localhost.
Only synthetic frames are sent. No credentials or FFmpeg stderr are printed.
"""
import argparse
import json
import os
import subprocess
import threading
import time
import urllib.request

import numpy as np
from live_stream import LivePublisher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--seconds", type=int, default=8, help="use 125 to check media-token renewal")
    args = parser.parse_args()
    token = ""
    base = "http://127.0.0.1:8080"

    def post(path, body):
        request = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        with urllib.request.urlopen(request, timeout=10) as r:
            return json.load(r)

    if args.integration:
        token = post("/api/v1/auth/login", dict(email=os.environ["API_EMAIL"], password=os.environ["API_PASSWORD"],
                                              deviceId="camera-check"))["accessToken"]
    stream = LivePublisher(lambda: (base, token), "camera-check", "side", "rtsp://127.0.0.1:8554", args.ffmpeg)
    frame = np.full((480, 640, 3), (30, 110, 210), dtype=np.uint8)
    for _ in range(1000):
        stream.next_frame = 0
        stream.submit(frame)
    assert len(stream.frames) == 1 and len(stream.frames[0]) == 640 * 360 * 3
    frame[:] = 0
    assert stream.frames[0][0] == 30, "queued frame must not share the capture buffer"
    print("PASS bounded queue and owned frame copy")
    if not args.integration:
        stream.stop()
        return

    end = threading.Event()

    def feed():
        while not end.wait(1 / 15):
            stream.submit(frame)

    stream.start()
    producer = threading.Thread(target=feed)
    producer.start()
    try:
        grant = post("/api/v1/auth/media-token", dict(deviceId="camera-check", camera="side", action="read"))
        url = "rtsp://127.0.0.1:8554/" + grant["path"]

        def read(media_token, path=url):
            return subprocess.run([args.ffmpeg, "-v", "error", "-rtsp_transport", "tcp", "-timeout", "5000000",
                    "-i", path + "?token=" + media_token, "-frames:v", "3", "-vf", "scale=80:45",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, timeout=12)

        time.sleep(3)
        result = read(grant["token"])
        assert result.returncode == 0 and len(result.stdout) == 80 * 45 * 3 * 3, (
                "real video decode failed: exit=" + str(result.returncode) + " bytes=" + str(len(result.stdout)))
        print("PASS edge OpenCV -> FFmpeg -> BE MediaMTX -> decoded frames")
        for name, bad_token, path in [("API token", token, url), ("anonymous", "", url),
                ("other device", grant["token"], url.replace("camera-check", "other-device")),
                ("other owner", grant["token"], "rtsp://127.0.0.1:8554/camera/00000000-0000-0000-0000-000000000000/camera-check/side"),
                ("wrong action", stream._grant()["token"], url)]:
            denied = read(bad_token, path)
            assert denied.returncode != 0 and (b"401 Unauthorized" in denied.stderr or b"403 Forbidden" in denied.stderr), name + " was not rejected by authentication"
            print("PASS rejected", name)
        if args.seconds > 8:
            time.sleep(args.seconds - 8)
            expired = read(grant["token"])
            assert expired.returncode != 0 and b"401 Unauthorized" in expired.stderr
            print("PASS expired grant rejected for new connections")
            grant = post("/api/v1/auth/media-token", dict(deviceId="camera-check", camera="side", action="read"))
            result = read(grant["token"])
            assert result.returncode == 0 and len(result.stdout) == 80 * 45 * 3 * 3
            print("PASS video still decodes after publisher token renewal")
    finally:
        end.set()
        producer.join(timeout=2)
        stream.stop()
        assert not stream.thread.is_alive(), "publisher did not stop"
        assert stream.process is None and not stream.frames
        print("PASS publisher shutdown and frame cleanup")


if __name__ == "__main__":
    main()
