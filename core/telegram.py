"""Telegram bot integration: reports, add tasks, and complete tasks remotely.

Uses the plain Bot API over HTTPS (no extra dependency beyond ``requests``):

* :meth:`TelegramBot.send` — send a message to the configured chat.
* :meth:`TelegramBot.report_text` — "done today" + remaining tasks + projects.
* :meth:`TelegramBot.get_updates` — long polling.
* :meth:`TelegramBot.handle_update` — run a command (``/done``, ``/add``, ...).

The module is import-safe without ``requests`` or a token: ``available`` and
``configured`` simply report ``False`` and every call degrades to a no-op.
"""
from __future__ import annotations

import os
from datetime import datetime

from .i18n import t, tf

try:  # pragma: no cover - exercised through the fallback path only
    import requests
except Exception:
    requests = None  # type: ignore

API_BASE = "https://api.telegram.org"

#: Long-poll seconds requested from Telegram (kept below the HTTP timeout).
POLL_TIMEOUT = 10


class TelegramBot:
    """Small, dependency-light Telegram Bot API client."""

    TIMEOUT = 15

    def __init__(self, token: str = "", chat_id: str = "", storage=None):
        self.token = (token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id or os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
        self.storage = storage
        self.last_error = ""
        self.offset = 0
        self.last_chat_id = ""
        self._base = f"{API_BASE}/bot{self.token}" if self.token else ""

    # ---- status ----
    @property
    def available(self) -> bool:
        """True when a token is present and ``requests`` is importable."""
        return bool(requests and self.token)

    def configure(self, token: str | None = None, chat_id: str | None = None) -> None:
        """Update credentials in place (the polling thread reuses this object)."""
        new_token = (self.token if token is None else token or "").strip()
        if new_token != self.token:
            # a different bot must not inherit the old offset
            self.offset = 0
            self.last_chat_id = ""
        self.token = new_token
        self.chat_id = str(self.chat_id if chat_id is None else chat_id or "").strip()
        self._base = f"{API_BASE}/bot{self.token}" if self.token else ""

    @property
    def configured(self) -> bool:
        """True when we can both talk to Telegram and know the target chat."""
        return bool(self.available and self.chat_id)

    def status(self) -> str:
        if not self.token:
            return t("not configured")
        if not self.chat_id:
            return t("chat ID missing")
        return t("ready")

    # ---- low level ----
    def _call(self, method: str, request_timeout: int | None = None, **params):
        """POST one Bot API method; returns ``result`` or ``None``."""
        if not self.available:
            self.last_error = t("Telegram token missing")
            return None
        try:
            resp = requests.post(
                f"{self._base}/{method}",
                json=params,
                timeout=request_timeout or self.TIMEOUT,
            )
            data = resp.json()
        except Exception as exc:  # network, TLS, invalid JSON
            self.last_error = str(exc)[:200]
            return None
        if not data.get("ok"):
            self.last_error = str(data.get("description") or t("Unknown error"))[:200]
            return None
        self.last_error = ""
        return data.get("result")

    # ---- public API ----
    def me(self) -> dict | None:
        """``getMe`` — cheap credential check."""
        return self._call("getMe")

    def send(self, text: str, chat_id: str | None = None) -> bool:
        """Send a message. Long text is split to respect Telegram's 4096 limit."""
        target = str(chat_id or self.chat_id or "").strip()
        if not target:
            self.last_error = t("Telegram chat ID missing")
            return False
        text = (text or "").strip()
        if not text:
            return False
        ok = True
        for chunk in _chunks(text, 4000):
            res = self._call("sendMessage", chat_id=target, text=chunk,
                             parse_mode="HTML", disable_web_page_preview=True)
            if res is None:
                ok = False
        return ok

    def get_updates(self, timeout: int = POLL_TIMEOUT) -> list[dict]:
        """Long-poll for new messages and advance the internal offset."""
        params = {"timeout": int(timeout), "allowed_updates": ["message"]}
        if self.offset:
            params["offset"] = self.offset
        res = self._call("getUpdates", request_timeout=int(timeout) + 15, **params)
        if not isinstance(res, list):
            return []
        for update in res:
            try:
                self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
            except (TypeError, ValueError):
                pass
        return res

    def detect_chat_id(self) -> str:
        """Return the chat id of the most recent message (or "")."""
        for update in reversed(self.get_updates(timeout=0)):
            chat = ((update.get("message") or update.get("edited_message") or {})
                    .get("chat") or {})
            if chat.get("id") is not None:
                self.chat_id = str(chat["id"])
                return self.chat_id
        return ""

    # ---- reports ----
    def report_text(self, store=None) -> str:
        """Build the daily report: done today, remaining tasks, projects, focus."""
        store = store or self.storage
        if store is None:
            return t("No data store available.")

        todos = store.get_todos()
        today = datetime.now().date().isoformat()
        done_today = [x for x in todos
                      if x.get("completed") and str(x.get("completed_at") or "")[:10] == today]
        open_tasks = [x for x in todos if not x.get("completed")]

        lines = [f"<b>{tf('📊 Rakez report — {date}', date=datetime.now().strftime('%Y-%m-%d'))}</b>"]

        # --- done today ---
        lines.append("")
        lines.append(f"<b>{tf('✅ Done today ({n})', n=len(done_today))}</b>")
        if done_today:
            for todo in done_today:
                lines.append(f"  • {_esc(todo.get('title', ''))}")
        else:
            lines.append(f"  {t('Nothing completed yet today.')}")

        # --- remaining ---
        lines.append("")
        lines.append(f"<b>{tf('📋 Remaining tasks ({n})', n=len(open_tasks))}</b>")
        if open_tasks:
            for idx, todo in enumerate(open_tasks, 1):
                cat = todo.get("category") or ""
                suffix = f"  <i>[{_esc(cat)}]</i>" if cat else ""
                lines.append(f"  {idx}. {_esc(todo.get('title', ''))}{suffix}")
            lines.append("")
            lines.append(f"<i>{t('Complete one with: /done N (or /done id)')}</i>")
        else:
            lines.append(f"  {t('All clear — nothing left to do. 🎉')}")

        # --- projects ---
        try:
            projects = store.get_projects()
        except Exception:
            projects = []
        if projects:
            lines.append("")
            lines.append(f"<b>{t('📁 Projects')}</b>")
            for proj in projects:
                lines.append(f"  • {_esc(proj['name'])} — {proj['done']}/{proj['total']} "
                             f"({proj['pct']}%)")

        # --- focus time today ---
        try:
            sessions = store.get_sessions()
        except Exception:
            sessions = []
        minutes = sum(int(s.get("duration_min", 0)) for s in sessions
                      if s.get("kind", "focus") == "focus"
                      and str(s.get("timestamp", ""))[:10] == today)
        if minutes:
            lines.append("")
            lines.append(f"<b>{tf('🔥 Focus today: {n} min', n=minutes)}</b>")

        return "\n".join(lines)

    # ---- command handling ----
    def handle_update(self, update: dict) -> bool:
        """Handle one update. Returns True when the task database changed."""
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        text = (message.get("text") or "").strip()
        if not text or not chat_id:
            return False
        # remember the sender so the GUI's "Detect chat ID" works even while
        # the background poller has already consumed the update
        self.last_chat_id = chat_id
        # Ignore strangers once a chat is configured.
        if self.chat_id and chat_id != str(self.chat_id):
            return False

        changed = False
        try:
            if text.startswith("/"):
                head, _, rest = text.partition(" ")
                command = head.split("@", 1)[0].lower()
                rest = rest.strip()
                if command in ("/start", "/help"):
                    self._reply(chat_id, self.help_text(chat_id))
                elif command in ("/report", "/today"):
                    self._reply(chat_id, self.report_text())
                elif command in ("/tasks", "/list"):
                    self._reply(chat_id, self.tasks_text())
                elif command in ("/projects",):
                    self._reply(chat_id, self.projects_text())
                elif command in ("/done", "/complete"):
                    changed = self._cmd_done(chat_id, rest)
                elif command in ("/add", "/new"):
                    changed = self._cmd_add(chat_id, rest)
                elif command in ("/id", "/chatid"):
                    self._reply(chat_id, tf("Your chat ID is {id}.", id=chat_id))
                else:
                    self._reply(chat_id, self.help_text(chat_id))
            else:
                # plain text = quick add
                changed = self._cmd_add(chat_id, text)
        except Exception as exc:  # never let one bad update kill polling
            self.last_error = str(exc)[:200]
            try:
                self._reply(chat_id, tf("⚠ Error: {err}", err=_esc(self.last_error)))
            except Exception:
                pass
        return changed

    def _reply(self, chat_id: str, text: str):
        self.send(text, chat_id=chat_id)

    def help_text(self, chat_id: str = "") -> str:
        lines = [f"<b>{t('🤖 Rakez bot')}</b>", ""]
        if chat_id:
            lines.append(tf("Your chat ID is {id}.", id=chat_id))
            lines.append(t("Save it in Settings → ✈️ Telegram to receive reports."))
            lines.append("")
        lines += [
            t("/report — done today + remaining tasks"),
            t("/tasks — numbered list of open tasks"),
            t("/done N — complete task number N"),
            t("/done id — complete by id or exact title"),
            t("/add title — add a task"),
            t("/add title | project — add it inside a project"),
            t("/projects — projects and their progress"),
            t("/id — show this chat's ID"),
            "",
            t("Any plain message is added as a new task."),
        ]
        return "\n".join(lines)

    def tasks_text(self) -> str:
        store = self.storage
        if store is None:
            return t("No data store available.")
        open_tasks = [x for x in store.get_todos() if not x.get("completed")]
        if not open_tasks:
            return t("All clear — nothing left to do. 🎉")
        lines = [f"<b>{tf('📋 Remaining tasks ({n})', n=len(open_tasks))}</b>", ""]
        for idx, todo in enumerate(open_tasks, 1):
            cat = todo.get("category") or ""
            suffix = f"  <i>[{_esc(cat)}]</i>" if cat else ""
            lines.append(f"  {idx}. {_esc(todo.get('title', ''))}{suffix}")
        lines += ["", f"<i>{t('Complete one with: /done N (or /done id)')}</i>"]
        return "\n".join(lines)

    def projects_text(self) -> str:
        store = self.storage
        if store is None:
            return t("No data store available.")
        try:
            projects = store.get_projects()
        except Exception:
            projects = []
        if not projects:
            return t("No projects yet. Add one from the app or with /add title | project.")
        lines = [f"<b>{t('📁 Projects')}</b>", ""]
        for proj in projects:
            lines.append(f"  • {_esc(proj['name'])} — {proj['done']}/{proj['total']} "
                         f"({proj['pct']}%)")
        return "\n".join(lines)

    # ---- individual commands ----
    def _cmd_done(self, chat_id: str, arg: str) -> bool:
        store = self.storage
        if store is None:
            self._reply(chat_id, t("No data store available."))
            return False
        if not arg:
            self._reply(chat_id, self.tasks_text())
            return False
        open_tasks = [x for x in store.get_todos() if not x.get("completed")]
        todo = None
        if arg.isdigit():
            index = int(arg) - 1
            if 0 <= index < len(open_tasks):
                todo = open_tasks[index]
            else:
                self._reply(chat_id, tf("No task number {n}. Send /tasks to see the list.",
                                        n=arg))
                return False
        else:
            todo = store.get_todo(arg)
            if todo is None:
                # fall back to a case-insensitive title match
                needle = arg.strip().lower()
                for candidate in open_tasks:
                    if (candidate.get("title") or "").strip().lower() == needle:
                        todo = candidate
                        break
        if todo is None:
            self._reply(chat_id, tf("Task not found: {name}", name=_esc(arg)))
            return False
        if todo.get("completed"):
            self._reply(chat_id, tf("Already done: {name}", name=_esc(todo.get("title", ""))))
            return False
        ok = store.set_completed(todo["id"], True)
        if ok:
            remaining = len([x for x in store.get_todos() if not x.get("completed")])
            self._reply(chat_id, tf("✅ Done: {name}\n📋 {n} task(s) left.",
                                    name=_esc(todo.get("title", "")), n=remaining))
        else:
            self._reply(chat_id, tf("⚠ Could not complete: {name}", name=_esc(arg)))
        return bool(ok)

    def _cmd_add(self, chat_id: str, arg: str) -> bool:
        store = self.storage
        if store is None:
            self._reply(chat_id, t("No data store available."))
            return False
        title, _, project = arg.partition("|")
        title = title.strip()
        project = project.strip()
        if not title:
            self._reply(chat_id, t("Usage: /add task title  (optionally: /add title | project)"))
            return False
        project_id = ""
        if project:
            try:
                proj = store.get_project_by_name(project)
                if proj is None:
                    proj = store.create_project(project)
                project_id = proj["id"]
            except Exception as exc:
                self._reply(chat_id, tf("⚠ Could not use project '{name}': {err}",
                                        name=_esc(project), err=_esc(str(exc)[:120])))
                return False
        try:
            todo = store.add_todo(title, project_id=project_id)
        except Exception as exc:
            self._reply(chat_id, tf("⚠ Could not add the task: {err}",
                                    err=_esc(str(exc)[:120])))
            return False
        where = f" [{_esc(project)}]" if project else ""
        self._reply(chat_id, tf("➕ Added: {name}{where}", name=_esc(todo["title"]), where=where))
        return True


def _chunks(text: str, size: int) -> list[str]:
    """Split long text on line boundaries for the 4096-char Telegram limit."""
    if len(text) <= size:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > size and current:
            chunks.append(current.rstrip())
            current = ""
        current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [text[:size]]


def _esc(text: str) -> str:
    """Escape the three characters Telegram's HTML parse mode treats as markup."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
