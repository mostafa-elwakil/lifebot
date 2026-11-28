"""IntegrationHub: storage events fan out to Google Tasks, Joplin, Notion."""
from core.storage import SqliteStorage
from core.sync import IntegrationHub


class FakeJoplin:
    available = True

    def __init__(self):
        self.created, self.updated, self.completed = [], [], []
        self.deleted, self.last_error = [], ""

    def find_todo_id(self, title, folder_name=""):
        return ""

    def create_todo(self, title, body="", folder_name="", tags=""):
        self.created.append(title)
        return {"id": f"joplin-{len(self.created)}"}

    def update_note(self, note_id, title=None, body=None):
        self.updated.append((note_id, title))
        return True

    def set_completed(self, note_id, done=True):
        self.completed.append((note_id, done))
        return True

    def delete_note(self, note_id):
        self.deleted.append(note_id)
        return True

    def sync_open_todos(self, todos, folder_name="", tags=""):
        return {"created": 1, "updated": 0, "skipped": 0, "error": ""}


class FakeGoogle:
    authorized = True

    def __init__(self):
        self.pushed, self.updated, self.status, self.deleted = [], [], [], []
        self.last_error = ""

    def find_task_id(self, title):
        return ""

    def push_task(self, title, notes="", completed=False):
        self.pushed.append((title, completed))
        return {"id": f"google-{len(self.pushed)}"}

    def update_task(self, task_id, title=None, notes=None):
        self.updated.append((task_id, title))
        return True

    def set_task_status(self, task_id, completed=True):
        self.status.append((task_id, completed))
        return True

    def delete_task(self, task_id):
        self.deleted.append(task_id)
        return True


class FakeNotion:
    available = True

    def __init__(self):
        self.upserts, self.done, self.archived = [], [], []
        self.last_error = ""

    def upsert_task(self, todo, project_name=""):
        self.upserts.append((todo["id"], project_name))
        return f"notion-{todo['id']}"

    def set_done(self, page_id, done, completed_at=""):
        self.done.append((page_id, done))
        return True

    def archive(self, page_id):
        self.archived.append(page_id)
        return True

    def sync_tasks(self, todos, project_names=None):
        return {"created": len(todos), "updated": 0, "failed": 0, "error": ""}

    def friendly_error(self):
        return ""


def _hub(tmp_path, **kwargs):
    store = SqliteStorage(data_dir=tmp_path)
    joplin, google, notion = FakeJoplin(), FakeGoogle(), FakeNotion()
    notified = []
    hub = IntegrationHub(
        store, joplin=joplin, google=google, notion=notion,
        enabled=kwargs.pop("enabled", lambda: True),
        notify_done=notified.append,
        project_lookup=lambda pid: "Project X",
        **kwargs)
    hub.attach()
    return store, hub, joplin, google, notion, notified


def test_created_task_is_pushed_everywhere(tmp_path):
    store, hub, joplin, google, notion, _ = _hub(tmp_path)

    project = store.create_project("Project X")
    todo = store.add_todo("Ship the release", "Deep Work", priority="high",
                          project_id=project["id"])
    assert hub.flush(5) is True

    assert joplin.created == ["Ship the release"]
    assert google.pushed == [("Ship the release", False)]
    assert notion.upserts == [(todo["id"], "Project X")]

    row = store.get_todo(todo["id"])
    assert row["joplin_id"] == "joplin-1"
    assert row["google_id"] == "google-1"
    assert row["notion_id"] == f"notion-{todo['id']}"
    store.close()


def test_completion_and_reopen_reach_every_service(tmp_path):
    store, hub, joplin, google, notion, notified = _hub(tmp_path)

    todo = store.add_todo("Finish the deck")
    hub.flush(5)

    store.set_completed(todo["id"], True)
    hub.flush(5)
    assert joplin.completed == [("joplin-1", True)]
    assert google.status == [("google-1", True)]
    assert notion.done == [(f"notion-{todo['id']}", True)]
    assert notified == ["Finish the deck"]

    store.set_completed(todo["id"], False)
    hub.flush(5)
    assert joplin.completed[-1] == ("joplin-1", False)
    assert google.status[-1] == ("google-1", False)
    assert notion.done[-1] == (f"notion-{todo['id']}", False)
    assert notified == ["Finish the deck"]  # only completion notifies
    store.close()


def test_delete_removes_remote_items(tmp_path):
    store, hub, joplin, google, notion, _ = _hub(tmp_path)

    todo = store.add_todo("Temporary task")
    hub.flush(5)

    store.delete_todo(todo["id"])
    hub.flush(5)
    assert joplin.deleted == ["joplin-1"]
    assert google.deleted == ["google-1"]
    assert notion.archived == [f"notion-{todo['id']}"]
    store.close()


def test_auto_sync_off_still_notifies_but_pushes_nothing(tmp_path):
    store, hub, joplin, google, notion, notified = _hub(
        tmp_path, enabled=lambda: False)

    todo = store.add_todo("No push please")
    store.set_completed(todo["id"], True)
    hub.flush(1)

    assert joplin.created == [] and google.pushed == [] and notion.upserts == []
    assert notified == ["No push please"]
    store.close()


def test_sync_all_reports_each_service(tmp_path):
    store, hub, joplin, google, notion, _ = _hub(tmp_path)
    store.add_todo("Backfill me")
    hub.flush(5)

    res = hub.sync_all()
    assert res["joplin"]["created"] == 1
    assert res["google"]["pushed"] >= 1
    assert res["notion"]["created"] >= 1
    assert res["errors"] == []
    store.close()
