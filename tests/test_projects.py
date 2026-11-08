"""Project grouping: projects contain tasks, progress = done/total."""
import tempfile
from pathlib import Path

import pytest

from core.storage import SqliteStorage


@pytest.fixture()
def storage():
    with tempfile.TemporaryDirectory() as td:
        s = SqliteStorage(data_dir=Path(td))
        try:
            yield s
        finally:
            s.close()


def test_create_project_progress(storage: SqliteStorage):
    p = storage.create_project("Website")
    t1 = storage.add_todo("Design", project_id=p["id"])
    storage.add_todo("Build", project_id=p["id"])
    storage.add_todo("Ungrouped")
    got = storage.get_project(p["id"])
    assert got["name"] == "Website"
    assert got["total"] == 2 and got["done"] == 0 and got["pct"] == 0
    storage.set_completed(t1["id"], True)
    got = storage.get_project(p["id"])
    assert got["done"] == 1 and got["pct"] == 50


def test_duplicate_project_rejected(storage: SqliteStorage):
    storage.create_project("Alpha")
    with pytest.raises(ValueError):
        storage.create_project("Alpha")
    # case-insensitive lookup finds it
    assert storage.get_project_by_name("ALPHA") is not None


def test_add_task_with_known_and_unknown_project(storage: SqliteStorage):
    p = storage.create_project("API")
    t = storage.add_todo("Endpoint", project_id=p["id"])
    assert t["project_id"] == p["id"]
    # unknown project id is stored as-is but not attachable via update_todo
    storage.add_todo("Ghost", project_id="zzzz")
    with pytest.raises(ValueError):
        storage.update_todo("Endpoint", {"project_id": "zzzz"})
    # assign by project NAME works
    storage.create_project("Ops")
    updated = storage.update_todo("Endpoint", {"project_id": "Ops"})
    assert updated["project_id"] == storage.get_project_by_name("Ops")["id"]


def test_delete_project_keeps_tasks(storage: SqliteStorage):
    p = storage.create_project("Temp")
    storage.add_todo("Task inside", project_id=p["id"])
    assert storage.delete_project(p["id"]) is True
    assert storage.delete_project(p["id"]) is False
    todos = storage.get_todos()
    task = next(t for t in todos if t["title"] == "Task inside")
    assert task["project_id"] == ""
    assert storage.get_project(p["id"]) is None


def test_get_project_todos_order_and_filter(storage: SqliteStorage):
    p = storage.create_project("Plan")
    done = storage.add_todo("First", project_id=p["id"])
    storage.add_todo("Second", project_id=p["id"])
    storage.add_todo("Not in project")
    storage.set_completed(done["id"], True)
    rows = storage.get_project_todos(p["id"])
    assert [r["title"] for r in rows] == ["Second", "First"]  # open first
    assert all(r["project_id"] == p["id"] for r in rows)
