"""Joplin REST integration (graceful offline fallback)."""
from __future__ import annotations
import os
from datetime import datetime

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


def end_of_today_ms() -> int:
    """Due-date default: today 23:59 local, as ms timestamp (Joplin todo_due)."""
    return int(datetime.now().replace(hour=23, minute=59, second=0, microsecond=0).timestamp() * 1000)


#: Single source of truth for the target notebook (config.yaml may override).
DEFAULT_FOLDER = "Projects/Lifebot/Tasks"


class JoplinClient:
    def __init__(self, base_url: str = "http://127.0.0.1:41184", token: str = ""):
        self.base_url = (base_url or os.getenv("JOPLIN_BASE_URL", "http://127.0.0.1:41184")).rstrip("/")
        self.token = token or os.getenv("JOPLIN_TOKEN", "")
        self.last_error = ""

    @property
    def available(self) -> bool:
        return bool(requests and self.token and self.token != "YOUR_JOPLIN_TOKEN")

    TIMEOUT = 8
    TIMEOUT_PING = 3

    def _candidate_urls(self, path: str) -> list[str]:
        """localhost on Windows may resolve to ::1 while Joplin listens on
        IPv4 (or vice versa) → hang/timeout. Try both automatically."""
        base = self.base_url
        urls = [f"{base}{path}"]
        if "localhost" in base:
            urls.append(f"{base.replace('localhost', '127.0.0.1')}{path}")
        elif "127.0.0.1" in base:
            urls.append(f"{base.replace('127.0.0.1', 'localhost')}{path}")
        return urls

    def _request(self, method: str, path: str, data: dict | None = None,
                 timeout: int | None = None, **params):
        # POST/DELETE are NOT retried blindly: a timed-out POST may already
        # have created the note server-side (retry = duplicate); a DELETE
        # on retry may 404. GET/PUT are idempotent → safe to retry.
        attempts = 2 if method in ("GET", "PUT") else 1
        if not self.available:
            self.last_error = "not configured"
            return None
        timeout = timeout or self.TIMEOUT
        query = dict(params)
        query["token"] = self.token
        r = None
        for url in self._candidate_urls(path):
            for _ in range(attempts):
                try:
                    if method == "GET":
                        r = requests.get(url, params=query, timeout=timeout)
                    elif method == "PUT":
                        r = requests.put(url, params=query, json=data, timeout=timeout)
                    elif method == "DELETE":
                        r = requests.delete(url, params=query, timeout=timeout)
                    else:
                        r = requests.post(url, params=query, json=data, timeout=timeout)
                    r.raise_for_status()
                    self.last_error = ""
                    try:
                        return r.json()
                    except Exception:
                        return r.text  # e.g. /ping returns plain text
                except Exception as e:
                    try:
                        self.last_error = f"{r.status_code} {r.text[:200]}"  # type: ignore
                    except Exception:
                        self.last_error = str(e)[:200]
        return None

    def friendly_error(self) -> str:
        """Short actionable hint for the GUI status label."""
        e = self.last_error or "unknown error"
        if "timed out" in e or "Timeout" in e:
            return "Joplin busy (syncing?) — wait a few seconds and retry"
        if "refused" in e or "Max retries" in e or "Failed to establish" in e:
            return "Joplin Desktop closed? Open it + enable Web Clipper (:41184)"
        if "403" in e:
            return "Wrong JOPLIN_TOKEN — copy it again from Web Clipper settings"
        return e[:120]

    def _get(self, path: str, timeout: int | None = None, **params):
        return self._request("GET", path, None, timeout=timeout, **params)

    def _post(self, path: str, data: dict):
        return self._request("POST", path, data)

    def _put(self, path: str, data: dict):
        return self._request("PUT", path, data)

    def _get_all(self, path: str, **params) -> list:
        """Fetch all pages (Joplin paginates with limit/page + has_more)."""
        out: list = []
        page = 1
        while page <= 50:  # safety cap
            data = self._get(path, page=page, **params)
            if isinstance(data, dict):
                out.extend(data.get("items", []))
                if not data.get("has_more"):
                    break
            elif isinstance(data, list):
                out.extend(data)
                break
            else:
                break
            page += 1
        return out

    def list_folders(self) -> list:
        return [f for f in self._get_all("/folders", limit=100) if isinstance(f, dict)]

    def _find_match(self, folders: list, title: str, parent_id: str):
        for f in folders:
            if (isinstance(f, dict) and f.get("title") == title
                    and (f.get("parent_id") or "") == parent_id):
                return f
        return None

    def _has_ancestor_chain(self, folders: list, folder: dict, chain: list[str]) -> bool:
        """Check folder sits under notebooks named chain[0..n] (root-first)."""
        by_id = {f.get("id"): f for f in folders if isinstance(f, dict)}
        node, i = folder, len(chain) - 1
        while node is not None and i >= 0:
            if node.get("title") != chain[i]:
                return False
            i -= 1
            pid = node.get("parent_id") or ""
            node = by_id.get(pid) if i >= 0 else None
        return i < 0

    def ensure_folder(self, folder_name: str = DEFAULT_FOLDER) -> str | None:
        """Return folder id, creating missing notebooks.

        Supports nested paths like "Lifebot/Tasks". If the exact chain is
        missing but a notebook with the final name already exists elsewhere
        (e.g. Lifebot/Wiki/Tasks), that existing one is reused instead of
        creating a look-alike duplicate.
        """
        parts = [p.strip() for p in str(folder_name).split("/") if p.strip()]
        if not parts:
            parts = [p.strip() for p in DEFAULT_FOLDER.split("/") if p.strip()]
        folders = self.list_folders()
        parent_id = ""
        for depth, part in enumerate(parts):
            match = self._find_match(folders, part, parent_id)
            if match:
                parent_id = match.get("id")
                continue
            # Exact chain missing: reuse an existing same-named notebook —
            # prefer one sitting under the leading chain (e.g. Lifebot that
            # lives under Projects), else a unique title anywhere, instead
            # of creating a look-alike duplicate in the wrong place.
            cands = [f for f in folders
                     if isinstance(f, dict) and f.get("title") == part]
            if depth > 0:
                chained = [f for f in cands
                           if self._has_ancestor_chain(folders, f, parts[:depth])]
                if chained:
                    parent_id = chained[0].get("id")
                    continue
            if len(cands) == 1:
                print(f"[joplin] using existing notebook '{part}' "
                      f"(id={cands[0].get('id', '')[:6]}) instead of creating a new one")
                parent_id = cands[0].get("id")
                continue
            payload = {"title": part}
            if parent_id:
                payload["parent_id"] = parent_id
            created = self._post("/folders", payload)
            if isinstance(created, dict) and created.get("id"):
                parent_id = created["id"]
                folders.append(created)
                continue
            # creation failed (offline?) — re-list in case it actually
            # succeeded server-side, else stop
            folders = self.list_folders()
            retry = self._find_match(folders, part, parent_id)
            if retry:
                parent_id = retry.get("id")
            else:
                break
        return parent_id or None

    def get_notes_in_folder(self, folder_id: str) -> list:
        """List notes/todos inside a notebook (all pages).

        Requests explicit fields — Joplin returns only a small subset
        (id/title/body/...) by default, WITHOUT is_todo/todo_due, so
        todos would be invisible to pull/sync without this.
        """
        return self._get_all(
            f"/folders/{folder_id}/notes",
            limit=100,
            fields="id,parent_id,title,body,is_todo,todo_due,todo_completed",
        )

    # --- tags ---
    def _ensure_tag(self, title: str) -> str | None:
        items = self._get_all("/tags", limit=100)
        for t in items:
            if isinstance(t, dict) and t.get("title", "").lower() == title.lower():
                return t.get("id")
        created = self._post("/tags", {"title": title})
        return created.get("id") if isinstance(created, dict) else None

    def add_tags(self, note_id: str, tags: str) -> bool:
        """Attach tags (comma-separated) to an existing note."""
        ok = True
        for name in [t.strip() for t in (tags or "").split(",") if t.strip()]:
            tag_id = self._ensure_tag(name)
            if not tag_id:
                ok = False
                continue
            res = self._post(f"/tags/{tag_id}/notes", {"id": note_id})
            if not res:
                ok = False
        return ok

    # --- todos ---
    def _set_due(self, note_id: str, due_ms: int):
        # Two-step: some Joplin versions ignore todo_due at creation (issue #6862),
        # so set it with PUT after creating.
        return self._put(f"/notes/{note_id}", {"todo_due": due_ms})

    def _find_note(self, folder_id: str, title: str) -> dict | None:
        for n in self.get_notes_in_folder(folder_id):
            if isinstance(n, dict) and (n.get("title") or "").strip() == title:
                return n
        return None

    def _complete_note(self, note: dict, tags: str, due_ms: int) -> bool:
        """Ensure due date + required tags on a note. True if changed."""
        touched = False
        try:
            required = {t.strip().lower() for t in (tags or "").split(",") if t.strip()}
            if not note.get("todo_due"):
                if self._set_due(note["id"], due_ms):
                    touched = True
            note_tags = self._get(f"/notes/{note['id']}/tags") or {}
            have = {x.get("title", "").lower() for x in note_tags.get("items", [])
                    if isinstance(x, dict)}
            if required and not (required & have):
                if self.add_tags(note["id"], tags):
                    touched = True
        except Exception:
            pass
        return touched

    def _create_note_idempotent(self, folder_id: str, title: str, body: str,
                                tags: str, due_ms: int) -> dict | None:
        """Create a todo exactly once.

        If the POST fails (e.g. timeout) the note may still have been
        created server-side — so verify by title before giving up instead
        of blindly re-posting (which produced duplicates).
        """
        res = self._post("/notes", {
            "title": title, "body": body, "parent_id": folder_id,
            "is_todo": 1, "todo_completed": 0,
        })
        if isinstance(res, dict) and res.get("id"):
            # tags are (re)applied via API — some Joplin versions ignore the
            # creation-time "tags" field, so enforce them explicitly.
            self._complete_note(res, tags, due_ms)
            return res
        found = self._find_note(folder_id, title)
        if found:
            self._complete_note(found, tags, due_ms)
            return found
        return None

    def create_todo(self, title: str, body: str = "", folder_name: str = DEFAULT_FOLDER,
                    tags: str = "task,lifebot", due_ms: int | None = None):
        """Create a real Joplin to-do visible in notebook + All-Tasks board.

        Sets is_todo=1, attaches tags (for tag-filtered boards) and a due
        date defaulting to end of today (for due-date boards like
        "All Tasks Due Date" + Timeline view).
        Never raises — returns the created note dict or None on failure.
        """
        try:
            folder_id = self.ensure_folder(folder_name)
            if not folder_id:
                self.last_error = self.last_error or "no folder available"
                return None
            return self._create_note_idempotent(
                folder_id, title, body, tags, due_ms or end_of_today_ms())
        except Exception as e:
            self.last_error = str(e)[:200]
            return None

    def sync_open_todos(self, todos: list[dict], folder_name: str = DEFAULT_FOLDER,
                        tags: str = "task,lifebot") -> dict:
        """Push all open Lifebot tasks to Joplin.

        - Creates missing todos (with tags + due date).
        - Backfills existing ones lacking tags or due date.
        Returns {"created": int, "updated": int, "skipped": int, "error": str}.
        Never raises.
        """
        try:
            folder_id = self.ensure_folder(folder_name)
            if not folder_id:
                return {"created": 0, "updated": 0, "skipped": 0,
                        "error": self.last_error or "no folder"}
            by_title = {}
            for n in self.get_notes_in_folder(folder_id):
                if isinstance(n, dict) and (n.get("title") or "").strip():
                    by_title[n["title"].strip()] = n
            created, updated, skipped = 0, 0, 0
            due = end_of_today_ms()
            for t in todos:
                if t.get("completed"):
                    continue
                title = (t.get("title") or "").strip()
                if not title:
                    continue
                if title not in by_title:
                    body = f"Category: {t.get('category', '')}\nPriority: {t.get('priority', '')}"
                    if self._create_note_idempotent(folder_id, title, body, tags, due):
                        created += 1
                    continue
                # backfill existing: tags + due date if missing
                if self._complete_note(by_title[title], tags, due):
                    updated += 1
                else:
                    skipped += 1
            return {"created": created, "updated": updated, "skipped": skipped,
                    "error": self.last_error}
        except Exception as e:
            return {"created": 0, "updated": 0, "skipped": 0, "error": str(e)[:200]}

    def find_duplicates(self, folder_name: str = DEFAULT_FOLDER) -> dict:
        """Group notes with identical titles. Returns {title: [notes]} (len>1)."""
        folder_id = self.ensure_folder(folder_name)
        if not folder_id:
            return {}
        items = self._get_all(f"/folders/{folder_id}/notes", limit=200,
                              fields="id,title,updated_time,is_todo")
        groups: dict[str, list] = {}
        for n in items:
            if isinstance(n, dict) and (n.get("title") or "").strip():
                groups.setdefault(n["title"].strip(), []).append(n)
        return {t: ns for t, ns in groups.items() if len(ns) > 1}

    def dedupe(self, folder_name: str = DEFAULT_FOLDER,
               dry_run: bool = True) -> dict:
        """Delete duplicate titles keeping the newest (by updated_time).

        Deleted notes go to Joplin Trash (restorable). dry_run only reports.
        Never raises. Returns {"groups": int, "deleted": [titles], "error": str}.
        """
        try:
            groups = self.find_duplicates(folder_name)
            deleted = []
            if not dry_run:
                for title, notes in groups.items():
                    ordered = sorted(notes, key=lambda n: n.get("updated_time") or 0)
                    for dup in ordered[:-1]:  # keep newest
                        if self._request("DELETE", f"/notes/{dup['id']}") is not None:
                            deleted.append(title)
            return {"groups": len(groups),
                    "dup_notes": sum(len(v) for v in groups.values()),
                    "deleted": deleted, "dry_run": dry_run,
                    "error": self.last_error}
        except Exception as e:
            return {"groups": 0, "dup_notes": 0, "deleted": [],
                    "dry_run": dry_run, "error": str(e)[:200]}

    def list_todos(self, limit: int = 50):
        """Return Joplin to-dos or None when offline/unconfigured."""
        data = self._get("/search", query="type:todo", limit=limit)
        if not data:
            return None
        return data.get("items", data)

    def pull_todos(self, folder_name: str = DEFAULT_FOLDER) -> list[dict]:
        """Fetch todos from a Joplin notebook as Lifebot-style dicts.

        Parses 'Category:'/'Priority:' lines from the body. Never raises —
        returns [] on failure.
        """
        try:
            folder_id = self.ensure_folder(folder_name)
            if not folder_id:
                return []
            out = []
            for n in self.get_notes_in_folder(folder_id):
                if not isinstance(n, dict):
                    continue
                if not n.get("is_todo"):
                    continue
                body = n.get("body", "") or ""
                cat, pri = "Deep Work", "medium"
                for line in body.splitlines():
                    low = line.strip().lower()
                    if low.startswith("category:"):
                        cat = line.split(":", 1)[1].strip() or cat
                    elif low.startswith("priority:"):
                        pri = line.split(":", 1)[1].strip().lower() or pri
                if pri not in ("low", "medium", "high"):
                    pri = "medium"
                out.append({
                    "title": (n.get("title") or "").strip(),
                    "category": cat,
                    "priority": pri,
                    "completed": bool(n.get("todo_completed")),
                    "joplin_id": n.get("id"),
                })
            return [t for t in out if t["title"]]
        except Exception as e:
            self.last_error = str(e)[:200]
            return []

    def status(self) -> str:
        if not requests:
            return "requests not installed"
        if not self.token or self.token == "YOUR_JOPLIN_TOKEN":
            return "not configured (set JOPLIN_TOKEN)"
        ping = self._get("/ping", timeout=self.TIMEOUT_PING)
        return "connected" if ping else "unreachable (is Joplin clipper running on :41184?)"
