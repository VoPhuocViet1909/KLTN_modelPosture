"""
Chế độ tham gia nghiên cứu (B1) và thẻ hỏi phút 120 (B3). Không phụ thuộc Qt/camera nên test được bằng đồng hồ giả.

Dữ liệu gửi khi bật: metrics 60 giây (như bình thường) và câu trả lời khảo sát. KHÔNG gửi video/ảnh.

ResearchStore  : SQLite theo (máy chủ, tài khoản): cờ bật, mã nghiên cứu, xác suất mời, sổ quyết định mỗi phiên.
SurveyScheduler: quyết định mời ở đầu phiên, hiện thẻ ở mốc ASK_SEC, hạn trả lời, kết thúc phiên.

Quy tắc đã chốt (kế hoạch mục 3.3):
- Mốc hỏi tính theo thời gian chạy của phiên (đồng hồ thật từ SESSION_START), KHÔNG trừ lúc rời ghế.
- Đúng mốc mà người dùng đang rời ghế thì chờ có người lại mới hiện thẻ; hạn 10 phút tính từ lúc thẻ hiện;
  asked_sec ghi thời điểm thẻ thực sự hiện.
- Tối đa 1 lần mời/người/ngày (giờ Việt Nam, UTC+7). Phiên không được mời (kể cả vì đã mời hôm nay) ghi `not_invited`.
- Mỗi (participant, session) đúng một bản ghi; ghi sổ TRƯỚC khi đưa vào outbox, gửi lại cùng khoá không tạo dòng mới.
"""
import hashlib
import json
import os
import random
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

CODE_RE = re.compile(r"^P\d{2}$")
VN_TZ = timezone(timedelta(hours=7))
ASK_SEC = 7200.0                  # phút 120
ANSWER_WINDOW_SEC = 600.0         # hạn 10 phút kể từ lúc thẻ hiện
DEFAULT_INVITE_PROB = 0.5
QUESTION_VERSION = "v1"
ANSWERS = ("none", "neck", "lower_back", "both")
SURVEY_ID_PREFIX = "survey-"

DESCRIPTION = ("Khi bật, ứng dụng gửi lên máy chủ: số liệu tư thế gộp theo 60 giây (như hiện nay) kèm mã nghiên cứu, "
               "và câu trả lời của bạn cho một câu hỏi về cảm giác khó chịu ở cuối buổi ngồi dài. "
               "Ứng dụng KHÔNG gửi video hay ảnh. Bạn tắt được bất cứ lúc nào.")


def valid_code(code):
    return bool(CODE_RE.match(str(code or "")))


def research_path(directory, server, owner):
    scope = hashlib.sha256((server.rstrip("/") + "\n" + str(owner)).encode()).hexdigest()
    return os.path.join(directory, "research-" + scope + ".db")


def vn_day(wall):
    return datetime.fromtimestamp(wall, VN_TZ).strftime("%Y-%m-%d")


def env_float(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if v > 0 else default
    except ValueError:
        return default


class ResearchStore:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS settings(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL DEFAULT 0,
            code TEXT, invite_prob REAL NOT NULL DEFAULT 0.5)""")
        self.db.execute("INSERT OR IGNORE INTO settings(singleton) VALUES(1)")
        # state: not_invited | invited | asked | done. day_claimed=1 khi phiên này đã dùng suất mời của ngày.
        self.db.execute("""CREATE TABLE IF NOT EXISTS sessions(
            session_id TEXT PRIMARY KEY, participant TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL,
            day_claimed INTEGER NOT NULL DEFAULT 0, invite_prob REAL NOT NULL, started_wall REAL NOT NULL,
            asked_sec REAL, asked_wall REAL, final_status TEXT)""")

    # ---------------------------------------------------------------- cài đặt
    def get(self):
        with self._lock:
            en, code, prob = self.db.execute("SELECT enabled, code, invite_prob FROM settings").fetchone()
        return dict(enabled=bool(en), code=code, invite_prob=prob)

    def save(self, enabled, code, invite_prob=None):
        code = (code or "").strip().upper() or None
        if enabled and not valid_code(code):
            raise ValueError("Mã nghiên cứu có dạng P và hai chữ số, ví dụ P04.")
        if code is not None and not valid_code(code):
            raise ValueError("Mã nghiên cứu có dạng P và hai chữ số, ví dụ P04.")
        with self._lock:
            self.db.execute("UPDATE settings SET enabled=?, code=?" + (", invite_prob=?" if invite_prob is not None else ""),
                            (int(bool(enabled)), code) + ((float(invite_prob),) if invite_prob is not None else ()))

    def close(self):
        with self._lock:
            self.db.close()


class SurveyScheduler:
    """Một đối tượng cho mỗi phiên. emit(item_id, payload) đưa bản ghi vào outbox (kind 'survey').
    show(session_id) báo giao diện hiện thẻ; hide() ẩn thẻ."""

    def __init__(self, store, user_id, session_id, emit, show=None, hide=None, clock=time.time, rng=None,
                 ask_sec=None, ignore_daily_limit=None):
        self.store, self.user_id, self.session_id = store, str(user_id), session_id
        self.emit, self.show, self.hide = emit, show or (lambda sid: None), hide or (lambda: None)
        self.clock = clock
        self.rng = rng or random.random
        self.ask_sec = ask_sec if ask_sec is not None else env_float("KLTN_RESEARCH_ASK_SEC", ASK_SEC)
        self.ignore_daily_limit = (os.environ.get("KLTN_RESEARCH_IGNORE_DAILY_LIMIT") == "1"
                                   if ignore_daily_limit is None else ignore_daily_limit)
        self.lock = threading.RLock()
        self.active = False
        self.participant = None
        self.invited = False
        self.asked_wall = None
        self.start_wall = None
        self.closed = False

    # ---------------------------------------------------------------- vòng đời
    def begin(self):
        """Gọi đầu phiên. Trả 'disabled' | 'invited' | 'not_invited'."""
        with self.lock:
            cfg = self.store.get()
            self.finalize_orphans()
            if not cfg["enabled"] or not valid_code(cfg["code"]):
                return "disabled"
            self.participant = cfg["code"]
            self.start_wall = self.clock()
            day = vn_day(self.start_wall)
            prob = env_float("KLTN_RESEARCH_INVITE_PROB", cfg["invite_prob"])
            db = self.store.db
            if db.execute("SELECT 1 FROM sessions WHERE session_id=?", (self.session_id,)).fetchone():
                self.closed = True                        # cùng phiên đã quyết định rồi: không quyết định lần hai
                return "disabled"
            taken = db.execute("SELECT 1 FROM sessions WHERE day=? AND participant=? AND day_claimed=1",
                               (day, self.participant)).fetchone() is not None
            chosen = (not taken or self.ignore_daily_limit) and self.rng() < prob
            db.execute("INSERT INTO sessions(session_id, participant, day, state, day_claimed, invite_prob, started_wall) "
                       "VALUES (?,?,?,?,?,?,?)", (self.session_id, self.participant, day,
                                                  "invited" if chosen else "not_invited", int(chosen), prob, self.start_wall))
            if chosen:
                self.invited = self.active = True
                return "invited"
            self._finish("not_invited", None, None, None)
            self.closed = True
            return "not_invited"

    def finalize_orphans(self):
        """Phiên trước bị tắt đột ngột (kill/mất điện) khi chưa chốt: ghi ended_early, không hỏi lại."""
        db = self.store.db
        rows = db.execute("SELECT session_id, participant, invite_prob, started_wall, asked_sec, state FROM sessions "
                          "WHERE state IN ('invited','asked') AND session_id<>?", (self.session_id,)).fetchall()
        for sid, participant, prob, _, asked_sec, state in rows:
            self._finish("ended_early", None, asked_sec, None, session_id=sid, participant=participant, prob=prob)

    def tick(self, away=False):
        """Gọi định kỳ từ vòng lặp engine (~mỗi giây hoặc mỗi khung). Hiện thẻ, hết hạn."""
        with self.lock:
            if not self.active or self.closed:
                return
            now = self.clock()
            if self.asked_wall is None:
                if now - self.start_wall >= self.ask_sec and not away:
                    self.asked_wall = now
                    asked_sec = round(now - self.start_wall, 1)
                    self.store.db.execute("UPDATE sessions SET state='asked', asked_sec=?, asked_wall=? WHERE session_id=?",
                                          (asked_sec, now, self.session_id))
                    self.show(self.session_id)
                return
            if now - self.asked_wall >= ANSWER_WINDOW_SEC:
                self._resolve("expired", None)

    def answer(self, value):
        """Người dùng bấm. value: none|neck|lower_back|both hoặc None/'skip' (Bỏ qua). Bấm lần hai bị bỏ qua. True nếu ghi nhận."""
        with self.lock:
            if not self.active or self.closed or self.asked_wall is None:
                return False
            if self.clock() - self.asked_wall >= ANSWER_WINDOW_SEC:
                self._resolve("expired", None)
                return False
            if value in ANSWERS:
                self._resolve("answered", value)
            elif value in (None, "skip", "dismissed"):
                self._resolve("dismissed", None)
            else:
                raise ValueError("Câu trả lời không hợp lệ")
            return True

    def end(self):
        """Phiên kết thúc (thoát, đăng xuất, đổi người dùng). Chưa trả lời thì ghi ended_early."""
        with self.lock:
            if self.active and not self.closed:
                self.hide()
                self._finish("ended_early", None, self._asked_sec(), None)
                self.closed = True
                self.active = False

    # ---------------------------------------------------------------- nội bộ
    def _asked_sec(self):
        if self.asked_wall is None:
            return None
        return round(self.asked_wall - self.start_wall, 1)

    def _resolve(self, status, answer):
        reply = round(self.clock() - self.start_wall, 1) if status == "answered" else None
        self.hide()
        self._finish(status, answer, self._asked_sec(), reply)
        self.closed = True
        self.active = False

    def _finish(self, status, answer, asked_sec, reply_sec, session_id=None, participant=None, prob=None):
        """Chốt bản ghi: ghi sổ rồi mới đưa vào outbox. Gọi lại với cùng phiên không tạo bản ghi thứ hai."""
        sid = session_id or self.session_id
        db = self.store.db
        if prob is None:
            prob = db.execute("SELECT invite_prob FROM sessions WHERE session_id=?", (sid,)).fetchone()[0]
        row = db.execute("SELECT final_status, participant FROM sessions WHERE session_id=?", (sid,)).fetchone()
        if row is None or row[0] is not None:
            return                                        # đã chốt: gửi lại/bấm lại không tạo bản ghi thứ hai
        payload = {"participant": participant or self.participant, "session": sid, "status": status, "answer": answer,
                   "asked_sec": asked_sec, "reply_sec": reply_sec, "question_version": QUESTION_VERSION,
                   "invite_prob": prob, "userId": self.user_id}
        # Vào outbox TRƯỚC rồi mới đánh dấu đã chốt: sập giữa chừng thì lần sau ghi lại cùng khoá (INSERT OR IGNORE).
        self.emit(SURVEY_ID_PREFIX + f"{payload['participant']}-{sid}", payload)
        db.execute("UPDATE sessions SET state=?, final_status=? WHERE session_id=?",
                   ("not_invited" if status == "not_invited" else "done", status, sid))
