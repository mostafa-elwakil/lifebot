"""SQLite storage with JSON migration. Backward compatible API."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

from .models import Todo, FocusSession

DEFAULT_TODOS = [
    {"title": "Core System Architecture", "category": "Deep Work"},
    {"title": "Automation Scripting", "category": "Scripting"},
    {"title": "Email & Inbox Zero", "category": "Admin"},
    {"title": "Database Ops", "category": "Ops"},
    {"title": "30 Min Cardio Workout", "category": "Exercise"},
]

CATEGORIES = ["Deep Work", "Scripting", "Admin", "Ops", "Exercise", "Project"]


class SqliteStorage:
    def __init__(self, data_dir: str | Path = "data"):
        # resolve relative to project root (parent of data_dir caller) or cwd
        base = Path(data_dir)
        if not base.is_absolute():
            # if run from project root, data/ works; else try file-adjacent
            here_project = Path(__file__).resolve().parent.parent / "data"
            base = here_project if here_project.parent.exists() else Path.cwd() / "data"
        self.data_dir = base
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "lifebot.db"
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate_json_once()

    # --- schema ---
    def _init_schema(self):
        cur = self._conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS todos(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT DEFAULT 'Deep Work',
            completed INTEGER DEFAULT 0, priority TEXT DEFAULT 'medium',
            estimate_pomodoros INTEGER DEFAULT 1, done_pomodoros INTEGER DEFAULT 0,
            created_at TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, category TEXT,
            duration_min INTEGER, kind TEXT DEFAULT 'focus', timestamp TEXT
        )""")
        self._conn.commit()

    def _migrate_json_once(self):
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM todos")
        if cur.fetchone()["c"] > 0:
            return
        todos_json = self.data_dir / "todos.json"
        legacy: list[dict] = []
        if todos_json.exists():
            try:
                legacy = json.loads(todos_json.read_text(encoding="utf-8"))
            except Exception:
                legacy = []
        if not legacy:
            legacy = DEFAULT_TODOS
        for t in legacy:
            try:
                if not isinstance(t, dict) or not (t.get("title") or "").strip():
                    continue
                self._insert_todo(Todo.from_dict(t))
            except Exception:
                continue  # one corrupt entry must not abort migration
        # migrate sessions.json if present
        sess_json = self.data_dir / "sessions.json"
        if sess_json.exists():
            try:
                for s in json.loads(sess_json.read_text(encoding="utf-8")):
                    self.log_session(s)
            except Exception:
                pass

    _INSERT_SQL = (
        "INSERT OR REPLACE INTO todos(id,title,category,completed,priority,"
        "estimate_pomodoros,done_pomodoros,created_at) VALUES(?,?,?,?,?,?,?,?)"
    )

    def _insert_todo(self, todo: Todo, commit: bool = True):
        self._conn.execute(
            self._INSERT_SQL,
            (todo.id, todo.title, todo.category, int(todo.completed), todo.priority,
             todo.estimate_pomodoros, todo.done_pomodoros, todo.created_at),
        )
        if commit:
            self._conn.commit()

    # --- backward-compatible API (dicts) ---
    def get_todos(self) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM todos ORDER BY completed, created_at")
        return [dict(r) | {"completed": bool(r["completed"])} for r in cur.fetchall()]

    def save_todos(self, todos: list[dict]):
        # single transaction: a mid-loop failure must not leave an empty table
        with self._conn:
            self._conn.execute("DELETE FROM todos")
            for t in todos:
                todo = Todo.from_dict(t)
                self._conn.execute(
                    self._INSERT_SQL,
                    (todo.id, todo.title, todo.category, int(todo.completed),
                     todo.priority, todo.estimate_pomodoros, todo.done_pomodoros,
                     todo.created_at),
                )

    def add_todo(self, title: str, category: str = "Deep Work", priority: str = "medium",
                 estimate: int = 1) -> dict:
        title = (title or "").strip()
        if not title:
            raise ValueError("task title must not be empty")
        todo = Todo(title=title, category=category, priority=priority,
                    estimate_pomodoros=estimate)
        self._insert_todo(todo)
        return todo.to_dict()

    def log_session(self, session: dict):
        self._conn.execute(
            "INSERT INTO sessions(task,category,duration_min,kind,timestamp) VALUES(?,?,?,?,?)",
            (session.get("task", ""), session.get("category", "Deep Work"),
             int(session.get("duration_min", 25)), session.get("kind", "focus"),
             session.get("timestamp") or datetime.now().isoformat()),
        )
        self._conn.commit()
        # auto-increment done_pomodoros for matching open task
        if session.get("kind", "focus") == "focus":
            self._conn.execute(
                "UPDATE todos SET done_pomodoros = done_pomodoros + 1 WHERE title = ? AND completed = 0",
                (session.get("task", ""),),
            )
            self._conn.commit()

    def get_sessions(self) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT task,category,duration_min,kind,timestamp FROM sessions ORDER BY timestamp")
        return [dict(r) for r in cur.fetchall()]

    # --- new CRUD ---
    def set_completed(self, todo_id_or_title: str, completed: bool = True) -> bool:
        cur = self._conn.cursor()
        cur.execute("UPDATE todos SET completed=? WHERE id=? OR title=?",
                    (int(completed), todo_id_or_title, todo_id_or_title))
        self._conn.commit()
        return cur.rowcount > 0

    def delete_todo(self, todo_id_or_title: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM todos WHERE id=? OR title=?", (todo_id_or_title, todo_id_or_title))
        self._conn.commit()
        return cur.rowcount > 0

    def clear_completed(self) -> int:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM todos WHERE completed=1")
        self._conn.commit()
        return cur.rowcount

    def import_todos(self, todos: list[dict]) -> dict:
        """Merge external todos (e.g. from Joplin) skipping existing titles.

        Returns {"added": int, "skipped": int}. Never raises.
        """
        try:
            existing = {(t.get("title") or "").strip().lower()
                        for t in self.get_todos()}
            added, skipped = 0, 0
            for t in todos:
                title = (t.get("title") or "").strip()
                if not title or title.lower() in existing:
                    skipped += 1
                    continue
                cat = t.get("category") or "Deep Work"
                if cat not in CATEGORIES:
                    cat = "Deep Work"
                pri = (t.get("priority") or "medium").lower()
                if pri not in ("low", "medium", "high"):
                    pri = "medium"
                todo = Todo(title=title, category=cat,
                            completed=bool(t.get("completed", False)),
                            priority=pri)
                self._insert_todo(todo)
                existing.add(title.lower())
                added += 1
            return {"added": added, "skipped": skipped}
        except Exception:
            return {"added": 0, "skipped": 0}

    # --- stats ---
    def stats(self, days: int = 7) -> dict:
        sessions = self.get_sessions()
        todos = self.get_todos()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        recent = [s for s in sessions if s.get("timestamp", "") >= cutoff and s.get("kind", "focus") == "focus"]
        mins = sum(int(s.get("duration_min", 0)) for s in recent)
        by_cat: dict[str, int] = {}
        for s in recent:
            by_cat[s.get("category", "?")] = by_cat.get(s.get("category", "?"), 0) + int(s.get("duration_min", 0))
        # streak: consecutive days with >=1 focus session
        days_with = sorted({s.get("timestamp", "")[:10] for s in sessions if s.get("kind", "focus") == "focus"})
        streak = 0
        day = datetime.now().date()
        dayset = set(days_with)
        while day.isoformat() in dayset:
            streak += 1
            day -= timedelta(days=1)
        return {
            "total_logged_sessions": len(sessions),
            "recent_sessions": len(recent),
            "recent_focus_minutes": mins,
            "total_tasks_count": len(todos),
            "open_tasks": sum(1 for t in todos if not t.get("completed")),
            "done_tasks": sum(1 for t in todos if t.get("completed")),
            "by_category_min": by_cat,
            "streak_days": streak,
        }

    def close(self):
        try:
            self._conn.commit()
            self._conn.close()
        except Exception:
            pass


# Keep old name working for run_lifebot.py
SimpleStorage = SqliteStorage
