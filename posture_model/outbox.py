"""
Outbox SQLite: mọi sự kiện / metrics được ghi xuống đĩa TRƯỚC khi gửi, nên mất mạng hay tắt app giữa chừng
cũng không mất dữ liệu. Gửi xong mới đánh dấu sent. Gửi lỗi thì hẹn giờ thử lại (backoff luỹ thừa).

Bảng outbox:
  id          eventId / metricId (khoá chính -> ghi trùng bị bỏ qua, server cũng chống trùng theo id)
  kind        'event' | 'metric'
  payload     JSON
  urgent      1 = gửi ngay (ALERT_STARTED...), 0 = chờ tới lượt gửi theo lô
  created_at, attempts, next_try, sent_at, dead (1 = server từ chối hẳn, không thử lại), last_error
"""
import json
import os
import random
import sqlite3
import threading
import time

BACKOFF_BASE, BACKOFF_MAX = 2.0, 300.0


class Outbox:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS outbox(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, urgent INTEGER DEFAULT 0,
            created_at REAL NOT NULL, attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0,
            sent_at REAL, dead INTEGER DEFAULT 0, last_error TEXT)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_due ON outbox(sent_at, dead, next_try)")

    def put(self, kind, item_id, payload, urgent=False):
        with self._lock:
            self.db.execute("INSERT OR IGNORE INTO outbox(id, kind, payload, urgent, created_at) VALUES (?,?,?,?,?)",
                            (item_id, kind, json.dumps(payload, ensure_ascii=False), int(urgent), time.time()))

    def due(self, limit=100, now=None):
        """Các mục chưa gửi, đã tới giờ thử. Ưu tiên urgent, rồi cũ trước."""
        now = time.time() if now is None else now
        with self._lock:
            rows = self.db.execute(
                "SELECT id, kind, payload FROM outbox WHERE sent_at IS NULL AND dead=0 AND next_try<=? "
                "ORDER BY urgent DESC, created_at LIMIT ?", (now, limit)).fetchall()
        return [(i, k, json.loads(p)) for i, k, p in rows]

    def has_urgent_due(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            return self.db.execute("SELECT 1 FROM outbox WHERE sent_at IS NULL AND dead=0 AND urgent=1 AND next_try<=? "
                                   "LIMIT 1", (now,)).fetchone() is not None

    def mark_sent(self, ids):
        if not ids:
            return
        with self._lock:
            self.db.executemany("UPDATE outbox SET sent_at=?, last_error=NULL WHERE id=?",
                                [(time.time(), i) for i in ids])

    def mark_failed(self, ids, error, now=None):
        """Lỗi tạm thời (mất mạng, 5xx): thử lại sau 2, 4, 8 ... tối đa 300 giây (+ ngẫu nhiên để tránh dồn)."""
        now = time.time() if now is None else now
        with self._lock:
            for i in ids:
                row = self.db.execute("SELECT attempts FROM outbox WHERE id=?", (i,)).fetchone()
                n = (row[0] if row else 0) + 1
                wait = min(BACKOFF_BASE ** n, BACKOFF_MAX) * random.uniform(0.8, 1.2)
                self.db.execute("UPDATE outbox SET attempts=?, next_try=?, last_error=? WHERE id=?",
                                (n, now + wait, str(error)[:300], i))

    def mark_dead(self, items):
        """Server từ chối hẳn (dữ liệu sai schema...) -> không gửi lại, giữ lại để xem lỗi."""
        with self._lock:
            self.db.executemany("UPDATE outbox SET dead=1, last_error=? WHERE id=?",
                                [(str(err)[:300], i) for i, err in items])

    def retry_now(self):
        """Mạng vừa có lại: bỏ thời gian chờ, thử lại ngay."""
        with self._lock:
            self.db.execute("UPDATE outbox SET next_try=0 WHERE sent_at IS NULL AND dead=0")

    def stats(self):
        with self._lock:
            pending, = self.db.execute("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL AND dead=0").fetchone()
            sent, = self.db.execute("SELECT COUNT(*) FROM outbox WHERE sent_at IS NOT NULL").fetchone()
            dead, = self.db.execute("SELECT COUNT(*) FROM outbox WHERE dead=1").fetchone()
        return {"pending": pending, "sent": sent, "dead": dead}

    def purge_sent(self, older_than_days=7):
        with self._lock:
            self.db.execute("DELETE FROM outbox WHERE sent_at IS NOT NULL AND sent_at < ?",
                            (time.time() - older_than_days * 86400,))

    def close(self):
        with self._lock:
            self.db.close()
