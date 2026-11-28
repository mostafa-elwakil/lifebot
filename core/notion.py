"""Notion push-sync for Rakez tasks (REST only, no extra dependency).

Setup (one time):
  1. https://www.notion.so/my-integrations → New integration → copy the
     "Internal Integration Secret".
  2. Create a database in Notion (a table is fine), open it → ⋯ → Connections
     → add your integration (otherwise the API returns 404).
  3. Paste the token under Settings → API and the database ID (the 32-char
     part of the database URL) under Settings → Integrations → Notion.

Rakez adds the properties it needs to that database on the first sync:
  Rakez ID (rich text), Done (checkbox), Category (select), Priority (select),
  Project (rich text), Completed at (date).
The page title is stored in the database's existing title property.

Everything here never raises: failures land in ``last_error``.
"""
from __future__ import annotations
import os

try:
    import requests
except Exception:  # pragma: no cover - optional import
    requests = None  # type: ignore


API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

PROP_ID = "Rakez ID"
PROP_DONE = "Done"
PROP_CATEGORY = "Category"
PROP_PRIORITY = "Priority"
PROP_PROJECT = "Project"
PROP_COMPLETED = "Completed at"

TEXT_LIMIT = 2000


def _rich_text(value: str) -> list[dict]:
    value = (value or "").strip()
    if not value:
        return []
    return [{"type": "text", "text": {"content": value[:TEXT_LIMIT]}}]


def _select(value: str, fallback: str) -> dict:
    name = (value or "").strip() or fallback
    return {"select": {"name": name[:100]}}


class NotionClient:
    TIMEOUT = 15

    def __init__(self, token: str = "", database_id: str = ""):
        self.token = (token or os.getenv("NOTION_TOKEN", "")).strip()
        self.database_id = (database_id or os.getenv("NOTION_DATABASE_ID", "")).strip()
        self.last_error = ""
        self._title_prop = ""
        self._schema_key = None

    # --- state ---
    @property
    def available(self) -> bool:
        return bool(requests and self.token and self.database_id)

    def status(self) -> str:
        if not requests:
            return "requests not installed"
        if not self.token:
            return "needs integration token (Settings → API)"
        if not self.database_id:
            return "needs database ID (Settings → Integrations)"
        return "configured (press Test)"

    def friendly_error(self) -> str:
        e = (self.last_error or "unknown error").strip()
        low = e.lower()
        if "401" in low or "unauthorized" in low:
            return ("Notion rejected the token (401). Copy the Internal "
                    "Integration Secret again from notion.so/my-integrations.")
        if "404" in low or "object_not_found" in low:
            return ("Notion cannot see that database (404). Open the database "
                    "in Notion → ⋯ → Connections → add your integration, and "
                    "check the database ID.")
        if "400" in low or "validation_error" in low:
            return f"Notion rejected the data: {e[:160]}"
        if "timed out" in low or "timeout" in low:
            return "Notion timed out — try again in a moment."
        return e[:160]

    # --- transport ---
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: dict | None = None):
        if not self.available:
            self.last_error = "not configured"
            return None
        try:
            r = requests.request(method, f"{API_BASE}{path}", headers=self._headers(),
                                 json=payload, timeout=self.TIMEOUT)
            if r.status_code >= 400:
                try:
                    detail = r.json().get("message", r.text[:200])
                except Exception:
                    detail = r.text[:200]
                self.last_error = f"{r.status_code} {detail}"
                return None
            self.last_error = ""
            try:
                return r.json() if r.content else {}
            except Exception:
                return {}
        except Exception as e:
            self.last_error = str(e)[:200]
            return None

    # --- schema ---
    def _title_property(self, properties: dict) -> str:
        for name, spec in (properties or {}).items():
            if isinstance(spec, dict) and spec.get("type") == "title":
                return name
        return "Name"

    def ensure_schema(self) -> bool:
        """Create the properties Rakez needs. Returns True when the DB is ready."""
        if not self.available:
            self.last_error = "not configured"
            return False
        # one GET per database per session (sync_all would otherwise fetch it
        # again for every single task)
        if self._schema_key == (self.token, self.database_id) and self._title_prop:
            return True
        db = self._request("GET", f"/databases/{self.database_id}")
        if not isinstance(db, dict) or not db.get("id"):
            return False
        props = db.get("properties") or {}
        self._title_prop = self._title_property(props)
        wanted = {
            PROP_ID: {"rich_text": {}},
            PROP_DONE: {"checkbox": {}},
            PROP_CATEGORY: {"select": {}},
            PROP_PRIORITY: {"select": {}},
            PROP_PROJECT: {"rich_text": {}},
            PROP_COMPLETED: {"date": {}},
        }
        missing = {name: spec for name, spec in wanted.items() if name not in props}
        if missing:
            res = self._request("PATCH", f"/databases/{self.database_id}",
                                {"properties": missing})
            if res is None:
                return False
        self._schema_key = (self.token, self.database_id)
        return True

    def _page_properties(self, todo: dict, project_name: str = "") -> dict:
        props = {
            self._title_prop or "Name": {"title": _rich_text(todo.get("title", ""))},
            PROP_ID: {"rich_text": _rich_text(todo.get("id", ""))},
            PROP_DONE: {"checkbox": bool(todo.get("completed"))},
            PROP_CATEGORY: _select(todo.get("category", ""), "Deep Work"),
            PROP_PRIORITY: _select(todo.get("priority", ""), "medium"),
            PROP_PROJECT: {"rich_text": _rich_text(project_name)},
        }
        completed_at = (todo.get("completed_at") or "").strip()
        props[PROP_COMPLETED] = {"date": {"start": completed_at} if completed_at else None}
        return props

    # --- pages ---
    def _find_page(self, rakez_id: str) -> str:
        if not rakez_id:
            return ""
        res = self._request("POST", f"/databases/{self.database_id}/query", {
            "filter": {"property": PROP_ID, "rich_text": {"equals": rakez_id}},
            "page_size": 1,
        })
        if not isinstance(res, dict):
            return ""
        results = res.get("results") or []
        return results[0].get("id", "") if results else ""

    def create_task(self, todo: dict, project_name: str = "") -> str:
        res = self._request("POST", "/pages", {
            "parent": {"database_id": self.database_id},
            "properties": self._page_properties(todo, project_name),
        })
        return res.get("id", "") if isinstance(res, dict) else ""

    def update_task(self, page_id: str, todo: dict, project_name: str = "") -> bool:
        res = self._request("PATCH", f"/pages/{page_id}", {
            "properties": self._page_properties(todo, project_name),
        })
        return isinstance(res, dict) and bool(res.get("id"))

    def upsert_task(self, todo: dict, project_name: str = "") -> str:
        """Create or update the page for this task. Returns the page id."""
        if not self.ensure_schema():
            return ""
        page_id = (todo.get("notion_id") or "").strip()
        if page_id and self.update_task(page_id, todo, project_name):
            return page_id
        found = self._find_page(todo.get("id", ""))
        if found:
            self.update_task(found, todo, project_name)
            return found
        return self.create_task(todo, project_name)

    def set_done(self, page_id: str, done: bool, completed_at: str = "") -> bool:
        props = {
            PROP_DONE: {"checkbox": bool(done)},
            PROP_COMPLETED: {"date": {"start": completed_at} if (done and completed_at) else None},
        }
        res = self._request("PATCH", f"/pages/{page_id}", {"properties": props})
        return isinstance(res, dict) and bool(res.get("id"))

    def archive(self, page_id: str) -> bool:
        res = self._request("PATCH", f"/pages/{page_id}", {"archived": True})
        return isinstance(res, dict) and bool(res.get("id"))

    # --- pull (completion states) ---
    @staticmethod
    def _page_text(page: dict, prop_name: str) -> str:
        prop = (page.get("properties") or {}).get(prop_name) or {}
        ptype = prop.get("type")
        if ptype == "title":
            parts = prop.get("title") or []
        elif ptype == "rich_text":
            parts = prop.get("rich_text") or []
        else:
            return ""
        return "".join(p.get("plain_text", "") for p in parts).strip()

    def fetch_tasks(self, max_pages: int = 5) -> list[dict]:
        """Read pages from the database (id, Rakez ID, title, Done).

        Used by the sync hub to pull ticks made in Notion back into Rakez.
        Never raises.
        """
        out: list[dict] = []
        if not self.available:
            return out
        if not self.ensure_schema():
            return out
        cursor = None
        for _ in range(max_pages):
            payload: dict = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            res = self._request("POST", f"/databases/{self.database_id}/query", payload)
            if not isinstance(res, dict):
                break
            for page in res.get("results") or []:
                done_prop = (page.get("properties") or {}).get(PROP_DONE) or {}
                completed = bool(done_prop.get("checkbox")) \
                    if done_prop.get("type") == "checkbox" else False
                out.append({
                    "notion_id": page.get("id", ""),
                    "rakez_id": self._page_text(page, PROP_ID),
                    "title": self._page_text(page, self._title_prop or "Name"),
                    "completed": completed,
                    "updated": page.get("last_edited_time", ""),
                })
            if not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
            if not cursor:
                break
        return out

    # --- bulk ---
    def sync_tasks(self, todos: list[dict], project_names: dict | None = None) -> dict:
        """Push every task to Notion. Returns counts, never raises."""
        out = {"created": 0, "updated": 0, "failed": 0, "error": ""}
        if not self.available:
            out["error"] = "not configured"
            return out
        if not self.ensure_schema():
            out["error"] = self.friendly_error()
            return out
        names = project_names or {}
        for todo in todos:
            before = bool((todo.get("notion_id") or "").strip())
            page_id = self.upsert_task(todo, names.get(todo.get("project_id", ""), ""))
            if page_id:
                if before:
                    out["updated"] += 1
                else:
                    out["created"] += 1
            else:
                out["failed"] += 1
        if out["failed"]:
            out["error"] = self.friendly_error()
        return out

    # --- connection check ---
    def test_connection(self) -> dict:
        """Retrieve the database + create missing properties. Never raises."""
        if not self.available:
            return {"ok": False, "message": self.status()}
        db = self._request("GET", f"/databases/{self.database_id}")
        if not isinstance(db, dict) or not db.get("id"):
            return {"ok": False, "message": self.friendly_error()}
        title = ""
        try:
            parts = db.get("title") or []
            title = "".join(p.get("plain_text", "") for p in parts) or "(untitled)"
        except Exception:
            title = "(untitled)"
        if not self.ensure_schema():
            return {"ok": False, "message": self.friendly_error()}
        return {"ok": True,
                "message": f"connected — database '{title}' is ready"}
