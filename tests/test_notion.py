"""Notion client: schema prep, upsert, completion and friendly errors."""
import json

import core.notion as notion


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.content = b"{}" if payload is not None else b""
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload


class FakeRequests:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json,
                           "headers": headers or {}})
        return self.responses.pop(0)


def _db(**props):
    base = {"Name": {"type": "title"}}
    base.update(props)
    return {"id": "db1", "title": [{"plain_text": "Rakez Tasks"}],
            "properties": base}


def _full_props():
    return {
        notion.PROP_ID: {"rich_text": {}},
        notion.PROP_DONE: {"checkbox": {}},
        notion.PROP_CATEGORY: {"select": {}},
        notion.PROP_PRIORITY: {"select": {}},
        notion.PROP_PROJECT: {"rich_text": {}},
        notion.PROP_COMPLETED: {"date": {}},
    }


def _todo(**extra):
    todo = {"id": "abc12345", "title": "Write the report", "completed": False,
            "category": "Deep Work", "priority": "high", "completed_at": "",
            "project_id": ""}
    todo.update(extra)
    return todo


def test_status_and_availability(monkeypatch):
    monkeypatch.setattr(notion, "requests", FakeRequests([]))
    c = notion.NotionClient()
    assert not c.available
    assert "token" in c.status()

    c.token = "secret"
    assert "database" in c.status()

    c.database_id = "db1"
    assert c.available


def test_ensure_schema_creates_missing_properties(monkeypatch):
    fake = FakeRequests([FakeResponse(payload=_db()),
                         FakeResponse(payload={"id": "db1"})])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")

    assert c.ensure_schema() is True
    patch = fake.calls[1]
    assert patch["method"] == "PATCH"
    assert patch["url"].endswith("/databases/db1")
    assert set(patch["json"]["properties"]) == {
        notion.PROP_ID, notion.PROP_DONE, notion.PROP_CATEGORY,
        notion.PROP_PRIORITY, notion.PROP_PROJECT, notion.PROP_COMPLETED,
    }
    assert c._title_prop == "Name"


def test_ensure_schema_is_idempotent(monkeypatch):
    fake = FakeRequests([FakeResponse(payload=_db(**_full_props()))])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")
    assert c.ensure_schema() is True
    assert len(fake.calls) == 1  # GET only, no PATCH


def test_upsert_creates_page_when_missing(monkeypatch):
    fake = FakeRequests([
        FakeResponse(payload=_db(**_full_props())),      # ensure_schema
        FakeResponse(payload={"results": []}),           # query by Rakez ID
        FakeResponse(payload={"id": "page1"}),           # create page
    ])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")

    page = c.upsert_task(_todo(), "Rakez")
    assert page == "page1"
    created = fake.calls[2]
    assert created["method"] == "POST" and created["url"].endswith("/pages")
    props = created["json"]["properties"]
    assert props["Name"]["title"][0]["text"]["content"] == "Write the report"
    assert props[notion.PROP_ID]["rich_text"][0]["text"]["content"] == "abc12345"
    assert props[notion.PROP_PROJECT]["rich_text"][0]["text"]["content"] == "Rakez"
    assert props[notion.PROP_DONE]["checkbox"] is False
    assert props[notion.PROP_COMPLETED]["date"] is None


def test_upsert_updates_known_page(monkeypatch):
    fake = FakeRequests([
        FakeResponse(payload=_db(**_full_props())),  # ensure_schema
        FakeResponse(payload={"id": "page1"}),       # PATCH page
    ])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")

    page = c.upsert_task(_todo(notion_id="page1", completed=True,
                               completed_at="2026-11-28T10:00:00"))
    assert page == "page1"
    patch = fake.calls[1]
    assert patch["method"] == "PATCH" and patch["url"].endswith("/pages/page1")
    props = patch["json"]["properties"]
    assert props[notion.PROP_DONE]["checkbox"] is True
    assert props[notion.PROP_COMPLETED]["date"]["start"] == "2026-11-28T10:00:00"


def test_set_done_and_archive(monkeypatch):
    fake = FakeRequests([FakeResponse(payload={"id": "page1"}),
                         FakeResponse(payload={"id": "page1"}),
                         FakeResponse(payload={"id": "page1"})])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")

    assert c.set_done("page1", True, "2026-11-28T10:00:00") is True
    body = fake.calls[0]["json"]["properties"]
    assert body[notion.PROP_DONE]["checkbox"] is True
    assert body[notion.PROP_COMPLETED]["date"]["start"].startswith("2026-11-28")

    assert c.set_done("page1", False) is True
    assert fake.calls[1]["json"]["properties"][notion.PROP_COMPLETED]["date"] is None

    assert c.archive("page1") is True


def test_error_messages_are_actionable(monkeypatch):
    fake = FakeRequests([FakeResponse(status=401, payload={"message": "Unauthorized"})])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="bad", database_id="db1")

    assert c._request("GET", "/databases/db1") is None
    assert "401" in c.last_error
    assert "Integration Secret" in c.friendly_error()

    fake = FakeRequests([FakeResponse(status=404, payload={"message": "Not found"})])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")
    assert c._request("GET", "/databases/db1") is None
    assert "Connections" in c.friendly_error()


def test_test_connection_reports_database_name(monkeypatch):
    fake = FakeRequests([FakeResponse(payload=_db(**_full_props())),
                         FakeResponse(payload=_db(**_full_props()))])
    monkeypatch.setattr(notion, "requests", fake)
    c = notion.NotionClient(token="t", database_id="db1")

    res = c.test_connection()
    assert res["ok"] is True
    assert "Rakez Tasks" in res["message"]
