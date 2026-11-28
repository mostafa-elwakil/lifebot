"""Storage emits task lifecycle events and keeps external sync ids."""
from core.storage import SqliteStorage


def test_storage_emits_lifecycle_events(tmp_path):
    store = SqliteStorage(data_dir=tmp_path)
    events = []
    store.add_listener(lambda event, todo: events.append((event, todo["title"])))

    todo = store.add_todo("Listen to me")
    store.update_todo(todo["id"], {"title": "Renamed task"})
    store.set_completed(todo["id"], True)
    store.set_completed(todo["id"], False)
    store.delete_todo(todo["id"])

    assert events == [
        ("created", "Listen to me"),
        ("updated", "Renamed task"),
        ("completed", "Renamed task"),
        ("reopened", "Renamed task"),
        ("deleted", "Renamed task"),
    ]
    store.close()


def test_listener_errors_do_not_break_storage(tmp_path):
    store = SqliteStorage(data_dir=tmp_path)

    def broken(event, todo):
        raise RuntimeError("boom")

    store.add_listener(broken)
    todo = store.add_todo("Still saved")
    assert store.get_todo(todo["id"])["title"] == "Still saved"
    store.close()


def test_set_sync_ids_persists_without_events(tmp_path):
    store = SqliteStorage(data_dir=tmp_path)
    events = []
    store.add_listener(lambda event, todo: events.append(event))
    todo = store.add_todo("Map me")
    events.clear()

    assert store.set_sync_ids(todo["id"], google_id="g1", joplin_id="j1",
                              notion_id="n1") is True
    row = store.get_todo(todo["id"])
    assert (row["google_id"], row["joplin_id"], row["notion_id"]) == ("g1", "j1", "n1")
    assert events == []
    store.close()


def test_import_todos_keeps_external_ids(tmp_path):
    store = SqliteStorage(data_dir=tmp_path)
    res = store.import_todos([
        {"title": "From Google", "google_id": "g-9"},
        {"title": "From Joplin", "joplin_id": "j-9"},
    ])
    assert res["added"] == 2
    by_title = {t["title"]: t for t in store.get_todos()}
    assert by_title["From Google"]["google_id"] == "g-9"
    assert by_title["From Joplin"]["joplin_id"] == "j-9"
    store.close()
