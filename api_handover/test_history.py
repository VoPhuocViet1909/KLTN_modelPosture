"""Test cho history.py (lịch sử cảnh báo và thống kê của mock_server.py):  python test_history.py"""
from datetime import datetime, timedelta, timezone

import history
from payloads import Device, iso

T0 = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)          # 08:00 giờ Việt Nam


def rows(items, user="u1"):
    return [dict(i, _receivedUserId=user) for i in items]


def q(**kw):
    return {k: [v] for k, v in kw.items()}


def test_session_timeout_and_reopen():
    dev = Device(seed=1)
    events = rows([dev.session_start(T0)] + dev.alert_pair(T0 + timedelta(minutes=1), 600)[:1])
    metrics = rows([dev.metric(T0 + timedelta(minutes=2))])
    # 2 phút sau dữ liệu cuối: còn mở
    s = history.build_sessions(events, metrics, T0 + timedelta(minutes=4))
    assert list(s.values())[0]["endReason"] is None
    # quá 3 phút: TIMEOUT, đóng tại dữ liệu cuối; cảnh báo chưa resolve kết thúc cùng phiên
    now = T0 + timedelta(minutes=10)
    page = history.sessions_page(events, metrics, now, q(**{"from": iso(T0 - timedelta(hours=1))}), "u1")
    sess = page["items"][0]
    assert (sess["endReason"], sess["endedAt"], sess["open"], sess["alertCount"]) == \
        ("TIMEOUT", "2026-10-14T01:02:00Z", False, 1), sess
    alert = history.alerts_page(events, metrics, now, q(), {"u1"})["items"][0]
    assert (alert["endReason"], alert["endedAt"], alert["open"]) == ("SESSION_TIMEOUT", "2026-10-14T01:02:00Z", False)
    # app gửi bù dữ liệu mới hơn: phiên mở lại
    metrics += rows([dev.metric(T0 + timedelta(minutes=9))])
    sess = history.sessions_page(events, metrics, now, q(), "u1")["items"][0]
    assert sess["open"] and sess["endReason"] is None
    # SESSION_END thật luôn thắng
    events += rows([dev.session_end(T0 + timedelta(minutes=9, seconds=30), 570.0)])
    sess = history.sessions_page(events, metrics, T0 + timedelta(hours=1), q(), "u1")["items"][0]
    assert (sess["endReason"], sess["endedAt"]) == ("SESSION_END", "2026-10-14T01:09:30Z"), sess


def test_alert_fields_order_filter_and_paging():
    dev = Device(seed=2)
    ev = rows([dev.session_start(T0)] + dev.alert_pair(T0 + timedelta(minutes=1), 45, repeat=True)
              + dev.alert_pair(T0 + timedelta(minutes=10), 20, alert_type="TOO_CLOSE")[:1])
    now = T0 + timedelta(minutes=12)
    page = history.alerts_page(ev, [], now, q(size="1"), {"u1"})
    assert page["total"] == 2 and len(page["items"]) == 1 and page["items"][0]["alertType"] == "TOO_CLOSE"
    first = history.alerts_page(ev, [], now, q(page="1", size="1"), {"u1"})["items"][0]
    assert (first["severity"], first["repeatCount"], first["durationSec"], first["endReason"]) == \
        ("MEDIUM", 1, 45, "CORRECTED"), first     # severity theo sự kiện có ts mới nhất (REPEATED lúc +245 s)
    assert history.alerts_page(ev, [], now, q(alertType="NECK_TRUNK"), {"u1"})["total"] == 1
    assert history.alerts_page(ev, [], now, q(), {"u2"})["total"] == 0


def test_validation_errors():
    now = T0
    for query, field in ((q(size="0"), "size"), (q(page="-1"), "page"), (q(size="x"), "size"),
                         (q(**{"from": "2026-10-14T00:00:00"}), "from"),     # thiếu offset
                         (q(**{"from": "2026-01-01T00:00:00Z"}), "from"),    # quá 92 ngày
                         (q(alertType="neck"), "alertType")):
        try:
            history.alerts_page([], [], now, query, {"u1"})
            raise AssertionError(f"không lỗi: {query}")
        except history.QueryError as e:
            assert e.field == field, (query, e.field)
    for fn, query, field in ((history.timeseries, q(bucket="week"), "bucket"),
                             (history.heatmap, q(weeks="13"), "weeks"), (history.heatmap, q(weeks="a"), "weeks")):
        try:
            fn([], now, query, "u1")
            raise AssertionError("không lỗi")
        except history.QueryError as e:
            assert e.field == field


def test_stats_weighting_vietnam_days_and_heatmap():
    dev = Device(seed=3)
    a = dev.metric(T0, bad_ratio=0.5, alerts={"NECK_TRUNK": 1})              # 08:00 VN thứ Tư
    a.update(postureScore=40, presenceSec=60.0, goodRatio=0.5)
    b = dev.metric(T0 + timedelta(minutes=1), bad_ratio=0.0, alerts={})
    b.update(postureScore=100, presenceSec=30.0, goodRatio=1.0)
    c = dev.metric(datetime(2026, 10, 14, 17, 30, tzinfo=timezone.utc))      # 00:30 VN thứ Năm
    c.update(postureScore=None, presenceSec=0.0, goodRatio=None, alertCount={})
    m = rows([a, b, c])
    now = T0 + timedelta(days=1)
    s = history.summary(m, now, q(), {"u1"})
    assert abs(s["meanScore"] - 60.0) < 1e-9 and s["badMinutes"] == 0.5 and s["presenceMinutes"] == 1.5, s
    assert s["alerts"] == {"NECK_TRUNK": 1}
    days = history.timeseries(m, now, q(bucket="day"), "u1")
    assert [d["start"] for d in days] == ["2026-10-13T17:00:00Z", "2026-10-14T17:00:00Z"], days
    assert days[1]["meanScore"] is None
    hours = history.timeseries(m, now, q(bucket="hour"), "u1")
    assert [h["start"] for h in hours] == ["2026-10-14T01:00:00Z", "2026-10-14T17:00:00Z"]
    cells = history.heatmap(m, now, q(), "u1")
    assert len(cells) == 168
    hit = [x for x in cells if x["meanScore"] is not None]
    assert hit == [{"weekday": 3, "hour": 8, "meanScore": 60.0}], hit


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("OK ", t.__name__)
    print(f"{len(tests)}/{len(tests)} test đạt")
