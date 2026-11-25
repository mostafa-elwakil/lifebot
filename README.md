<div align="center">

<img src="assets/logo.svg" width="88" alt="Rakez logo" />

# Rakez ركّز
**A complete personal productivity system: floating Pomodoro + tasks and projects + AI coach + Joplin and Google sync.**

[![Release](https://img.shields.io/github/v/release/mostafa-elwakil/lifebot?label=latest&color=7aa2f7)](https://github.com/mostafa-elwakil/lifebot/releases/latest)
[![Build](https://github.com/mostafa-elwakil/lifebot/actions/workflows/build-windows.yml/badge.svg)](https://github.com/mostafa-elwakil/lifebot/actions/workflows/build-windows.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-9ece6a)](#-download)

**🌐 [العربية](README.ar.md) · [English](README.md)**

[Download](#-download) · [Features](#-features) · [Website](#-website) · [Troubleshooting](#-troubleshooting)

</div>

---

## ✨ Features

### ⏱️ A floating Pomodoro above every app
- Always-on-top timer with several designs: **Glass Pill / Neon Card / Split Flip / Typewriter**.
- Focus periods + automatic short/long breaks (long break every 4 cycles), sound alerts, notifications, and a live progress bar.
- Play/pause, reset, and switch tasks right from the widget.

### 📁 Projects with progress
- Create **projects**, put tasks inside them, and get the progress automatically: `2/5 (40%)`.
- Tasks are grouped under each project header, plus a section for ungrouped tasks.
- Move an existing task into a project, or create a new project from the same dialog.
- Deleting a project keeps its tasks — they simply become ungrouped.

### 🧠 Hermes AI coach
- A morning plan, help resolving excuses, and a daily review.
- Works with **Gemini** when you add a key; without one it offers a genuinely useful **Offline** mode.

### 🔄 Two-way sync
- **Joplin**: your tasks show up instantly in `Projects/Lifebot/Tasks` with tags and a due date, and you can pull Joplin to-dos into the app (Pull button + automatically on startup). The `dedupe` command cleans up duplicates.
- **Google Tasks**: push/pull tasks.
- **Google Calendar**: finished focus sessions are logged as events automatically.
- **Test connection** really checks your permissions and returns friendly error messages (for example `access_denied` with the exact fix).

### 📊 Analytics and progress
- Focus minutes over the last 7 days, minutes per category, streak, and completed tasks.

### 🎨 Light and dark themes
- **Dark (Tokyo Night)** and **Light (Paper)** themes for both the dashboard and the widget.
- Custom accent color, widget size, opacity, and background (including light backgrounds).

### ⬆️ One-click updates
- The app checks GitHub Releases on startup; **Download & Install update** downloads the installer with a progress bar, installs it, and closes the app — no release page needed.

### 💻 CLI + local API
- Everything is available from the terminal (add/complete/stats/projects/sync).
- A local HTTP API for integrations, protectable with a bearer token and startable from **Settings → 🌐 API**.

### 🌐 Arabic and English UI
- Switch language in **Settings → ⚙️ General** — the window, the widget, and every message change instantly with no restart.
- English is the default; Arabic can be picked manually or automatically from the system language on first run.
- The same switch exists in the CLI: `python -m cli.app --lang ar projects`.

### ✈️ Telegram bot
- **Ready-made reports**: what you finished today, the remaining tasks, per-project progress, and focus minutes.
- **Automatic daily report** at the hour you choose (default 8 PM).
- **Instant notification** whenever a task is completed — from the app or the floating widget.
- **Full control from your phone**: `/add title` to add a task, `/done 3` to finish task number 3, `/tasks`, `/projects`, `/report`.
- Any plain message to the bot becomes a new task, and `/add title | project` puts it inside a project.
- Runs as background long polling, so it never freezes or slows the UI.

---

## 📥 Download

> **Windows 10/11** — no Python required.

[**⬇️ Download the latest release (Rakez-Setup.exe)**](https://github.com/mostafa-elwakil/lifebot/releases/latest)

1. Download the installer and run it (optionally create a desktop shortcut).
2. Open Rakez — your data is stored in `%APPDATA%\Rakez\data`.
3. Future updates are one click away: **Settings → Check for updates → Download & Install**.

> Note: the installer is not signed with a Code Signing certificate, so Windows SmartScreen may show “Unknown publisher”. Press **More info → Run anyway** — the publisher in the file properties is **Mostafa Elwakil**.
>
> Linux: `bash packaging/build_linux.sh` after installing the requirements.

---

## 🌐 Website

Marketing site (GitHub Pages): **https://mostafa-elwakil.github.io/lifebot/** — Arabic version: **/ar/**

Source in [`website/`](website) — an English page at the root and an Arabic RTL page under `ar/`, with a language switch, a modern light/dark design, and automatic download of the latest release.

---

## 🚀 Run from source | Quickstart

```bash
git clone https://github.com/mostafa-elwakil/lifebot.git
cd lifebot
pip install -r requirements.txt
cp .env.example .env        # optional — fill in what you need
python run_lifebot.py       # GUI
```

Try the CLI:

```bash
python -m cli.app list
python -m cli.app add "Design the landing page" --project Website --priority high
python -m cli.app projects
python -m cli.app stats --days 7
python -m cli.app google-test          # check the Google connection
python -m pytest tests -q              # 87 tests
```

---

## ⚙️ Configuration

### `.env` variables (all optional)

```env
GEMINI_API_KEY=            # Hermes coach online (offline mode without it)
JOPLIN_TOKEN=              # Joplin Desktop → Settings → Web Clipper
JOPLIN_BASE_URL=http://127.0.0.1:41184
GOOGLE_CLIENT_ID=          # from Google Cloud Console (Desktop app)
GOOGLE_CLIENT_SECRET=
API_TOKEN=                 # protects the local HTTP API (Bearer)
TELEGRAM_BOT_TOKEN=        # bot token from @BotFather (optional)
TELEGRAM_CHAT_ID=          # your Telegram chat ID (optional)
```

### `config/config.yaml`

```yaml
joplin:
  base_url: "http://127.0.0.1:41184"
  token: "YOUR_JOPLIN_TOKEN"
  folder_name: "Projects/Lifebot/Tasks"   # nested paths supported, missing ones created
  tags: "task,lifebot"                    # tags for Kanban boards
```

> Joplin requires **Joplin Desktop to be open** (Web Clipper on port `41184`). The Synchronise button is not needed to create notes.

### Connecting Google (Calendar + Tasks)

1. [Google Cloud Console](https://console.cloud.google.com) → new project.
2. Enable **Google Calendar API** and **Google Tasks API**.
3. **OAuth consent screen** → External → add your email under **Test users**.
4. **Credentials → Create OAuth client ID → Desktop app** → copy the Client ID + Secret.
5. Inside Rakez → **Settings → 🌐 API**: paste both values → **💾 Save settings**, then open **Integrations → 🔓 Authorize** → **🔌 Test connection**.

> ⚠️ If you see **"Access blocked: Rakez has not completed verification"**, your account is not a Test user. Add it under OAuth consent screen → Test users. The app shows these steps automatically.
>
> In Testing mode the token expires every 7 days. For a permanent fix: **Publish app** → In production (the “unverified” screen is normal for a personal app).

### Connecting Telegram (reports + remote tasks)

1. Open [@BotFather](https://t.me/BotFather) in Telegram → `/newbot` → copy the **Token**.
2. In Rakez → **Settings → 🌐 API**: paste the token → **💾 Save settings**.
3. In Telegram, send `/start` to your bot, then in **Settings → 🔗 Integrations** press **🔎 Detect chat ID** (or send `/id` and copy the number).
4. Press **🔌 Test** — a test message arrives — then **📊 Send report now**.
5. Optionally enable **Notify me when a task is completed** and **Daily report at 20:00**.

Bot commands: `/report` · `/tasks` · `/done N` · `/done id` · `/add title | project` · `/projects` · `/id` · `/help`.

---

## 🖥️ Usage

### GUI

| Tab | What it does |
|---|---|
| ⏱️ Pomodoro | Pick a task and duration → send it to the floating widget and start |
| 📋 Tasks | Add/complete/delete, projects and progress, push/pull Joplin and Google |
| 🧠 Hermes | Morning plan / resolve a snag / daily review |
| 📊 Analytics | Focus stats, categories, and streak |
| ⚙️ Settings | Sidebar sections: General, Appearance, Floating widget, Integrations, **API** (all keys + the local HTTP server), Updates |

Shortcuts: `Enter` to add a task, `double-click` to complete it.

### Command line

```bash
python -m cli.app list                          # open tasks
python -m cli.app add "Task" -p Website        # add inside a project (creates it if new)
python -m cli.app projects                      # projects and their progress
python -m cli.app assign "Task" "Project"      # move a task into a project
python -m cli.app done <id|title>
python -m cli.app rm <id|title>
python -m cli.app stats --days 7
python -m cli.app plan | python -m cli.app review
python -m cli.app dedupe [--apply]
python -m cli.app google-test [--authorize]
python -m cli.app telegram-test                # token check + test message
python -m cli.app telegram-chat-id             # detect the chat ID
python -m cli.app telegram-report [--no-send]  # report (and send it)
python -m cli.app telegram-poll                # run the bot in the terminal
python -m cli.app serve --port 8765
python -m cli.app --lang ar list               # Arabic output
```

---

## 🔌 Local HTTP API

Start it from **Settings → 🌐 API** (**Port**, optional **API token**, **▶ Start**, **🧪 Test**, **📋 Copy URL**) or from the terminal:

```bash
python -m cli.app serve --port 8765
# API_TOKEN=secret python -m cli.app serve    # requires Authorization: Bearer <token>
```

| Request | Description |
|---|---|
| `GET /health` | Health check |
| `GET /tasks` · `POST /tasks` | List/create `{title, category?, priority?, estimate?, project_id?}` |
| `PUT /tasks/<id-or-title>` | Update `{completed?, title?, category?, priority?, project_id?}` |
| `DELETE /tasks/<id-or-title>` | Delete a task |
| `GET /projects` | Projects with `total/done/pct` |
| `POST /projects` | Create a project `{name}` |
| `DELETE /projects/<id-or-name>` | Delete a project (its tasks stay ungrouped) |
| `GET /projects/<id>/tasks` | Tasks of a project (`_NO_PROJECT_` for ungrouped) |
| `GET /sessions` · `POST /sessions` | Focus sessions |
| `GET /stats?days=7` | Statistics |

---

## 🧪 Development and build

```bash
python -m pytest tests -q          # 87 tests

python packaging/build_windows.py  # dist/Rakez.exe
iscc packaging/Rakez.iss           # dist/Rakez-Setup-<version>.exe
```

- The current version lives in: `core/updater.py` (`APP_VERSION`), `packaging/Rakez.iss`, `packaging/version_info.txt`.
- **GitHub Actions** builds and tests the installer on every new **tag** (`v*`) and publishes it to Releases.
- The marketing site is published automatically from `website/` via GitHub Pages.

### Project layout

```
run_lifebot.py        GUI (PyQt6) + floating widget
core/
  models.py           task models
  storage.py          SQLite + projects + JSON migration
  coach.py            Hermes (Gemini + offline)
  joplin.py           Joplin Web Clipper client
  google_sync.py      Calendar + Tasks (OAuth2)
  telegram.py         Telegram bot (reports + commands)
  updater.py          update check/download/install
  api.py              local HTTP API
  i18n.py             English/Arabic strings + Qt translator
  settings.py         settings and themes
cli/app.py            Typer commands
config/               config.yaml + prompt.py
website/              marketing site (GitHub Pages)
packaging/            PyInstaller + Inno Setup + Linux
tests/                87 tests
```

---

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| `Joplin busy — wait and retry` | Joplin is syncing — wait a few seconds and retry |
| `Joplin not configured` | Add `JOPLIN_TOKEN` or paste it in Settings |
| Pull finds nothing | The to-do must be a **New to-do** inside the same notebook |
| `access_denied` from Google | Add your email under Test users (the in-app message explains the steps) |
| `invalid_client` | Re-copy the Client ID/Secret and make sure the type is **Desktop app** |
| No update appears | Check your connection, or download the installer manually from Releases |
| Data missing after an update | Your data is in `%APPDATA%\Rakez\data` and is never touched by updates |

---

<div align="center">

Made with ❤️ by **Mostafa Elwakil**

⭐ If you like the project, give it a star on GitHub

</div>
