"""Lifebot CLI (typer + rich). Usage: python -m cli.app <command>"""
from __future__ import annotations
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

app = typer.Typer(help="Lifebot productivity system")
console = Console()


def _store() -> SqliteStorage:
    return SqliteStorage()


@app.command()
def add(title: str, category: str = "Deep Work", priority: str = "medium", estimate: int = 1):
    """Add a task."""
    if not (title or "").strip():
        console.print("[red]Title must not be empty[/red]")
        raise typer.Exit(1)
    if estimate < 1:
        console.print("[red]Estimate must be >= 1[/red]")
        raise typer.Exit(1)
    s = _store()
    t = s.add_todo(title, category, priority, estimate)
    console.print(f"[green]Added:[/green] {t['title']} [{t['category']}] (id={t['id']})")


@app.command(name="list")
def list_tasks(all: bool = False):
    """List tasks."""
    s = _store()
    todos = s.get_todos()
    if not all:
        todos = [t for t in todos if not t.get("completed")]
    table = Table(title="Lifebot Tasks")
    table.add_column("ID"); table.add_column("Title"); table.add_column("Cat")
    table.add_column("Pri"); table.add_column("Done"); table.add_column("Pom")
    for t in todos:
        table.add_row(t.get("id","")[:8], t.get("title",""), t.get("category",""),
                      t.get("priority",""), "x" if t.get("completed") else "o",
                      f"{t.get('done_pomodoros',0)}/{t.get('estimate_pomodoros',1)}")
    console.print(table)


@app.command()
def done(key: str):
    """Mark task done by id or title."""
    s = _store()
    ok = s.set_completed(key, True)
    console.print("[green]Done x[/green]" if ok else "[red]Not found[/red]")


@app.command()
def rm(key: str):
    """Delete a task."""
    s = _store()
    ok = s.delete_todo(key)
    console.print("[green]Deleted[/green]" if ok else "[red]Not found[/red]")


@app.command()
def stats(days: int = 7):
    """Show focus stats."""
    s = _store()
    st = s.stats(days=days)
    console.print(f"Sessions: {st['total_logged_sessions']} (last {days}d: {st['recent_sessions']})")
    console.print(f"Focus minutes (last {days}d): {st['recent_focus_minutes']}")
    console.print(f"Tasks: {st['done_tasks']}/{st['total_tasks_count']} done | streak: {st['streak_days']}d")
    if st["by_category_min"]:
        t = Table(title=f"Minutes by category ({days}d)")
        t.add_column("Category"); t.add_column("Min")
        for k, v in sorted(st["by_category_min"].items(), key=lambda x: -x[1]):
            bar = "█" * min(30, max(1, v // 5))
            t.add_row(k, f"{v} {bar}")
        console.print(t)


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
        console.print("[red]Joplin not configured (set JOPLIN_TOKEN)[/red]")
        raise typer.Exit(1)
    res = c.dedupe(folder, dry_run=not apply)
    if res.get("error"):
        console.print(f"[yellow]{res['error']}[/yellow]")
    console.print(f"Duplicate groups: {res['groups']} ({res['dup_notes']} notes)")
    if not apply:
        console.print("Dry run — nothing deleted. Re-run with --apply to clean.")
    else:
        console.print(f"Deleted {len(res['deleted'])} duplicates (see Joplin Trash).")


if __name__ == "__main__":
    app()
