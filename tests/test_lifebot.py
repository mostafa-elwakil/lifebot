import tempfile
from pathlib import Path
from core.storage import SqliteStorage
from core.coach import HermesCoach


def test_add_complete_delete():
    with tempfile.TemporaryDirectory() as td:
        s = SqliteStorage(data_dir=Path(td))
        try:
            t = s.add_todo("Test task", "Deep Work")
            assert any(x["title"] == "Test task" for x in s.get_todos())
            assert s.set_completed(t["id"], True)
            assert s.delete_todo(t["id"])
        finally:
            s.close()


def test_log_session_increments_pomodoros():
    with tempfile.TemporaryDirectory() as td:
        s = SqliteStorage(data_dir=Path(td))
        try:
            s.add_todo("Focus me", "Deep Work")
            s.log_session({"task": "Focus me", "category": "Deep Work", "duration_min": 25, "kind": "focus"})
            todos = s.get_todos()
            assert [t for t in todos if t["title"] == "Focus me"][0]["done_pomodoros"] >= 1
        finally:
            s.close()


def test_coach_offline_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    c = HermesCoach()
    c.online = False
    out = c.morning_plan([{"title": "X", "category": "Deep Work", "completed": False}])
    assert "Phase 1" in out or "phase" in out.lower() or len(out) > 20
    r = c.resolve_snag("tired")
    assert "Option A" in r


def test_joplin_pull_and_import_roundtrip(monkeypatch):
    import tempfile
    from pathlib import Path
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    c.ensure_folder = lambda name="Lifebot": "folder1"
    c.get_notes_in_folder = lambda fid: [
        {"id": "n1", "title": "From Joplin", "is_todo": 1, "todo_completed": 0,
         "body": "Category: Ops\nPriority: high"},
        {"id": "n2", "title": "Plain note", "is_todo": 0, "todo_completed": 0, "body": ""},
        {"id": "n3", "title": "Done thing", "is_todo": 1, "todo_completed": 1700000000000, "body": ""},
    ]
    pulled = c.pull_todos()
    assert len(pulled) == 2  # only real todos
    assert pulled[0]["category"] == "Ops" and pulled[0]["priority"] == "high"
    assert pulled[1]["completed"] is True
    with tempfile.TemporaryDirectory() as td:
        s = SqliteStorage(data_dir=Path(td))
        try:
            r1 = s.import_todos(pulled)
            assert r1["added"] == 2
            r2 = s.import_todos(pulled)  # duplicates skipped
            assert r2["added"] == 0 and r2["skipped"] == 2
        finally:
            s.close()


def test_get_notes_requests_todo_fields(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    seen = {}
    def fake_get(path, **params):
        seen.update(params)
        return {"items": []}
    c._get = fake_get
    assert c.get_notes_in_folder("abc") == []
    # Joplin omits is_todo/todo_due by default — we must request them
    assert "is_todo" in seen.get("fields", "")
    assert "todo_due" in seen.get("fields", "")
    assert "todo_completed" in seen.get("fields", "")


def test_ensure_folder_nested_path(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    c._get = lambda path, **kw: {"items": [
        {"id": "root1", "title": "Lifebot", "parent_id": ""},
    ]}
    created = {}
    def fake_post(path, data):
        assert path == "/folders"
        new_id = f"new-{data['title']}"
        created.update(data)
        created["id"] = new_id
        return {"id": new_id, "title": data["title"], "parent_id": data.get("parent_id", "")}
    c._post = fake_post
    fid = c.ensure_folder("Lifebot/Tasks")
    assert fid == "new-Tasks"
    assert created.get("parent_id") == "root1"  # created UNDER Lifebot
    # existing nested path resolves without creating
    c._get = lambda path, **kw: {"items": [
        {"id": "root1", "title": "Lifebot", "parent_id": ""},
        {"id": "sub1", "title": "Tasks", "parent_id": "root1"},
    ]}
    calls = []
    c._post = lambda path, data: calls.append(data) or {"id": "x"}
    assert c.ensure_folder("Lifebot/Tasks") == "sub1"
    assert calls == []


def test_ensure_folder_lifebot_under_projects(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    c._get = lambda path, **kw: {"items": [
        {"id": "proj", "title": "Projects", "parent_id": ""},
        {"id": "life", "title": "Lifebot", "parent_id": "proj"},
        {"id": "task", "title": "Tasks", "parent_id": "life"},
    ]}
    calls = []
    c._post = lambda path, data: calls.append(data) or {"id": "x"}
    assert c.ensure_folder("Projects/Lifebot/Tasks") == "task"
    assert calls == []  # exact chain found — nothing created
    # intermediate segment reused when only nested copy exists
    c._get = lambda path, **kw: {"items": [
        {"id": "proj", "title": "Projects", "parent_id": ""},
        {"id": "life", "title": "Lifebot", "parent_id": "proj"},
    ]}
    created = {}
    def fake_post(path, data):
        created.update(data)
        created["id"] = "new-tasks"
        return {"id": "new-tasks"}
    c._post = fake_post
    assert c.ensure_folder("Projects/Lifebot/Tasks") == "new-tasks"
    assert created.get("parent_id") == "life"  # Tasks created UNDER Projects/Lifebot


def test_dedupe_keeps_newest(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    c.ensure_folder = lambda name="x": "folder1"
    c._get = lambda path, **kw: {"items": [
        {"id": "old", "title": "Same", "updated_time": 100, "is_todo": 1},
        {"id": "new", "title": "Same", "updated_time": 200, "is_todo": 1},
        {"id": "solo", "title": "Unique", "updated_time": 300, "is_todo": 1},
    ]}
    groups = c.find_duplicates()
    assert list(groups) == ["Same"] and len(groups["Same"]) == 2
    deleted = []
    c._request = lambda method, path, data=None, **kw: deleted.append(path) or {}
    res = c.dedupe(dry_run=False)
    assert res["groups"] == 1 and res["deleted"] == ["Same"]
    assert deleted == ["/notes/old"]  # newest kept
    res2 = c.dedupe(dry_run=True)
    assert res2["groups"] == 1  # dry run deletes nothing (no exception)


def test_get_all_pages(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    seen_pages = []
    def fake_get(path, **kw):
        seen_pages.append(kw.get("page"))
        if kw.get("page", 1) == 1:
            return {"items": [{"id": "a"}], "has_more": True}
        return {"items": [{"id": "b"}], "has_more": False}
    c._get = fake_get
    assert c._get_all("/folders") == [{"id": "a"}, {"id": "b"}]
    assert seen_pages == [1, 2]


def test_complete_note_uses_custom_tags(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    c._put = lambda path, data: {"id": "n1"}
    c._get = lambda path, **kw: {"items": [{"title": "other"}]}
    added = []
    c.add_tags = lambda nid, tags: added.append((nid, tags)) or True
    assert c._complete_note({"id": "n1", "todo_due": 0}, "foo,bar", 999) is True
    assert added == [("n1", "foo,bar")]
    # already-tagged note with custom tag → only due date touched
    c._get = lambda path, **kw: {"items": [{"title": "Foo"}]}
    added.clear()
    puts = []
    c._put = lambda path, data: puts.append(data) or {"id": "n1"}
    assert c._complete_note({"id": "n1", "todo_due": 0}, "foo,bar", 999) is True
    assert added == [] and puts == [{"todo_due": 999}]


def test_migration_skips_corrupt_entries():
    import json
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td)
        (data_dir / "todos.json").write_text(json.dumps([
            {"title": "Good", "category": "Ops"},
            {"title": "Bad numbers", "estimate_pomodoros": None, "done_pomodoros": "xx"},
            {"no_title": True},
            "not-a-dict",
        ]), encoding="utf-8")
        s = SqliteStorage(data_dir=data_dir)
        try:
            titles = [t["title"] for t in s.get_todos()]
            assert "Good" in titles and "Bad numbers" in titles
            assert len(titles) == 2
        finally:
            s.close()


def test_add_todo_rejects_empty():
    import tempfile
    from pathlib import Path as P
    with tempfile.TemporaryDirectory() as td:
        s = SqliteStorage(data_dir=P(td))
        try:
            try:
                s.add_todo("   ")
                raise AssertionError("should have raised")
            except ValueError:
                pass
        finally:
            s.close()


def test_settings_roundtrip_and_sanitize():
    import tempfile
    from pathlib import Path as P
    from core.settings import load_settings, save_settings, DEFAULTS
    with tempfile.TemporaryDirectory() as td:
        d = P(td)
        assert load_settings(d) == DEFAULTS  # missing file → defaults
        cfg = dict(DEFAULTS)
        cfg.update({"widget_w": 9999, "widget_h": -5, "accent": "nope",
                    "gemini_key": "k", "unknown": 1})
        assert save_settings(d, cfg) is True
        back = load_settings(d)
        assert back["widget_w"] == 700 and back["widget_h"] == 90  # clamped
        assert back["accent"] == DEFAULTS["accent"]  # invalid accent reset
        assert back["gemini_key"] == "k" and "unknown" not in back


def test_custom_colors_preserved():
    import tempfile
    from pathlib import Path as P
    from core.settings import load_settings, save_settings, DEFAULTS, valid_hex
    assert valid_hex("#123abc") and not valid_hex("nope") and not valid_hex("#xyz")
    with tempfile.TemporaryDirectory() as td:
        d = P(td)
        cfg = dict(DEFAULTS, accent="#123abc", background="#00ff00")
        assert save_settings(d, cfg) is True
        back = load_settings(d)
        assert back["accent"] == "#123abc" and back["background"] == "#00ff00"
        cfg2 = dict(DEFAULTS, opacity=150)
        save_settings(d, cfg2)
        assert load_settings(d)["opacity"] == 100
        cfg3 = dict(DEFAULTS, opacity="junk")
        save_settings(d, cfg3)
        assert load_settings(d)["opacity"] == 95


def test_sound_patterns_and_sanitize(monkeypatch):
    import sys
    import run_lifebot as rl
    assert set(rl.SOUND_PATTERNS) == {"Default beep", "Chime", "Alert", "Silent"}
    assert rl.SOUND_PATTERNS["Silent"] == []
    assert all(f >= 37 and ms > 0 for name in rl.SOUND_PATTERNS
               for f, ms in rl.SOUND_PATTERNS[name])
    from core.settings import load_settings, DEFAULTS
    import tempfile
    from pathlib import Path as P
    with tempfile.TemporaryDirectory() as td:
        d = P(td)
        cfg = dict(DEFAULTS, sound="nope")
        from core.settings import save_settings
        save_settings(d, cfg)
        assert load_settings(d)["sound"] == "Default beep"
    # no real beeps during tests
    class FakeWinsound:
        def __init__(self):
            self.calls = []
        def Beep(self, f, ms):
            self.calls.append((f, ms))
    fake = FakeWinsound()
    monkeypatch.setitem(sys.modules, "winsound", fake)
    rl.play_done_sound(None, "Chime")
    assert fake.calls == rl.SOUND_PATTERNS["Chime"]
    rl.play_done_sound(None, "Silent")
    assert len(fake.calls) == 3  # silent adds nothing
    rl.play_done_sound(None, "bogus-name")  # falls back to default pattern


def test_request_falls_back_to_ipv4(monkeypatch):
    import core.joplin as jm
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = jm.JoplinClient(base_url="http://localhost:41184", token="dummy")
    calls = []

    class FakeResp:
        text = '{"ok": true}'
        def raise_for_status(self):
            pass
        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if "localhost" in url:
            raise ConnectionError("::1 refused")
        return FakeResp()

    monkeypatch.setattr(jm.requests, "get", fake_get)
    assert c._get("/ping") == {"ok": True}
    assert calls[0].startswith("http://localhost")
    assert any("127.0.0.1" in u for u in calls)


def test_post_is_not_blindly_retried(monkeypatch):
    """A timed-out POST must not be re-fired (it may have succeeded)."""
    import core.joplin as jm
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = jm.JoplinClient(base_url="http://127.0.0.1:41184", token="dummy")
    posts, gets = [], []

    class Boom:
        def __call__(self, *a, **k):
            posts.append(a[0] if a else "")
            raise TimeoutError("read timed out")
    monkeypatch.setattr(jm.requests, "post", Boom())
    monkeypatch.setattr(jm.requests, "get",
                        lambda url, params=None, timeout=None: gets.append(url) or (_ for _ in ()).throw(TimeoutError("x")))
    assert c._post("/notes", {"title": "t"}) is None
    # 1 attempt per candidate host, no extra retries of the same URL
    from collections import Counter
    assert max(Counter(posts).values()) == 1


def test_failed_post_verifies_before_giving_up(monkeypatch):
    """Timeout after server-side creation → reuse found note, no 2nd POST."""
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    c.ensure_folder = lambda name="Lifebot": "folder1"
    posts = []
    c._post = lambda path, data: posts.append(path) or None  # POST "fails"
    c.get_notes_in_folder = lambda fid: [
        {"id": "srv1", "title": "Dup?", "is_todo": 1, "todo_completed": 0,
         "todo_due": 123, "body": ""}]
    c._put = lambda path, data: (_ for _ in ()).throw(AssertionError("no PUT needed"))
    c._get = lambda path, **kw: {"items": [{"title": "task"}]}  # tags already there
    note = c.create_todo("Dup?")
    assert note and note["id"] == "srv1"
    assert posts == ["/notes"]  # exactly one POST — no duplicate


def test_joplin_create_never_crashes(monkeypatch):
    from core.joplin import JoplinClient
    monkeypatch.delenv("JOPLIN_TOKEN", raising=False)
    monkeypatch.delenv("JOPLIN_BASE_URL", raising=False)
    c = JoplinClient(token="dummy")
    # dict-style paginated response (real Joplin format)
    c._get = lambda path, **kw: {"items": [{"id": "abc", "title": "Lifebot"}], "has_more": False}
    posted = {}
    calls = []
    def fake_post(path, data):
        calls.append((path, data))
        posted["path"] = path
        posted["data"] = data
        return {"id": "new"}
    c._post = fake_post
    c._put = lambda path, data: {"id": "new"}
    created = c.create_todo("hello", folder_name="Lifebot")
    assert created and created.get("id") == "new"
    # must use the real Joplin endpoint: POST /notes with is_todo=1
    first = calls[0]
    assert first[0] == "/notes"
    assert first[1]["is_todo"] == 1
    assert first[1]["parent_id"] == "abc"
    # unreachable server
    c._get = lambda path, **kw: None
    c._post = lambda path, data: None
    assert c.create_todo("x", folder_name="Lifebot") is None
    # no token
    assert JoplinClient(token="").create_todo("x", folder_name="Lifebot") is None
