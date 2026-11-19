"""Telegram integration: report text, commands, and completed_at bookkeeping.

No network: ``core.telegram.requests`` is replaced with a fake that records
the Bot API calls and returns canned results.
"""
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

import core.telegram as telegram
from core.settings import load_settings, save_settings
from core.storage import SqliteStorage
from core.telegram import TelegramBot


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeRequests:
    """Records every Bot API call; ``result`` feeds getUpdates."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else []

    def post(self, url, json=None, timeout=None):
        payload = json or {}
        self.calls.append({"url": url, "json": payload, "timeout": timeout})
        method = url.rsplit("/", 1)[-1]
        if method == "getMe":
            return _Resp({"ok": True, "result": {"username": "rakez_bot"}})
        if method == "getUpdates":
            return _Resp({"ok": True, "result": self.result})
        return _Resp({"ok": True, "result": {"message_id": 1}})

    def sent(self):
        return [c["json"]["text"] for c in self.calls
                if c["url"].endswith("/sendMessage")]


@pytest.fixture()
def storage():
    with tempfile.TemporaryDirectory() as td:
        s = SqliteStorage(data_dir=Path(td))
        # a fresh DB is seeded with demo tasks — clear them for exact counts
        for todo in s.get_todos():
            s.delete_todo(todo["id"])
        try:
            yield s
        finally:
            s.close()


@pytest.fixture()
def bot(storage, monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(telegram, "requests", fake)
    b = TelegramBot(token="123:abc", chat_id="42", storage=storage)
    b.fake = fake
    return b


def _message(text, chat_id=42):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


# ---- gating ----
def test_unconfigured_bot_is_a_noop(storage, monkeypatch):
    monkeypatch.setattr(telegram, "requests", FakeRequests())
    b = TelegramBot(token="", storage=storage)
    assert not b.available and not b.configured
    assert b.send("hi") is False


def test_token_without_chat_is_not_configured(storage, monkeypatch):
    monkeypatch.setattr(telegram, "requests", FakeRequests())
    b = TelegramBot(token="1:a", chat_id="", storage=storage)
    assert b.available and not b.configured


# ---- sending ----
def test_send_posts_to_the_configured_chat(bot):
    assert bot.send("hello")
    call = bot.fake.calls[-1]
    assert call["url"].endswith("/bot123:abc/sendMessage")
    assert call["json"]["chat_id"] == "42"
    assert call["json"]["text"] == "hello"


def test_long_messages_are_split(bot):
    long_text = "\n".join("x" * 100 for _ in range(100))  # ~10k chars
    assert bot.send(long_text)
    chunks = bot.fake.sent()
    assert len(chunks) > 1
    assert all(len(chunk) <= 4000 for chunk in chunks)


def test_get_updates_advances_the_offset(bot):
    bot.fake.result = [{"update_id": 7, "message": {"chat": {"id": 42}, "text": "/tasks"}}]
    updates = bot.get_updates(timeout=0)
    assert len(updates) == 1
    assert bot.offset == 8


def test_configure_resets_offset_when_token_changes(storage, monkeypatch):
    monkeypatch.setattr(telegram, "requests", FakeRequests())
    b = TelegramBot(token="1:a", chat_id="42", storage=storage)
    b.offset = 99
    b.configure(token="2:b", chat_id="77")
    assert b.offset == 0
    assert b.chat_id == "77"
    assert b._base.endswith("/bot2:b")

    b.offset = 5
    b.configure(chat_id="88")  # same token keeps the offset
    assert b.offset == 5
    assert b.chat_id == "88"


# ---- report ----
def test_report_lists_done_today_remaining_and_projects(bot, storage):
    done = storage.add_todo("Write docs")
    storage.add_todo("Build app")
    project = storage.create_project("Website")
    storage.add_todo("Design", project_id=project["id"])
    storage.set_completed(done["id"], True)

    text = bot.report_text()
    assert "Write docs" in text
    assert "Done today (1)" in text
    assert "Remaining tasks (2)" in text
    assert "Website" in text and "0/1" in text


def test_report_escapes_html(bot, storage):
    storage.add_todo("<b>bad</b>")
    assert "&lt;b&gt;bad&lt;/b&gt;" in bot.report_text()


def test_report_without_store():
    assert TelegramBot(token="1:a").report_text() == "No data store available."


# ---- commands ----
def test_done_by_number(bot, storage):
    first = storage.add_todo("First")
    second = storage.add_todo("Second")

    assert bot.handle_update(_message("/done 1")) is True
    assert storage.get_todo(first["id"])["completed"] is True
    assert storage.get_todo(second["id"])["completed"] is False
    assert "Done: First" in bot.fake.sent()[-1]


def test_done_by_title(bot, storage):
    todo = storage.add_todo("Review the release")
    assert bot.handle_update(_message("/done Review the release")) is True
    assert storage.get_todo(todo["id"])["completed"] is True


def test_done_reply_escapes_html_in_the_title(bot, storage):
    storage.add_todo("A < B")
    assert bot.handle_update(_message("/done A < B")) is True
    assert "A &lt; B" in bot.fake.sent()[-1]


def test_done_out_of_range_replies_without_changing(bot, storage):
    storage.add_todo("Only one")
    assert bot.handle_update(_message("/done 9")) is False
    assert "No task number 9" in bot.fake.sent()[-1]


def test_add_with_project(bot, storage):
    assert bot.handle_update(_message("/add Ship it | Launch")) is True
    todo = next(t for t in storage.get_todos() if t["title"] == "Ship it")
    assert storage.get_project(todo["project_id"])["name"] == "Launch"


def test_plain_message_adds_a_task(bot, storage):
    assert bot.handle_update(_message("Buy milk")) is True
    assert any(t["title"] == "Buy milk" for t in storage.get_todos())


def test_stranger_is_ignored_when_chat_is_configured(bot, storage):
    assert bot.handle_update(_message("/add Hacked", chat_id=999)) is False
    assert not any(t["title"] == "Hacked" for t in storage.get_todos())


def test_start_reveals_the_chat_id(bot):
    bot.chat_id = ""
    bot.handle_update(_message("/start", chat_id=777))
    assert bot.last_chat_id == "777"
    assert "777" in bot.fake.sent()[-1]


def test_unknown_command_returns_help(bot):
    bot.handle_update(_message("/nonsense"))
    assert "/report" in bot.fake.sent()[-1]


def test_tasks_and_projects_commands(bot, storage):
    storage.add_todo("Alpha")
    project = storage.create_project("Beta")
    storage.add_todo("Gamma", project_id=project["id"])
    bot.handle_update(_message("/tasks"))
    assert "Alpha" in bot.fake.sent()[-1]
    bot.handle_update(_message("/projects"))
    assert "Beta" in bot.fake.sent()[-1]


# ---- completed_at ----
def test_set_completed_records_and_clears_completed_at(storage):
    todo = storage.add_todo("Finish me")
    assert todo["completed_at"] == ""

    storage.set_completed(todo["id"], True)
    row = storage.get_todo(todo["id"])
    assert row["completed"] is True
    assert row["completed_at"][:10] == datetime.now().date().isoformat()

    storage.set_completed(todo["id"], False)
    row = storage.get_todo(todo["id"])
    assert row["completed"] is False
    assert row["completed_at"] == ""


def test_update_todo_keeps_completed_at_in_sync(storage):
    todo = storage.add_todo("Via update")
    storage.update_todo(todo["id"], {"completed": True})
    assert storage.get_todo(todo["id"])["completed_at"]

    storage.update_todo(todo["id"], {"completed": False})
    assert storage.get_todo(todo["id"])["completed_at"] == ""


# ---- settings ----
def test_telegram_settings_defaults_and_sanitize():
    with tempfile.TemporaryDirectory() as td:
        cfg = load_settings(td)
        assert cfg["telegram_reports"] is True
        assert cfg["telegram_daily"] is False
        assert cfg["telegram_daily_hour"] == 20

        cfg["telegram_daily_hour"] = 99
        cfg["telegram_token"] = "  123  "
        assert save_settings(td, cfg)

        again = load_settings(td)
        assert again["telegram_daily_hour"] == 23
        assert again["telegram_token"] == "123"
