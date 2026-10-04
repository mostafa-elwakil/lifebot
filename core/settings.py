"""App settings persisted as JSON (GUI-editable alternative to .env)."""
from __future__ import annotations
import json
from pathlib import Path

DEFAULTS = {
    "widget_w": 370,
    "widget_h": 104,
    "accent": "#7aa2f7",
    "gemini_key": "",
    "joplin_token": "",
    "joplin_base": "http://127.0.0.1:41184",
    "joplin_folder": "Projects/Lifebot/Tasks",
    "joplin_tags": "task,lifebot",
    "sound": "Default beep",
    "google_client_id": "",
    "google_client_secret": "",
    "design": "pill",
    "background": "#1a1b26",
    "opacity": 95,
}

ACCENTS = {
    "Tokyo Blue": "#7aa2f7",
    "Focus Green": "#9ece6a",
    "Calm Purple": "#bb9af7",
    "Alert Red": "#f7768e",
    "Warm Orange": "#e0af68",
}

#: Notification sound names (patterns live in run_lifebot.SOUND_PATTERNS).
SOUND_NAMES = ["Default beep", "Chime", "Alert", "Silent"]

#: Widget designs.
DESIGNS = {"Glass Pill": "pill", "Neon Card": "neon", "Split Flip": "split",
           "Typewriter": "retro"}

#: Card background colors.
BACKGROUNDS = {
    "Tokyo Night": "#1a1b26",
    "Pure Black": "#0d0d12",
    "Deep Navy": "#16213e",
    "Slate": "#2a2e45",
}

#: Extra combo entry that opens a full color picker.
CUSTOM_LABEL = "🎨 Custom…"


def valid_hex(value: str) -> bool:
    v = (value or "").strip()
    if len(v) != 7 or not v.startswith("#"):
        return False
    try:
        int(v[1:], 16)
        return True
    except ValueError:
        return False

FILENAME = "settings.json"


def settings_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / FILENAME


def load_settings(data_dir: str | Path) -> dict:
    """Load settings, falling back to defaults for missing keys. Never raises."""
    cfg = dict(DEFAULTS)
    try:
        p = settings_path(data_dir)
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS:
                        cfg[k] = v
    except Exception:
        pass
    # sanitize widget size
    try:
        cfg["widget_w"] = max(260, min(700, int(cfg.get("widget_w", 370))))
    except (TypeError, ValueError):
        cfg["widget_w"] = 370
    try:
        cfg["widget_h"] = max(90, min(320, int(cfg.get("widget_h", 104))))
    except (TypeError, ValueError):
        cfg["widget_h"] = 104
    if not valid_hex(cfg.get("accent", "")):
        cfg["accent"] = DEFAULTS["accent"]
    if cfg.get("sound") not in SOUND_NAMES:
        cfg["sound"] = DEFAULTS["sound"]
    if cfg.get("design") not in ("pill", "neon", "split", "retro"):
        cfg["design"] = DEFAULTS["design"]
    if not valid_hex(cfg.get("background", "")):
        cfg["background"] = DEFAULTS["background"]
    try:
        cfg["opacity"] = max(30, min(100, int(cfg.get("opacity", 95))))
    except (TypeError, ValueError):
        cfg["opacity"] = 95
    return cfg


def save_settings(data_dir: str | Path, cfg: dict) -> bool:
    """Persist known keys only. Returns True on success."""
    try:
        p = settings_path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        p.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False
