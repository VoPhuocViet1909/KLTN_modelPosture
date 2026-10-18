"""Opt-in live video v1. Contract/setup: api_handover/live-camera.md.

No video outbox: one latest frame, one encoder, bounded retry and token lifetime.
"""
import atexit
import collections
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request


class LivePublisher:
    def __init__(self, config, device_id, camera, rtsp_base, ffmpeg="ffmpeg", auth=None):
        if camera not in ("side", "front") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", device_id):
            raise ValueError("Invalid camera or device ID")
        base = urllib.parse.urlsplit(rtsp_base)
        if base.scheme != "rtsp" or not base.hostname or base.username or base.password or base.query or base.fragment or base.path not in ("", "/"):
            raise ValueError("Use an RTSP base without credentials, path or query")
        self.ffmpeg = shutil.which(ffmpeg)
        if not self.ffmpeg:
            raise ValueError("FFmpeg is required when live streaming is enabled")
        self.config, self.device_id, self.camera = config, device_id, camera
        self.auth = auth
        self.rtsp_base = rtsp_base.rstrip("/")
        self.frames = collections.deque(maxlen=1)
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.next_frame = 0
        self.state = "connecting"
        self.thread = threading.Thread(target=self._run, name="camera-publisher", daemon=True)

    def start(self):
        atexit.register(self.stop)
        self.thread.start()

    def submit(self, frame):
        now = time.monotonic()
        if frame is None or self.stopped.is_set() or now < self.next_frame:
            return
        import cv2  # Already used by the capture application; no additional Python dependency.
        self.next_frame = now + 1 / 15
        data = cv2.resize(frame, (640, 360)).tobytes()
        with self.condition:
            self.frames.append(data)
            self.condition.notify()

    def _grant(self):
        api, token = self.config()
        base = urllib.parse.urlsplit(api)
        if base.scheme not in ("http", "https") or not base.hostname or base.username or base.password or base.query or base.fragment:
            raise ValueError("Invalid API base")
        request = urllib.request.Request(api.rstrip("/") + "/api/v1/auth/media-token",
                data=json.dumps(dict(deviceId=self.device_id, camera=self.camera, action="publish")).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
        # Do not follow redirects carrying Authorization to another origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with (self.auth.open(request, timeout=5) if self.auth else
              urllib.request.build_opener(NoRedirect).open(request, timeout=5)) as response:
            grant = json.loads(response.read(16384))
        if not re.fullmatch(r"camera/[0-9a-f-]{36}/" + re.escape(self.device_id) + "/" + self.camera, grant["path"]):
            raise ValueError("Invalid granted path")
        if grant.get("action") != "publish" or not 20 <= grant["expiresIn"] <= 120:
            raise ValueError("Invalid media grant")
        return grant

    def _kill(self):
        with self.process_lock:
            if self.process is not None and self.process.poll() is None:
                self.process.kill()

    def _run(self):
        while not self.stopped.is_set():
            process, expiry = None, None
            renew_at = float("inf")
            try:
                self.state = "connecting"
                grant = self._grant()
                url = self.rtsp_base + "/" + grant["path"] + "?token=" + urllib.parse.quote(grant["token"], safe="")
                command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
                           "-pixel_format", "bgr24", "-video_size", "640x360", "-framerate", "15", "-i", "pipe:0",
                           "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                           "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-bf", "0", "-g", "30",
                           "-b:v", "600k", "-maxrate", "600k", "-bufsize", "600k", "-threads", "1",
                           "-f", "rtsp", "-rtsp_transport", "tcp", url]
                with self.process_lock:
                    if self.stopped.is_set():
                        return
                    process = self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, bufsize=0,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                # Also kills a blocked pipe/network write; the capture thread never waits on it.
                expiry = threading.Timer(grant["expiresIn"] - 15, process.kill)
                renew_at = time.monotonic() + grant["expiresIn"] - 15
                expiry.daemon = True
                expiry.start()
                with self.condition:
                    self.frames.clear()  # Never replay a frame left over from an outage.
                while not self.stopped.is_set() and process.poll() is None:
                    with self.condition:
                        self.condition.wait_for(lambda: self.frames or self.stopped.is_set(), timeout=1)
                        data = self.frames.pop() if self.frames else None
                    if data is not None:
                        remaining = memoryview(data)
                        while remaining:
                            written = process.stdin.write(remaining)
                            if not written:
                                raise BrokenPipeError()
                            remaining = remaining[written:]
                        self.state = "publishing"
            except (OSError, ValueError, KeyError, TypeError):
                # FFmpeg stderr/URLs and HTTP exceptions can contain credentials. Never print them.
                if not self.stopped.is_set() and time.monotonic() < renew_at:
                    print("Live camera unavailable; retrying in 5 seconds.")
            finally:
                if expiry:
                    expiry.cancel()
                if process:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    process.stdin.close()
                with self.process_lock:
                    self.process = None
            if time.monotonic() < renew_at:
                self.state = "retrying"
                self.stopped.wait(5)

    def stop(self, wait=True):
        self.stopped.set()
        self.state = "stopped"
        with self.condition:
            self.frames.clear()
            self.condition.notify_all()
        self._kill()
        if wait and self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=7)
        atexit.unregister(self.stop)
