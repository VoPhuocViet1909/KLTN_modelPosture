"""Sender không được chết khi Outbox SQLite ghi lỗi (đầy đĩa): báo lỗi, giữ mục chưa ghi, tự phục hồi.

Tạo SQLITE_FULL bằng PRAGMA max_page_count giống hồ sơ NC-10.07; không cần camera/server.
In ra một dòng JSON tóm tắt để làm bằng chứng trước/sau sửa.
"""
import json
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sender import Sender
from outbox import Outbox


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def scenario(sender_cls=Sender, check=True):
    with tempfile.TemporaryDirectory() as directory, closing(Outbox(str(Path(directory) / 'outbox.db'))) as box:
        box.bind('https://example.invalid', 'owner-a')
        sender = sender_cls(box, None, check_schema=False, interval=0.05)   # base_url None: chỉ ghi Outbox
        if hasattr(sender, 'storage_retry_sec'):
            sender.storage_retry_sec = 0.05
        sender.start()
        sender.enqueue_metric({'metricId': 'm-1', 'userId': 'owner-a'})
        assert wait_for(lambda: box.stats()['pending'] == 1), 'first metric should be written'
        with box._lock:
            pages = box.db.execute('PRAGMA page_count').fetchone()[0]
            box.db.execute(f'PRAGMA max_page_count={pages}')
        sender.enqueue_metric({'metricId': 'm-2', 'userId': 'owner-a', 'blob': 'x' * 65536})
        sender._wake.set()
        time.sleep(0.5)
        during = dict(alive=sender.is_alive(), status=sender.status_text(),
                      storageError=getattr(sender, 'storage_error', None), pending=box.stats()['pending'])
        with box._lock:
            box.db.execute('PRAGMA max_page_count=1073741823')
        sender._wake.set()
        wait_for(lambda: box.stats()['pending'] == 2, 2.0)
        after = dict(alive=sender.is_alive(), status=sender.status_text(),
                     storageError=getattr(sender, 'storage_error', None), pending=box.stats()['pending'])
        sender.stop()
        result = dict(duringDiskFull=during, afterSpaceFreed=after)
        if check:
            assert during['alive'], 'Sender thread must survive SQLITE_FULL'
            assert during['storageError'] and 'LOI GHI OUTBOX' in during['status'], 'status must report the write failure'
            assert during['pending'] == 1, 'failed write is not in SQLite yet'
            assert after['alive'] and after['storageError'] is None, 'Sender must recover after space is freed'
            assert after['pending'] == 2, 'held item must be written once space is available'
            assert 'LOI GHI OUTBOX' not in after['status']
        return result


def diagnostics_not_ok():
    """Đã từng gửi OK, sau đó lỗi ghi: chẩn đoán không được báo OK."""
    with tempfile.TemporaryDirectory() as directory, closing(Outbox(str(Path(directory) / 'outbox.db'))) as box:
        box.bind('https://example.invalid', 'owner-a')
        sender = Sender(box, 'https://example.invalid', check_schema=False)
        sender.last_ok = time.time()
        assert sender.diagnostics()['deliveryState'] == 'OK'
        sender._storage_failed(OSError(28, 'No space left on device'))
        diag = sender.diagnostics()
        assert diag['deliveryState'] == 'RETRYING', diag
        assert 'No space' not in json.dumps(diag), 'raw error text must not leave the machine'


def main():
    result = scenario()
    diagnostics_not_ok()
    print(json.dumps(result, ensure_ascii=False))
    print('PASS: Sender survives SQLITE_FULL, reports it, keeps the unwritten item and recovers')


if __name__ == '__main__': main()
