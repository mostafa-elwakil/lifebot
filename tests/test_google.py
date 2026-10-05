"""Tests for Google Calendar/Tasks sync (fully mocked, no network)."""
import tempfile
from pathlib import Path

from core.google_sync import GoogleSync, SCOPES


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
