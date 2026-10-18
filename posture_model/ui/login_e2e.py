"""Kiểm luồng đăng nhập với BACKEND THẬT + Windows Credential Manager thật (video trắng + landmark giả cấp dữ liệu).
Mật khẩu lấy từ biến môi trường DEMO_PW (không in ra). Chạy từng pha, mỗi pha là một tiến trình riêng:

    python ui/login_e2e.py login  <thư mục>   # sai mật khẩu -> đúng, ghi nhớ, chạy ~30 s, thoát KHÔNG đăng xuất
    python ui/login_e2e.py resume <thư mục>   # mở lại: tự vào, rồi đăng xuất bằng menu khay -> keyring sạch
    python ui/login_e2e.py lost   <thư mục>   # đăng nhập rồi phá phiên: phải về màn đăng nhập kèm thông báo
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

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
EMAIL = os.environ.get("DEMO_EMAIL", "demo@kltn.local")


class PacedFake(FakePoseDetector):
    schedule = [(6, 0), (16, 70), (1e9, 0)]       # thẳng -> cúi giây 6-16 -> thẳng lại

    def __call__(self, frame, ts):
        time.sleep(0.1)
        return super().__call__(frame, ts)


def main(phase, out):
    os.makedirs(out, exist_ok=True)
    engine_mod.PoseDetector = PacedFake
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    video = os.path.join(work, "v.avi")
    if not os.path.exists(video):
        make_blank_video(video, 60)
    default_ob = os.path.join(work, "outbox.db")
    opts = EngineOptions(side_video=video, front="-1", config=write_config(os.path.join(work, "cfg.json"),
                         api_base_url=BASE), events=os.path.join(work, "ev.jsonl"),
                         metrics_out=os.path.join(work, "m.jsonl"), outbox=default_ob)
    app = QApplication(sys.argv[:1])
    ctl = AppController(app, opts, base_url=BASE)
    ctl.default_outbox = default_ob
    log = {"phase": phase, "events": []}
    shot = lambda name: ctl.window.grab().save(os.path.join(out, f"{phase}_{name}.png"))
    note = lambda k, v: (log.update({k: v}), print(f"[{phase}] {k}: {v}"))
    lg = ctl.window.login

    def fill(pw):
        lg.email.setText(EMAIL)
        lg.password.setText(pw)
        lg.btn_login.click()

    def at(ms, fn):
        QTimer.singleShot(ms, fn)

    if phase == "login":
        note("tray_mode_dau", ctl.tray.mode)
        ctl.start()
        at(800, lambda: shot("1_man_dang_nhap"))
        at(1200, lambda: fill("mat-khau-sai"))
        at(3500, lambda: (note("loi_sai_mat_khau", lg.error.text()), shot("2_sai_mat_khau")))
        at(4000, lambda: fill(os.environ["DEMO_PW"]))
        at(9000, lambda: (note("mode", ctl.mode), note("tai_khoan", ctl.window.account.text()),
                          note("noi_dung_ket_noi", ctl.window.conn.text.text()),
                          note("keyring_co_phien", bool(ctl.store.load())), shot("3_dang_nhap_xong")))
        at(17000, lambda: shot("4_ngoi_sai_dang_gui"))
        at(26000, lambda: (note("ket_noi_cuoi", ctl.window.conn.text.text()),
                           note("user_id", ctl.auth.user_id if ctl.auth else None)))
        at(28000, app.quit)
    elif phase == "resume":
        t0 = time.time()
        ctl.start()
        poll = QTimer(interval=100)

        def check():
            if ctl.mode == "session":
                poll.stop()
                note("tu_vao_sau_s", round(time.time() - t0, 1))
                note("tai_khoan", ctl.window.account.text())
                note("keyring_truoc_dang_xuat", ctl.store.load()["refreshToken"][:6] + "…")
                log["old_refresh"] = ctl.store.load()["refreshToken"]
                at(6000, lambda: (shot("1_tu_vao"), ctl.logout()))
        poll.timeout.connect(check)
        poll.start()

        def fin():
            note("mode_sau_dang_xuat", ctl.mode)
            note("trang_dang_nhap", ctl.window.on_login_page())
            note("thong_bao", lg.info.text())
            note("keyring_sau_dang_xuat", ctl.store.load())
            note("o_mat_khau_trong", lg.password.text() == "")
            shot("2_sau_dang_xuat")
            # token cũ phải bị thu hồi trên máy chủ
            import urllib.request, urllib.error
            req = urllib.request.Request(BASE + "/api/v1/auth/refresh", data=json.dumps(
                {"refreshToken": log["old_refresh"]}).encode(), headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=5)
                note("token_cu_sau_dang_xuat", "VẪN DÙNG ĐƯỢC (lỗi)")
            except urllib.error.HTTPError as e:
                note("token_cu_sau_dang_xuat", f"bị từ chối HTTP {e.code}")
            app.quit()
        ctl.tray.logoutRequested.connect(lambda: QTimer.singleShot(0, lambda: None))
        at(20000, fin)
    elif phase == "lost":
        ctl.start()
        at(500, lambda: fill(os.environ["DEMO_PW"]))
        at(8000, lambda: (note("mode_truoc", ctl.mode), ctl.auth.__dict__.update(_refresh="bogus", _expires=0)))
        at(16000, lambda: (note("mode_sau", ctl.mode), note("trang_dang_nhap", ctl.window.on_login_page()),
                           note("thong_bao", lg.error.text()), note("keyring", ctl.store.load()), shot("1_het_phien")))
        at(17000, app.quit)
    app.exec()
    if phase == "login":
        for f in os.listdir(work):
            if f.startswith("outbox-") and f.endswith(".db"):
                from outbox import Outbox
                ob = Outbox(os.path.join(work, f))
                note("outbox_" + f[7:15], ob.stats())
                ob.close()
    print(json.dumps({k: v for k, v in log.items() if k != "old_refresh"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp()))
