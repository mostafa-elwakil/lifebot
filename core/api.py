"""Minimal local HTTP API over the Rakez core (stdlib only, no new deps).

Endpoints (JSON):
    GET  /health
    GET  /tasks            -> {"tasks": [...]}
    POST /tasks            {"title": str, "category"?, "priority"?, "estimate"?, "project_id"?}
    PUT  /tasks/<id-or-title>   {"completed"?, "title"?, "category"?, "priority"?, "project_id"?}
    DELETE /tasks/<id-or-title>
    GET  /projects         -> {"projects": [...]} (each with total/done/pct)
    POST /projects         {"name": str}
    DELETE /projects/<id-or-name>   (tasks survive, become unassigned)
    GET  /sessions         -> {"sessions": [...]}
    POST /sessions         {"task": str, "category"?, "duration_min"?, "kind"?}
    GET  /stats?days=7

Auth: if env API_TOKEN is set, every request needs
`Authorization: Bearer <token>` (this is what TestSprite injects as the
project credential). Otherwise the API is open (local dev).

Run:  python -m cli.app serve --port 8765
"""
from __future__ import annotations
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from .storage import SqliteStorage

API_TOKEN_ENV = "API_TOKEN"
PROJECT_PLACEHOLDER = "_NO_PROJECT_"  # route-safe placeholder for "no project"


def _expected_token() -> str:
    return (os.getenv(API_TOKEN_ENV, "") or "").strip()


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "RakezAPI/1.3"

    # -- helpers --
    @property
    def store(self) -> SqliteStorage:
        return self.server.store  # type: ignore[attr-defined]

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = _expected_token()
        if not expected:
            return True
        got = self.headers.get("Authorization", "")
        return got == f"Bearer {expected}"

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return {}

    def _route(self) -> tuple[str, list[str], dict]:
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        return self.command, parts, parse_qs(parsed.query)

    def log_message(self, *args):  # quieter than default stderr logging
        pass

    # -- verbs --
    def _handle(self):
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        method, parts, query = self._route()
        try:
            if method == "GET" and parts == ["health"]:
                self._send(200, {"ok": True, "app": "Rakez"})
            elif method == "GET" and parts == ["tasks"]:
                self._send(200, {"tasks": self.store.get_todos()})
            elif method == "POST" and parts == ["tasks"]:
                data = self._read_json()
                try:
                    todo = self.store.add_todo(
                        data.get("title", ""),
                        data.get("category", "Deep Work"),
                        priority=data.get("priority", "medium"),
                        estimate=int(data.get("estimate", 1)),
                        project_id=str(data.get("project_id") or ""),
                    )
                except (ValueError, TypeError) as e:
                    self._send(400, {"error": str(e)[:200]})
                    return
                self._send(201, todo)
            elif method == "PUT" and len(parts) == 2 and parts[0] == "tasks":
                try:
                    updated = self.store.update_todo(parts[1], self._read_json())
                except ValueError as e:
                    self._send(400, {"error": str(e)[:200]})
                    return
                if updated is None:
                    self._send(404, {"error": "not found"})
                else:
                    self._send(200, updated)
            elif method == "DELETE" and len(parts) == 2 and parts[0] == "tasks":
                if self.store.delete_todo(parts[1]):
                    self._send(200, {"deleted": True})
                else:
                    self._send(404, {"error": "not found"})
            elif method == "GET" and parts == ["projects"]:
                self._send(200, {"projects": self.store.get_projects()})
            elif method == "POST" and parts == ["projects"]:
                data = self._read_json()
                try:
                    self.store.create_project(data.get("name", ""))
                except ValueError as e:
                    self._send(400, {"error": str(e)[:200]})
                    return
                self._send(201, {"created": True})
            elif method == "DELETE" and len(parts) == 2 and parts[0] == "projects":
                p = (self.store.get_project(parts[1])
                     or self.store.get_project_by_name(parts[1]))
                if p is None:
                    self._send(404, {"error": "not found"})
                elif self.store.delete_project(p["id"]):
                    self._send(200, {"deleted": True})
                else:
                    self._send(404, {"error": "not found"})
            elif method == "GET" and len(parts) == 3 and parts[0] == "projects" \
                    and parts[2] == "tasks":
                target = None
                if parts[1] != PROJECT_PLACEHOLDER:
                    p = (self.store.get_project(parts[1])
                         or self.store.get_project_by_name(parts[1]))
                    target = p["id"] if p else None
                if target:
                    todos = self.store.get_project_todos(target)
                else:
                    todos = [t for t in self.store.get_todos() if not t.get("project_id")]
                self._send(200, {"tasks": todos})
            elif method == "GET" and parts == ["sessions"]:
                self._send(200, {"sessions": self.store.get_sessions()})
            elif method == "POST" and parts == ["sessions"]:
                data = self._read_json()
                if not (data.get("task") or "").strip():
                    self._send(400, {"error": "task is required"})
                    return
                session = {
                    "task": data["task"].strip(),
                    "category": data.get("category", "Deep Work"),
                    "duration_min": int(data.get("duration_min", 25)),
                    "kind": data.get("kind", "focus"),
                }
                self.store.log_session(session)
                self._send(201, session)
            elif method == "GET" and parts == ["stats"]:
                try:
                    days = int((query.get("days") or ["7"])[0])
                except ValueError:
                    days = 7
                self._send(200, self.store.stats(days=days))
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # never leak a traceback as HTML
            self._send(500, {"error": str(e)[:200]})

    do_GET = do_POST = do_PUT = do_DELETE = _handle


def run_server(port: int = 8765, data_dir=None, block: bool = True):
    """Start the API server. Returns (server, thread) when block=False."""
    store = SqliteStorage(data_dir=data_dir) if data_dir else SqliteStorage()
    server = ThreadingHTTPServer(("127.0.0.1", port), ApiHandler)
    server.store = store  # type: ignore[attr-defined]
    if block:
        server.serve_forever()
        return server, None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
