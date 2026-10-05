"""End-to-end tests for the local HTTP API (core/api.py)."""
import json
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from core.api import run_server

BASE = "http://127.0.0.1:18765"


def _req(method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def setup_module():
    tmp = tempfile.TemporaryDirectory()
    setup_module.tmp = tmp
    server, _ = run_server(port=18765, data_dir=Path(tmp.name), block=False)
    setup_module.server = server


def teardown_module():
    setup_module.server.shutdown()
    setup_module.server.server_close()
    try:
        setup_module.server.store.close()
    except Exception:
        pass
    setup_module.tmp.cleanup()


def test_health():
    code, body = _req("GET", "/health")
    assert code == 200 and body.get("ok") is True


def test_tasks_crud_roundtrip():
    code, created = _req("POST", "/tasks", {"title": "API task", "category": "Ops"})
    assert code == 201 and created["title"] == "API task"
    tid = created["id"]

    code, body = _req("GET", "/tasks")
    assert code == 200 and any(t["id"] == tid for t in body["tasks"])

    code, body = _req("PUT", f"/tasks/{tid}", {"completed": True})
    assert code == 200 and body["completed"] is True

    code, body = _req("DELETE", f"/tasks/{tid}")
    assert code == 200 and body.get("deleted") is True

    code, _ = _req("GET", "/tasks")
    assert all(t["id"] != tid for t in _req("GET", "/tasks")[1]["tasks"])


def test_tasks_validation():
    assert _req("POST", "/tasks", {"title": "   "})[0] == 400
    assert _req("PUT", "/tasks/no-such-id", {"completed": True})[0] == 404
    assert _req("DELETE", "/tasks/no-such-id")[0] == 404
    assert _req("GET", "/nope")[0] == 404


def test_sessions_and_stats():
    code, s = _req("POST", "/sessions", {"task": "API focus", "duration_min": 25})
    assert code == 201 and s["duration_min"] == 25
    assert _req("POST", "/sessions", {"task": "  "})[0] == 400
    code, body = _req("GET", "/sessions")
    assert code == 200 and any(x["task"] == "API focus" for x in body["sessions"])
    code, body = _req("GET", "/stats?days=7")
    assert code == 200 and body["recent_focus_minutes"] >= 25


def test_auth_when_token_set(monkeypatch):
    import os
    monkeypatch.setenv("API_TOKEN", "secret-123")
    req = urllib.request.Request(BASE + "/health", method="GET")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("should be 401")
    except urllib.error.HTTPError as e:
        assert e.code == 401
    req = urllib.request.Request(BASE + "/health", method="GET",
                                 headers={"Authorization": "Bearer secret-123"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
