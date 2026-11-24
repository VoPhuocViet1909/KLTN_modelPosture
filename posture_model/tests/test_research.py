"""B1 + B3 + B4: chế độ nghiên cứu và thẻ hỏi phút 120. Đồng hồ giả, không chờ 2 giờ thật, không cần camera.
  PYTHONUTF8=1 QT_QPA_PLATFORM=offscreen python tests/test_research.py   (hoặc pytest)"""
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from research import ANSWER_WINDOW_SEC, ASK_SEC, ResearchStore, SurveyScheduler, research_path  # noqa: E402
from schema import validate  # noqa: E402

DAY = datetime(2026, 11, 24, 3, 0, 0, tzinfo=timezone.utc).timestamp()      # 10:00 giờ Việt Nam


class Clock:
    def __init__(self, t=DAY):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Rig:
    """Một phiên: store + scheduler + danh sách bản ghi đã vào outbox + số lần thẻ hiện/ẩn."""

    def __init__(self, store, clock, session="sess-1", user="u1", rng=lambda: 0.0, **kw):
        self.out, self.shown, self.hidden = {}, [], []
        self.sch = SurveyScheduler(store, user, session, emit=self._emit, show=self.shown.append,
                                   hide=lambda: self.hidden.append(1), clock=clock, rng=rng, **kw)

    def _emit(self, item_id, payload):
        self.out.setdefault(item_id, payload)         # giống Outbox INSERT OR IGNORE

    def only(self):
        assert len(self.out) == 1, self.out
        return next(iter(self.out.values()))


def make_store(code="P04", enabled=True, prob=0.5):
    path = os.path.join(tempfile.mkdtemp(), "research.db")
    s = ResearchStore(path)
    s.save(enabled, code, prob)
    return s


def public(p):
    return {k: v for k, v in p.items() if k != "userId"}


# ================================================================ B1
def test_default_off_and_code_validation():
    s = ResearchStore(os.path.join(tempfile.mkdtemp(), "r.db"))
    assert s.get() == dict(enabled=False, code=None, invite_prob=0.5)           # không tự bật
    for bad in ("", "P4", "P123", "p04x", "X01", "P0A"):
        try:
            s.save(True, bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    s.save(True, "p07")
    assert s.get()["enabled"] and s.get()["code"] == "P07"
    assert research.valid_code("P00") and not research.valid_code("P1")


def test_settings_scoped_by_account_and_server():
    d = tempfile.mkdtemp()
    a = research_path(d, "http://srv", "user-A")
    assert a != research_path(d, "http://srv", "user-B") and a != research_path(d, "http://other", "user-A")
    assert a == research_path(d, "http://srv/", "user-A")
    sa, sb = ResearchStore(a), ResearchStore(research_path(d, "http://srv", "user-B"))
    sa.save(True, "P01")
    assert sb.get()["enabled"] is False and sb.get()["code"] is None             # đổi người dùng không mang cờ sang
    assert ResearchStore(a).get()["code"] == "P01"                                # mở lại vẫn nhớ


def test_disabled_makes_no_records_and_no_card():
    clock = Clock()
    r = Rig(make_store(enabled=False), clock)
    assert r.sch.begin() == "disabled"
    clock.advance(8000)
    r.sch.tick()
    r.sch.end()
    assert r.out == {} and r.shown == []


def test_setup_dialog_saves_and_validates():
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    import iot_config
    import ui.setup_view as setup
    app = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    setup.preferences = lambda: QSettings(os.path.join(tmp, "s.ini"), QSettings.IniFormat)
    iot_config.PATH = os.path.join(tmp, "iot.json")
    store = ResearchStore(os.path.join(tmp, "r.db"))
    dlg = setup.SetupDialog("0", "-1", "http://localhost:8080", research_store=store)
    assert not dlg.research_enabled.isChecked()                                   # mặc định tắt
    assert "KHÔNG gửi video" in research.DESCRIPTION
    dlg.research_enabled.setChecked(True)
    dlg.research_code.setText("abc")
    dlg.save()
    assert dlg.result_values is None and "P" in dlg.error.text() and store.get()["enabled"] is False
    dlg.research_code.setText("p12")
    dlg.save()
    assert dlg.result_values is not None and store.get() == dict(enabled=True, code="P12", invite_prob=0.5)
    # chưa đăng nhập: mục bị khóa, lưu vẫn chạy bình thường
    dlg2 = setup.SetupDialog("0", "-1", "http://localhost:8080", research_store=None)
    assert not dlg2.research_enabled.isEnabled()
    dlg2.save()
    assert dlg2.result_values is not None


# ================================================================ B3
def test_invite_decision_recorded_even_when_not_invited():
    clock = Clock()
    r = Rig(make_store(prob=0.5), clock, rng=lambda: 0.9)                         # 0.9 ≥ 0.5 -> không mời
    assert r.sch.begin() == "not_invited"
    p = r.only()
    assert p["status"] == "not_invited" and p["answer"] is None and p["asked_sec"] is None and p["invite_prob"] == 0.5
    assert validate("survey", public(p)) == []
    clock.advance(9000)
    r.sch.tick()
    assert r.shown == []                                                          # không bao giờ hiện thẻ


def test_invite_prob_configurable_and_env_override():
    clock = Clock()
    r = Rig(make_store(prob=0.2), clock, rng=lambda: 0.3)
    assert r.sch.begin() == "not_invited"
    os.environ["KLTN_RESEARCH_INVITE_PROB"] = "1"
    try:
        r2 = Rig(make_store(prob=0.2), clock, rng=lambda: 0.99)
        assert r2.sch.begin() == "invited"
    finally:
        del os.environ["KLTN_RESEARCH_INVITE_PROB"]


def test_card_at_7200_and_answer():
    clock = Clock()
    r = Rig(make_store(), clock)
    assert r.sch.begin() == "invited" and r.out == {}
    clock.advance(ASK_SEC - 1)
    r.sch.tick()
    assert r.shown == []
    clock.advance(1)
    r.sch.tick()
    assert r.shown == ["sess-1"]
    clock.advance(30)
    assert r.sch.answer("neck") is True
    p = r.only()
    assert (p["status"], p["answer"], p["asked_sec"], p["reply_sec"]) == ("answered", "neck", 7200.0, 7230.0)
    assert p["participant"] == "P04" and p["session"] == "sess-1" and p["question_version"] == "v1"
    assert validate("survey", public(p)) == [] and r.hidden


def test_all_answer_values_and_skip():
    for value, status, answer in (("none", "answered", "none"), ("lower_back", "answered", "lower_back"),
                                  ("both", "answered", "both"), ("skip", "dismissed", None)):
        clock = Clock()
        r = Rig(make_store(), clock)
        r.sch.begin()
        clock.advance(ASK_SEC)
        r.sch.tick()
        assert r.sch.answer(value)
        p = r.only()
        assert (p["status"], p["answer"]) == (status, answer) and validate("survey", public(p)) == []


def test_away_at_7200_waits_for_return_then_deadline_from_card():
    clock = Clock()
    r = Rig(make_store(), clock)
    r.sch.begin()
    clock.advance(ASK_SEC + 300)
    r.sch.tick(away=True)
    assert r.shown == []                                                          # đang rời ghế: chưa hiện
    clock.advance(600)                                                            # 15 phút sau mốc, người dùng quay lại
    r.sch.tick(away=False)
    assert r.shown == ["sess-1"]
    clock.advance(ANSWER_WINDOW_SEC - 1)                                          # hạn 10 phút tính từ lúc thẻ hiện
    r.sch.tick()
    assert r.out == {}
    assert r.sch.answer("both")
    p = r.only()
    assert p["asked_sec"] == ASK_SEC + 900 and p["reply_sec"] == ASK_SEC + 900 + ANSWER_WINDOW_SEC - 1


def test_expires_after_10_minutes():
    clock = Clock()
    r = Rig(make_store(), clock)
    r.sch.begin()
    clock.advance(ASK_SEC)
    r.sch.tick()
    clock.advance(ANSWER_WINDOW_SEC)
    r.sch.tick()
    p = r.only()
    assert (p["status"], p["answer"], p["reply_sec"], p["asked_sec"]) == ("expired", None, None, 7200.0)
    assert validate("survey", public(p)) == [] and r.hidden
    assert r.sch.answer("neck") is False and len(r.out) == 1                      # trả lời muộn không ghi


def test_answer_too_late_without_tick_counts_as_expired():
    clock = Clock()
    r = Rig(make_store(), clock)
    r.sch.begin()
    clock.advance(ASK_SEC)
    r.sch.tick()
    clock.advance(ANSWER_WINDOW_SEC + 5)
    assert r.sch.answer("neck") is False
    assert r.only()["status"] == "expired"


def test_session_ends_before_7200_is_ended_early():
    clock = Clock()
    r = Rig(make_store(), clock)
    r.sch.begin()
    clock.advance(3600)
    r.sch.tick()
    r.sch.end()
    r.sch.end()                                                                   # gọi hai lần không thêm bản ghi
    p = r.only()
    assert (p["status"], p["answer"], p["asked_sec"], p["reply_sec"]) == ("ended_early", None, None, None)
    assert validate("survey", public(p)) == []


def test_double_press_records_once():
    clock = Clock()
    r = Rig(make_store(), clock)
    r.sch.begin()
    clock.advance(ASK_SEC)
    r.sch.tick()
    assert r.sch.answer("neck") is True
    assert r.sch.answer("both") is False and r.sch.answer("skip") is False
    assert r.only()["answer"] == "neck"


def test_daily_limit_uses_vietnam_day():
    store = make_store()
    base = datetime(2026, 11, 24, 16, 59, 0, tzinfo=timezone.utc).timestamp()      # 23:59 ngày 24 giờ VN
    c = Clock(base)
    a = Rig(store, c, session="a")
    assert a.sch.begin() == "invited"
    a.sch.end()
    c.advance(30)                                                                  # vẫn 23:59 ngày 24 -> hết suất
    b = Rig(store, c, session="b")
    assert b.sch.begin() == "not_invited" and b.only()["status"] == "not_invited"
    c.advance(120)                                                                 # 00:01 ngày 25 giờ VN
    d = Rig(store, c, session="c")
    assert d.sch.begin() == "invited"
    # chưa được mời (xác suất trượt) thì chưa tốn suất trong ngày
    store2 = make_store()
    e = Rig(store2, Clock(), session="e", rng=lambda: 0.9)
    assert e.sch.begin() == "not_invited"
    f = Rig(store2, Clock(), session="f", rng=lambda: 0.0)
    assert f.sch.begin() == "invited"


def test_dev_override_ask_after_one_minute():
    os.environ["KLTN_RESEARCH_ASK_SEC"] = "60"
    try:
        clock = Clock()
        r = Rig(make_store(), clock)
        r.sch.begin()
        clock.advance(60)
        r.sch.tick()
        assert r.shown == ["sess-1"]
    finally:
        del os.environ["KLTN_RESEARCH_ASK_SEC"]


# ================================================================ B4
def test_app_killed_while_card_shown_then_reopened():
    """Tắt/mở app giữa lúc thẻ đang hiện: phiên cũ ghi ended_early đúng một lần, phiên mới không hỏi lần hai trong ngày."""
    store = make_store()
    clock = Clock()
    a = Rig(store, clock, session="s-old")
    a.sch.begin()
    clock.advance(ASK_SEC)
    a.sch.tick()
    assert a.shown == ["s-old"] and a.out == {}                                    # thẻ đang hiện, app bị kill (không end())
    clock.advance(120)
    b = Rig(store, clock, session="s-new")
    assert b.sch.begin() == "not_invited"                                          # không hỏi lần hai
    ids = list(b.out)
    statuses = {p["session"]: p["status"] for p in b.out.values()}
    assert statuses == {"s-old": "ended_early", "s-new": "not_invited"}, statuses
    assert b.out[[i for i in ids if "s-old" in i][0]]["asked_sec"] == 7200.0
    b.sch.end()
    c = Rig(store, clock, session="s-third")                                      # mở lại lần nữa: không tạo lại bản ghi cũ
    c.sch.begin()
    assert "s-old" not in {p["session"] for p in c.out.values()}


def test_crash_between_outbox_and_ledger_is_idempotent():
    store = make_store()
    clock = Clock()
    r = Rig(store, clock, session="s1")
    r.sch.begin()
    clock.advance(100)
    r.sch.end()
    first = dict(r.out)
    store.db.execute("UPDATE sessions SET final_status=NULL, state='invited' WHERE session_id='s1'")   # sập trước khi đánh dấu
    r2 = Rig(store, clock, session="s2")
    r2.sch.begin()
    assert set(first) <= set(r2.out) and r2.out[next(iter(first))]["session"] == "s1"
    assert len({k for k in r2.out if "s1" in k}) == 1                              # cùng khoá -> outbox bỏ trùng


def test_user_switch_does_not_leak_flag_or_day_claim():
    d = tempfile.mkdtemp()
    server = "http://srv"
    clock = Clock()
    sa = ResearchStore(research_path(d, server, "user-A"))
    sa.save(True, "P01")
    a = Rig(sa, clock, user="user-A", session="a1")
    assert a.sch.begin() == "invited"                                              # A giữ thẻ đang hiện, rồi đăng xuất
    clock.advance(ASK_SEC)
    a.sch.tick()
    a.sch.end()                                                                    # đăng xuất: ended_early của A
    assert a.only()["participant"] == "P01" and a.only()["userId"] == "user-A"
    sb = ResearchStore(research_path(d, server, "user-B"))
    b = Rig(sb, clock, user="user-B", session="b1")
    assert b.sch.begin() == "disabled" and b.out == {}                             # B chưa bật: không kế thừa cờ của A
    sb.save(True, "P02")
    b2 = Rig(sb, clock, user="user-B", session="b2")
    assert b2.sch.begin() == "invited"                                             # suất mời trong ngày của A không trừ vào B
    assert b2.out == {}


def test_outbox_rejects_other_owner_survey():
    from outbox import Outbox
    ob = Outbox(os.path.join(tempfile.mkdtemp(), "o.db"))
    ob.bind("http://srv", "user-A")
    clock = Clock()
    s = make_store()
    r = Rig(s, clock, user="user-B")
    r.sch.begin()
    clock.advance(10)
    r.sch.end()
    (item_id, payload), = r.out.items()
    try:
        ob.put("survey", item_id, payload, True)
        raise AssertionError("outbox nhận bản ghi của người khác")
    except ValueError:
        pass


# ---------------------------------------------------------------- gửi: mất mạng rồi có lại
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_until(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def post(base, tok, body):
    import json
    req = urllib.request.Request(base + "/api/v1/research/survey", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_offline_then_online_single_record_no_dead():
    from mock_server import serve
    from outbox import Outbox
    from sender import Sender
    port, d = free_port(), tempfile.mkdtemp()
    base = f"http://127.0.0.1:{port}"
    ob = Outbox(os.path.join(d, "o.db"))
    snd = Sender(ob, base, "tok", "dev-1", interval=0.3)
    snd.probe_sec = 0.5
    snd.start()                                                                    # server chưa chạy = mất mạng
    clock = Clock()
    r = Rig(make_store(), clock, user="u1", session="sess-net")
    r.sch._emit = lambda i, p: snd.enqueue_survey(i, p)
    r.sch.emit = r.sch._emit
    r.sch.begin()
    clock.advance(ASK_SEC)
    r.sch.tick()
    r.sch.answer("both")
    r.sch.end()                                                                    # bấm lại / kết thúc: vẫn một bản ghi
    assert wait_until(lambda: ob.stats()["pending"] == 1 and snd.q.empty())
    assert wait_until(lambda: snd.online is False)
    assert ob.stats()["dead"] == 0                                                 # mất mạng không tạo dead
    srv, store = serve(port, token="tok", folder=os.path.join(d, "srv"), quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    assert wait_until(lambda: ob.stats()["pending"] == 0, 20), ob.stats()
    assert ob.stats()["dead"] == 0 and ob.stats()["sent"] == 1
    assert len(store.surveys) == 1
    rec = next(iter(store.surveys.values()))["record"]
    assert rec["status"] == "answered" and rec["answer"] == "both" and "userId" not in rec
    # gửi lại cùng khoá: 200 và cùng nội dung, không thêm dòng
    status, body = post(base, "tok", rec)
    assert status == 200 and body == rec and len(store.surveys) == 1
    snd.stop()
    srv.shutdown()
    srv.server_close()


def test_mock_server_idempotent_and_private():
    from mock_server import serve
    port, d = free_port(), tempfile.mkdtemp()
    srv, store = serve(port, token="tok", folder=d, quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    rec = dict(participant="P09", session="s9", status="dismissed", answer=None, asked_sec=7200.0, reply_sec=None,
               question_version="v1", invite_prob=0.5)
    s1, b1 = post(base, "tok", rec)
    s2, b2 = post(base, "tok", rec)
    assert (s1, s2) == (201, 200) and b1 == b2 == rec and len(store.surveys) == 1
    try:
        post(base, "tok", dict(rec, status="answered"))                            # sai schema (answered mà answer = null)
        raise AssertionError("mock nhận bản ghi sai schema")
    except urllib.error.HTTPError as e:
        assert e.code == 400
    srv.shutdown()
    srv.server_close()


# ---------------------------------------------------------------- tích hợp engine (không cần camera)
def test_engine_hooks_invite_and_answer():
    from engine import PostureEngine
    store_path = os.path.join(tempfile.mkdtemp(), "r.db")
    s = ResearchStore(store_path)
    s.save(True, "P05", 1.0)
    s.close()
    sent, shown = [], []
    fake = SimpleNamespace(auth=SimpleNamespace(user_id="u1"), elog=SimpleNamespace(session_id="eng-1"),
                           sender=SimpleNamespace(enqueue_survey=lambda i, p: sent.append((i, p))),
                           listener=SimpleNamespace(on_survey=shown.append, on_survey_hide=lambda: None))
    fake._make_survey = lambda o: PostureEngine._make_survey(fake, o)
    os.environ["KLTN_RESEARCH_ASK_SEC"] = "0.05"
    try:
        sch = PostureEngine._make_survey(fake, SimpleNamespace(send=True, research_db=store_path))
        assert sch is not None
        fake.survey = sch
        time.sleep(0.1)
        sch.tick()
        assert shown == ["eng-1"]
        assert PostureEngine.answer_survey(fake, "none") is True and PostureEngine.answer_survey(fake, "neck") is False
        assert [p["answer"] for _, p in sent] == ["none"]
    finally:
        del os.environ["KLTN_RESEARCH_ASK_SEC"]
    # không đăng nhập hoặc không có CSDL -> không chạy
    assert PostureEngine._make_survey(SimpleNamespace(auth=None), SimpleNamespace(send=True, research_db=store_path)) is None
    assert PostureEngine._make_survey(SimpleNamespace(auth=fake.auth), SimpleNamespace(send=True, research_db=None)) is None


def test_survey_card_buttons_and_close():
    from PySide6.QtWidgets import QApplication
    from ui.survey_card import SurveyCard
    app = QApplication.instance() or QApplication([])
    card = SurveyCard()
    got = []
    card.answered.connect(got.append)
    card.present()
    card.buttons["neck"].click()
    card.buttons["both"].click()                                                   # bấm lần hai (nút đã khóa) không phát thêm
    assert got == ["neck"] and not card.isVisible()
    card.present()
    card.close()                                                                   # đóng bằng X = Bỏ qua
    assert got == ["neck", "skip"]
    card.present()
    card.dismiss()                                                                 # engine ẩn thẻ (hết hạn): không phát câu trả lời
    assert got == ["neck", "skip"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
