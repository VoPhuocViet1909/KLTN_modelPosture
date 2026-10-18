"""Kiểm realtime Desktop App -> backend -> Web Dashboard (trang Tổng quan, ô "Tư thế lúc này").

App thật (đăng nhập tài khoản demo, engine chạy video trắng + landmark giả: thẳng -> cúi -> thẳng) và một trình duyệt Edge
headless (CDP) mở web, đăng nhập CÙNG tài khoản, đo thời điểm chữ trạng thái trên trang đổi so với lúc app phát sự kiện.

Cần: backend chạy (Gateway :8080), web dev đang chạy (:5173), Edge, biến môi trường DEMO_PW (không in ra).
    python ui/web_realtime_check.py <thư mục kết quả>
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import engine as engine_mod
from engine import EngineOptions
from fake_pose import FakePoseDetector, make_blank_video, write_config
from ui.controller import AppController

BASE = os.environ.get("API_BASE", "http://localhost:8080")
WEB = os.environ.get("WEB_URL", "http://localhost:5173")
EMAIL = os.environ.get("DEMO_EMAIL", "demo@kltn.local")
EDGE = os.environ.get("BROWSER_BINARY", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
LABELS = ["Ngồi đúng", "Đang ngồi sai", "Vắng mặt", "Không kết nối", "Mở Desktop App"]
BAD_FROM, BAD_UNTIL = 6, 40                        # giây (thời gian video): cúi từ 6 s đến 40 s


class PacedFake(FakePoseDetector):
    schedule = [(BAD_FROM, 0), (BAD_UNTIL, 70), (1e9, 0)]

    def __call__(self, frame, ts):
        time.sleep(0.1)
        return super().__call__(frame, ts)


class Cdp:
    def __init__(self, port):
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        self.n = 0
        self.lock = threading.Lock()

    def call(self, method, **params):
        with self.lock:
            self.n += 1
            self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
            while True:
                msg = json.loads(self.ws.recv())
                if msg.get("id") == self.n:
                    return msg.get("result", {})

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def shot(self, path):
        data = self.call("Page.captureScreenshot", format="png").get("data")
        if data:
            open(path, "wb").write(base64.b64decode(data))


READ = ("(()=>{const s=document.querySelector('section');const t=s?s.innerText:'';"
        "const l=%s.find(x=>t.includes(x));return l||null})()" % json.dumps(LABELS, ensure_ascii=False))
FILL = """(()=>{const set=(id,v)=>{const el=document.getElementById(id);if(!el)return false;
const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);
el.dispatchEvent(new Event('input',{bubbles:true}));return true};
const ok=set('email',%s)&&set('password',%s);if(ok)document.querySelector('button[type=submit]').click();return ok})()"""


def main(out):
    os.makedirs(out, exist_ok=True)
    pw = os.environ["DEMO_PW"]
    port = 9333
    prof = tempfile.mkdtemp(prefix="edge-prof-")
    edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
                             "--window-size=1280,900", "--no-first-run", "--remote-allow-origins=*", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = {"web": WEB, "transitions": [], "engine": []}
    try:
        cdp = Cdp(port)
        cdp.call("Page.enable")
        cdp.call("Page.navigate", url=WEB + "/")
        time.sleep(3)
        for _ in range(20):
            if cdp.js(FILL % (json.dumps(EMAIL), json.dumps(pw))):
                break
            time.sleep(0.5)
        for _ in range(40):                         # chờ trang Tổng quan hiện ô "Tư thế lúc này"
            if cdp.js("document.body.innerText.includes('Tư thế lúc này')"):
                break
            time.sleep(0.5)
        result["web_logged_in"] = bool(cdp.js("document.body.innerText.includes('Tư thế lúc này')"))
        result["web_before_app"] = cdp.js(READ)
        cdp.shot(os.path.join(out, "web_1_truoc_khi_mo_app.png"))

        stop = threading.Event()
        last = [None]

        def watch():
            while not stop.is_set():
                try:
                    cur = cdp.js(READ)
                except Exception:
                    continue
                if cur != last[0]:
                    last[0] = cur
                    result["transitions"].append((time.time(), cur))
                time.sleep(0.03)
        threading.Thread(target=watch, daemon=True).start()

        # ------------------------------------------------ app thật
        engine_mod.PoseDetector = PacedFake
        work = os.path.join(out, "work")
        os.makedirs(work, exist_ok=True)
        video = os.path.join(work, "v.avi")
        make_blank_video(video, 75)
        ob = os.path.join(work, "outbox.db")
        opts = EngineOptions(side_video=video, front="-1", config=write_config(os.path.join(work, "cfg.json"),
                             api_base_url=BASE), events=os.path.join(work, "ev.jsonl"),
                             metrics_out=os.path.join(work, "m.jsonl"), outbox=ob)
        app = QApplication(sys.argv[:1])
        ctl = AppController(app, opts, store=None, base_url=BASE)
        ctl.default_outbox = ob
        ctl.start()
        t_app = {}

        def hook():
            if ctl.engine is not None and ctl.engine.elog is not None and "hooked" not in t_app:
                t_app["hooked"] = True

                def on_ev(ev):
                    if ev["eventType"] in ("ALERT_STARTED", "ALERT_RESOLVED", "SESSION_START", "SESSION_END",
                                           "USER_AWAY", "USER_BACK"):
                        result["engine"].append((time.time(), ev["eventType"], ev.get("alertType")))
                ctl.engine.elog.listeners.append(on_ev)
        poll = QTimer(interval=50)
        poll.timeout.connect(hook)
        poll.start()
        lg = ctl.window.login
        QTimer.singleShot(500, lambda: (lg.email.setText(EMAIL), lg.password.setText(pw), lg.btn_login.click()))
        shots = {"web_2_ngoi_dung": 11000, "web_3_ngoi_sai": 30000, "web_4_ngoi_lai": 58000}
        for name, ms in shots.items():
            QTimer.singleShot(ms, lambda n=name: (cdp.shot(os.path.join(out, n + ".png")),
                                                  ctl.window.grab().save(os.path.join(out, "app_" + n[4:] + ".png"))))
        QTimer.singleShot(68000, app.quit)
        app.exec()
        stop.set()
        time.sleep(0.2)
    finally:
        edge.terminate()

    # ------------------------------------------------ phân tích
    t0 = result["engine"][0][0] if result["engine"] else None
    rel = lambda t: None if t0 is None else round(t - t0, 2)
    trans = [(rel(t), v) for t, v in result["transitions"]]
    out_lines = {"web_logged_in": result.get("web_logged_in"), "web_truoc_app": result.get("web_before_app"),
                 "web_doi_trang_thai": trans, "app_phat_su_kien": [(rel(t), e, a) for t, e, a in result["engine"]]}
    lat = {}
    for t, e, a in result["engine"]:
        want = {"ALERT_STARTED": "Đang ngồi sai", "ALERT_RESOLVED": "Ngồi đúng"}.get(e)
        if want:
            seen = next((tt for tt, v in result["transitions"] if tt >= t - 0.05 and v == want), None)
            lat[e] = None if seen is None else round(seen - t, 2)
    out_lines["do_tre_giay"] = lat
    print(json.dumps(out_lines, ensure_ascii=False, indent=1))
    json.dump(out_lines, open(os.path.join(out, "web_realtime_result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0 if lat.get("ALERT_STARTED") is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()))
