"""Google Calendar + Google Tasks integration (OAuth2, optional dependency).

Setup (one time, user does this in Google Cloud Console):
  1. Create project → enable "Google Calendar API" + "Google Tasks API".
  2. OAuth consent screen (External, test mode) + add yourself as test user.
  3. Credentials → Create OAuth client ID (Desktop app) → copy Client ID + Secret.
  4. Paste them in Rakez Settings tab → Authorize (browser opens once).

Tokens are stored in <data_dir>/google_token.json (auto-refreshed).
All google imports are lazy so the app works without these packages.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]


def available() -> bool:
    try:
        import googleapiclient.discovery  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        return True
    except Exception:
        return False


class GoogleSync:
    def __init__(self, data_dir: str | Path = "data", client_id: str = "",
                 client_secret: str = ""):
        base = Path(data_dir)
        self.data_dir = base
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.token_path = base / "google_token.json"
        self.last_error = ""
        self._cal = None
        self._tasks = None

    @property
    def configured(self) -> bool:
        return bool(available() and self.client_id and self.client_secret)

    @property
    def authorized(self) -> bool:
        return self.configured and self.token_path.exists()

    def status(self) -> str:
        if not available():
            return "libs missing (pip install google-api-python-client google-auth-oauthlib)"
        if not self.client_id or not self.client_secret:
            return "needs Client ID + Secret (see Settings)"
        if self.token_path.exists():
            return "connected"
        return "needs authorization (press Authorize)"

    def _client_config(self) -> dict:
        return {"installed": {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }}

    def authorize(self) -> bool:
        """Interactive OAuth (opens browser). Returns True on success."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_config(self._client_config(), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            self._cal = self._tasks = None
            return True
        except Exception as e:
            self.last_error = str(e)[:200]
            return False

    def _creds(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        if not self.token_path.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json(), encoding="utf-8")
            except Exception as e:
                self.last_error = str(e)[:200]
                return None
        return creds if creds and creds.valid else None

    def _cal_service(self):
        if self._cal is None:
            from googleapiclient.discovery import build
            creds = self._creds()
            if not creds:
                return None
            self._cal = build("calendar", "v3", credentials=creds)
        return self._cal

    def _tasks_service(self):
        if self._tasks is None:
            from googleapiclient.discovery import build
            creds = self._creds()
            if not creds:
                return None
            self._tasks = build("tasks", "v1", credentials=creds)
        return self._tasks

    # --- Calendar ---
    def log_focus_event(self, title: str, minutes: int = 25) -> dict | None:
        """Create a Calendar event for a finished focus session. Never raises."""
        try:
            svc = self._cal_service()
            if not svc:
                return None
            end = datetime.now()
            start = end - timedelta(minutes=minutes)
            ev = svc.events().insert(calendarId="primary", body={
                "summary": f"🍅 {title}",
                "description": f"Focus session via Rakez ({minutes} min)",
                "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            }).execute()
            return {"id": ev.get("id"), "link": ev.get("htmlLink")}
        except Exception as e:
            self.last_error = str(e)[:200]
            return None

    # --- Tasks ---
    def _default_list(self) -> str:
        svc = self._tasks_service()
        if not svc:
            return "@default"
        try:
            lists = svc.tasklists().list().execute().get("items", [])
            if lists:
                return lists[0]["id"]
        except Exception:
            pass
        return "@default"

    def push_task(self, title: str, notes: str = "") -> dict | None:
        """Add a task to Google Tasks. Never raises."""
        try:
            svc = self._tasks_service()
            if not svc:
                return None
            t = svc.tasks().insert(tasklist=self._default_list(),
                                   body={"title": title, "notes": notes}).execute()
            return {"id": t.get("id"), "title": t.get("title")}
        except Exception as e:
            self.last_error = str(e)[:200]
            return None

    def pull_tasks(self, max_n: int = 50) -> list[dict]:
        """Fetch open Google Tasks as Lifebot-style dicts. Never raises."""
        try:
            svc = self._tasks_service()
            if not svc:
                return []
            items = svc.tasks().list(tasklist=self._default_list(),
                                     showCompleted=False,
                                     maxResults=max_n).execute().get("items", [])
            out = []
            for t in items:
                if t.get("status") == "completed":
                    continue
                out.append({"title": (t.get("title") or "").strip(),
                            "category": "Deep Work", "priority": "medium",
                            "completed": False, "google_id": t.get("id")})
            return [t for t in out if t["title"]]
        except Exception as e:
            self.last_error = str(e)[:200]
            return []
