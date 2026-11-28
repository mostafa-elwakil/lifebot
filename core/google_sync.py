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
from datetime import datetime, timedelta, timezone
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


def friendly_error(raw: str) -> str:
    """Turn Google API/OAuth errors into actionable, user-facing messages."""
    text = (raw or "").strip()
    low = text.lower()
    if "access_denied" in low or "403" in low or "verification process" in low:
        return (
            "Google blocked access (403 access_denied): this account is not a "
            "developer-approved tester. Fix: Google Cloud Console → APIs & Services → "
            "OAuth consent screen → Test users → + Add users → add the exact Gmail you "
            "sign in with → Save, then press Authorize again. Make sure it is the same "
            "Google Cloud project that owns the Client ID.")
    if "invalid_client" in low or "unauthorized_client" in low:
        return (
            "Google rejected the Client ID/Secret (invalid_client). Re-copy both values "
            "from Credentials → OAuth client ID, and make sure the client type is "
            "'Desktop app' (not 'Web application').")
    if "redirect_uri_mismatch" in low:
        return (
            "Redirect URI mismatch: recreate the OAuth client as a 'Desktop app' type "
            "and paste its Client ID + Secret again.")
    if "invalid_grant" in low or "expired" in low or "revoked" in low:
        return ("Google authorization expired or was revoked. Press Authorize to reconnect.")
    if "insufficient" in low and "scope" in low:
        return (
            "Google granted insufficient permissions. Remove Rakez from "
            "https://myaccount.google.com/permissions then press Authorize again.")
    if "quota" in low or "rate limit" in low:
        return ("Google API quota/rate limit reached — try again in a minute.")
    return text


class GoogleSync:
    def __init__(self, data_dir: str | Path = "data", client_id: str = "",
                 client_secret: str = ""):
        base = Path(data_dir)
        self.data_dir = base
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.token_path = base / "google_token.json"
        self.last_error = ""
        self.last_raw_error = ""
        self._cal = None
        self._tasks = None

    def _set_error(self, exc_or_text) -> None:
        """Keep the raw error for diagnostics, expose the friendly one."""
        raw = str(exc_or_text) or exc_or_text.__class__.__name__
        self.last_raw_error = raw[:500]
        self.last_error = friendly_error(raw)

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
        if not self.client_id or not self.client_secret:
            self.last_error = ("Client ID + Secret are missing — paste them from "
                               "Google Cloud Console, then press Authorize again")
            return False
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_config(self._client_config(), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            self._cal = self._tasks = None
            return True
        except Exception as e:
            self._set_error(e)
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
                self._set_error(e)
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
            self._set_error(e)
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

    def push_task(self, title: str, notes: str = "", completed: bool = False) -> dict | None:
        """Add a task to Google Tasks. Never raises."""
        try:
            svc = self._tasks_service()
            if not svc:
                return None
            body = {"title": title, "notes": notes}
            if completed:
                body["status"] = "completed"
                body["completed"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            t = svc.tasks().insert(tasklist=self._default_list(),
                                   body=body).execute()
            return {"id": t.get("id"), "title": t.get("title")}
        except Exception as e:
            self._set_error(e)
            return None

    def update_task(self, task_id: str, title: str | None = None,
                    notes: str | None = None) -> bool:
        """Rename/annotate an existing Google Task. Never raises."""
        if not task_id:
            return False
        body = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if not body:
            return True
        try:
            svc = self._tasks_service()
            if not svc:
                return False
            svc.tasks().patch(tasklist=self._default_list(), task=task_id,
                              body=body).execute()
            return True
        except Exception as e:
            self._set_error(e)
            return False

    def set_task_status(self, task_id: str, completed: bool = True) -> bool:
        """Mark a Google Task completed (or reopen it). Never raises."""
        if not task_id:
            return False
        try:
            svc = self._tasks_service()
            if not svc:
                return False
            svc.tasks().patch(
                tasklist=self._default_list(), task=task_id,
                body={"status": "completed" if completed else "needsAction"},
            ).execute()
            return True
        except Exception as e:
            self._set_error(e)
            return False

    def delete_task(self, task_id: str) -> bool:
        """Delete a Google Task. Never raises."""
        if not task_id:
            return False
        try:
            svc = self._tasks_service()
            if not svc:
                return False
            svc.tasks().delete(tasklist=self._default_list(), task=task_id).execute()
            return True
        except Exception as e:
            self._set_error(e)
            return False

    def find_task_id(self, title: str) -> str:
        """Find an open Google Task by exact title (case-insensitive)."""
        wanted = (title or "").strip().lower()
        if not wanted:
            return ""
        try:
            svc = self._tasks_service()
            if not svc:
                return ""
            items = svc.tasks().list(tasklist=self._default_list(),
                                     showCompleted=False, maxResults=100
                                     ).execute().get("items", [])
            for t in items:
                if (t.get("title") or "").strip().lower() == wanted:
                    return t.get("id", "")
        except Exception as e:
            self._set_error(e)
        return ""

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
            self._set_error(e)
            return []

    # --- connection check ---
    def test_connection(self) -> dict:
        """Real, lightweight API call to verify auth + scopes.

        Returns {"ok": bool, "message": str}. Never raises.
        """
        if not available():
            return {"ok": False, "message": "libs missing (pip install google-api-python-client google-auth-oauthlib)"}
        if not self.client_id or not self.client_secret:
            return {"ok": False, "message": "needs Client ID + Secret (Settings tab)"}
        if not self.token_path.exists():
            return {"ok": False, "message": "needs authorization (press Authorize)"}
        try:
            tsvc = self._tasks_service()
            if not tsvc:
                return {"ok": False, "message": self.last_error or "credentials invalid — re-authorize"}
            lists = tsvc.tasklists().list().execute().get("items", [])
            first = lists[0].get("title", "?") if lists else "(empty)"
            cal_svc = self._cal_service()
            if not cal_svc:
                return {"ok": False, "message": self.last_error or "calendar access failed — re-authorize"}
            evs = cal_svc.events().list(calendarId="primary", maxResults=1).execute()
            n_ev = len(evs.get("items", []))
            return {"ok": True,
                    "message": f"connected — Tasks: {len(lists)} list(s) (first: {first}), "
                               f"Calendar: primary OK ({n_ev} sample event)"}
        except Exception as e:
            self._set_error(e)
            return {"ok": False, "message": f"API error: {self.last_error}"}
