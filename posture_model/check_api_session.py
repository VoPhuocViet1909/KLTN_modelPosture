"""Run: python posture_model/check_api_session.py (stdlib, no camera/backend needed)."""
import concurrent.futures
import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from api_session import ApiSession, AuthError
from outbox import Outbox
from sender import Sender


def main():
    state = dict(rotations=0, refreshes=[], reject=False, fail=False, redirect=False, deliveries=0, revoked=False)
    sending, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, result = 200, {}
            if state["redirect"]:
                self.send_response(307)
                self.send_header("Location", "/credential-sink")
                self.end_headers()
                return
            if self.path.endswith("/login"):
                result = dict(accessToken="access0", refreshToken="refresh0", expiresIn=900,
                              user=dict(id="11111111-1111-4111-8111-111111111111"))
            elif self.path.endswith("/refresh"):
                state["refreshes"].append(data["refreshToken"])
                assert data["refreshToken"] == "refresh" + str(state["rotations"])
                if state["revoked"]:
                    self.send_response(401)
                    self.end_headers()
                    return
                state["rotations"] += 1
                if state["fail"]:
                    self.close_connection = True  # Response lost after the server rotated.
                    return
                result = dict(accessToken="access" + str(state["rotations"]),
                              refreshToken="refresh" + str(state["rotations"]), expiresIn=900)
                state["reject"] = False
            elif self.path.endswith("/batch"):
                if state.get("block"):
                    sending.set()
                    assert release.wait(5)
                if state["reject"]:
                    status = 401
                else:
                    state["deliveries"] += 1
                    result = dict(accepted=[e["eventId"] for e in data["events"]], rejected=[])
            else:
                raise AssertionError("Unexpected request or redirect followed")
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_port)
    try:
        session = ApiSession(base, "example@test.invalid", "test-password")
        session._expires = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as workers:
            tokens = list(workers.map(lambda _: session.token(), range(24)))
        assert set(tokens) == {"access1"} and state["refreshes"] == ["refresh0"]
        session._expires = 0
        assert session.token() == "access2" and state["refreshes"][-1] == "refresh1"
        for invalid in ("http://example.org", base + "/other", base + "?key=secret"):
            try:
                ApiSession(invalid, "email", "password")
                raise AssertionError("Unsafe base accepted")
            except AuthError:
                pass
        try:
            session.credentials("https://other.invalid")
            raise AssertionError("Session crossed API origin")
        except AuthError:
            pass
        with tempfile.TemporaryDirectory() as directory:
            outbox = Outbox(str(Path(directory) / "outbox.db"))
            try:
                sender = Sender(outbox, base, auth=session, check_schema=False)
                outbox.put("event", "one", {"eventId": "one", "userId": session.user_id})
                state["reject"] = True
                assert sender._send(outbox.due())
                assert outbox.stats() == dict(sent=1, pending=0, dead=0)
                assert state["deliveries"] == 1 and state["rotations"] == 3
                outbox.put("event", "two", {"eventId": "two", "userId": session.user_id})
                state["fail"] = True
                session._expires = 0
                assert not sender._send(outbox.due())
                outbox.retry_now()
                assert not sender._send(outbox.due())
                assert outbox.stats() == dict(sent=1, pending=1, dead=0)
                assert state["rotations"] == 4  # Never replay uncertain single-use refresh.
                error = outbox.db.execute("SELECT last_error FROM outbox WHERE id='two'").fetchone()[0]
                assert "password" not in error and "refresh3" not in error and "access3" not in error
                state["fail"], state["revoked"] = False, True
                session._refresh, session._expires = "refresh4", 0
                outbox.retry_now()
                assert not sender._send(outbox.due())
                count = len(state["refreshes"])
                outbox.retry_now()
                assert not sender._send(outbox.due())
                assert len(state["refreshes"]) == count and outbox.stats()["pending"] == 1
                outbox.put("event", "other-account", {"eventId": "other-account", "userId": "other"})
                assert not sender._send([("other-account", "event", {"userId": "other"})])
                assert "another user" in sender.last_error and state["deliveries"] == 1
            finally:
                outbox.close()
        state["redirect"] = True
        try:
            ApiSession(base, "email", "password")
            raise AssertionError("Login followed a redirect")
        except AuthError:
            pass
        request = urllib.request.Request(base + "/api/v1/telemetry/batch", data=b"{}")
        session._refresh, session._expires = "unused", float("inf")
        try:
            session.open(request)
            raise AssertionError("Bearer followed a redirect")
        except urllib.error.HTTPError as error:
            assert error.code == 307
            error.close()
        state.update(redirect=False, block=True, reject=False)
        with tempfile.TemporaryDirectory() as directory:
            outbox = Outbox(str(Path(directory) / "shutdown.db"))
            sender = Sender(outbox, base, token="manual-token", interval=0.01, check_schema=False)
            sender.enqueue_event({"eventId": "shutdown", "eventType": "SESSION_END"})
            sender.start()
            assert sending.wait(3)
            stopping = threading.Thread(target=lambda: sender.stop(timeout=None))
            stopping.start()
            assert sender._halt.wait(2) and stopping.is_alive()
            release.set()
            stopping.join(5)
            assert not stopping.is_alive() and not sender.is_alive()
            assert outbox.stats() == dict(sent=1, pending=0, dead=0)
            outbox.close()
        print("PASS: concurrent/rotating refresh, 401 replay, retained outbox, uncertain refresh, origin and redirect guards")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
