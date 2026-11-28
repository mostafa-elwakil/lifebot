"""Google Tasks: push/update/complete/delete helpers used by the sync hub."""
from core.google_sync import GoogleSync


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeTasks:
    def __init__(self):
        self.inserted, self.patched, self.deleted = [], [], []
        self.items = [{"id": "g-old", "title": "Existing task"}]

    def insert(self, tasklist, body):
        self.inserted.append((tasklist, body))
        return _Exec({"id": f"g-{len(self.inserted)}", "title": body["title"]})

    def patch(self, tasklist, task, body):
        self.patched.append((tasklist, task, body))
        return _Exec({})

    def delete(self, tasklist, task):
        self.deleted.append((tasklist, task))
        return _Exec({})

    def list(self, tasklist, showCompleted=False, maxResults=50):
        return _Exec({"items": list(self.items)})


class FakeService:
    def __init__(self):
        self._tasks = FakeTasks()

    def tasks(self):
        return self._tasks


def _sync(tmp_path):
    gs = GoogleSync(data_dir=tmp_path)
    service = FakeService()
    gs._tasks_service = lambda: service
    gs._default_list = lambda: "L1"
    return gs, service


def test_push_task_defaults_to_open(tmp_path):
    gs, service = _sync(tmp_path)
    res = gs.push_task("Write docs", "Category: Deep Work")
    assert res["id"] == "g-1"
    tasklist, body = service._tasks.inserted[0]
    assert tasklist == "L1"
    assert body["title"] == "Write docs"
    assert "status" not in body


def test_push_task_can_be_completed(tmp_path):
    gs, service = _sync(tmp_path)
    gs.push_task("Already done", completed=True)
    body = service._tasks.inserted[0][1]
    assert body["status"] == "completed"
    assert body["completed"].endswith("Z")


def test_update_and_complete_and_delete(tmp_path):
    gs, service = _sync(tmp_path)

    assert gs.update_task("g-1", title="New title", notes="n") is True
    assert service._tasks.patched[-1] == ("L1", "g-1",
                                          {"title": "New title", "notes": "n"})

    assert gs.set_task_status("g-1", True) is True
    assert service._tasks.patched[-1][2] == {"status": "completed"}

    assert gs.set_task_status("g-1", False) is True
    assert service._tasks.patched[-1][2] == {"status": "needsAction"}

    assert gs.delete_task("g-1") is True
    assert service._tasks.deleted == [("L1", "g-1")]


def test_find_task_id_matches_title_case_insensitively(tmp_path):
    gs, service = _sync(tmp_path)
    assert gs.find_task_id("  existing TASK ") == "g-old"
    assert gs.find_task_id("missing") == ""


def test_helpers_are_noops_without_service(tmp_path):
    gs = GoogleSync(data_dir=tmp_path)
    gs._tasks_service = lambda: None
    assert gs.update_task("g-1", title="x") is False
    assert gs.set_task_status("g-1", True) is False
    assert gs.delete_task("g-1") is False
    assert gs.find_task_id("x") == ""
