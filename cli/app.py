"""Rakez CLI (typer + rich). Usage: python -m cli.app <command>"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import typer
from rich.table import Table
from rich.console import Console

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from core.storage import SqliteStorage
from core.coach import HermesCoach
from core.joplin import DEFAULT_FOLDER as JOPLIN_DEFAULT_FOLDER
from core.i18n import set_language, t as tr, tf

app = typer.Typer(help="Rakez focus system")
console = Console()


@app.callback()
def main(lang: str = typer.Option("en", "--lang", "-l",
                                  help="Output language: en or ar")):
    """Rakez focus system — bilingual CLI (English / العربية)."""
    set_language(lang)


_hub = None


def _store() -> SqliteStorage:
    """Open the database and wire automatic integration sync (same as the GUI)."""
    global _hub
    store = SqliteStorage()
    try:
        from core.settings import load_settings
        from core.joplin import JoplinClient
        from core.google_sync import GoogleSync
        from core.notion import NotionClient
        from core.sync import IntegrationHub
        from core.telegram import TelegramBot
        cfg = load_settings(_data_dir())
        joplin = JoplinClient(
            base_url=cfg.get("joplin_base") or os.getenv("JOPLIN_BASE_URL", ""),
            token=cfg.get("joplin_token") or os.getenv("JOPLIN_TOKEN", ""))
        google = GoogleSync(
            data_dir=_data_dir(),
            client_id=cfg.get("google_client_id") or os.getenv("GOOGLE_CLIENT_ID", ""),
            client_secret=cfg.get("google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET", ""))
        notion = NotionClient(
            token=cfg.get("notion_token") or os.getenv("NOTION_TOKEN", ""),
            database_id=cfg.get("notion_database_id") or os.getenv("NOTION_DATABASE_ID", ""))
        telegram = TelegramBot(
            token=cfg.get("telegram_token") or os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=cfg.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", ""),
            storage=store)

        def notify_done(title: str):
            if cfg.get("telegram_reports", True) and telegram.configured:
                remaining = len([x for x in store.get_todos() if not x.get("completed")])
                telegram.send(tf("✅ Done: {name}\n📋 {n} task(s) left.",
                                 name=title, n=remaining))

        hub = IntegrationHub(
            store, joplin=joplin, google=google, notion=notion,
            enabled=lambda: bool(cfg.get("auto_sync", True)),
            notify_done=notify_done,
            project_lookup=lambda pid: (store.get_project(pid) or {}).get("name", ""),
            joplin_folder=cfg.get("joplin_folder", JOPLIN_DEFAULT_FOLDER),
            joplin_tags=cfg.get("joplin_tags", "task,lifebot"))
        hub.attach()
        _hub = hub
    except Exception:
        _hub = None
    return store


def _flush_sync(timeout: float = 15.0) -> None:
    """Wait for the background sync queue before the CLI process exits."""
    if _hub is not None:
        try:
            _hub.flush(timeout)
        except Exception:
            pass


def _data_dir() -> Path:
    """Where settings.json lives (matches run_lifebot's DATA_DIR)."""
    if getattr(sys, "frozen", False):
        if os.name == "nt":
            return Path(os.getenv("APPDATA", ".")) / "Rakez" / "data"
        return Path.home() / ".local" / "share" / "Rakez" / "data"
    return Path(__file__).resolve().parent.parent / "data"


def _telegram_bot():
    """TelegramBot from settings.json (falling back to environment variables)."""
    from core.settings import load_settings
    from core.telegram import TelegramBot
    cfg = load_settings(_data_dir())
    return TelegramBot(
        token=cfg.get("telegram_token") or os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=cfg.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", ""),
        storage=_store())


def _plain(text: str) -> str:
    """Strip the HTML tags used for Telegram's parse mode (CLI display)."""
    for tag in ("<b>", "</b>", "<i>", "</i>"):
        text = text.replace(tag, "")
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


@app.command()
def add(title: str, category: str = "Deep Work", priority: str = "medium", estimate: int = 1,
        project: str = typer.Option("", "--project", "-p", help="Project name (created if new)")):
    """Add a task."""
    if not (title or "").strip():
        console.print(f"[red]{tr('Title must not be empty')}[/red]")
        raise typer.Exit(1)
    if estimate < 1:
        console.print(f"[red]{tr('Estimate must be >= 1')}[/red]")
        raise typer.Exit(1)
    s = _store()
    pid = ""
    if (project or "").strip():
        proj = s.get_project_by_name(project)
        if proj is None:
            try:
                proj = s.create_project(project)
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(1)
        pid = proj["id"]
    t = s.add_todo(title, category, priority, estimate, project_id=pid)
    _flush_sync()
    label = f" [{proj['name']}]" if proj else ""
    console.print(f"[green]{tr('Added:')}[/green] {t['title']}{label} "
                  f"[{tr(t['category'])}] (id={t['id']})")


@app.command()
def projects():
    """List projects with progress."""
    s = _store()
    table = Table(title=tr("Rakez Projects"))
    table.add_column(tr("ID")); table.add_column(tr("Name"))
    table.add_column(tr("Progress"))
    table.add_column(tr("Tasks")); table.add_column("%")
    for p in s.get_projects():
        table.add_row(p["id"], p["name"], f"{p['done']}/{p['total']}", "", f"{p['pct']}%")
    console.print(table)


@app.command()
def assign(key: str, project: str):
    """Move a task (id or title) into a project (creates it if new)."""
    s = _store()
    proj = s.get_project_by_name(project)
    if proj is None:
        try:
            proj = s.create_project(project)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    try:
        updated = s.update_todo(key, {"project_id": proj["id"]})
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if updated is None:
        console.print(f"[red]{tr('Task not found')}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{tr('Assigned:')}[/green] {updated['title']} → {proj['name']}")


@app.command(name="list")
def list_tasks(all: bool = False):
    """List tasks."""
    s = _store()
    todos = s.get_todos()
    if not all:
        todos = [t for t in todos if not t.get("completed")]
    table = Table(title=tr("Rakez Tasks"))
    table.add_column(tr("ID")); table.add_column(tr("Title"))
    table.add_column(tr("Cat"))
    table.add_column(tr("Pri")); table.add_column(tr("Done")); table.add_column("Pom")
    for t in todos:
        table.add_row(t.get("id","")[:8], t.get("title",""), tr(t.get("category","")),
                      tr(t.get("priority","")), "x" if t.get("completed") else "o",
                      f"{t.get('done_pomodoros',0)}/{t.get('estimate_pomodoros',1)}")
    console.print(table)


@app.command()
def done(key: str):
    """Mark task done by id or title."""
    s = _store()
    ok = s.set_completed(key, True)
    _flush_sync()
    console.print(f"[green]{tr('Done x')}[/green]" if ok
                  else f"[red]{tr('Not found')}[/red]")


@app.command()
def rm(key: str):
    """Delete a task."""
    s = _store()
    ok = s.delete_todo(key)
    _flush_sync()
    console.print(f"[green]{tr('Deleted')}[/green]" if ok
                  else f"[red]{tr('Not found')}[/red]")


@app.command()
def stats(days: int = 7):
    """Show focus stats."""
    s = _store()
    st = s.stats(days=days)
    console.print(tf("Sessions: {total} (last {days}d: {recent})",
                     total=st['total_logged_sessions'], days=days,
                     recent=st['recent_sessions']))
    console.print(tf("Focus minutes (last {days}d): {minutes}",
                     days=days, minutes=st['recent_focus_minutes']))
    console.print(tf("Tasks: {done}/{total} done | streak: {streak}d",
                     done=st['done_tasks'], total=st['total_tasks_count'],
                     streak=st['streak_days']))
    if st["by_category_min"]:
        tbl = Table(title=tf("Minutes by category ({days}d)", days=days))
        tbl.add_column(tr("Category")); tbl.add_column("Min")
        for k, v in sorted(st["by_category_min"].items(), key=lambda x: -x[1]):
            bar = "█" * min(30, max(1, v // 5))
            tbl.add_row(tr(k), f"{v} {bar}")
        console.print(tbl)


@app.command(name="google-test")
def google_test(authorize: bool = typer.Option(False, "--authorize", "-a",
                                               help="Run the browser OAuth flow first")):
    """Test the Google Calendar + Tasks connection (real API calls)."""
    from core.google_sync import GoogleSync
    from core.settings import load_settings
    cfg = load_settings(_data_dir())
    gs = GoogleSync(data_dir=_data_dir(),
                    client_id=cfg.get("google_client_id", ""),
                    client_secret=cfg.get("google_client_secret", ""))
    if authorize:
        console.print(tr("Opening browser for Google authorization..."))
        if not gs.authorize():
            console.print(f"[red]{tr('Authorization failed:')}[/red] {gs.last_error}")
            raise typer.Exit(1)
        console.print(f"[green]{tr('Authorized.')}[/green] "
                      f"{tr('Token saved to data/google_token.json')}")
    res = gs.test_connection()
    color = "green" if res["ok"] else "yellow"
    console.print(f"[{color}]{res['message']}[/{color}]")
    if not res["ok"]:
        raise typer.Exit(1)


@app.command(name="notion-test")
def notion_test():
    """Test the Notion token + database and create the properties Rakez needs."""
    from core.notion import NotionClient
    from core.settings import load_settings
    cfg = load_settings(_data_dir())
    client = NotionClient(
        token=cfg.get("notion_token") or os.getenv("NOTION_TOKEN", ""),
        database_id=cfg.get("notion_database_id") or os.getenv("NOTION_DATABASE_ID", ""))
    res = client.test_connection()
    color = "green" if res.get("ok") else "yellow"
    console.print(f"[{color}]{res.get('message', '')}[/{color}]")
    if not res.get("ok"):
        raise typer.Exit(1)


@app.command()
def sync():
    """Push every task to every configured service (Joplin, Google Tasks, Notion)."""
    _store()
    if _hub is None:
        console.print(f"[yellow]{tr('No integrations configured yet.')}[/yellow]")
        return
    res = _hub.sync_all()
    j = res.get("joplin") or {}
    if j:
        console.print(tr("Joplin: {c} added, {u} updated, {d} completed").format(
            c=j.get("created", 0), u=j.get("updated", 0), d=j.get("completed", 0)))
    g = res.get("google") or {}
    if g:
        console.print(tr("Google Tasks: {n} pushed").format(n=g.get("pushed", 0)))
    n = res.get("notion") or {}
    if n:
        console.print(tr("Notion: {c} created, {u} updated").format(
            c=n.get("created", 0), u=n.get("updated", 0)))
    for err in res.get("errors") or []:
        console.print(f"[yellow]{err}[/yellow]")


@app.command()
def plan():
    """Print morning plan."""
    s = _store()
    console.print(HermesCoach().morning_plan(s.get_todos()))


@app.command()
def review():
    """Print daily review."""
    s = _store()
    console.print(HermesCoach().daily_review(s.get_sessions(), s.get_todos()))


@app.command()
def dedupe(folder: str = JOPLIN_DEFAULT_FOLDER, apply: bool = False):
    """Report (default) or delete duplicate Joplin todos, keeping newest."""
    from core.joplin import JoplinClient
    c = JoplinClient()
    if not c.available:
        console.print(f"[red]{tr('Joplin not configured (set JOPLIN_TOKEN)')}[/red]")
        raise typer.Exit(1)
    res = c.dedupe(folder, dry_run=not apply)
    if res.get("error"):
        console.print(f"[yellow]{res['error']}[/yellow]")
    console.print(tf("Duplicate groups: {groups} ({notes} notes)",
                     groups=res['groups'], notes=res['dup_notes']))
    if not apply:
        console.print(tr("Dry run — nothing deleted. Re-run with --apply to clean."))
    else:
        console.print(tf("Deleted {n} duplicates (see Joplin Trash).",
                         n=len(res['deleted'])))


@app.command(name="telegram-test")
def telegram_test():
    """Check the Telegram bot token and send a test message."""
    bot = _telegram_bot()
    if not bot.token:
        console.print(f"[red]{tr('Telegram token missing (Settings → API)')}[/red]")
        raise typer.Exit(1)
    me = bot.me()
    if me is None:
        console.print(f"[red]{tf('Telegram error: {err}', err=bot.last_error)}[/red]")
        raise typer.Exit(1)
    name = me.get("username") or me.get("first_name") or "bot"
    console.print(f"[green]{tf('Connected as @{name}', name=name)}[/green]")
    if not bot.chat_id:
        console.print(f"[yellow]{tr('No chat ID yet — send /start to the bot, then run telegram-chat-id')}[/yellow]")
        return
    if bot.send(tf("✅ Rakez CLI test — @{name}", name=name)):
        console.print(f"[green]{tr('Test message sent')}[/green]")
    else:
        console.print(f"[red]{tf('Send failed: {err}', err=bot.last_error)}[/red]")
        raise typer.Exit(1)


@app.command(name="telegram-chat-id")
def telegram_chat_id():
    """Detect the chat ID from the latest message sent to the bot."""
    bot = _telegram_bot()
    if not bot.token:
        console.print(f"[red]{tr('Telegram token missing (Settings → API)')}[/red]")
        raise typer.Exit(1)
    chat = bot.detect_chat_id()
    if chat:
        console.print(f"[green]{tf('Chat ID: {id}', id=chat)}[/green]")
        console.print(tr("Save it in Settings → 🔗 Integrations (Chat ID) to receive reports."))
    else:
        console.print(f"[yellow]{tr('No messages found — send /start to your bot and try again.')}[/yellow]")


@app.command(name="telegram-report")
def telegram_report(send: bool = typer.Option(True, "--send/--no-send",
                                              help="Send it to Telegram (default) or only print it")):
    """Print the done-today + remaining-tasks report (and send it to Telegram)."""
    bot = _telegram_bot()
    report = bot.report_text(bot.storage)
    console.print(_plain(report))
    if not send:
        return
    if not bot.configured:
        console.print(f"[yellow]{tr('Token or chat ID missing — report not sent.')}[/yellow]")
        return
    if bot.send(report):
        console.print(f"[green]{tr('Report sent to Telegram')}[/green]")
    else:
        console.print(f"[red]{tf('Send failed: {err}', err=bot.last_error)}[/red]")
        raise typer.Exit(1)


@app.command(name="telegram-poll")
def telegram_poll():
    """Run the bot command loop in the terminal (Ctrl+C to stop)."""
    import time
    bot = _telegram_bot()
    if not bot.available:
        console.print(f"[red]{tr('Telegram token missing (Settings → API)')}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{tr('Listening for Telegram commands… Ctrl+C to stop')}[/green]")
    try:
        while True:
            updates = bot.get_updates()
            for update in updates:
                bot.handle_update(update)
            if not updates:
                time.sleep(2)
    except KeyboardInterrupt:
        console.print(f"[yellow]{tr('Stopped')}[/yellow]")


@app.command()
def serve(port: int = 8765):
    """Run the local HTTP API (for TestSprite backend runs and integrations)."""
    from core.api import run_server
    console.print(f"Rakez API on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    run_server(port=port, store=_store())


if __name__ == "__main__":
    app()
