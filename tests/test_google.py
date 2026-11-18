"""Tests for Google Calendar/Tasks sync (fully mocked, no network)."""
import tempfile
from pathlib import Path

from core.google_sync import GoogleSync, SCOPES, friendly_error


class _FakeEvents:
    def __init__(self, calls):
        self.calls = calls

    def insert(self, calendarId=None, body=None):
        self.calls.append(("event", calendarId, body))
        outer = self

        class R:
            def execute(self):
                return {"id": "ev1", "htmlLink": "http://x"}
        return R()


class _FakeCal:
    def __init__(self, calls):
        self._calls = calls

    def events(self):
        return _FakeEvents(self._calls)


class _FakeTasks:
    def __init__(self, calls, items):
        self._calls = calls
        self._items = items

    def tasklists(self):
        outer = self

        class L:
            def list(self):
                class R:
                    def execute(self):
                        return {"items": [{"id": "list1"}]}
                return R()
        return L()

    def tasks(self):
        outer = self

        class T:
            def insert(self, tasklist=None, body=None):
                outer._calls.append(("push", tasklist, body))

                class R:
                    def execute(self):
                        return {"id": "t1", "title": body["title"]}
                return R()

            def list(self, **kw):
                class R:
                    def execute(inner_self):
                        return {"items": outer._items}
                return R()
        return T()


def _gsync(tmp):
    gs = GoogleSync(data_dir=Path(tmp), client_id="id", client_secret="s")
    calls = []
    gs._cal_service = lambda: _FakeCal(calls)
    items = [
        {"id": "g1", "title": "G task", "status": "needsAction"},
        {"id": "g2", "title": "Done one", "status": "completed"},
    ]
    gs._tasks_service = lambda: _FakeTasks(calls, items)
    gs._calls = calls
    return gs


def test_status_and_scopes():
    assert "calendar.events" in SCOPES[0] and "tasks" in SCOPES[1]
    gs = GoogleSync(data_dir="/nonexistent-xyz", client_id="", client_secret="")
    assert "Client ID" in gs.status() or "libs" in gs.status()


def test_log_focus_event():
    with tempfile.TemporaryDirectory() as td:
        gs = _gsync(td)
        ev = gs.log_focus_event("Deep work", 25)
        assert ev and ev["id"] == "ev1"
        kind, cal, body = gs._calls[0]
        assert kind == "event" and cal == "primary" and "Deep work" in body["summary"]


def test_push_and_pull_tasks():
    with tempfile.TemporaryDirectory() as td:
        gs = _gsync(td)
        pushed = gs.push_task("Hello", "notes")
        assert pushed and pushed["title"] == "Hello"
        pulled = gs.pull_tasks()
        assert len(pulled) == 1 and pulled[0]["title"] == "G task"
        assert pulled[0]["completed"] is False


def test_failures_never_raise(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        gs = GoogleSync(data_dir=Path(td), client_id="id", client_secret="s")
        gs._cal_service = lambda: None
        gs._tasks_service = lambda: None
        assert gs.log_focus_event("x") is None
        assert gs.push_task("x") is None
        assert gs.pull_tasks() == []


def test_authorize_without_credentials_fails_fast():
    """Must not open a broken browser page with an empty client_id."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        gs = GoogleSync(data_dir=Path(td), client_id="", client_secret="")
        assert gs.authorize() is False
        assert "Client ID" in gs.last_error


def test_access_denied_shows_test_user_guidance(monkeypatch):
    """The exact Google 403 screen users hit must yield actionable advice."""
    import google_auth_oauthlib.flow as flow_mod
    import tempfile

    class _Boom:
        @classmethod
        def from_client_config(cls, *a, **k):
            return cls()

        def run_local_server(self, **k):
            raise RuntimeError("(access_denied) access_denied: 403")

    monkeypatch.setattr(flow_mod, "InstalledAppFlow", _Boom)
    with tempfile.TemporaryDirectory() as td:
        gs = GoogleSync(data_dir=Path(td), client_id="id", client_secret="s")
        assert gs.authorize() is False
        assert "Test users" in gs.last_error
        assert "access_denied" in gs.last_raw_error


def test_friendly_error_mapping():
    assert "Test users" in friendly_error("403: access_denied")
    assert "Desktop app" in friendly_error("invalid_client")
    assert "expired" in friendly_error("invalid_grant: Token has been expired or revoked")
    # unknown errors pass through untouched
    assert friendly_error("something odd") == "something odd"


def test_connection_unconfigured():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        gs = GoogleSync(data_dir=Path(td), client_id="", client_secret="")
        res = gs.test_connection()
        assert res["ok"] is False
        assert "Client ID" in res["message"] or "libs" in res["message"]
        # configured but never authorized (no token file)
        gs2 = GoogleSync(data_dir=Path(td), client_id="id", client_secret="s")
        res2 = gs2.test_connection()
        assert res2["ok"] is False and "authoriz" in res2["message"].lower()


def test_connection_ok_with_fake_services():
    import tempfile

    class _Ev:
        def list(self, calendarId=None, maxResults=None):
            class R:
                def execute(self):
                    return {"items": [{"id": "e1"}]}
            return R()

    class _Cal:
        def events(self):
            return _Ev()

    class _Tasks:
        def tasklists(self):
            class L:
                def list(self):
                    class R:
                        def execute(self):
                            return {"items": [{"id": "l1", "title": "My Tasks"}]}
                    return R()
            return L()

    with tempfile.TemporaryDirectory() as td:
        gs = GoogleSync(data_dir=Path(td), client_id="id", client_secret="s")
        gs.token_path.write_text("{}", encoding="utf-8")  # pretend authorized
        gs._tasks_service = lambda: _Tasks()
        gs._cal_service = lambda: _Cal()
        res = gs.test_connection()
        assert res["ok"] is True
        assert "My Tasks" in res["message"] and "Calendar" in res["message"]


def test_connection_api_error_never_raises():
    import tempfile

    class _Boom:
        def tasklists(self):
            raise RuntimeError("quota exceeded")

    with tempfile.TemporaryDirectory() as td:
        gs = GoogleSync(data_dir=Path(td), client_id="id", client_secret="s")
        gs.token_path.write_text("{}", encoding="utf-8")
        gs._tasks_service = lambda: _Boom()
        res = gs.test_connection()
        assert res["ok"] is False and "quota" in res["message"]

