"""The desktop app starts the local API on its own SqliteStorage instance."""
import json
import socket
import urllib.error
import urllib.request

from core.api import run_server
from core.storage import SqliteStorage


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(base: str, path: str, token: str = ""):
    request = urllib.request.Request(base + path)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode() or "{}")


def test_run_server_reuses_existing_store(tmp_path, monkeypatch):
    store = SqliteStorage(data_dir=tmp_path)
    store.add_todo("Added from the widget")
    port = _free_port()
    monkeypatch.setenv("API_TOKEN", "test-token")

    server, thread = run_server(port=port, store=store, block=False)
    base = f"http://127.0.0.1:{port}"
    try:
        status, payload = _get(base, "/health", token="test-token")
        assert status == 200 and payload["ok"] is True

        status, payload = _get(base, "/tasks", token="test-token")
        assert status == 200
        titles = [t["title"] for t in payload["tasks"]]
        assert "Added from the widget" in titles
        assert len(titles) == len(store.get_todos())

        # the token is required as soon as it is configured
        status, payload = _get(base, "/health")
        assert status == 401 and payload["error"] == "unauthorized"

        assert thread is not None and thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        store.close()
