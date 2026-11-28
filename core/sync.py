"""Two-way task sync: Rakez ⇄ Google Tasks / Joplin / Notion.

The storage layer emits ``created`` / ``updated`` / ``completed`` /
``reopened`` / ``deleted`` events; this hub forwards them to every configured
integration on a background worker so the UI and the local HTTP API never
block on the network. :meth:`IntegrationHub.pull` reads the remote state back
so a task ticked in Google Tasks, Joplin or Notion is completed in Rakez too
(and then fans out to the remaining services).

Rules:
  * A task is pushed to Google Tasks only after Google is authorized.
  * Joplin is used only when a token is configured (same as before).
  * Notion is used only when the token + database ID are set.
  * External ids are stored on the task row, so later updates/completions
    touch the same remote item instead of creating duplicates.
  * Everything is best-effort: failures are collected, never raised.
"""
from __future__ import annotations
import queue
import re
import threading
import time
from datetime import datetime, timedelta


def _norm_title(title) -> str:
    """Loose title key for matching a remote item with a local task."""
    return re.sub(r"\s+", " ", str(title or "").strip()).casefold()


def _recent(when, days: int = 14) -> bool:
    """True when a remote timestamp falls inside the recency window.

    Used to keep a title-only match from completing a brand-new local task
    just because an old remote item happens to share its title.
    """
    text = str(when or "").strip()
    if not text:
        return False
    if text.isdigit():
        try:
            return time.time() - float(text) / 1000.0 <= days * 86400
        except ValueError:
            return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is not None:
        now = datetime.now(parsed.tzinfo)
    else:
        now = datetime.now()
    return now - parsed <= timedelta(days=days)


class IntegrationHub:
    def __init__(self, storage, joplin=None, google=None, notion=None,
                 enabled=None, notify_done=None, project_lookup=None,
                 joplin_folder: str = "Projects/Lifebot/Tasks",
                 joplin_tags: str = "task,lifebot"):
        self.storage = storage
        self.joplin = joplin
        self.google = google
        self.notion = notion
        self.enabled = enabled            # callable → bool (auto_sync setting)
        self.notify_done = notify_done    # callable(title) for Telegram etc.
        self.project_lookup = project_lookup
        self.joplin_folder = joplin_folder
        self.joplin_tags = joplin_tags
        self._queue = None
        self._worker = None
        self._start_lock = threading.Lock()
        self._pull_lock = threading.Lock()
        self.last_errors: list[str] = []

    # --- wiring ---
    def attach(self) -> None:
        """Subscribe to storage events (call once)."""
        self.storage.add_listener(self._on_event)

    def _auto_enabled(self) -> bool:
        if self.enabled is None:
            return True
        try:
            return bool(self.enabled())
        except Exception:
            return True

    def _has_targets(self) -> bool:
        try:
            if self.joplin is not None and self.joplin.available:
                return True
        except Exception:
            pass
        try:
            if self.google is not None and self.google.authorized:
                return True
        except Exception:
            pass
        try:
            if self.notion is not None and self.notion.available:
                return True
        except Exception:
            pass
        return False

    # --- background worker ---
    def _ensure_worker(self) -> None:
        with self._start_lock:
            if self._queue is not None:
                return
            self._queue = queue.Queue()
            self._worker = threading.Thread(
                target=self._run, name="rakez-sync", daemon=True)
            self._worker.start()

    def _run(self) -> None:
        while True:
            event, todo = self._queue.get()
            try:
                self.process(event, todo)
            except Exception as e:  # pragma: no cover - defensive
                self.last_errors.append(str(e)[:160])
            finally:
                self._queue.task_done()

    def _on_event(self, event: str, todo: dict | None) -> None:
        if not todo:
            return
        if event == "completed" and self.notify_done is not None:
            try:
                self.notify_done((todo.get("title") or "").strip())
            except Exception:
                pass
        if not self._auto_enabled() or not self._has_targets():
            return
        self._ensure_worker()
        self._queue.put((event, dict(todo)))

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until queued sync work finishes (used by tests)."""
        end = time.time() + timeout
        while time.time() < end:
            q = self._queue
            if q is None or q.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

    # --- helpers ---
    def _project_name(self, todo: dict) -> str:
        pid = (todo.get("project_id") or "").strip()
        if not pid or self.project_lookup is None:
            return ""
        try:
            return str(self.project_lookup(pid) or "")
        except Exception:
            return ""

    @staticmethod
    def _notes(todo: dict, project: str = "") -> str:
        lines = [f"Category: {todo.get('category', '')}",
                 f"Priority: {todo.get('priority', '')}"]
        if project:
            lines.append(f"Project: {project}")
        return "\n".join(lines)

    def _error(self, service: str, detail: str) -> None:
        msg = f"{service}: {detail}".strip()
        if msg and msg not in self.last_errors:
            self.last_errors.append(msg)
        if len(self.last_errors) > 40:
            del self.last_errors[:-40]

    # --- dispatch ---
    def process(self, event: str, todo: dict) -> dict:
        out = {"event": event, "title": todo.get("title", ""), "actions": [], "errors": []}
        if not self._auto_enabled():
            return out
        project = self._project_name(todo)
        if event in ("created", "updated"):
            self._push_joplin(todo, project, out)
            self._push_google(todo, project, out)
            self._push_notion(todo, project, out)
        elif event in ("completed", "reopened"):
            done = event == "completed"
            self._set_joplin_done(todo, done, out)
            self._set_google_done(todo, done, out)
            self._set_notion_done(todo, done, project, out)
        elif event == "deleted":
            self._delete_joplin(todo, out)
            self._delete_google(todo, out)
            self._delete_notion(todo, out)
        return out

    # --- Joplin ---
    def _push_joplin(self, todo: dict, project: str, out: dict) -> None:
        c = self.joplin
        if c is None or not getattr(c, "available", False):
            return
        notes = self._notes(todo, project)
        note_id = (todo.get("joplin_id") or "").strip()
        if not note_id:
            try:
                note_id = c.find_todo_id(todo.get("title", ""), self.joplin_folder)
            except Exception:
                note_id = ""
            if note_id:
                self.storage.set_sync_ids(todo["id"], joplin_id=note_id)
        if note_id:
            if c.update_note(note_id, title=todo.get("title", ""), body=notes):
                out["actions"].append("joplin:updated")
                return
            if "404" not in (c.last_error or "").lower():
                self._error("Joplin", c.last_error)
                out["errors"].append("joplin")
                return
            # the note was deleted in Joplin → forget the id and create it again
            self.storage.set_sync_ids(todo["id"], joplin_id="")
            note_id = ""
        created = c.create_todo(title=todo.get("title", ""), body=notes,
                                folder_name=self.joplin_folder, tags=self.joplin_tags)
        if isinstance(created, dict) and created.get("id"):
            self.storage.set_sync_ids(todo["id"], joplin_id=created["id"])
            out["actions"].append("joplin:created")
        else:
            self._error("Joplin", c.last_error or "could not create todo")
            out["errors"].append("joplin")

    def _set_joplin_done(self, todo: dict, done: bool, out: dict) -> None:
        c = self.joplin
        if c is None or not getattr(c, "available", False):
            return
        note_id = (todo.get("joplin_id") or "").strip()
        if not note_id:
            try:
                note_id = c.find_todo_id(todo.get("title", ""), self.joplin_folder)
            except Exception:
                note_id = ""
            if note_id:
                self.storage.set_sync_ids(todo["id"], joplin_id=note_id)
        if not note_id:
            return
        if c.set_completed(note_id, done):
            out["actions"].append("joplin:completed" if done else "joplin:reopened")
            return
        if "404" in (c.last_error or "").lower():
            # stale id: the note was deleted in Joplin → recreate it, then tick it
            self.storage.set_sync_ids(todo["id"], joplin_id="")
            self._push_joplin(todo, self._project_name(todo), out)
            new_id = (self.storage.get_todo(todo["id"]) or {}).get("joplin_id", "")
            if new_id:
                c.set_completed(new_id, done)
            return
        self._error("Joplin", c.last_error)
        out["errors"].append("joplin")

    def _delete_joplin(self, todo: dict, out: dict) -> None:
        c = self.joplin
        if c is None or not getattr(c, "available", False):
            return
        note_id = (todo.get("joplin_id") or "").strip()
        if not note_id:
            try:
                note_id = c.find_todo_id(todo.get("title", ""), self.joplin_folder)
            except Exception:
                note_id = ""
        if note_id and c.delete_note(note_id):
            out["actions"].append("joplin:deleted")
        elif note_id:
            self._error("Joplin", c.last_error)
            out["errors"].append("joplin")

    # --- Google Tasks ---
    def _push_google(self, todo: dict, project: str, out: dict) -> None:
        g = self.google
        if g is None or not getattr(g, "authorized", False):
            return
        notes = self._notes(todo, project)
        task_id = (todo.get("google_id") or "").strip()
        if not task_id:
            try:
                task_id = g.find_task_id(todo.get("title", ""))
            except Exception:
                task_id = ""
            if task_id:
                self.storage.set_sync_ids(todo["id"], google_id=task_id)
        if task_id:
            if g.update_task(task_id, title=todo.get("title", ""), notes=notes):
                out["actions"].append("google:updated")
                return
            if "404" not in (g.last_error or "").lower():
                self._error("Google", g.last_error)
                out["errors"].append("google")
                return
            # the task was deleted in Google Tasks → forget the id and recreate
            self.storage.set_sync_ids(todo["id"], google_id="")
            task_id = ""
        res = g.push_task(todo.get("title", ""), notes,
                          completed=bool(todo.get("completed")))
        if isinstance(res, dict) and res.get("id"):
            self.storage.set_sync_ids(todo["id"], google_id=res["id"])
            out["actions"].append("google:created")
        else:
            self._error("Google", g.last_error or "could not create task")
            out["errors"].append("google")

    def _set_google_done(self, todo: dict, done: bool, out: dict) -> None:
        g = self.google
        if g is None or not getattr(g, "authorized", False):
            return
        task_id = (todo.get("google_id") or "").strip()
        if not task_id:
            try:
                task_id = g.find_task_id(todo.get("title", ""))
            except Exception:
                task_id = ""
            if task_id:
                self.storage.set_sync_ids(todo["id"], google_id=task_id)
        if not task_id:
            self._push_google(todo, self._project_name(todo), out)
            task_id = ""
            try:
                task_id = (self.storage.get_todo(todo["id"]) or {}).get("google_id", "")
            except Exception:
                task_id = ""
        if not task_id:
            return
        if g.set_task_status(task_id, done):
            out["actions"].append("google:completed" if done else "google:reopened")
            return
        if "404" in (g.last_error or "").lower():
            # stale id: the task was deleted in Google Tasks → create it again
            self.storage.set_sync_ids(todo["id"], google_id="")
            self._push_google(todo, self._project_name(todo), out)
            return
        self._error("Google", g.last_error)
        out["errors"].append("google")

    def _delete_google(self, todo: dict, out: dict) -> None:
        g = self.google
        if g is None or not getattr(g, "authorized", False):
            return
        task_id = (todo.get("google_id") or "").strip()
        if not task_id:
            try:
                task_id = g.find_task_id(todo.get("title", ""))
            except Exception:
                task_id = ""
        if task_id and g.delete_task(task_id):
            out["actions"].append("google:deleted")
        elif task_id:
            self._error("Google", g.last_error)
            out["errors"].append("google")

    # --- Notion ---
    def _push_notion(self, todo: dict, project: str, out: dict) -> None:
        c = self.notion
        if c is None or not getattr(c, "available", False):
            return
        page_id = c.upsert_task(todo, project)
        if page_id:
            if (todo.get("notion_id") or "") != page_id:
                self.storage.set_sync_ids(todo["id"], notion_id=page_id)
            out["actions"].append("notion:synced")
        else:
            self._error("Notion", c.friendly_error())
            out["errors"].append("notion")

    def _set_notion_done(self, todo: dict, done: bool, project: str, out: dict) -> None:
        c = self.notion
        if c is None or not getattr(c, "available", False):
            return
        page_id = (todo.get("notion_id") or "").strip()
        if not page_id:
            page_id = c.upsert_task(todo, project)
            if page_id:
                self.storage.set_sync_ids(todo["id"], notion_id=page_id)
        if not page_id:
            self._error("Notion", c.friendly_error())
            out["errors"].append("notion")
            return
        if c.set_done(page_id, done, todo.get("completed_at", "")):
            out["actions"].append("notion:completed" if done else "notion:reopened")
        else:
            self._error("Notion", c.friendly_error())
            out["errors"].append("notion")

    def _delete_notion(self, todo: dict, out: dict) -> None:
        c = self.notion
        if c is None or not getattr(c, "available", False):
            return
        page_id = (todo.get("notion_id") or "").strip()
        if page_id and c.archive(page_id):
            out["actions"].append("notion:archived")
        elif page_id:
            self._error("Notion", c.friendly_error())
            out["errors"].append("notion")

    # --- pull: remote completions → local ---
    def pull(self) -> dict:
        """Mark local tasks done when Google/Joplin/Notion says they are done.

        Runs at most once at a time. The resulting storage event still fans the
        completion out to the other services, so every integration converges.
        Never raises.
        """
        out = {"completed": 0, "google": 0, "joplin": 0, "notion": 0,
               "errors": []}
        if not self._pull_lock.acquire(blocking=False):
            return out
        try:
            todos = self.storage.get_todos()
            by_id = {t["id"]: t for t in todos}
            by_title: dict[str, dict] = {}
            for t in todos:
                if not t.get("completed"):
                    by_title.setdefault(_norm_title(t.get("title")), t)

            def apply(service: str, field: str, remote_id: str, title: str,
                      local_id: str = "", when: str = "") -> int:
                todo = by_id.get(local_id) if local_id else None
                if todo is None and remote_id:
                    todo = next((t for t in todos
                                 if (t.get(field) or "") == remote_id), None)
                if todo is None and title and (not when or _recent(when)):
                    candidate = by_title.get(_norm_title(title))
                    # never steal a title match that already belongs to a
                    # different remote item
                    if candidate is not None and remote_id:
                        current = (candidate.get(field) or "").strip()
                        if current and current != remote_id:
                            candidate = None
                    todo = candidate
                if todo is None or todo.get("completed"):
                    return 0
                if remote_id and (todo.get(field) or "") != remote_id:
                    self.storage.set_sync_ids(todo["id"], **{field: remote_id})
                    todo[field] = remote_id
                ok = self.storage.set_completed(todo["id"], True)
                if not ok:
                    return 0
                todo["completed"] = True
                by_title.pop(_norm_title(todo.get("title")), None)
                return 1

            # --- Google Tasks ---
            g = self.google
            if (g is not None and getattr(g, "authorized", False)
                    and hasattr(g, "fetch_tasks")):
                try:
                    for item in g.fetch_tasks(include_completed=True):
                        if item.get("completed"):
                            out["google"] += apply(
                                "google", "google_id", item.get("id", ""),
                                item.get("title", ""),
                                when=item.get("completed_at") or item.get("updated", ""))
                except Exception as e:
                    out["errors"].append(f"Google pull: {str(e)[:120]}")

            # --- Joplin ---
            j = self.joplin
            if (j is not None and getattr(j, "available", False)
                    and hasattr(j, "pull_todos")):
                try:
                    for item in j.pull_todos(folder_name=self.joplin_folder):
                        if item.get("completed"):
                            out["joplin"] += apply(
                                "joplin", "joplin_id", item.get("joplin_id", ""),
                                item.get("title", ""),
                                when=item.get("updated", ""))
                except Exception as e:
                    out["errors"].append(f"Joplin pull: {str(e)[:120]}")

            # --- Notion ---
            n = self.notion
            if (n is not None and getattr(n, "available", False)
                    and hasattr(n, "fetch_tasks")):
                try:
                    for item in n.fetch_tasks():
                        if item.get("completed"):
                            out["notion"] += apply(
                                "notion", "notion_id", item.get("notion_id", ""),
                                item.get("title", ""), item.get("rakez_id", ""),
                                when=item.get("updated", ""))
                except Exception as e:
                    out["errors"].append(f"Notion pull: {str(e)[:120]}")

            out["completed"] = out["google"] + out["joplin"] + out["notion"]
        except Exception as e:  # pragma: no cover - defensive
            out["errors"].append(str(e)[:160])
        finally:
            self._pull_lock.release()
        return out

    # --- manual full sync ---
    def sync_all(self, pull: bool = True) -> dict:
        """Push every task to every configured service (Sync now button).

        With ``pull=True`` (default) completions made in Google Tasks, Joplin
        or Notion are applied locally first, then the resulting state is
        pushed everywhere.
        """
        out = {"joplin": {}, "google": {}, "notion": {}, "pulled": 0,
               "errors": []}
        if pull:
            pulled = self.pull()
            out["pulled"] = pulled.get("completed", 0)
            out["errors"].extend(pulled.get("errors") or [])
        todos = self.storage.get_todos()
        names = {}
        for t in todos:
            pid = t.get("project_id") or ""
            if pid and pid not in names:
                names[pid] = self._project_name(t)
        if self.joplin is not None and getattr(self.joplin, "available", False):
            res = self.joplin.sync_open_todos(
                todos, folder_name=self.joplin_folder, tags=self.joplin_tags)
            done = 0
            for t in todos:
                if t.get("completed"):
                    note_id = (t.get("joplin_id") or "").strip() or \
                        self.joplin.find_todo_id(t.get("title", ""), self.joplin_folder)
                    if note_id and self.joplin.set_completed(note_id, True):
                        self.storage.set_sync_ids(t["id"], joplin_id=note_id)
                        done += 1
            res = dict(res or {})
            res["completed"] = done
            out["joplin"] = res
            if res.get("error"):
                out["errors"].append(f"Joplin: {res['error']}")
        if self.google is not None and getattr(self.google, "authorized", False):
            pushed, failed = 0, 0
            for t in todos:
                fresh = dict(t)
                before = (t.get("google_id") or "").strip()
                self._push_google(fresh, names.get(t.get("project_id", ""), ""), {"actions": [], "errors": []})
                after = (self.storage.get_todo(t["id"]) or {}).get("google_id", "")
                if after:
                    pushed += 1
                    if t.get("completed"):
                        self.google.set_task_status(after, True)
                elif not before:
                    failed += 1
            out["google"] = {"pushed": pushed, "failed": failed}
            if failed:
                out["errors"].append(f"Google: {self.google.last_error or 'push failed'}")
        if self.notion is not None and getattr(self.notion, "available", False):
            out["notion"] = self.notion.sync_tasks(todos, names)
            if out["notion"].get("error"):
                out["errors"].append(f"Notion: {out['notion']['error']}")
        if not out["joplin"] and not out["google"] and not out["notion"]:
            out["errors"].append("No integrations configured yet.")
        return out
