"""Giao diện công cụ quay (PySide6): 2 hình camera có khung xương, hiệu lệnh chữ lớn, đồng hồ, kiểm tư thế trực tiếp.
Dùng theme + font Be Vietnam Pro của app (ui/theme.py). Mọi logic nằm ở recording/session.py; file này chỉ vẽ và nhận phím."""
import math
import threading

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QVBoxLayout, QWidget)

from posture_features import IDX
from recording.script import (CHUA_DU, DAT, KHONG_THAY, STATUS_TEXT, THEO_HIEU_LENH, describe_check)
from recording.session import AWAIT_CM, COUNTDOWN, IDLE, RECORDING
from ui.tokens import color, status_color

STATUS_COLOR = {DAT: status_color("GOOD"), CHUA_DU: status_color("AWAY"), KHONG_THAY: status_color("BAD"),
                THEO_HIEU_LENH: color("muted-foreground")}
MSG_COLOR = {"info": color("foreground"), "ok": status_color("GOOD"), "warn": "#9a6700", "bad": status_color("BAD")}
KEYS_HINT = "Space bắt đầu   R quay lại clip vừa rồi   N clip kế   B clip trước   C quay lại A1   Esc hủy clip   Q thoát"


def make_beeper(app=None):
    """Bíp không chặn giao diện: winsound trên Windows, nếu không có thì tiếng bíp của Qt."""
    tones = {"start": (1320, 450), "mark": (880, 300), "end": (523, 600)}

    def beep(kind):
        hz, ms = tones.get(kind, (880, 250))
        try:
            import winsound
            threading.Thread(target=winsound.Beep, args=(hz, ms), daemon=True).start()
        except Exception:                                                            # noqa: BLE001
            QApplication.beep()
    return beep


def ask_resume(parent, text):
    """Hộp hỏi 'tiếp từ clip nào' khi mở lại buổi đã quay dở. True = tiếp, False = bắt đầu lại từ đầu."""
    box = QMessageBox(QMessageBox.Question, "Buổi quay dở", text, QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("Tiếp tục")
    box.button(QMessageBox.No).setText("Từ đầu")
    return box.exec() == QMessageBox.Yes


class CmDialog(QDialog):
    """E7: nhập số cm đo bằng thước tại từng mức 70 / 60 / 50 / 40."""

    def __init__(self, parent=None, labels=("70 cm", "60 cm", "50 cm", "40 cm")):
        super().__init__(parent)
        self.setWindowTitle("E7 – số cm đo bằng thước")
        lay = QVBoxLayout(self)
        note = QLabel("Nhập khoảng cách thật (cm) đo bằng thước dây từ mặt màn hình đến đuôi mắt ở từng mức. Có thể bỏ trống.")
        note.setWordWrap(True)
        lay.addWidget(note)
        form = QFormLayout()
        self.edits = []
        for lb in labels:
            e = QLineEdit()
            e.setPlaceholderText(lb.split()[0])
            self.edits.append(e)
            form.addRow(f"Mức {lb}", e)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Lưu")
        bb.button(QDialogButtonBox.Cancel).setText("Bỏ qua")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        out = []
        for e in self.edits:
            t = e.text().strip().replace(",", ".")
            try:
                out.append(float(t))
            except ValueError:
                out.append(t)                      # bỏ trống hoặc chữ: giữ nguyên để người dùng thấy
        return out if any(str(v) != "" for v in out) else None


def ask_cm(parent):
    d = CmDialog(parent)
    return d.values() if d.exec() == QDialog.Accepted else None


def _qimage(bgr):
    h, w = bgr.shape[:2]
    return QImage(np.ascontiguousarray(bgr).data, w, h, 3 * w, QImage.Format_BGR888).copy()


def render_camera(frame, L, pairs, ids, target_w):
    """Thu nhỏ khung (BGR) về target_w rộng rồi vẽ khung xương (landmark pixel ảnh gốc) lên."""
    h, w = frame.shape[:2]
    s = min(1.0, target_w / w)
    small = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1.0 else frame
    img = _qimage(small)
    if L is not None:
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#ffffff"), 3, Qt.SolidLine, Qt.RoundCap))
        for a, b in pairs:
            if min(L[a, 2], L[b, 2]) > 0.3:
                p.drawLine(int(L[a, 0] * s), int(L[a, 1] * s), int(L[b, 0] * s), int(L[b, 1] * s))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(QColor(color("chart-1")))
        for i in ids:
            if L[i, 2] > 0.3:
                p.drawEllipse(int(L[i, 0] * s) - 6, int(L[i, 1] * s) - 6, 12, 12)
        p.end()
    return img


class CameraBox(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        self.img = QLabel("Chưa có hình")
        self.img.setObjectName("preview")
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setMinimumSize(320, 180)
        lay.addWidget(self.title)
        lay.addWidget(self.img, 1)
        self._src = None

    def show_image(self, qimg):
        self._src = qimg
        self._fit()

    def _fit(self):
        if self._src is not None:
            self.img.setPixmap(QPixmap.fromImage(self._src).scaled(self.img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


def _label(text="", size=16, weight=400, col=None, wrap=False, align=None):
    lb = QLabel(text)
    lb.setStyleSheet(f"font-size:{size}px; font-weight:{weight};" + (f"color:{col};" if col else ""))
    lb.setWordWrap(wrap)
    if align is not None:
        lb.setAlignment(align)
    return lb


class RecorderWindow(QWidget):
    def __init__(self, session, ask_cm_fn=ask_cm, refresh_ms=33):
        super().__init__()
        self.s = session
        self.ask_cm_fn = ask_cm_fn
        self._asking = False
        self._tick_n = 0
        self.setObjectName("root")
        self.setWindowTitle(f"Quay dữ liệu {session.person} {session.session}")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 12)
        root.setSpacing(8)

        self.head = _label("", 22, 600, color("muted-foreground"))
        self.cue = _label("", 40, 700, wrap=True)
        self.goal = _label("", 24, 500, color("primary"), wrap=True)
        root.addWidget(self.head)
        root.addWidget(self.cue)
        root.addWidget(self.goal)

        cams = QHBoxLayout()
        self.box_side, self.box_front = CameraBox("Camera hông"), CameraBox("Camera laptop")
        cams.addWidget(self.box_side, 1)
        if "front" in session.sources:
            cams.addWidget(self.box_front, 1)
        else:
            self.box_front.hide()
        self.summary = _label("", 15, 400, wrap=True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary.hide()
        cams.addWidget(self.summary, 1)
        root.addLayout(cams, 1)

        mid = QHBoxLayout()
        self.banner = _label("", 72, 700, color("primary"), align=Qt.AlignCenter)
        self.banner.setMinimumHeight(96)
        self.badge = _label("", 30, 700, "#ffffff", align=Qt.AlignCenter)
        self.badge.setMinimumWidth(560)
        self.badge.setMinimumHeight(64)
        mid.addWidget(self.banner, 1)
        mid.addWidget(self.badge)
        root.addLayout(mid)

        clock = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(22)
        self.bar.setStyleSheet(f"QProgressBar{{background:{color('muted')};border:none;border-radius:11px;}}"
                               f"QProgressBar::chunk{{background:{color('primary')};border-radius:11px;}}")
        self.secs = _label("", 34, 700, align=Qt.AlignRight | Qt.AlignVCenter)
        self.secs.setMinimumWidth(180)
        clock.addWidget(self.bar, 1)
        clock.addWidget(self.secs)
        root.addLayout(clock)

        self.numbers = _label("", 22, 500)
        self.calib = _label("", 18, 500, color("muted-foreground"))
        self.message = _label("", 22, 600, wrap=True)
        self.disk = _label("", 16, 500, color("muted-foreground"), wrap=True)
        self.compress = _label("", 16, 500, color("muted-foreground"), wrap=True)
        self.warn = _label("", 22, 700, "#ffffff", wrap=True)
        self.warn.setStyleSheet(f"font-size:22px;font-weight:700;color:#ffffff;background:{status_color('BAD')};padding:8px 12px;border-radius:6px;")
        self.warn.hide()
        self.hint = _label(KEYS_HINT, 14, 400, color("muted-foreground"))
        for w in (self.numbers, self.calib, self.message, self.disk, self.compress, self.warn, self.hint):
            root.addWidget(w)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(refresh_ms)

    # ------------------------------------------------------------------ phím
    def keyPressEvent(self, e):
        k, s = e.key(), self.s
        if k == Qt.Key_Space:
            s.press_start()
        elif k == Qt.Key_R:
            s.press_redo()
        elif k == Qt.Key_N:
            s.press_next()
        elif k == Qt.Key_B:
            s.press_prev()
        elif k == Qt.Key_C:
            s.press_calibrate()
        elif k == Qt.Key_Escape:
            s.press_cancel()
        elif k == Qt.Key_Q:
            self.close()
            return
        else:
            return super().keyPressEvent(e)
        self.refresh()

    def closeEvent(self, e):
        self.timer.stop()
        self.s.close()
        super().closeEvent(e)

    # ------------------------------------------------------------------ vẽ
    def on_tick(self):
        self.s.tick()
        if self.s.state == AWAIT_CM and not self._asking:
            self._asking = True
            self.s.submit_cm(self.ask_cm_fn(self))
            self._asking = False
        self._tick_n += 1
        self.refresh(cameras=self._tick_n % 2 == 0)

    @staticmethod
    def _fmt(v, unit="°", nd=0, mul=1.0):
        if v is None or not math.isfinite(v):
            return "–"
        return f"{v * mul:+.{nd}f}{unit}" if unit == "°" else f"{v * mul:.{nd}f}{unit}"

    def refresh(self, cameras=True):
        s = self.s
        clip = s.current
        if clip is None:
            return
        self._refresh_disk()
        self._summary_mode(s.finished)
        if s.finished:
            self._show_summary()
            return
        live = s.live
        t = s.elapsed() if s.state == RECORDING else None
        n, total = s.position
        self.head.setText(f"{clip.id} · {clip.clip}   ({n}/{total})   ·   cam chính: {clip.cam_text}   ·   {clip.duration} s")
        self.cue.setText(clip.cue)
        self.goal.setText(self._goal_text(clip, t))

        # đồng hồ / chữ nổi
        if s.state == COUNTDOWN:
            left = s.count_left()
            self.banner.setText(str(max(1, math.ceil(left))))
            self.bar.setValue(0)
            self.secs.setText(f"{clip.duration} s")
        elif s.state == RECORDING:
            t = min(t, clip.duration)
            self.banner.setText(clip.banner(t))
            self.bar.setValue(int(1000 * t / clip.duration))
            nxt = clip.next_phase(t)
            extra = f"\nKế tiếp: {nxt.label} sau {math.ceil(nxt.start - t)} s" if nxt and clip.id in ("C1", "E7") else ""
            self.secs.setText(f"còn {math.ceil(clip.duration - t)} s" + extra)
        else:
            self.banner.setText("Bấm Space để bắt đầu" if s.state == IDLE else "")
            self.bar.setValue(0)
            self.secs.setText(f"{clip.duration} s")

        # trạng thái đạt / chưa đủ
        st = live["status"]
        pct = s.counter.pct if s.counter is not None else None
        txt = STATUS_TEXT[st] + ("" if pct is None or st == THEO_HIEU_LENH else f" · đã đạt {pct:.0f}% thời gian")
        if s.state == COUNTDOWN:
            st, txt = THEO_HIEU_LENH, "Chuẩn bị"
        if clip.is_calibration:
            st, txt = THEO_HIEU_LENH, "Lấy baseline"
        self.badge.setText(txt)
        self.badge.setStyleSheet(f"font-size:26px;font-weight:700;color:#ffffff;border-radius:10px;background:{STATUS_COLOR[st]};")

        # số trực tiếp
        d = live["dist"]
        self.numbers.setText(
            f"Cổ {self._fmt(live['neck'])}   Thân {self._fmt(live['trunk'])}   Lệch vai {self._fmt(live['tilt'], nd=1)}   "
            f"Nhún vai {self._fmt(live['raise_'], '%', 0, 100)}   Cách màn hình {'–' if d is None else f'{d:.0f} cm'}"
            + ("" if s.baseline else "     (chưa có baseline: quay A1)"))
        self.calib.setText("   ".join(("✓ " if ok else "✗ " if ok is False else "… ") + lb for lb, ok in s.calib_view)
                           if clip.is_calibration else "")
        self.message.setText(s.message)
        self.message.setStyleSheet(f"font-size:22px;font-weight:600;color:{MSG_COLOR[s.message_level]};")
        self.warn.setText("⚠ " + "   ".join(s.warnings))
        self.warn.setVisible(bool(s.warnings))
        if cameras:
            self._show_cameras()

    def _refresh_disk(self):
        """Dòng dung lượng ổ ở màn hình sẵn sàng (không hiện lúc đếm ngược / đang quay); đỏ khi dưới 5 GB."""
        s = self.s
        d = s.refresh_disk()
        self.disk.setText(d["text"])
        col = status_color("BAD") if d["low"] else color("muted-foreground")
        self.disk.setStyleSheet(f"font-size:16px;font-weight:{700 if d['low'] else 500};color:{col};")
        self.disk.setVisible(s.state in (IDLE, AWAIT_CM))
        level, txt = s.compress_status()                               # luôn hiện: đang nén / đã nén / nén lỗi / không có ffmpeg
        self.compress.setText("Nén video: " + txt if not txt.startswith(("Chưa nén", "Nén nền")) else txt)
        ccol = {"ok": status_color("GOOD"), "info": color("muted-foreground"), "warn": "#9a6700", "bad": status_color("BAD")}[level]
        self.compress.setStyleSheet(f"font-size:16px;font-weight:{700 if level == 'bad' else 500};color:{ccol};")

    def _summary_mode(self, on):
        for w in (self.box_side, self.box_front, self.banner, self.badge, self.bar, self.secs, self.numbers, self.calib):
            if on:
                w.hide()
            elif w is not self.box_front or "front" in self.s.sources:
                w.show()
        self.summary.setVisible(on)

    def _show_summary(self):
        s = self.s
        self.head.setText(f"ĐÃ QUAY XONG BUỔI {s.person} {s.session}")
        self.cue.setText("Cảm ơn người tham gia!")
        self.goal.setText("Space không làm gì  ·  R quay lại clip vừa rồi  ·  B về clip trước  ·  Q thoát")
        rows = []
        for cid, name, pct, takes, low in s.summary_rows():
            txt = "chưa quay" if takes == 0 else ("theo hiệu lệnh" if pct is None else f"{pct:.0f}%")
            col = status_color("BAD") if takes == 0 else "#9a6700" if low else color("foreground")
            flag = " ← nên quay lại" if low else ""
            rows.append(f"<tr style='color:{col}'><td>{cid}</td><td>{name}</td><td align='right'>{txt}</td>"
                        f"<td align='right'>{max(0, takes - 1)}</td><td>{flag}</td></tr>")
        low_n = sum(1 for r in s.summary_rows() if r[4])
        head = "<tr><th align='left'>Mã</th><th align='left'>Clip</th><th>% đạt</th><th>Quay lại</th><th></th></tr>"
        self.summary.setText(f"<p>{low_n} clip % thấp nên quay lại (R rồi chọn bằng B).</p>"
                             f"<table cellspacing='3'>{head}{''.join(rows)}</table>")
        self.message.setText(s.message)
        self.message.setStyleSheet(f"font-size:22px;font-weight:600;color:{MSG_COLOR[s.message_level]};")
        self.warn.setVisible(False)

    def _goal_text(self, clip, t):
        ph = clip.phase_at(t if t is not None else clip.margin)
        lab = f"[{ph.label}] " if ph.label and (len(clip.phases) > 1) else ""
        if ph.check is not None:
            return f"Mức cần đạt: {lab}{describe_check(ph.check)}"
        if len(clip.phases) > 1 and clip.id in ("C1", "E7"):
            return f"Mức cần đạt: {lab}theo hiệu lệnh"
        return f"Mức cần đạt: {lab}{clip.goal}" if clip.goal not in ("–", "") else f"Mức cần đạt: {lab}theo hiệu lệnh"

    def _show_cameras(self):
        s = self.s
        for cam, box, pairs_fn in (("side", self.box_side, self._side_pairs), ("front", self.box_front, self._front_pairs)):
            src = s.sources.get(cam)
            lt = src.latest() if src else None
            if lt is None:
                continue
            L = s.live["Ls"] if cam == "side" else s.live["Lf"]
            pairs, ids = pairs_fn(L)
            box.show_image(render_camera(lt[1], L, pairs, ids, max(box.img.width(), 320)))

    def _side_pairs(self, L):
        sd = self.s.baseline["side"] if self.s.baseline else None
        if sd is None and L is not None:
            sd = 0 if L[[7, 11, 23], 2].mean() >= L[[8, 12, 24], 2].mean() else 1
        sd = 0 if sd is None else sd
        e, sh, h, ey = IDX["ear"][sd], IDX["shoulder"][sd], IDX["hip"][sd], IDX["eye"][sd]
        return [(e, sh), (sh, h), (e, ey)], [e, sh, h, ey]

    @staticmethod
    def _front_pairs(L):
        return [(11, 12), (7, 11), (8, 12)], [7, 8, 11, 12]
