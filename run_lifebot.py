import sys
import os
import json
import tempfile
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PyQt6.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QAction, QIcon, QCursor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox, QMessageBox,
    QInputDialog, QSystemTrayIcon, QMenu,
    QCheckBox, QSizePolicy, QSizeGrip, QProgressBar, QGridLayout, QFrame,
    QScrollArea, QStackedWidget, QButtonGroup
)

from core.storage import SqliteStorage, CATEGORIES
from core.coach import HermesCoach
from core.joplin import JoplinClient, DEFAULT_FOLDER as JOPLIN_DEFAULT_FOLDER
from core.settings import load_settings, save_settings, ACCENTS, DEFAULTS as SETTINGS_DEFAULTS
from core.settings import (SOUND_NAMES, DESIGNS, BACKGROUNDS, THEMES,
                           THEME_BACKGROUNDS, valid_hex, is_light_color)
from core.google_sync import GoogleSync
from core.notion import NotionClient
from core.sync import IntegrationHub
from core.telegram import TelegramBot
from core.api import run_server
from core.i18n import (LANGUAGES, detect_language, get_language, is_arabic,
                       set_language, t, tf, translate_tree)
from core import updater

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

if getattr(sys, "frozen", False):
    # Running from a PyInstaller bundle: _MEIPASS is read-only temp,
    # so user data + .env live outside the bundle.
    if os.name == "nt":
        DATA_DIR = Path(os.getenv("APPDATA", ".")) / "Rakez" / "data"
        _exe_dir = Path(sys.executable).resolve().parent
    else:
        DATA_DIR = Path.home() / ".local" / "share" / "Rakez" / "data"
        _exe_dir = Path(sys.executable).resolve().parent
    try:
        from dotenv import load_dotenv
        load_dotenv(_exe_dir / ".env")
        load_dotenv(DATA_DIR / ".env")
    except Exception:
        pass

DEFAULTS = {"focus": 25, "short_break": 5, "long_break": 15}
try:
    cfg = yaml.safe_load((PROJECT_ROOT / "config" / "config.yaml").read_text(encoding="utf-8")) or {}
    pom = cfg.get("pomodoro", {})
    DEFAULTS["focus"] = int(pom.get("default_duration_min", 25))
    DEFAULTS["short_break"] = int(pom.get("short_break_min", 5))
    DEFAULTS["long_break"] = int(pom.get("long_break_min", 15))
    _joplin_cfg = cfg.get("joplin", {})
    _ai_cfg = cfg.get("ai_coach", {})
except Exception:
    _joplin_cfg = {}
    _ai_cfg = {}


SOUND_PATTERNS = {
    "Default beep": [(880, 300), (660, 300)],
    "Chime": [(660, 200), (880, 200), (1320, 350)],
    "Alert": [(440, 150), (440, 150), (880, 400)],
    "Silent": [],
}


def play_done_sound(app: QApplication | None = None, sound: str = "Default beep"):
    """Cross-platform done sound: winsound patterns on Windows, else Qt beep."""
    pattern = SOUND_PATTERNS.get(sound, SOUND_PATTERNS["Default beep"])
    if not pattern:
        return
    try:
        import winsound
        for freq, ms in pattern:
            winsound.Beep(freq, ms)
        return
    except Exception:
        pass
    try:
        if app is not None:
            app.beep()
    except Exception:
        pass


class _UpdateChecker(QThread):
    """Background version check so the GUI never blocks on the network."""
    checked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current = updater.APP_VERSION

    def run(self):
        self.checked.emit(updater.check_latest(self.current))


class _UpdateDownloader(QThread):
    """Background installer download with progress so the GUI stays responsive."""
    progress = pyqtSignal(int)
    done = pyqtSignal(dict)

    def __init__(self, url: str, filename: str = "", parent=None):
        super().__init__(parent)
        self.url = url
        self.filename = filename
        self.dest = Path(tempfile.gettempdir()) / "Rakez-Update"

    def run(self):
        res = updater.download_installer(
            self.url, self.dest, filename=self.filename,
            progress=lambda pct, done, total: self.progress.emit(pct))
        if res.get("ok"):
            updater.cleanup_downloads(self.dest, keep=res["path"])
        self.done.emit(res)


class _TelegramPoller(QThread):
    """Long-poll Telegram in the background so the GUI never blocks."""

    changed = pyqtSignal()

    def __init__(self, bot: TelegramBot, parent=None):
        super().__init__(parent)
        self.bot = bot
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                updates = self.bot.get_updates()
            except Exception:
                updates = []
            for update in updates:
                if self._stop.is_set():
                    break
                try:
                    if self.bot.handle_update(update):
                        self.changed.emit()
                except Exception:
                    pass
            if not updates:
                # network hiccup or no messages: wait before polling again
                self._stop.wait(2)


class _RingWidget(QWidget):
    """Circular progress ring with % text (Glass Pill design)."""
    def __init__(self, parent=None, color="#7aa2f7", size=84):
        super().__init__(parent)
        self._value = 0
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def setValue(self, v: int):
        self._value = max(0, min(100, int(v)))
        self.update()

    def setColor(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 12
        x = (self.width() - side) // 2
        y = (self.height() - side) // 2
        pen = QPen(QColor("#414868"), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawEllipse(x, y, side, side)
        pen = QPen(self._color, 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(x, y, side, side, 90 * 16, -int(self._value / 100 * 360 * 16))
        p.setPen(QColor("#c0caf5"))
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self._value}%")
        p.end()


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # hide immediately: deleteLater is deferred, and stale widgets
            # would otherwise keep painting (ghost buttons) until then
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


class FloatingTimerWidget(QWidget):
    open_dashboard_requested = pyqtSignal()
    session_completed = pyqtSignal(dict)
    quit_requested = pyqtSignal()
    task_added = pyqtSignal(dict)
    widget_size_changed = pyqtSignal(int, int)
    notice_answered = pyqtSignal(object)

    def __init__(self, storage: SqliteStorage):
        super().__init__()
        self.storage = storage
        self.drag_position = QPoint()

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.mode = "focus"  # focus | short_break | long_break
        self.cycles_done = 0
        self.accent = "#7aa2f7"
        self.background = "#1a1b26"
        self.design = "pill"  # pill | neon | split | retro
        self.sound = "Default beep"
        self._pre_form_size = None
        self.setWindowOpacity(0.95)
        self.remaining_seconds = DEFAULTS["focus"] * 60
        self.total_seconds = DEFAULTS["focus"] * 60
        self.is_running = False
        self.current_task = "Select a Task"
        self.current_category = "Deep Work"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._init_ui()

    @staticmethod
    def _hex_to_rgb(hx: str) -> str:
        hx = (hx or "#1a1b26").lstrip("#")
        try:
            r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        except Exception:
            r, g, b = 26, 27, 38
        return f"{r}, {g}, {b}"

    def _float_style(self, attached: bool = False) -> str:
        a = self.accent
        bg = self._hex_to_rgb(self.background)
        light = is_light_color(self.background)
        text = "#1f2430" if light else "#c0caf5"
        sub_bg = "#e5e9f3" if light else "#24283b"
        border = "#c3c9d9" if light else "#414868"
        bottom = "0px" if attached else "16px"
        return f"""
            QWidget#container {{
                background-color: rgba({bg}, 0.95);
                border: 2px solid {a};
                border-top-left-radius: 16px;
                border-top-right-radius: 16px;
                border-bottom-left-radius: {bottom};
                border-bottom-right-radius: {bottom};
                border-bottom: {"none" if attached else f"2px solid {a}"};
            }}
            QWidget#attached {{
                background-color: rgba({bg}, 0.95);
                border: 2px solid {a};
                border-top: none;
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
                border-bottom-left-radius: 16px;
                border-bottom-right-radius: 16px;
            }}
            QLabel {{ color: {text}; font-family: 'Segoe UI', Arial; }}
            QPushButton {{
                background-color: {sub_bg};
                border: 1px solid {a};
                border-radius: 8px;
                color: {a};
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {a}; color: {"#ffffff" if light else "#1a1b26"}; }}
            QLineEdit, QComboBox {{
                background-color: {sub_bg};
                border: 1px solid {border};
                border-radius: 6px;
                color: {text};
                padding: 5px;
            }}
            QProgressBar {{
                background-color: {sub_bg};
                border: 1px solid {border};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{ background-color: {a}; border-radius: 3px; }}
        """

    def _restyle(self, attached: bool):
        try:
            self.setStyleSheet(self._float_style(attached=attached))
        except Exception:
            pass

    def set_accent(self, accent: str):
        self.accent = accent if valid_hex(accent) else "#7aa2f7"
        self._build_design()

    def set_background(self, background: str):
        self.background = background if valid_hex(background) else "#1a1b26"
        self._build_design()

    DESIGN_MIN_SIZES = {"pill": (300, 130), "neon": (380, 140), "split": (420, 110),
                        "retro": (340, 420)}

    def set_design(self, design: str):
        self.design = design if design in ("pill", "neon", "split", "retro") else "pill"
        mw, mh = self.DESIGN_MIN_SIZES[self.design]
        self.setMinimumSize(mw, mh)
        # keep the user's size — only clamp up if below the new minimums
        # (never jump back to defaults; Save must not reset the size)
        if self.width() < mw or self.height() < mh:
            self.resize(max(mw, self.width()), max(mh, self.height()))
        self._build_design()

    def set_size(self, w: int, h: int):
        mw, mh = self.DESIGN_MIN_SIZES.get(self.design, (260, 90))
        self.setMinimumSize(mw, mh)
        self.resize(max(mw, w), max(mh, h))

    def set_sound(self, sound: str):
        from core.settings import SOUND_NAMES
        self.sound = sound if sound in SOUND_NAMES else "Default beep"

    def set_opacity(self, percent: int):
        try:
            pct = max(30, min(100, int(percent)))
        except (TypeError, ValueError):
            pct = 95
        self.setWindowOpacity(pct / 100.0)
        return pct

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.widget_size_changed.emit(self.width(), self.height())
        except Exception:
            pass

    def _init_ui(self):
        # resizable: only a minimum size, user can drag any edge/corner
        self.setMinimumSize(300, 104)
        self.resize(370, 104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        container = QWidget(self)
        container.setObjectName("container")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._float_container = container
        # NOTE: no QGraphicsDropShadowEffect — on Windows a blur shadow on a
        # translucent frameless window spams "UpdateLayeredWindowIndirect
        # failed (The parameter is incorrect)".

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(container)
        # resize handle (frameless windows have no native one)
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 6, 2)
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setToolTip("Drag to resize")
        grip_row.addWidget(grip)
        main_layout.addLayout(grip_row)
        self._build_design()
        self._build_inline_panel(main_layout)
        translate_tree(self)

    def _build_inline_panel(self, main_layout):
        """Attached slide-down panel: quick-add form AND inline notices.

        Same card style as the widget — no separate windows.
        """
        from core.storage import CATEGORIES as _CATS
        self.inline_panel = QWidget(self)
        self.inline_panel.setObjectName("attached")
        self.inline_panel.setVisible(False)
        pv = QVBoxLayout(self.inline_panel)
        pv.setContentsMargins(12, 8, 12, 8)

        # --- quick-add form ---
        self.inline_form = QWidget()
        fv = QVBoxLayout(self.inline_form)
        fv.setContentsMargins(0, 0, 0, 0)
        self.inline_title = QLineEdit()
        self.inline_title.setPlaceholderText("Task title... (Enter to add)")
        self.inline_title.returnPressed.connect(self._submit_inline_task)
        fv.addWidget(self.inline_title)
        frow = QHBoxLayout()
        self.inline_category = QComboBox()
        for cat in _CATS:
            self.inline_category.addItem(t(cat), cat)
        frow.addWidget(self.inline_category, stretch=2)
        ok_btn = QPushButton(t("Add"))
        ok_btn.clicked.connect(self._submit_inline_task)
        frow.addWidget(ok_btn, stretch=1)
        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedWidth(36)
        cancel_btn.setToolTip("Close")
        cancel_btn.clicked.connect(self._hide_panel)
        frow.addWidget(cancel_btn)
        fv.addLayout(frow)
        pv.addWidget(self.inline_form)

        # --- notice area ---
        self.inline_notice = QWidget()
        nv = QVBoxLayout(self.inline_notice)
        nv.setContentsMargins(0, 0, 0, 0)
        self.notice_label = QLabel("")
        self.notice_label.setWordWrap(True)
        self.notice_label.setFont(QFont("Segoe UI", 9))
        nv.addWidget(self.notice_label)
        self.notice_btns = QHBoxLayout()
        nv.addLayout(self.notice_btns)
        pv.addWidget(self.inline_notice)

        main_layout.insertWidget(1, self.inline_panel)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self._hide_panel)

    def _show_panel(self, form: bool):
        self.inline_form.setVisible(form)
        self.inline_notice.setVisible(not form)
        self.inline_panel.setVisible(True)
        self._restyle(True)  # merge visually with the card above
        self._notice_timer.stop()

    def _hide_panel(self):
        self._notice_timer.stop()
        self.inline_panel.setVisible(False)
        self._restyle(False)  # restore full rounded card
        # restore pre-form size (auto-grow is temporary)
        try:
            saved = getattr(self, "_pre_form_size", None)
            if saved is not None:
                mw, mh = self.DESIGN_MIN_SIZES.get(self.design, (280, 96))
                self.resize(max(mw, saved.width()), max(mh, saved.height()))
                self._pre_form_size = None
        except Exception:
            pass

    def show_form(self):
        """Attached quick-add form (replaces the old popup dialog)."""
        if not self.inline_panel.isVisible():
            # remember size to restore after add/cancel; grow to fit form
            self._pre_form_size = self.size()
        self._show_panel(form=True)
        self.inline_title.clear()
        self.inline_title.setFocus()
        try:
            QApplication.processEvents()
            hint = self.sizeHint()
            self.resize(max(self.width(), self.minimumWidth()), max(self.height(), hint.height()))
        except Exception:
            pass

    def _submit_inline_task(self):
        title = self.inline_title.text().strip()
        if not title:
            return
        try:
            todo = self.storage.add_todo(
                title, self.inline_category.currentData() or "Deep Work")
        except ValueError:
            return
        self._hide_panel()
        self.set_task(todo["title"], todo["category"], round(self.total_seconds / 60))
        if self.is_running:
            self.toggle_timer()  # pause — fresh period for the new task
        self.task_added.emit(todo)

    def show_notice(self, text: str, actions: list | None = None,
                    timeout_ms: int = 6000):
        """Attached notification. actions=[(label, value)]; emits notice_answered."""
        self._show_panel(form=False)
        self.notice_label.setText(text)
        while self.notice_btns.count():
            item = self.notice_btns.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if actions:
            for label, value in actions:
                btn = QPushButton(label)
                btn.clicked.connect(lambda _c, v=value: self._answer_notice(v))
                self.notice_btns.addWidget(btn)
        else:
            self._notice_timer.start(timeout_ms)

    def _answer_notice(self, value):
        self._hide_panel()
        self.notice_answered.emit(value)

    # ---------- designs ----------
    def _make_task_labels(self, time_size: int = 15):
        """Shared labels (recreated on every design build)."""
        light = is_light_color(self.background)
        cat_color = "#7c3aed" if light else "#bb9af7"
        mode_color = "#2f9e44" if light else "#9ece6a"
        time_color = "#2f9e44" if light else "#9ece6a"
        self.task_label = QLabel(self.current_task)
        self.task_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.task_label.setStyleSheet(f"color: {self.accent};")
        self.task_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_label.setToolTip("Click to switch task")
        self.task_label.mousePressEvent = lambda _e: self._switch_task_menu()

        self.cat_label = QLabel(f"🏷️ {t(self.current_category)}")
        self.cat_label.setFont(QFont("Segoe UI", 8))
        self.cat_label.setStyleSheet(f"color: {cat_color};")

        self.mode_label = QLabel("🎯 FOCUS")
        self.mode_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.mode_label.setStyleSheet(f"color: {mode_color};")

        self.time_label = QLabel(f"{DEFAULTS['focus']:02d}:00")
        self.time_label.setFont(QFont("Consolas", time_size, QFont.Weight.Bold))
        self.time_label.setStyleSheet(f"color: {time_color};")
        self._update_time_display()

    def _make_buttons(self):
        toggle_btn = QPushButton("▶")
        toggle_btn.setFixedSize(34, 34)
        toggle_btn.setToolTip("Start/Pause")
        toggle_btn.clicked.connect(self.toggle_timer)

        expand_btn = QPushButton("⛶")
        expand_btn.setFixedSize(34, 34)
        expand_btn.setToolTip("Open dashboard")
        expand_btn.clicked.connect(self.open_dashboard_requested.emit)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(34, 34)
        add_btn.setToolTip("Quick add task")
        add_btn.clicked.connect(self.show_form)

        break_btn = QPushButton("☕")
        break_btn.setFixedSize(34, 28)
        break_btn.setToolTip("Start short break")
        break_btn.clicked.connect(lambda: self.start_break("short_break"))

        reset_btn = QPushButton("↺")
        reset_btn.setFixedSize(34, 28)
        reset_btn.setToolTip("Reset timer")
        reset_btn.clicked.connect(self.reset_timer)

        quit_btn = QPushButton("✕")
        quit_btn.setFixedSize(34, 28)
        quit_btn.setToolTip("Quit Rakez completely")
        quit_btn.setStyleSheet(
            "QPushButton { border-color: #f7768e; color: #f7768e; }"
            "QPushButton:hover { background-color: #f7768e; color: #1a1b26; }")
        quit_btn.clicked.connect(self.quit_requested.emit)

        done_btn = QPushButton("✓")
        done_btn.setFixedSize(34, 28)
        done_btn.setToolTip("Mark current task as done")
        done_btn.setStyleSheet(
            "QPushButton { border-color: #9ece6a; color: #9ece6a; }"
            "QPushButton:hover { background-color: #9ece6a; color: #1a1b26; }")
        done_btn.clicked.connect(self._done_current_task)

        self.toggle_btn = toggle_btn
        self.expand_btn = expand_btn
        self.add_btn = add_btn
        self.break_btn = break_btn
        self.reset_btn = reset_btn
        self.quit_btn = quit_btn
        self.done_btn = done_btn
        return toggle_btn, expand_btn, add_btn, break_btn, reset_btn, quit_btn, done_btn

    def _make_bar(self, height: int = 8):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(height)
        return bar

    def _build_design(self):
        """Rebuild the container content for the active design."""
        if not hasattr(self, "_float_container"):
            return
        mw, mh = self.DESIGN_MIN_SIZES.get(self.design, (280, 96))
        self.setMinimumSize(mw, mh)
        lay = self._float_container.layout()
        if lay is not None:
            _clear_layout(lay)
        else:
            lay = QHBoxLayout(self._float_container)
        self._restyle(self.inline_panel.isVisible() if hasattr(self, "inline_panel") else False)
        self._float_container.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_arabic()
            else Qt.LayoutDirection.LeftToRight)
        self.ring = None
        self.bar = None
        {"pill": self._build_pill, "neon": self._build_neon,
         "split": self._build_split, "retro": self._build_retro}[self.design](lay)
        self._refresh_progress()
        translate_tree(self._float_container)

    def _build_pill(self, layout):
        """A — Glass Pill: ring + info + time on top, all buttons one bottom row."""
        layout.setContentsMargins(15, 10, 15, 10)
        self._make_task_labels(time_size=15)
        outer = QVBoxLayout()
        top = QHBoxLayout()
        self.ring = _RingWidget(color=self.accent)
        self.ring.setValue(self._elapsed_pct())
        top.addWidget(self.ring)

        info = QVBoxLayout()
        info.addWidget(self.task_label)
        info.addWidget(self.cat_label)
        info.addWidget(self.mode_label)
        top.addLayout(info, stretch=3)

        mid = QVBoxLayout()
        mid.addWidget(self.time_label, stretch=2)
        self.bar = self._make_bar(height=6)
        mid.addWidget(self.bar)
        top.addLayout(mid, stretch=2)
        outer.addLayout(top)

        t, e, a, d, b, r, q = self._make_buttons()
        bottom = QHBoxLayout()
        for btn in (t, e, a, d, b, r, q):
            bottom.addWidget(btn)
        outer.addLayout(bottom)
        layout.addLayout(outer)

    def _build_neon(self, layout):
        """B — Neon Card: badge + huge time + chunky progress bar."""
        layout.setContentsMargins(15, 12, 15, 12)
        self._make_task_labels(time_size=26)
        self.mode_label.setStyleSheet(
            f"background-color: {self.accent}; color: #1a1b26; "
            "font-weight: bold; border-radius: 6px; padding: 3px 10px;")
        outer = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(self.mode_label)
        top.addWidget(self.task_label, stretch=1)
        top.addWidget(self.cat_label)
        outer.addLayout(top)
        mid = QHBoxLayout()
        mid.addWidget(self.time_label, stretch=3)
        t, e, a, d, b, r, q = self._make_buttons()
        grid = QGridLayout()
        grid.addWidget(t, 0, 0)
        grid.addWidget(e, 0, 1)
        grid.addWidget(a, 0, 2)
        grid.addWidget(d, 0, 3)
        grid.addWidget(b, 1, 0)
        grid.addWidget(r, 1, 1)
        grid.addWidget(q, 1, 2)
        mid.addLayout(grid)
        outer.addLayout(mid)
        self.bar = self._make_bar(height=10)
        outer.addWidget(self.bar)
        layout.addLayout(outer)

    def _build_split(self, layout):
        """C — Split Flip: time block + info/controls block."""
        layout.setContentsMargins(12, 10, 12, 10)
        self._make_task_labels(time_size=20)
        left = QFrame()
        overlay = "rgba(0,0,0,0.04)" if is_light_color(self.background) else "rgba(0,0,0,0.25)"
        left.setStyleSheet(
            f"QFrame {{ background-color: {overlay}; "
            f"border: 1px solid {self.accent}; border-radius: 12px; }}")
        lv = QVBoxLayout(left)
        lv.addWidget(self.time_label)
        lv.addWidget(self.mode_label)
        self.bar = self._make_bar(height=6)
        lv.addWidget(self.bar)
        layout.addWidget(left, stretch=2)

        right = QVBoxLayout()
        right.addWidget(self.task_label)
        right.addWidget(self.cat_label)
        t, e, a, d, b, r, q = self._make_buttons()
        grid = QGridLayout()
        grid.addWidget(t, 0, 0)
        grid.addWidget(e, 0, 1)
        grid.addWidget(a, 0, 2)
        grid.addWidget(d, 0, 3)
        grid.addWidget(b, 1, 0)
        grid.addWidget(r, 1, 1)
        grid.addWidget(q, 1, 2)
        right.addLayout(grid)
        layout.addLayout(right, stretch=3)

    # --- retro typewriter constants ---
    RETRO_PAPER = "#f2ede0"
    RETRO_INK = "#2b2b2b"
    RETRO_RED = "#8e2f25"
    RETRO_KEYBAR = "#b3392e"

    def _build_retro(self, layout):
        """D — Typewriter: paper sheet, phase groups, clickable checkboxes."""
        from datetime import date
        layout.setContentsMargins(10, 10, 10, 10)
        self._make_task_labels(time_size=22)
        # paper sheet
        sheet = QFrame()
        sheet.setStyleSheet(
            f"QFrame {{ background-color: {self.RETRO_PAPER}; "
            "border-radius: 4px; }}")
        sv = QVBoxLayout(sheet)
        sv.setContentsMargins(12, 8, 12, 8)
        header = QLabel(f"··· {date.today().isoformat()} — RAKEZ DAY ···")
        header.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {self.RETRO_RED};")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sv.addWidget(header)
        rule = QFrame()
        rule.setFixedHeight(2)
        rule.setStyleSheet(f"background-color: {self.RETRO_RED};")
        sv.addWidget(rule)
        # timer strip on the paper
        strip = QHBoxLayout()
        self.time_label.setStyleSheet(f"color: {self.RETRO_RED};")
        strip.addWidget(self.time_label)
        strip.addWidget(self.task_label, stretch=1)
        self.task_label.setStyleSheet(f"color: {self.RETRO_INK};")
        sv.addLayout(strip)
        # scrollable phase list
        self.retro_scroll = QScrollArea()
        self.retro_scroll.setWidgetResizable(True)
        self.retro_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {self.RETRO_PAPER}; border: none; }}")
        self.retro_list = QWidget()
        self.retro_list.setStyleSheet(f"background-color: {self.RETRO_PAPER};")
        self.retro_list_layout = QVBoxLayout(self.retro_list)
        self.retro_list_layout.setContentsMargins(4, 4, 4, 4)
        self.retro_list_layout.addStretch()
        self.retro_scroll.setWidget(self.retro_list)
        sv.addWidget(self.retro_scroll, stretch=1)
        self.retro_count = QLabel("")
        self.retro_count.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.retro_count.setStyleSheet(f"color: {self.RETRO_RED};")
        self.retro_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sv.addWidget(self.retro_count)
        layout.addWidget(sheet, stretch=1)
        # red typewriter key bar
        keybar = QFrame()
        keybar.setStyleSheet(
            f"QFrame {{ background-color: {self.RETRO_KEYBAR}; border-radius: 10px; }}")
        kv = QHBoxLayout(keybar)
        kv.setContentsMargins(10, 6, 10, 6)
        t, e, a, d, b, r, q = self._make_buttons()
        for btn in (t, e, a, d, b, r, q):
            btn.setStyleSheet(
                "QPushButton { background-color: #f2ede0; color: #2b2b2b; "
                "border: 1px solid #2b2b2b; border-radius: 14px; }"
                "QPushButton:hover { background-color: #ffffff; }")
            kv.addWidget(btn)
        layout.addWidget(keybar)
        self._refresh_retro_list()
        # mode/category shown via task line; keep refs valid
        self.mode_label.setStyleSheet(f"color: {self.RETRO_RED};")

    def _refresh_retro_list(self):
        """Rebuild phase-grouped checkboxes from storage."""
        if getattr(self, "retro_list_layout", None) is None:
            return
        lay = self.retro_list_layout
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        todos = self.storage.get_todos()
        order, groups = [], {}
        for todo in todos:
            c = todo.get("category", "Deep Work")
            if c not in groups:
                groups[c] = []
                order.append(c)
            groups[c].append(todo)
        n_done = sum(1 for todo in todos if todo.get("completed"))
        for cat in order:
            head = QLabel(tf("PHASE: {cat}", cat=cat.upper()))
            head.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            head.setStyleSheet(f"color: {self.RETRO_RED};")
            lay.addWidget(head)
            for todo in groups[cat]:
                done = bool(todo.get("completed"))
                box = "☒" if done else "☐"
                cb = QCheckBox(f"{box}  {todo.get('title')}")
                cb.setFont(QFont("Consolas", 9))
                cb.setChecked(done)
                cb.setStyleSheet(
                    f"QCheckBox {{ color: {self.RETRO_INK}; spacing: 4px; }}")
                cb.setProperty("todo_id", todo.get("id"))
                cb.toggled.connect(self._toggle_retro_task)
                lay.addWidget(cb)
        lay.addStretch()
        total = len(todos)
        self.retro_count.setText(
            tf("{n_done}/{total} done", n_done=n_done, total=total) if total
            else t("no tasks yet"))
        self._refresh_progress()

    def _toggle_retro_task(self, checked: bool):
        box = self.sender()
        if box is None:
            return
        todo_id = box.property("todo_id")
        try:
            self.storage.set_completed(todo_id, checked)
        except Exception:
            pass
        todo = None
        try:
            for t in self.storage.get_todos():
                if t.get("id") == todo_id:
                    todo = t
                    break
        except Exception:
            pass
        self._refresh_retro_list()
        if todo is not None:
            self.task_added.emit(todo)

    def _done_current_task(self):
        """Mark the current widget task as done, then auto-advance."""
        name = (self.current_task or "").strip()
        if not name or name == "Select a Task":
            self.show_notice(t("No task selected — pick one first."))
            return
        try:
            done_ok = self.storage.set_completed(name, True)
        except Exception:
            done_ok = False
        if not done_ok:
            self.show_notice(tf("⚠ Could not complete '{name}'.", name=name))
            return
        self.show_notice(tf("✓ '{name}' completed!", name=name))
        if self.is_running:
            self.toggle_timer()  # pause — fresh period ahead
        remaining = [t for t in self.storage.get_todos() if not t.get("completed")]
        if remaining:
            nxt = remaining[0]
            self.set_task(nxt["title"], nxt.get("category", "Deep Work"),
                          round(self.total_seconds / 60))
        else:
            self.set_task("Select a Task", "Deep Work", round(self.total_seconds / 60))
        try:
            self.task_added.emit({"title": name, "completed": True})
        except Exception:
            pass

    def _switch_task_menu(self):
        """Popup menu of open tasks — switch without opening the dashboard."""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1f2335; color: #c0caf5; border: 1px solid #414868; }"
            "QMenu::item:selected { background-color: #7aa2f7; color: #1a1b26; }")
        open_tasks = [t for t in self.storage.get_todos() if not t.get("completed")]
        if not open_tasks:
            act = menu.addAction(t("(no open tasks)"))
            act.setEnabled(False)
        for t in open_tasks[:20]:
            label = f"{t.get('title')}  [{t.get('category')}]"
            if t.get("title") == self.current_task:
                label = "● " + label
            act = menu.addAction(label)
            act.setData(t)
        chosen = menu.exec(QCursor.pos())
        if chosen is not None and chosen.data() is not None:
            t = chosen.data()
            self.set_task(t["title"], t["category"], round(self.total_seconds / 60))
            if self.is_running:
                self.toggle_timer()  # pause — fresh period for the new task

    def set_task(self, task_name, category, duration_min=25):
        self.current_task = task_name
        self.current_category = category
        self.mode = "focus"
        self.task_label.setText(task_name[:20] + "..." if len(task_name) > 20 else task_name)
        self.cat_label.setText(f"🏷️ {t(category)}")
        self.mode_label.setText(t("🎯 FOCUS"))
        self.total_seconds = duration_min * 60
        self.remaining_seconds = self.total_seconds
        self._update_time_display()
        self._refresh_retro_list()
        translate_tree(self._float_container)

    def start_break(self, kind="short_break", minutes: int | None = None):
        if minutes is None:
            minutes = DEFAULTS["short_break"] if kind == "short_break" else DEFAULTS["long_break"]
        self.mode = kind
        label = "☕ SHORT BREAK" if kind == "short_break" else "🌴 LONG BREAK"
        self.mode_label.setText(t(label))
        self.total_seconds = minutes * 60
        self.remaining_seconds = self.total_seconds
        self._update_time_display()
        if not self.is_running:
            self.toggle_timer()

    def reset_timer(self):
        self.timer.stop()
        self.is_running = False
        self.toggle_btn.setText("▶")
        self.remaining_seconds = self.total_seconds
        self._update_time_display()

    def toggle_timer(self):
        light = is_light_color(self.background)
        running_color = "#2f9e44" if light else "#9ece6a"
        paused_color = "#b45309" if light else "#e0af68"
        if self.is_running:
            self.timer.stop()
            self.is_running = False
            self.toggle_btn.setText("▶")
            self.time_label.setStyleSheet(f"color: {paused_color};")
        else:
            if self.remaining_seconds <= 0:
                # expired timer: restart the same interval instead of
                # instantly emitting a duplicate DONE session
                self.remaining_seconds = self.total_seconds
                self._update_time_display()
            self.timer.start(1000)
            self.is_running = True
            self.toggle_btn.setText("⏸")
            self.time_label.setStyleSheet(f"color: {running_color};")

    def _tick(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self._update_time_display()
        else:
            self.timer.stop()
            self.is_running = False
            self.toggle_btn.setText("▶")
            self.time_label.setText(t("DONE!"))
            play_done_sound(QApplication.instance(), self.sound)
            finished_mode = self.mode
            payload = {
                "task": self.current_task if finished_mode == "focus" else f"{finished_mode} break",
                "category": self.current_category,
                "duration_min": round(self.total_seconds / 60),
                "kind": finished_mode,
                "timestamp": datetime.now().isoformat(),
            }
            if finished_mode == "focus":
                self.cycles_done += 1
            self.session_completed.emit(payload)

    def _elapsed_pct(self) -> int:
        if not self.total_seconds:
            return 0
        done = self.total_seconds - self.remaining_seconds
        return max(0, min(100, round(done / self.total_seconds * 100)))

    def _refresh_progress(self):
        pct = self._elapsed_pct()
        try:
            if getattr(self, "ring", None) is not None:
                self.ring.setValue(pct)
                self.ring.setColor(self.accent)
            if getattr(self, "bar", None) is not None:
                self.bar.setValue(pct)
        except Exception:
            pass

    def _update_time_display(self):
        mins = self.remaining_seconds // 60
        secs = self.remaining_seconds % 60
        self.time_label.setText(f"{mins:02d}:{secs:02d}")
        self._refresh_progress()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()


class RakezMainWindow(QMainWindow):
    # background pull of remote completions → GUI refresh on the main thread
    remote_sync_finished = pyqtSignal(dict)

    def __init__(self, storage: SqliteStorage):
        super().__init__()
        self.storage = storage
        # GUI settings file wins over .env when non-empty (editable in Settings tab)
        self.app_settings = load_settings(DATA_DIR)
        gemini_key = self.app_settings.get("gemini_key") or os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key
        joplin_token = (self.app_settings.get("joplin_token")
                        or os.getenv("JOPLIN_TOKEN", _joplin_cfg.get("token", "")))
        joplin_base = (self.app_settings.get("joplin_base")
                       or _joplin_cfg.get("base_url", "http://127.0.0.1:41184"))
        self.coach = HermesCoach(model=_ai_cfg.get("model", "gemini-2.5-flash"))
        self.joplin = JoplinClient(base_url=joplin_base, token=joplin_token)
        self.joplin_folder = (self.app_settings.get("joplin_folder")
                              or _joplin_cfg.get("folder_name", JOPLIN_DEFAULT_FOLDER)
                              or JOPLIN_DEFAULT_FOLDER)
        self.joplin_tags = (self.app_settings.get("joplin_tags")
                            or _joplin_cfg.get("tags", "task,lifebot") or "task,lifebot")
        self.gsync = GoogleSync(
            data_dir=DATA_DIR,
            client_id=self.app_settings.get("google_client_id", ""),
            client_secret=self.app_settings.get("google_client_secret", ""))
        self.telegram = TelegramBot(
            token=self.app_settings.get("telegram_token", ""),
            chat_id=self.app_settings.get("telegram_chat_id", ""),
            storage=self.storage)
        self.notion = NotionClient(
            token=self.app_settings.get("notion_token", ""),
            database_id=self.app_settings.get("notion_database_id", ""))
        # fan-out sync: storage events → Google Tasks / Joplin / Notion
        self.sync_hub = IntegrationHub(
            self.storage, joplin=self.joplin, google=self.gsync,
            notion=self.notion,
            enabled=lambda: bool(self.app_settings.get("auto_sync", True)),
            notify_done=self._telegram_notify_done,
            project_lookup=lambda pid: (self.storage.get_project(pid) or {}).get("name", ""),
            joplin_folder=self.joplin_folder, joplin_tags=self.joplin_tags)
        self.sync_hub.attach()
        self._remote_sync_thread = None
        self.remote_sync_finished.connect(self._after_remote_pull)
        self._telegram_poller = None
        self._telegram_last_daily = ""
        # settings sidebar remembers the section across language switches
        self._settings_section_index = 0
        # the active top-level tab is preserved when the UI is rebuilt
        self._active_tab_index = 0
        # local HTTP API server state (started from Settings → API)
        self._api_server = None
        self._api_thread = None
        self._api_fingerprint = None
        self.theme = self.app_settings.get("theme", "dark")
        lang = self.app_settings.get("language") or ""
        if lang not in ("en", "ar"):
            lang = detect_language()
        self.app_settings["language"] = lang
        set_language(lang)
        self.setWindowTitle(t("Rakez ركّز - AI Coach & Pomodoro"))
        self.resize(880, 640)

        self.floating_widget = FloatingTimerWidget(self.storage)
        self.floating_widget.open_dashboard_requested.connect(self.show_dashboard)
        self.floating_widget.session_completed.connect(self._on_session_finished)
        self.floating_widget.quit_requested.connect(self._quit_app)
        self.floating_widget.task_added.connect(self._on_widget_task_added)
        self.floating_widget.widget_size_changed.connect(self._on_widget_resized)
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.timeout.connect(
            lambda: save_settings(DATA_DIR, self.app_settings))
        # Settings → API: refresh the task lists when tasks change through HTTP
        self._api_watch_timer = QTimer(self)
        self._api_watch_timer.setInterval(5000)
        self._api_watch_timer.timeout.connect(self._api_watch)
        # two-way sync: every two minutes pull completions made in Google
        # Tasks / Joplin / Notion back into Rakez (then fan out to the rest)
        self._remote_pull_timer = QTimer(self)
        self._remote_pull_timer.setInterval(120_000)
        self._remote_pull_timer.timeout.connect(self._pull_remote_completions)
        self._remote_pull_timer.start()
        QTimer.singleShot(8000, self._pull_remote_completions)
        # apply saved widget look
        self.floating_widget.background = self.app_settings.get("background", "#1a1b26")
        self.floating_widget.accent = self.app_settings.get("accent", "#7aa2f7")
        self.floating_widget.design = self.app_settings.get("design", "pill")
        self.floating_widget.set_sound(self.app_settings.get("sound", "Default beep"))
        self.floating_widget.set_size(self.app_settings.get("widget_w", 370),
                                      self.app_settings.get("widget_h", 104))
        self.floating_widget.set_opacity(self.app_settings.get("opacity", 95))
        self.floating_widget._build_design()
        self.floating_widget._build_design()

        self._init_ui()
        self._apply_theme()
        self._init_tray()
        # Telegram: background long polling + the daily report ticker
        self._start_telegram_polling()
        self._telegram_daily_timer = QTimer(self)
        self._telegram_daily_timer.setInterval(60_000)
        self._telegram_daily_timer.timeout.connect(self._check_telegram_daily)
        self._telegram_daily_timer.start()

    def _apply_theme(self):
        """Dark (Tokyo Night) or Light (Paper) stylesheet for the dashboard."""
        light = getattr(self, "theme", "dark") == "light"
        if light:
            bg, panel, border = "#f5f6fa", "#ffffff", "#d7dbe7"
            text, muted, accent, accent2 = "#1f2430", "#6b7280", "#3b6fd4", "#7c3aed"
            btn_bg, hover_text, input_bg = "#eef1f8", "#ffffff", "#ffffff"
        else:
            bg, panel, border = "#1a1b26", "#1f2335", "#292e42"
            text, muted, accent, accent2 = "#c0caf5", "#565f89", "#7aa2f7", "#bb9af7"
            btn_bg, hover_text, input_bg = "#24283b", "#1a1b26", "#24283b"
        sidebar_border = "border-left" if is_arabic() else "border-right"
        nav_align = "right" if is_arabic() else "left"
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background-color: {bg}; color: {text}; font-family: 'Segoe UI', sans-serif; }}
            QTabWidget::pane {{ border: 1px solid {border}; background-color: {panel}; border-radius: 8px; }}
            QTabBar::tab {{ background-color: {bg}; color: {accent}; padding: 10px 18px; font-weight: bold; }}
            QTabBar::tab:selected {{ background-color: {panel}; color: {accent2}; border-bottom: 2px solid {accent}; }}
            QPushButton {{ background-color: {btn_bg}; border: 1px solid {border}; border-radius: 6px; color: {accent}; padding: 8px 14px; font-weight: bold; }}
            QPushButton:hover {{ background-color: {accent}; color: {hover_text}; }}
            QPushButton:disabled {{ color: {muted}; border-color: {border}; }}
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox {{
                background-color: {input_bg}; border: 1px solid {border}; border-radius: 6px;
                color: {text}; padding: 6px; selection-background-color: {accent};
                selection-color: {hover_text};
            }}
            QListWidget::item {{ padding: 4px 2px; }}
            QListWidget::item:selected {{ background-color: {accent}; color: {hover_text}; }}
            QComboBox QAbstractItemView {{
                background-color: {input_bg}; color: {text};
                border: 1px solid {border}; selection-background-color: {accent};
                selection-color: {hover_text};
            }}
            QCheckBox {{ color: {text}; }}
            QScrollArea, QScrollBar:vertical {{ background-color: {panel}; }}
            QStackedWidget#settingsStack, QWidget#settingsSection {{
                background-color: {panel};
            }}
            QWidget#settingsSidebar {{
                background-color: {panel}; {sidebar_border}: 1px solid {border};
            }}
            QFrame#settingsSidebarLine {{
                background-color: {border}; border: none; max-width: 1px;
            }}
            QLabel#settingsSidebarTitle {{ color: {accent2}; }}
            QPushButton#settingsNavButton {{
                background-color: transparent; border: 1px solid transparent;
                border-radius: 7px; color: {text}; font-weight: normal;
                padding: 9px 10px; text-align: {nav_align};
            }}
            QPushButton#settingsNavButton:hover {{
                background-color: {btn_bg}; color: {accent};
            }}
            QPushButton#settingsNavButton:checked {{
                background-color: {accent}; color: {hover_text}; font-weight: bold;
            }}
            QPushButton#settingsSaveButton {{
                background-color: {accent}; color: {hover_text}; border: none;
            }}
            QPushButton#settingsSaveButton:hover {{
                background-color: {accent2}; color: {hover_text};
            }}
            QLabel[muted="true"] {{ color: {muted}; }}
            QFrame[muted="true"] {{
                background-color: {border}; border: none; max-height: 1px;
            }}
        """)
        # labels created with inline styles (inline wins over the stylesheet)
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(f"color: {accent};")
        if hasattr(self, "status_label"):
            self.status_label.setStyleSheet(f"color: {muted};")
        if hasattr(self, "update_label"):
            self.update_label.setStyleSheet(f"color: {muted};")
        if hasattr(self, "api_status_label"):
            self._refresh_api_status()

    def _apply_theme_choice(self, name: str):
        """Settings dropdown → switch the whole app palette instantly."""
        key = THEMES.get(name, "dark")
        if key == getattr(self, "theme", "dark"):
            return
        self.theme = key
        self.app_settings["theme"] = key
        self._apply_theme()
        # keep the floating widget in the matching palette (unless the user
        # deliberately picked a custom background from the other family)
        current = getattr(self.floating_widget, "background", "#1a1b26")
        if is_light_color(current) != (key == "light"):
            bg = THEME_BACKGROUNDS.get(key, "#1a1b26")
            self.floating_widget.set_background(bg)
            self.app_settings["background"] = bg
            if hasattr(self, "bg_combo"):
                for label, hx in BACKGROUNDS.items():
                    if hx == bg:
                        self.bg_combo.setCurrentText(label)
                        break
        save_settings(DATA_DIR, self.app_settings)

    def _change_language(self, *_):
        """Settings dropdown → rebuild the whole dashboard in that language."""
        code = self.lang_combo.currentData()
        if code not in ("en", "ar") or code == get_language():
            return
        set_language(code)
        self.app_settings["language"] = code
        save_settings(DATA_DIR, self.app_settings)
        self.setWindowTitle(t("Rakez ركّز - AI Coach & Pomodoro"))
        # Qt owns the old central widget: setCentralWidget() drops it for us
        self._init_ui()
        self._apply_theme()
        self._refresh_telegram_status()
        try:
            self.floating_widget._build_design()
            translate_tree(self.floating_widget)
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.hide()
                self.tray.deleteLater()
                self.tray = None
                self._init_tray()
        except Exception:
            pass

    def _init_ui(self):
        main_widget = QWidget()
        main_widget.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if is_arabic()
            else Qt.LayoutDirection.LeftToRight)
        layout = QVBoxLayout(main_widget)

        header = QHBoxLayout()
        self.title_label = QLabel("🤖 Rakez ركّز Productivity System")
        self.title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #7aa2f7;")

        toggle_float_btn = QPushButton("📌 Show/Hide Floating")
        toggle_float_btn.clicked.connect(self.toggle_floating)

        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(toggle_float_btn)
        layout.addLayout(header)

        # status bar: coach mode + joplin
        status_row = QHBoxLayout()
        coach_mode = "🟢 Gemini AI" if self.coach.online else "🟡 Offline coach (set GEMINI_API_KEY)"
        self.status_label = QLabel(f"{coach_mode}  •  Joplin: {self.joplin.status()}")
        self.status_label.setFont(QFont("Segoe UI", 8))
        self.status_label.setStyleSheet("color: #565f89;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        tabs = QTabWidget()
        tabs.addTab(self._create_pomodoro_tab(), "⏱️ Pomodoro")
        tabs.addTab(self._create_todos_tab(), "📋 Tasks")
        tabs.addTab(self._create_coach_tab(), "🧠 Hermes AI Coach")
        tabs.addTab(self._create_analytics_tab(), "📊 Analytics")
        tabs.addTab(self._create_settings_tab(), "⚙️ Settings")
        tabs.currentChanged.connect(self._remember_tab)
        tabs.setCurrentIndex(
            min(int(getattr(self, "_active_tab_index", 0)), tabs.count() - 1))
        self.tabs = tabs
        layout.addWidget(tabs)

        self.setCentralWidget(main_widget)
        translate_tree(self)

    def _remember_tab(self, index: int):
        self._active_tab_index = index

    # ---- tabs ----
    def _create_pomodoro_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Select a Task for this Focus Session:"))
        self.task_selector = QComboBox()
        self._refresh_task_dropdown()
        layout.addWidget(self.task_selector)

        dur_layout = QHBoxLayout()
        dur_layout.addWidget(QLabel("Focus (min):"))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 90)
        self.duration_spin.setValue(DEFAULTS["focus"])
        dur_layout.addWidget(self.duration_spin)
        dur_layout.addWidget(QLabel("Break (min):"))
        self.break_spin = QSpinBox()
        self.break_spin.setRange(1, 30)
        self.break_spin.setValue(DEFAULTS["short_break"])
        dur_layout.addWidget(self.break_spin)
        dur_layout.addStretch()
        layout.addLayout(dur_layout)

        self.cycle_label = QLabel("Cycles completed: 0 (long break every 4)")
        layout.addWidget(self.cycle_label)

        self.cal_check = QCheckBox("📅 Log finished focus to Google Calendar")
        self.cal_check.setToolTip("Creates a calendar event when a focus session completes")
        layout.addWidget(self.cal_check)

        start_btn = QPushButton("🚀 Send Task to Floating Widget & Start")
        start_btn.setStyleSheet("background-color: #9ece6a; color: #1a1b26; font-size: 14px; padding: 12px;")
        start_btn.clicked.connect(self._start_pomodoro)
        layout.addWidget(start_btn)
        layout.addStretch()
        return tab

    def _create_todos_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Show:"))
        self.show_done_check = QCheckBox("completed")
        self.show_done_check.stateChanged.connect(lambda _: self._load_todos_list())
        filter_row.addWidget(self.show_done_check)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.todos_list = QListWidget()
        self.todos_list.itemDoubleClicked.connect(self._toggle_selected)
        layout.addWidget(self.todos_list)
        self._load_todos_list()

        proj_row = QHBoxLayout()
        proj_add_btn = QPushButton("📁 New Project")
        proj_add_btn.setToolTip("Create a project, then add tasks to it")
        proj_add_btn.clicked.connect(self._add_project)
        proj_del_btn = QPushButton("🗑 Delete Project")
        proj_del_btn.setToolTip("Deletes the selected project header (tasks become unassigned)")
        proj_del_btn.clicked.connect(self._delete_project)
        proj_move_btn = QPushButton("📁 Move to Project")
        proj_move_btn.setToolTip("Assign the selected task to a project")
        proj_move_btn.clicked.connect(self._move_selected_to_project)
        proj_row.addWidget(proj_add_btn)
        proj_row.addWidget(proj_del_btn)
        proj_row.addWidget(proj_move_btn)
        proj_row.addStretch()
        layout.addLayout(proj_row)

        add_layout = QHBoxLayout()
        self.new_task_input = QLineEdit()
        self.new_task_input.setPlaceholderText("New task title... (Enter to add)")
        self.new_task_input.returnPressed.connect(self._add_task)
        self.category_combo = QComboBox()
        for cat in CATEGORIES:
            self.category_combo.addItem(t(cat), cat)
        self.priority_combo = QComboBox()
        for pri in ("low", "medium", "high"):
            self.priority_combo.addItem(t(pri), pri)
        self.priority_combo.setCurrentIndex(1)
        self.project_combo = QComboBox()
        add_btn = QPushButton("➕ Add")
        add_btn.clicked.connect(self._add_task)

        add_layout.addWidget(self.new_task_input, stretch=3)
        add_layout.addWidget(self.project_combo, stretch=1)
        add_layout.addWidget(self.category_combo, stretch=1)
        add_layout.addWidget(self.priority_combo, stretch=1)
        add_layout.addWidget(add_btn, stretch=1)
        layout.addLayout(add_layout)

        row = QHBoxLayout()
        done_btn = QPushButton("✓ Toggle Done (double-click)")
        done_btn.clicked.connect(self._toggle_selected)
        del_btn = QPushButton("🗑 Delete")
        del_btn.clicked.connect(self._delete_selected)
        clear_btn = QPushButton("🧹 Clear completed")
        clear_btn.clicked.connect(self._clear_completed)
        row.addWidget(done_btn)
        row.addWidget(del_btn)
        row.addWidget(clear_btn)
        layout.addLayout(row)

        sync_row = QHBoxLayout()
        sync_btn = QPushButton("⬆ Sync all to Joplin All-Tasks")
        sync_btn.setToolTip("Push every open task to the Joplin notebook (skips existing)")
        sync_btn.clicked.connect(self._sync_all_to_joplin)
        pull_btn = QPushButton("⬇ Pull from Joplin")
        pull_btn.setToolTip("Import todos created in Joplin into Rakez (skips existing)")
        pull_btn.clicked.connect(self._pull_from_joplin)
        self.joplin_status_label = QLabel("")
        self.joplin_status_label.setFont(QFont("Segoe UI", 8))
        sync_row.addWidget(sync_btn)
        sync_row.addWidget(pull_btn)
        sync_row.addWidget(self.joplin_status_label, stretch=1)
        layout.addLayout(sync_row)

        grow = QHBoxLayout()
        gpush_btn = QPushButton("📤 Selected → Google Tasks")
        gpush_btn.setToolTip("Push the selected task to Google Tasks")
        gpush_btn.clicked.connect(self._push_selected_to_google)
        grow.addWidget(gpush_btn)
        gpull_btn = QPushButton("📥 Google Tasks → Rakez")
        gpull_btn.setToolTip("Import open Google Tasks (skips existing)")
        gpull_btn.clicked.connect(self._pull_from_google)
        grow.addWidget(gpull_btn)
        self.google_status_label = QLabel("")
        self.google_status_label.setFont(QFont("Segoe UI", 8))
        grow.addWidget(self.google_status_label, stretch=1)
        layout.addLayout(grow)
        return tab

    def _create_coach_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        bar = QHBoxLayout()
        p_btn = QPushButton("🌅 Morning Plan")
        p_btn.clicked.connect(self._plan_morning)
        s_btn = QPushButton("🛡️ Resolve Snag / Excuse")
        s_btn.clicked.connect(self._resolve_snag)
        r_btn = QPushButton("📊 Daily Review")
        r_btn.clicked.connect(self._daily_review)

        bar.addWidget(p_btn)
        bar.addWidget(s_btn)
        bar.addWidget(r_btn)
        layout.addLayout(bar)

        self.coach_output = QTextEdit()
        self.coach_output.setReadOnly(True)
        self.coach_output.setFont(QFont("Consolas", 10))
        self.coach_output.setPlaceholderText("Hermes coach output will appear here...")
        layout.addWidget(self.coach_output)
        return tab

    def _create_analytics_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.analytics_box = QTextEdit()
        self.analytics_box.setReadOnly(True)
        self.analytics_box.setFont(QFont("Consolas", 10))
        layout.addWidget(self.analytics_box)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._load_analytics)
        layout.addWidget(refresh_btn)
        self._load_analytics()
        return tab

    # ---- settings: sidebar + stacked sections ----

    def _create_settings_tab(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 14, 12, 14)
        side.setSpacing(4)

        side_title = QLabel("Settings")
        side_title.setObjectName("settingsSidebarTitle")
        side_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        side.addWidget(side_title)
        side.addSpacing(6)

        self._settings_stack = QStackedWidget()
        self._settings_stack.setObjectName("settingsStack")
        self._settings_section_ids = []
        self._settings_nav_buttons = []
        self._settings_nav_group = QButtonGroup(page)
        self._settings_nav_group.setExclusive(True)

        sections = (
            ("general", "⚙️ General", self._settings_general_section),
            ("appearance", "🎨 Appearance", self._settings_appearance_section),
            ("widget", "🔳 Floating widget", self._settings_widget_section),
            ("integrations", "🔗 Integrations", self._settings_integrations_section),
            ("api", "🌐 API", self._settings_api_section),
            ("updates", "⬆️ Updates", self._settings_updates_section),
        )
        for index, (section_id, label, builder) in enumerate(sections):
            btn = QPushButton(label)
            btn.setObjectName("settingsNavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, i=index: self._show_settings_section(i))
            self._settings_nav_group.addButton(btn, index)
            self._settings_nav_buttons.append(btn)
            side.addWidget(btn)
            self._settings_stack.addWidget(self._settings_page(builder()))
            self._settings_section_ids.append(section_id)

        side.addStretch(1)

        save_btn = QPushButton("💾 Save settings")
        save_btn.setObjectName("settingsSaveButton")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_settings)
        side.addWidget(save_btn)

        self.settings_status = QLabel("")
        self.settings_status.setFont(QFont("Segoe UI", 8))
        self.settings_status.setWordWrap(True)
        self.settings_status.setProperty("muted", True)
        side.addWidget(self.settings_status)

        divider = QFrame()
        divider.setObjectName("settingsSidebarLine")
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)

        outer.addWidget(sidebar)
        outer.addWidget(divider)
        outer.addWidget(self._settings_stack, stretch=1)

        index = max(0, min(int(getattr(self, "_settings_section_index", 0) or 0),
                           len(self._settings_section_ids) - 1))
        self._show_settings_section(index)
        return page

    def _settings_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _settings_section(self):
        body = QWidget()
        body.setObjectName("settingsSection")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(9)
        return body, layout

    def _settings_heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        return label

    def _settings_subheading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        label.setContentsMargins(0, 6, 0, 0)
        return label

    def _settings_hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 8))
        label.setWordWrap(True)
        label.setProperty("muted", True)
        return label

    def _settings_rule(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setProperty("muted", True)
        return line

    def _show_settings_section(self, index: int):
        stack = getattr(self, "_settings_stack", None)
        if stack is None or stack.count() == 0:
            return
        index = max(0, min(int(index), stack.count() - 1))
        stack.setCurrentIndex(index)
        self._settings_section_index = index
        for i, btn in enumerate(getattr(self, "_settings_nav_buttons", [])):
            wanted = (i == index)
            if btn.isChecked() != wanted:
                btn.setChecked(wanted)

    def _jump_to_settings(self, section_id: str):
        ids = getattr(self, "_settings_section_ids", [])
        if section_id in ids:
            self._show_settings_section(ids.index(section_id))

    # ---- settings sections ----

    def _settings_general_section(self) -> QWidget:
        s = self.app_settings
        body, layout = self._settings_section()
        layout.addWidget(self._settings_heading("General"))
        layout.addWidget(self._settings_hint(
            "Language and notification sound for the whole app."))

        layout.addSpacing(6)
        layout.addWidget(QLabel("🌐 Language:"))
        lang_row = QHBoxLayout()
        self.lang_combo = QComboBox()
        for label, code in LANGUAGES.items():
            self.lang_combo.addItem(label, code)
        self.lang_combo.setMinimumWidth(200)
        self.lang_combo.setCurrentIndex(
            max(0, self.lang_combo.findData(get_language())))
        self.lang_combo.currentIndexChanged.connect(self._change_language)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)
        layout.addWidget(self._settings_hint(
            "The interface and the floating widget switch instantly."))

        layout.addSpacing(10)
        layout.addWidget(QLabel("🔔 Notification sound:"))
        sound_row = QHBoxLayout()
        self.sound_combo = QComboBox()
        self.sound_combo.addItems(SOUND_NAMES)
        cur_sound = s.get("sound", "Default beep")
        if cur_sound in SOUND_NAMES:
            self.sound_combo.setCurrentText(cur_sound)
        self.sound_combo.currentTextChanged.connect(self._apply_sound)
        sound_row.addWidget(self.sound_combo)
        sound_test = QPushButton("🔊 Test")
        sound_test.setToolTip("Preview the selected sound")
        sound_test.clicked.connect(self._test_sound)
        sound_row.addWidget(sound_test)
        sound_row.addStretch()
        layout.addLayout(sound_row)
        layout.addStretch(1)
        return body

    def _settings_appearance_section(self) -> QWidget:
        s = self.app_settings
        body, layout = self._settings_section()
        layout.addWidget(self._settings_heading("Appearance"))
        layout.addWidget(self._settings_hint(
            "Dashboard theme and the highlight color used across Rakez."))

        layout.addSpacing(6)
        layout.addWidget(QLabel("🎨 Theme:"))
        theme_row = QHBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        for label, key in THEMES.items():
            if key == s.get("theme", "dark"):
                self.theme_combo.setCurrentText(label)
                break
        self.theme_combo.currentTextChanged.connect(self._apply_theme_choice)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)
        layout.addWidget(self._settings_hint(
            "Light mode applies to the dashboard and the floating widget."))

        layout.addSpacing(10)
        layout.addWidget(QLabel("🎨 Accent color:"))
        accent_row = QHBoxLayout()
        self.accent_combo = QComboBox()
        self.accent_combo.addItems(list(ACCENTS.keys()))
        cur_hex = s.get("accent", "#7aa2f7")
        for name, hx in ACCENTS.items():
            if hx == cur_hex:
                self.accent_combo.setCurrentText(name)
                break
        self.accent_combo.currentTextChanged.connect(self._apply_accent)
        accent_row.addWidget(self.accent_combo)
        accent_row.addStretch()
        layout.addLayout(accent_row)
        layout.addStretch(1)
        return body

    def _settings_widget_section(self) -> QWidget:
        s = self.app_settings
        body, layout = self._settings_section()
        layout.addWidget(self._settings_heading("Floating widget"))
        layout.addWidget(self._settings_hint(
            "Shape, size, and transparency of the always-on-top timer. "
            "Changes preview immediately."))

        layout.addSpacing(6)
        layout.addWidget(QLabel("🔳 Floating widget size:"))
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Width:"))
        self.set_w_spin = QSpinBox()
        self.set_w_spin.setRange(260, 700)
        self.set_w_spin.setValue(int(s.get("widget_w", 370)))
        size_row.addWidget(self.set_w_spin)
        size_row.addWidget(QLabel("Height:"))
        self.set_h_spin = QSpinBox()
        self.set_h_spin.setRange(90, 320)
        self.set_h_spin.setValue(int(s.get("widget_h", 104)))
        size_row.addWidget(self.set_h_spin)
        size_apply = QPushButton("Apply size")
        size_apply.clicked.connect(self._apply_widget_size)
        size_row.addWidget(size_apply)
        size_row.addStretch()
        layout.addLayout(size_row)

        layout.addSpacing(10)
        layout.addWidget(QLabel("🖌️ Widget design & background:"))
        design_row = QHBoxLayout()
        design_row.addWidget(QLabel("Design:"))
        self.design_combo = QComboBox()
        self.design_combo.addItems(list(DESIGNS.keys()))
        cur_design = s.get("design", "pill")
        for name, key in DESIGNS.items():
            if key == cur_design:
                self.design_combo.setCurrentText(name)
                break
        self.design_combo.currentTextChanged.connect(self._apply_design)
        design_row.addWidget(self.design_combo)
        design_row.addWidget(QLabel("Background:"))
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(list(BACKGROUNDS.keys()))
        cur_bg = s.get("background", "#1a1b26")
        for name, hx in BACKGROUNDS.items():
            if hx == cur_bg:
                self.bg_combo.setCurrentText(name)
                break
        self.bg_combo.currentTextChanged.connect(self._apply_background)
        design_row.addWidget(self.bg_combo)
        design_row.addStretch()
        layout.addLayout(design_row)

        layout.addSpacing(10)
        layout.addWidget(QLabel("🔆 Widget transparency:"))
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Opacity:"))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(30, 100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setValue(int(s.get("opacity", 95)))
        self.opacity_spin.valueChanged.connect(self._apply_opacity)
        op_row.addWidget(self.opacity_spin)
        op_row.addStretch()
        layout.addLayout(op_row)
        layout.addStretch(1)
        return body

    def _settings_integrations_section(self) -> QWidget:
        s = self.app_settings
        body, layout = self._settings_section()
        layout.addWidget(self._settings_heading("Integrations"))
        layout.addWidget(self._settings_hint(
            "Connect Rakez to the services you already use. "
            "Tokens and client credentials live under API."))

        keys_row = QHBoxLayout()
        keys_btn = QPushButton("🔑 Edit API keys")
        keys_btn.setToolTip("Jump to the API section to paste tokens and keys")
        keys_btn.clicked.connect(lambda: self._jump_to_settings("api"))
        keys_row.addWidget(keys_btn)
        keys_row.addStretch()
        layout.addLayout(keys_row)

        self.auto_sync_check = QCheckBox(
            "Two-way sync with Google Tasks, Joplin and Notion")
        self.auto_sync_check.setToolTip(
            "Push every task change to the connected services and pull back "
            "tasks completed there (checked every 2 minutes)")
        self.auto_sync_check.setChecked(bool(s.get("auto_sync", True)))
        layout.addWidget(self.auto_sync_check)

        # --- Joplin ---
        layout.addSpacing(8)
        layout.addWidget(self._settings_subheading("🗒️ Joplin"))
        layout.addWidget(self._settings_hint(
            "Base URL and notebook used when syncing tasks."))
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("Base:"))
        self.joplin_base_edit = QLineEdit()
        self.joplin_base_edit.setText(s.get("joplin_base", "http://127.0.0.1:41184"))
        base_row.addWidget(self.joplin_base_edit, stretch=2)
        base_row.addWidget(QLabel("Folder:"))
        self.joplin_folder_edit = QLineEdit()
        self.joplin_folder_edit.setText(self.joplin_folder)
        base_row.addWidget(self.joplin_folder_edit, stretch=2)
        base_row.addWidget(QLabel("Tags:"))
        self.joplin_tags_edit = QLineEdit()
        self.joplin_tags_edit.setText(self.joplin_tags)
        base_row.addWidget(self.joplin_tags_edit, stretch=1)
        layout.addLayout(base_row)

        # --- Google ---
        layout.addSpacing(8)
        layout.addWidget(self._settings_subheading("📅 Google Calendar + Tasks"))
        layout.addWidget(self._settings_hint(
            "Save the OAuth client ID and secret under API first, "
            "then authorize once here. New tasks are pushed to Google Tasks "
            "automatically."))
        grow = QHBoxLayout()
        auth_btn = QPushButton("🔓 Authorize")
        auth_btn.setToolTip("Open browser once to grant access")
        auth_btn.clicked.connect(self._authorize_google)
        grow.addWidget(auth_btn)
        test_btn = QPushButton("🔌 Test connection")
        test_btn.setToolTip("Real API check: Google Tasks list + Calendar events access")
        test_btn.clicked.connect(self._test_google_connection)
        grow.addWidget(test_btn)
        grow.addStretch()
        layout.addLayout(grow)

        # --- Notion ---
        layout.addSpacing(8)
        layout.addWidget(self._settings_subheading("🗂️ Notion"))
        layout.addWidget(self._settings_hint(
            "Paste the integration token under API, share the database with "
            "your integration in Notion (⋯ → Connections), then paste its ID "
            "here. Rakez adds the properties it needs automatically."))
        notion_row = QHBoxLayout()
        notion_row.addWidget(QLabel("Database ID:"))
        self.notion_db_edit = QLineEdit()
        self.notion_db_edit.setPlaceholderText("32-character ID from the database URL")
        self.notion_db_edit.setText(s.get("notion_database_id", ""))
        notion_row.addWidget(self.notion_db_edit, stretch=1)
        layout.addLayout(notion_row)

        notion_btns = QHBoxLayout()
        notion_test = QPushButton("🔌 Test")
        notion_test.setToolTip("Check the token, the database and its properties")
        notion_test.clicked.connect(self._test_notion)
        notion_btns.addWidget(notion_test)
        notion_sync = QPushButton("🔄 Sync now")
        notion_sync.setToolTip(
            "Pull tasks completed in Google Tasks, Joplin or Notion, then push "
            "every task to all of them")
        notion_sync.clicked.connect(self._sync_all_integrations)
        notion_btns.addWidget(notion_sync)
        notion_btns.addStretch()
        layout.addLayout(notion_btns)

        self.notion_status_label = QLabel("")
        self.notion_status_label.setFont(QFont("Segoe UI", 8))
        self.notion_status_label.setProperty("muted", True)
        layout.addWidget(self.notion_status_label)

        # --- Telegram ---
        layout.addSpacing(8)
        layout.addWidget(self._settings_subheading("✈️ Telegram"))
        layout.addWidget(self._settings_hint(
            "The bot token is stored under API. Any message you send to the "
            "bot becomes a task."))
        tg_row = QHBoxLayout()
        tg_row.addWidget(QLabel("Chat ID:"))
        self.tg_chat_edit = QLineEdit()
        self.tg_chat_edit.setPlaceholderText("Send /start to the bot, then Detect")
        self.tg_chat_edit.setText(s.get("telegram_chat_id", ""))
        tg_row.addWidget(self.tg_chat_edit, stretch=1)
        layout.addLayout(tg_row)

        tg_btns = QHBoxLayout()
        tg_test = QPushButton("🔌 Test")
        tg_test.setToolTip("Check the token and send a test message")
        tg_test.clicked.connect(self._test_telegram)
        tg_detect = QPushButton("🔎 Detect chat ID")
        tg_detect.setToolTip("Read the latest message sent to the bot")
        tg_detect.clicked.connect(self._detect_telegram_chat)
        tg_report = QPushButton("📊 Send report now")
        tg_report.setToolTip("Send done-today + remaining tasks to Telegram")
        tg_report.clicked.connect(self._send_telegram_report)
        tg_btns.addWidget(tg_test)
        tg_btns.addWidget(tg_detect)
        tg_btns.addWidget(tg_report)
        tg_btns.addStretch()
        layout.addLayout(tg_btns)

        tg_opts = QHBoxLayout()
        self.tg_reports_check = QCheckBox("Notify me when a task is completed")
        self.tg_reports_check.setChecked(bool(s.get("telegram_reports", True)))
        tg_opts.addWidget(self.tg_reports_check)
        tg_opts.addStretch()
        layout.addLayout(tg_opts)

        tg_daily = QHBoxLayout()
        self.tg_daily_check = QCheckBox("Daily report at")
        self.tg_daily_check.setChecked(bool(s.get("telegram_daily", False)))
        tg_daily.addWidget(self.tg_daily_check)
        self.tg_hour_spin = QSpinBox()
        self.tg_hour_spin.setRange(0, 23)
        self.tg_hour_spin.setSuffix(":00")
        self.tg_hour_spin.setValue(int(s.get("telegram_daily_hour", 20)))
        tg_daily.addWidget(self.tg_hour_spin)
        tg_daily.addStretch()
        layout.addLayout(tg_daily)

        self.telegram_status_label = QLabel("")
        self.telegram_status_label.setFont(QFont("Segoe UI", 8))
        self.telegram_status_label.setProperty("muted", True)
        layout.addWidget(self.telegram_status_label)
        layout.addStretch(1)
        return body

    def _settings_api_section(self) -> QWidget:
        s = self.app_settings
        body, layout = self._settings_section()
        layout.addWidget(self._settings_heading("API keys"))
        layout.addWidget(self._settings_hint(
            "Stored locally in settings.json. Press Save settings to apply them."))

        layout.addSpacing(6)
        layout.addWidget(QLabel("🤖 Gemini API key"))
        self.gemini_edit = QLineEdit()
        self.gemini_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_edit.setPlaceholderText("GEMINI_API_KEY (empty = offline coach)")
        self.gemini_edit.setText(s.get("gemini_key", "") or os.getenv("GEMINI_API_KEY", ""))
        layout.addWidget(self.gemini_edit)

        layout.addSpacing(8)
        layout.addWidget(QLabel("🗒️ Joplin token"))
        self.joplin_token_edit = QLineEdit()
        self.joplin_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.joplin_token_edit.setPlaceholderText("JOPLIN_TOKEN (Joplin → Web Clipper)")
        self.joplin_token_edit.setText(s.get("joplin_token", ""))
        layout.addWidget(self.joplin_token_edit)

        layout.addSpacing(8)
        layout.addWidget(QLabel("📅 Google OAuth client"))
        google_row = QHBoxLayout()
        google_row.addWidget(QLabel("Client ID:"))
        self.google_id_edit = QLineEdit()
        self.google_id_edit.setPlaceholderText("...apps.googleusercontent.com")
        self.google_id_edit.setText(s.get("google_client_id", ""))
        google_row.addWidget(self.google_id_edit, stretch=2)
        google_row.addWidget(QLabel("Secret:"))
        self.google_secret_edit = QLineEdit()
        self.google_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_secret_edit.setText(s.get("google_client_secret", ""))
        google_row.addWidget(self.google_secret_edit, stretch=1)
        layout.addLayout(google_row)

        layout.addSpacing(8)
        layout.addWidget(QLabel("✈️ Telegram bot token"))
        self.tg_token_edit = QLineEdit()
        self.tg_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tg_token_edit.setPlaceholderText("Bot token from @BotFather")
        self.tg_token_edit.setText(s.get("telegram_token", ""))
        layout.addWidget(self.tg_token_edit)

        layout.addSpacing(8)
        layout.addWidget(QLabel("🗂️ Notion integration token"))
        self.notion_token_edit = QLineEdit()
        self.notion_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.notion_token_edit.setPlaceholderText("Internal Integration Secret (notion.so/my-integrations)")
        self.notion_token_edit.setText(s.get("notion_token", ""))
        layout.addWidget(self.notion_token_edit)

        # --- local HTTP server ---
        layout.addSpacing(14)
        layout.addWidget(self._settings_rule())
        layout.addSpacing(6)
        layout.addWidget(self._settings_heading("Local HTTP API"))
        layout.addWidget(self._settings_hint(
            "A small server on this computer lets other apps read and add "
            "your tasks. It listens on 127.0.0.1 only, so nothing is exposed "
            "to the network."))

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self.api_port_spin = QSpinBox()
        self.api_port_spin.setRange(1024, 65535)
        self.api_port_spin.setValue(int(s.get("api_port", 8765)))
        port_row.addWidget(self.api_port_spin)
        port_row.addWidget(QLabel("API token (optional)"))
        self.api_token_edit = QLineEdit()
        self.api_token_edit.setPlaceholderText("Leave empty for open local access")
        self.api_token_edit.setText(s.get("api_token", ""))
        port_row.addWidget(self.api_token_edit, stretch=1)
        layout.addLayout(port_row)
        layout.addWidget(self._settings_hint(
            "If a token is set, clients must send: "
            "Authorization: Bearer <token>"))

        api_btns = QHBoxLayout()
        self.api_toggle_btn = QPushButton("▶ Start")
        self.api_toggle_btn.setToolTip("Start the local HTTP server")
        self.api_toggle_btn.clicked.connect(self._toggle_api_server)
        api_btns.addWidget(self.api_toggle_btn)
        api_test = QPushButton("🧪 Test")
        api_test.setToolTip("Call /health and show the response")
        api_test.clicked.connect(self._test_local_api)
        api_btns.addWidget(api_test)
        api_copy = QPushButton("📋 Copy URL")
        api_copy.setToolTip("Copy the API base URL")
        api_copy.clicked.connect(self._copy_api_url)
        api_btns.addWidget(api_copy)
        api_btns.addStretch()
        layout.addLayout(api_btns)

        self.api_status_label = QLabel("")
        self.api_status_label.setWordWrap(True)
        self.api_status_label.setFont(QFont("Segoe UI", 9))
        layout.addWidget(self.api_status_label)
        layout.addWidget(self._settings_hint(
            "Endpoints: GET /health · GET|POST /tasks · PUT|DELETE /tasks/<id> · "
            "GET|POST /projects · GET|POST /sessions · GET /stats"))
        layout.addStretch(1)
        self._refresh_api_status()
        return body

    def _settings_updates_section(self) -> QWidget:
        body, layout = self._settings_section()
        layout.addWidget(self._settings_heading("Updates"))
        layout.addWidget(self._settings_hint(
            "Rakez checks GitHub releases and can install a new version for you."))

        layout.addSpacing(8)
        upd_row = QHBoxLayout()
        self.update_btn = QPushButton("🔄 Check for updates")
        self.update_btn.setToolTip("Compare this version against the latest GitHub release")
        self.update_btn.clicked.connect(self._check_for_updates)
        upd_row.addWidget(self.update_btn)
        self.update_install_btn = QPushButton("⬇️ Download & Install update")
        self.update_install_btn.setVisible(False)
        self.update_install_btn.setToolTip("Download the new installer and install it automatically")
        self.update_install_btn.setStyleSheet(
            "background-color: #9ece6a; color: #1a1b26; font-weight: bold;")
        self.update_install_btn.clicked.connect(self._download_and_install_update)
        upd_row.addWidget(self.update_install_btn)
        upd_row.addStretch()
        layout.addLayout(upd_row)

        self.update_label = QLabel(tf("Current version: {v}", v=updater.APP_VERSION))
        self.update_label.setFont(QFont("Segoe UI", 8))
        self.update_label.setProperty("muted", True)
        layout.addWidget(self.update_label)
        layout.addStretch(1)
        return body

    # ---- local HTTP API ----

    def _api_base_url(self) -> str:
        try:
            port = int(self.app_settings.get("api_port", 8765))
        except (TypeError, ValueError):
            port = 8765
        return f"http://127.0.0.1:{port}"

    def _refresh_api_status(self, extra: str = ""):
        if not hasattr(self, "api_status_label"):
            return
        running = self._api_server is not None
        if running:
            text = tf("Status: running on {url}", url=self._api_base_url())
            if extra:
                text = f"{text} — {extra}"
            color = "#3d8b40" if getattr(self, "theme", "dark") == "light" else "#9ece6a"
        else:
            text = t("Status: stopped")
            if extra:
                text = f"{text} — {extra}"
            color = "#6b7280"
        self.api_status_label.setText(text)
        self.api_status_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        if hasattr(self, "api_toggle_btn"):
            self.api_toggle_btn.setText(t("⏹ Stop") if running else t("▶ Start"))
            self.api_toggle_btn.setToolTip(
                t("Stop the local HTTP server") if running
                else t("Start the local HTTP server"))

    def _toggle_api_server(self):
        if self._api_server is None:
            self._start_api_server()
        else:
            self._stop_api_server()

    def _start_api_server(self):
        if self._api_server is not None:
            return
        try:
            port = int(self.api_port_spin.value())
        except AttributeError:
            port = int(self.app_settings.get("api_port", 8765))
        try:
            token = self.api_token_edit.text().strip()
        except AttributeError:
            token = self.app_settings.get("api_token", "")
        self.app_settings["api_port"] = port
        self.app_settings["api_token"] = token
        os.environ["API_TOKEN"] = token
        save_settings(DATA_DIR, self.app_settings)
        try:
            server, thread = run_server(port=port, store=self.storage, block=False)
        except OSError as err:
            self._api_server = None
            self._api_thread = None
            self._refresh_api_status()
            QMessageBox.warning(
                self, t("Local HTTP API"),
                tf("Could not start the local API server: {err}", err=err))
            return
        self._api_server = server
        self._api_thread = thread
        self._api_fingerprint = self._todos_fingerprint()
        self._api_watch_timer.start()
        self._refresh_api_status()

    def _stop_api_server(self):
        server = self._api_server
        self._api_server = None
        self._api_thread = None
        timer = getattr(self, "_api_watch_timer", None)
        if timer is not None:
            timer.stop()
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        self._refresh_api_status()

    def _test_local_api(self):
        if self._api_server is None:
            self._refresh_api_status(t("Local API is not running."))
            return
        request = urllib.request.Request(self._api_base_url() + "/health")
        token = ""
        try:
            token = self.api_token_edit.text().strip()
        except AttributeError:
            token = self.app_settings.get("api_token", "")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
            app_name = payload.get("app", "Rakez")
            self._refresh_api_status(
                tf("✓ API is healthy: {app}", app=app_name))
        except Exception as err:
            self._refresh_api_status(
                tf("⚠ API test failed: {err}", err=err))

    def _copy_api_url(self):
        url = self._api_base_url()
        QApplication.clipboard().setText(url)
        self._refresh_api_status(tf("✓ Copied: {url}", url=url))

    def _todos_fingerprint(self):
        try:
            return tuple(
                (str(t.get("id", "")), t.get("title", ""),
                 bool(t.get("completed")), str(t.get("project_id") or ""))
                for t in self.storage.get_todos())
        except Exception:
            return ()

    def _api_watch(self):
        if self._api_server is None:
            return
        fingerprint = self._todos_fingerprint()
        if fingerprint == self._api_fingerprint:
            return
        self._api_fingerprint = fingerprint
        try:
            self._load_todos_list()
        except Exception:
            pass
        try:
            self._refresh_task_dropdown()
        except Exception:
            pass

    def _apply_widget_size(self):
        w, h = self.set_w_spin.value(), self.set_h_spin.value()
        self.floating_widget.set_size(w, h)
        self.app_settings["widget_w"] = w
        self.app_settings["widget_h"] = h
        save_settings(DATA_DIR, self.app_settings)

    def _apply_accent(self, name: str):
        hx = ACCENTS.get(name, "#7aa2f7")
        self.floating_widget.set_accent(hx)
        self.app_settings["accent"] = hx
        save_settings(DATA_DIR, self.app_settings)

    def _apply_sound(self, name: str):
        self.floating_widget.set_sound(name)
        self.app_settings["sound"] = self.floating_widget.sound
        save_settings(DATA_DIR, self.app_settings)

    def _apply_design(self, name: str):
        key = DESIGNS.get(name, "pill")
        self.floating_widget.set_design(key)
        self.app_settings["design"] = key
        save_settings(DATA_DIR, self.app_settings)

    def _apply_background(self, name: str):
        hx = BACKGROUNDS.get(name, "#1a1b26")
        self.floating_widget.set_background(hx)
        self.app_settings["background"] = hx
        save_settings(DATA_DIR, self.app_settings)

    def _apply_opacity(self, value: int):
        pct = self.floating_widget.set_opacity(value)
        self.app_settings["opacity"] = pct
        save_settings(DATA_DIR, self.app_settings)

    def _test_sound(self):
        play_done_sound(QApplication.instance(), self.sound_combo.currentText())

    # ---- Telegram ----
    def _telegram_settings_from_ui(self) -> dict:
        """Read the Telegram row from Settings (empty dict when not built yet)."""
        if not hasattr(self, "tg_token_edit"):
            return {}
        return {
            "telegram_token": self.tg_token_edit.text().strip(),
            "telegram_chat_id": self.tg_chat_edit.text().strip(),
            "telegram_reports": bool(self.tg_reports_check.isChecked()),
            "telegram_daily": bool(self.tg_daily_check.isChecked()),
            "telegram_daily_hour": int(self.tg_hour_spin.value()),
        }

    def _apply_telegram_settings(self, values: dict | None = None, persist: bool = True):
        """Apply the current values to the live bot and start/stop polling."""
        values = values if values is not None else self._telegram_settings_from_ui()
        if not values:
            return
        self.app_settings.update(values)
        # mutate the existing bot: a running poller keeps its offset and never
        # processes the same update twice
        self.telegram.configure(
            token=values.get("telegram_token", ""),
            chat_id=values.get("telegram_chat_id", ""))
        self._telegram_last_daily = ""
        if persist:
            save_settings(DATA_DIR, self.app_settings)
        if self.telegram.available:
            self._start_telegram_polling()
        else:
            self._stop_telegram_polling()

    def _refresh_telegram_status(self, extra: str = ""):
        if not hasattr(self, "telegram_status_label"):
            return
        text = tf("Telegram: {status}", status=self.telegram.status())
        if extra:
            text = f"{text} — {extra}"
        self.telegram_status_label.setText(text)

    def _start_telegram_polling(self):
        self._refresh_telegram_status()
        if not self.telegram.available:
            return
        poller = getattr(self, "_telegram_poller", None)
        if poller is not None and poller.isRunning() and poller.bot is self.telegram:
            # already polling the live bot (settings were updated in place)
            self._refresh_telegram_status(t("listening for commands"))
            return
        self._stop_telegram_polling()
        self._telegram_poller = _TelegramPoller(self.telegram, self)
        self._telegram_poller.changed.connect(self._on_telegram_changed)
        self._telegram_poller.start()
        self._refresh_telegram_status(t("listening for commands"))

    def _stop_telegram_polling(self):
        poller = getattr(self, "_telegram_poller", None)
        if poller is not None:
            try:
                poller.stop()
                if not poller.wait(1500):
                    # the thread is blocked in a long poll; it is safe to kill
                    # at this point (quit or token removed)
                    poller.terminate()
                    poller.wait(500)
            except Exception:
                pass
            self._telegram_poller = None

    def _on_telegram_changed(self):
        """A Telegram command changed tasks — refresh the GUI."""
        try:
            self._load_todos_list()
            self._refresh_task_dropdown()
        except Exception:
            pass
        self._refresh_telegram_status(t("task list updated from Telegram"))

    def _test_telegram(self):
        values = self._telegram_settings_from_ui()
        bot = TelegramBot(token=values.get("telegram_token", ""),
                          chat_id=values.get("telegram_chat_id", ""),
                          storage=self.storage)
        if not bot.token:
            QMessageBox.warning(self, t("Telegram"),
                                t("Paste the bot token from @BotFather first."))
            return
        self.telegram_status_label.setText(t("⏳ testing Telegram..."))
        QApplication.processEvents()
        me = bot.me()
        if me is None:
            err = bot.last_error or t("Unknown error")
            self.telegram_status_label.setText(tf("⚠ Telegram: {err}", err=err))
            QMessageBox.warning(self, t("Telegram"),
                                tf("Token check failed:\n{err}", err=err))
            return
        name = me.get("username") or me.get("first_name") or "bot"
        if not bot.chat_id:
            self.telegram_status_label.setText(
                tf("✓ @{name} — send /start to the bot, then press Detect chat ID", name=name))
            QMessageBox.information(
                self, t("Telegram"),
                tf("Token OK (@{name}).\n\nOpen Telegram, send /start to the bot, "
                   "then press 🔎 Detect chat ID.", name=name))
            self._apply_telegram_settings(values)
            return
        if bot.send(tf("✅ Rakez is connected to Telegram.\nBot: @{name}", name=name)):
            self.telegram_status_label.setText(tf("✓ connected to @{name}", name=name))
            QMessageBox.information(self, t("Telegram"),
                                    tf("Connection OK — a test message was sent to your chat.\n"
                                       "Bot: @{name}", name=name))
        else:
            err = bot.last_error or t("Unknown error")
            self.telegram_status_label.setText(tf("⚠ Telegram: {err}", err=err))
            QMessageBox.warning(self, t("Telegram"),
                                tf("Could not send the test message:\n{err}\n\n"
                                   "Check the Chat ID (press Detect chat ID).", err=err))
        self._apply_telegram_settings(values)

    def _detect_telegram_chat(self):
        values = self._telegram_settings_from_ui()
        token = values.get("telegram_token", "")
        if not token:
            QMessageBox.warning(self, t("Telegram"),
                                t("Paste the bot token from @BotFather first."))
            return
        # the poller may already have seen the message: reuse its last chat id
        chat_id = getattr(self.telegram, "last_chat_id", "") or ""
        if not chat_id:
            bot = TelegramBot(token=token, storage=self.storage)
            bot.offset = getattr(self.telegram, "offset", 0)
            self.telegram_status_label.setText(t("⏳ reading the latest message..."))
            QApplication.processEvents()
            chat_id = bot.detect_chat_id()
        if not chat_id:
            self.telegram_status_label.setText(t("⚠ no messages found"))
            QMessageBox.information(
                self, t("Telegram"),
                t("No messages found.\n\nOpen Telegram, send /start to your bot, "
                  "then press Detect chat ID again."))
            return
        self.tg_chat_edit.setText(chat_id)
        values["telegram_chat_id"] = chat_id
        self._apply_telegram_settings(values)
        self.telegram_status_label.setText(tf("✓ chat ID {id}", id=chat_id))
        QMessageBox.information(self, t("Telegram"),
                                tf("Chat ID saved: {id}", id=chat_id))

    def _send_telegram_report(self):
        values = self._telegram_settings_from_ui()
        bot = TelegramBot(token=values.get("telegram_token", ""),
                          chat_id=values.get("telegram_chat_id", ""),
                          storage=self.storage)
        if not bot.configured:
            QMessageBox.warning(
                self, t("Telegram"),
                t("Set the bot token and chat ID first.\n"
                  "Send /start to your bot, then press Detect chat ID."))
            return
        self.telegram_status_label.setText(t("⏳ sending the report..."))
        QApplication.processEvents()
        if bot.send(bot.report_text(self.storage)):
            self.telegram_status_label.setText(t("✓ report sent"))
        else:
            err = bot.last_error or t("Unknown error")
            self.telegram_status_label.setText(tf("⚠ Telegram: {err}", err=err))
            QMessageBox.warning(self, t("Telegram"),
                                tf("Could not send the report:\n{err}", err=err))
        self._apply_telegram_settings(values)

    def _telegram_notify_done(self, title: str):
        """Push a completion message to Telegram (background, never blocks)."""
        title = (title or "").strip()
        if not title or not self.app_settings.get("telegram_reports", True):
            return
        bot = self.telegram
        if not bot.configured:
            return
        try:
            remaining = len([x for x in self.storage.get_todos() if not x.get("completed")])
        except Exception:
            remaining = 0
        msg = tf("✅ Done: {name}\n📋 {n} task(s) left.", name=title, n=remaining)
        threading.Thread(target=bot.send, args=(msg,), daemon=True).start()

    def _check_telegram_daily(self):
        """Once a minute: send the report when the chosen hour arrives."""
        if not self.app_settings.get("telegram_daily"):
            return
        if not self.telegram.configured:
            return
        now = datetime.now()
        try:
            hour = int(self.app_settings.get("telegram_daily_hour", 20))
        except (TypeError, ValueError):
            hour = 20
        if now.hour != hour:
            return
        today = now.date().isoformat()
        if self._telegram_last_daily == today:
            return
        self._telegram_last_daily = today
        bot = self.telegram
        report = bot.report_text(self.storage)
        threading.Thread(target=bot.send, args=(report,), daemon=True).start()

    # ---- update check ----
    def _check_for_updates(self, silent: bool = False):
        """Check GitHub for a newer version (background thread)."""
        if getattr(self, "_update_worker", None) is not None and self._update_worker.isRunning():
            return
        self._update_silent = silent
        self.update_btn.setEnabled(False)
        self.update_btn.setText(t("⏳ Checking..."))
        self.update_label.setText(t("Checking GitHub for updates..."))
        self._update_worker = _UpdateChecker(self)
        self._update_worker.checked.connect(self._on_update_checked)
        self._update_worker.start()

    def _on_update_checked(self, info: dict):
        self.update_btn.setEnabled(True)
        self.update_btn.setText(t("🔄 Check for updates"))
        cur = info.get("current", updater.APP_VERSION)
        if not info.get("ok"):
            msg = info.get("error") or t("Unknown error")
            self.update_label.setText(tf("⚠ Update check failed: {msg}", msg=msg))
            self.update_label.setStyleSheet("color: #e0af68;")
            return
        latest = info.get("latest") or cur
        self._update_info = info
        if info.get("update_available"):
            self.update_label.setText(
                tf("🆕 New version available: {latest} (you have {cur})",
                   latest=latest, cur=cur))
            self.update_label.setStyleSheet("color: #9ece6a; font-weight: bold;")
            has_installer = bool(info.get("asset_url"))
            self.update_install_btn.setVisible(has_installer)
            self.update_install_btn.setEnabled(True)
            self.update_install_btn.setText(t("⬇️ Download & Install update"))
            if has_installer:
                self._notify(t("Rakez"),
                             tf("New version {latest} is ready — open Settings and press Download & Install.",
                                latest=latest))
            else:
                self._notify(t("Rakez"),
                             tf("New version {latest} is available, but the release has no installer attached.",
                                latest=latest))
        else:
            self.update_label.setText(tf("✓ Up to date — {cur} is the latest release", cur=cur))
            self.update_label.setStyleSheet("color: #565f89;")
            self.update_install_btn.setVisible(False)
            if not getattr(self, "_update_silent", False):
                QMessageBox.information(self, t("Updates"),
                                        tf("You are on the latest version ({cur}).", cur=cur))
        self._update_silent = False

    # ---- download & install update ----
    def _download_and_install_update(self):
        info = getattr(self, "_update_info", {}) or {}
        url = info.get("asset_url") or ""
        latest = info.get("latest") or t("new version")
        if not url:
            QMessageBox.warning(
                self, t("Updates"),
                t("This release has no installer file attached.\n"
                  "Ask the publisher to attach Rakez-Setup-*.exe to the GitHub release."))
            return
        size_mb = (info.get("asset_size") or 0) / (1024 * 1024)
        detail = f" ({size_mb:.0f} MB)" if size_mb else ""
        if QMessageBox.question(
                self, t("Install update"),
                tf("Download and install Rakez {latest}{detail}?\n\n"
                   "The installer will run silently and Rakez will close to finish.\n"
                   "Your tasks and settings are kept.",
                   latest=latest, detail=detail),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        if getattr(self, "_download_worker", None) is not None and self._download_worker.isRunning():
            return
        self.update_install_btn.setEnabled(False)
        self.update_install_btn.setText(tf("⏳ Downloading… {pct}%", pct=0))
        self.update_label.setText(tf("Downloading Rakez {latest}…", latest=latest))
        self.update_label.setStyleSheet("color: #7aa2f7;")
        self._download_worker = _UpdateDownloader(url, info.get("asset_name") or "", self)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.done.connect(self._on_download_done)
        self._download_worker.start()

    def _on_download_progress(self, pct: int):
        if pct < 0:
            self.update_install_btn.setText(t("⏳ Downloading…"))
        else:
            self.update_install_btn.setText(tf("⏳ Downloading… {pct}%", pct=pct))

    def _on_download_done(self, res: dict):
        self.update_install_btn.setEnabled(True)
        self.update_install_btn.setText(t("⬇️ Download & Install update"))
        if not res.get("ok"):
            err = res.get("error", t("Unknown error"))
            self.update_label.setText(tf("⚠ Download failed: {err}", err=err))
            self.update_label.setStyleSheet("color: #e0af68;")
            QMessageBox.warning(self, t("Update failed"),
                                tf("Could not download the update:\n\n{err}", err=err))
            return
        path = res.get("path", "")
        self.update_label.setText(t("✓ Downloaded — installing and restarting…"))
        self.update_label.setStyleSheet("color: #9ece6a;")
        if not updater.run_installer(path):
            self.update_label.setText(t("⚠ Could not start the installer"))
            self.update_label.setStyleSheet("color: #e0af68;")
            QMessageBox.warning(self, t("Update"),
                                tf("The installer could not be started.\n\n"
                                   "You can run it manually:\n{path}", path=path))
            return
        QMessageBox.information(
            self, t("Installing update"),
            t("Rakez will close now and the installer will finish the update.\n"
              "Open Rakez again after a few seconds."))
        self._quit_app()

    def _save_settings(self):
        s = self.app_settings
        old_api_port = s.get("api_port", 8765)
        s["theme"] = THEMES.get(getattr(self, "theme_combo").currentText(), self.theme)
        s["widget_w"] = self.set_w_spin.value()
        s["widget_h"] = self.set_h_spin.value()
        s["accent"] = ACCENTS.get(self.accent_combo.currentText(), "#7aa2f7")
        s["background"] = BACKGROUNDS.get(self.bg_combo.currentText(), "#1a1b26")
        s["gemini_key"] = self.gemini_edit.text().strip()
        s["joplin_token"] = self.joplin_token_edit.text().strip()
        s["joplin_base"] = self.joplin_base_edit.text().strip() or "http://127.0.0.1:41184"
        s["joplin_folder"] = self.joplin_folder_edit.text().strip() or JOPLIN_DEFAULT_FOLDER
        s["joplin_tags"] = self.joplin_tags_edit.text().strip() or "task,lifebot"
        s["sound"] = self.sound_combo.currentText()
        s["design"] = DESIGNS.get(self.design_combo.currentText(), "pill")
        s["opacity"] = self.opacity_spin.value()
        s["google_client_id"] = self.google_id_edit.text().strip()
        s["google_client_secret"] = self.google_secret_edit.text().strip()
        s["notion_token"] = self.notion_token_edit.text().strip()
        s["notion_database_id"] = self.notion_db_edit.text().strip()
        if hasattr(self, "auto_sync_check"):
            s["auto_sync"] = bool(self.auto_sync_check.isChecked())
        if hasattr(self, "api_port_spin"):
            s["api_port"] = int(self.api_port_spin.value())
        if hasattr(self, "api_token_edit"):
            s["api_token"] = self.api_token_edit.text().strip()
        s.update(self._telegram_settings_from_ui())
        ok = save_settings(DATA_DIR, s)
        # apply instantly — no restart, no .env
        if s["gemini_key"]:
            os.environ["GEMINI_API_KEY"] = s["gemini_key"]
        elif "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        self.coach.online = bool(os.getenv("GEMINI_API_KEY"))
        self.joplin.token = s["joplin_token"] or os.getenv("JOPLIN_TOKEN", "")
        self.joplin.base_url = s["joplin_base"].rstrip("/")
        self.joplin_folder = s["joplin_folder"]
        self.joplin_tags = s["joplin_tags"]
        self.notion.token = s["notion_token"]
        self.notion.database_id = s["notion_database_id"]
        self.sync_hub.joplin_folder = self.joplin_folder
        self.sync_hub.joplin_tags = self.joplin_tags
        self.gsync.client_id = s["google_client_id"]
        self.gsync.client_secret = s["google_client_secret"]
        self.gsync._cal = self.gsync._tasks = None
        self.google_status_label.setText(f"Google: {self.gsync.status()}")
        if hasattr(self, "notion_status_label"):
            self.notion_status_label.setText(f"Notion: {self.notion.status()}")
        self._apply_telegram_settings(s, persist=False)
        self.floating_widget.set_accent(s["accent"])
        self.floating_widget.set_sound(s["sound"])
        self.floating_widget.set_design(s["design"])
        self.floating_widget.set_background(s["background"])
        self.floating_widget.set_size(s["widget_w"], s["widget_h"])
        self.floating_widget.set_opacity(s["opacity"])
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setValue(int(s["opacity"]))
        self.opacity_spin.blockSignals(False)
        mode = t("🟢 Gemini AI") if self.coach.online else t("🟡 Offline coach")
        self.status_label.setText(f"{mode}  •  Joplin: {self.joplin.status()}")
        os.environ["API_TOKEN"] = s.get("api_token", "")
        self._refresh_api_status()
        if self._api_server is not None and s.get("api_port") != old_api_port:
            self._stop_api_server()
            self._start_api_server()
        self.settings_status.setText(t("✓ saved to settings.json") if ok
                                     else t("⚠ save failed"))

    def _apply_google_creds_from_ui(self) -> bool:
        """Pick up Client ID/Secret typed in Settings (no Save needed) and persist."""
        cid = self.google_id_edit.text().strip()
        sec = self.google_secret_edit.text().strip()
        changed = (cid != (self.app_settings.get("google_client_id") or "")
                   or sec != (self.app_settings.get("google_client_secret") or ""))
        if changed:
            self.app_settings["google_client_id"] = cid
            self.app_settings["google_client_secret"] = sec
            save_settings(DATA_DIR, self.app_settings)
            self.gsync._cal = self.gsync._tasks = None  # rebuild with new creds
        self.gsync.client_id = cid or os.getenv("GOOGLE_CLIENT_ID", "")
        self.gsync.client_secret = sec or os.getenv("GOOGLE_CLIENT_SECRET", "")
        if not (self.gsync.client_id and self.gsync.client_secret):
            QMessageBox.warning(
                self, t("Google"),
                t("Client ID and Client Secret are required.\n\n"
                  "Google Cloud Console → APIs & Services → Credentials →\n"
                  "Create OAuth client ID → Desktop app → copy both values here."))
            return False
        return True

    def _authorize_google(self):
        if not self._apply_google_creds_from_ui():
            return
        self.google_status_label.setText(t("⏳ opening browser for Google authorization..."))
        QApplication.processEvents()
        if self.gsync.authorize():
            self.google_status_label.setText(t("✓ Google connected"))
            QMessageBox.information(self, t("Google"), t("Connected! Tokens saved locally."))
        else:
            self.google_status_label.setText(tf("⚠ Google: {err}", err=self.gsync.last_error))
            QMessageBox.warning(self, t("Google"),
                                tf("Authorization failed:\n{err}", err=self.gsync.last_error))

    def _test_google_connection(self):
        """Real API round-trip: Tasks list + Calendar primary (no writes)."""
        if not self._apply_google_creds_from_ui():
            return
        self.google_status_label.setText(t("⏳ testing Google connection..."))
        QApplication.processEvents()
        res = self.gsync.test_connection()
        if res.get("ok"):
            self.google_status_label.setText(f"✓ {res['message']}")
            QMessageBox.information(self, t("Google Test"),
                                    tf("Connection OK\n\n{msg}", msg=res['message']))
        elif "authoriz" in res["message"].lower():
            # configured but no token yet → offer the browser flow right away
            if QMessageBox.question(
                    self, t("Google Test"),
                    tf("{msg}\n\nAuthorize now?", msg=res['message']),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                self._authorize_google()
        else:
            self.google_status_label.setText(tf("⚠ Google: {err}", err=res['message']))
            QMessageBox.warning(self, t("Google Test"),
                                tf("Connection failed:\n\n{msg}", msg=res['message']))

    def _apply_notion_from_ui(self) -> bool:
        """Use the values typed in Settings even before Save."""
        try:
            self.notion.token = self.notion_token_edit.text().strip()
            self.notion.database_id = self.notion_db_edit.text().strip()
        except Exception:
            pass
        if not self.notion.available:
            self.notion_status_label.setText(f"⚠ {self.notion.status()}")
            return False
        return True

    def _test_notion(self):
        if not self._apply_notion_from_ui():
            return
        self.notion_status_label.setText(t("⏳ testing Notion..."))
        QApplication.processEvents()
        res = self.notion.test_connection()
        if res.get("ok"):
            self.notion_status_label.setText(f"✓ {res['message']}")
            QMessageBox.information(self, t("Notion Test"),
                                    tf("Connection OK\n\n{msg}", msg=res["message"]))
        else:
            self.notion_status_label.setText(
                tf("⚠ Notion: {err}", err=res.get("message", "")))
            QMessageBox.warning(self, t("Notion Test"),
                                tf("Connection failed:\n\n{msg}",
                                   msg=res.get("message", "")))

    def _pull_remote_completions(self):
        """Pull completions made in Google Tasks / Joplin / Notion (background)."""
        if not self.app_settings.get("auto_sync", True):
            return
        if (self._remote_sync_thread is not None
                and self._remote_sync_thread.is_alive()):
            return

        def worker():
            try:
                res = self.sync_hub.pull()
            except Exception as e:
                res = {"completed": 0, "errors": [str(e)[:160]]}
            self.remote_sync_finished.emit(res)

        self._remote_sync_thread = threading.Thread(target=worker, daemon=True)
        self._remote_sync_thread.start()

    def _after_remote_pull(self, res: dict):
        """Refresh the UI after a background pull (main thread)."""
        n = int((res or {}).get("completed") or 0)
        if not n:
            return
        self._load_todos_list()
        self._refresh_task_dropdown()
        if hasattr(self, "notion_status_label"):
            self.notion_status_label.setText(
                tf("✓ {n} task(s) completed from other services", n=n))

    def _sync_all_integrations(self):
        """Push every task to all configured services (manual full sync)."""
        self._apply_notion_from_ui()
        self.notion_status_label.setText(t("⏳ syncing tasks..."))
        QApplication.processEvents()
        try:
            res = self.sync_hub.sync_all()
        except Exception as e:
            res = {"errors": [str(e)[:160]]}
        parts = []
        pulled = int(res.get("pulled") or 0)
        if pulled:
            parts.append(tf("✓ {n} task(s) completed from other services",
                            n=pulled))
        j = res.get("joplin") or {}
        if j:
            parts.append(tf("Joplin: {c} added, {u} updated, {d} completed",
                            c=j.get("created", 0), u=j.get("updated", 0),
                            d=j.get("completed", 0)))
        g = res.get("google") or {}
        if g:
            parts.append(tf("Google Tasks: {n} pushed", n=g.get("pushed", 0)))
        n = res.get("notion") or {}
        if n:
            parts.append(tf("Notion: {c} created, {u} updated",
                            c=n.get("created", 0), u=n.get("updated", 0)))
        errors = res.get("errors") or []
        summary = "\n".join(parts) or t("No integrations configured yet.")
        if errors:
            summary += "\n\n" + "\n".join(errors[:4])
            self.notion_status_label.setText(tf("⚠ {err}", err=errors[0]))
            QMessageBox.warning(self, t("Sync"), summary)
        else:
            self.notion_status_label.setText(
                t("✓ tasks synced to Notion") if n else t("✓ sync finished"))
            QMessageBox.information(self, t("Sync"), summary)
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _push_selected_to_google(self):
        key = self._selected_todo_key()
        if not key:
            return
        todos = {todo["id"]: todo for todo in self.storage.get_todos()}
        todo = todos.get(key)
        if not todo:
            return
        res = self.gsync.push_task(todo["title"], f"Category: {todo.get('category','')}")
        if isinstance(res, dict) and res.get("id"):
            self.storage.set_sync_ids(todo["id"], google_id=res["id"])
        self.google_status_label.setText(
            t("✓ in Google Tasks") if res
            else tf("⚠ Google: {err}", err=self.gsync.last_error or self.gsync.status()))

    def _pull_from_google(self):
        incoming = self.gsync.pull_tasks()
        if not incoming and self.gsync.last_error:
            self.google_status_label.setText(tf("⚠ Google: {err}", err=self.gsync.last_error))
            return
        res = self.storage.import_todos(incoming)
        if res.get("added"):
            self._load_todos_list()
            self._refresh_task_dropdown()
        self.google_status_label.setText(
            tf("✓ Google has {n} open — pulled {added}",
               n=len(incoming), added=res['added']))

    def _init_tray(self):
        self.tray = None
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = QSystemTrayIcon(self)
                self.tray.setToolTip("Rakez ركّز")
                try:
                    logo = PROJECT_ROOT / "assets" / "icon-256.png"
                    if logo.exists():
                        self.tray.setIcon(QIcon(str(logo)))
                except Exception:
                    pass
                menu = QMenu()
                show_act = QAction(t("Show Dashboard"), self)
                show_act.triggered.connect(self.show_dashboard)
                quit_act = QAction(t("Quit"), self)
                quit_act.triggered.connect(self._quit_app)
                menu.addAction(show_act)
                menu.addAction(quit_act)
                self.tray.setContextMenu(menu)
                self.tray.show()
        except Exception:
            self.tray = None

    def _notify(self, title: str, msg: str):
        try:
            if self.tray is not None:
                self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 5000)
        except Exception:
            pass

    # ---- actions ----
    def toggle_floating(self):
        if self.floating_widget.isVisible():
            self.floating_widget.hide()
        else:
            self.floating_widget.show()
            self.floating_widget.move(self.x() + self.width() - 390, self.y() + 60)

    def show_dashboard(self):
        self.show()
        self.activateWindow()

    def _on_widget_task_added(self, todo: dict):
        """Refresh lists when a task is quick-added or completed from the widget."""
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _on_widget_resized(self, w: int, h: int):
        """Mirror corner-resize dimensions into the Settings tab (debounced save)."""
        try:
            if hasattr(self, "set_w_spin"):
                self.set_w_spin.blockSignals(True)
                self.set_h_spin.blockSignals(True)
                self.set_w_spin.setValue(w)
                self.set_h_spin.setValue(h)
                self.set_w_spin.blockSignals(False)
                self.set_h_spin.blockSignals(False)
            self.app_settings["widget_w"] = w
            self.app_settings["widget_h"] = h
            self._settings_save_timer.start(800)
        except Exception:
            pass

    def _quit_app(self):
        """Quit the whole program (floating ✕ button or tray Quit)."""
        try:
            self._stop_telegram_polling()
        except Exception:
            pass
        try:
            self._stop_api_server()
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.hide()
        except Exception:
            pass
        try:
            self.floating_widget.hide()
        except Exception:
            pass
        QApplication.instance().quit()

    def _refresh_task_dropdown(self):
        self.task_selector.clear()
        for t in self.storage.get_todos():
            if not t.get("completed"):
                pom = f"{t.get('done_pomodoros',0)}/{t.get('estimate_pomodoros',1)}🍅"
                self.task_selector.addItem(f"{t.get('title')} [{t.get('category')}] {pom}", t)

    def _selected_todo_key(self) -> str | None:
        item = self.todos_list.currentItem()
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("header"):
            return None
        return data.get("id")

    def _selected_project_id(self) -> str | None:
        """Project id when a project header row is selected."""
        item = self.todos_list.currentItem()
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict) and data.get("header"):
            return data.get("id")
        return None

    def _refresh_project_combo(self):
        """(No project) + every project name in the add-task combo."""
        cur = getattr(self, "project_combo", None)
        if cur is None:
            return
        cur.blockSignals(True)
        cur.clear()
        cur.addItem("📁 (No project)", "")
        for p in self.storage.get_projects():
            cur.addItem(f"📁 {p['name']}", p["id"])
        cur.blockSignals(False)

    def _load_todos_list(self):
        show_done = self.show_done_check.isChecked() if hasattr(self, "show_done_check") else False
        self._refresh_project_combo()
        self.todos_list.clear()
        todos = self.storage.get_todos()

        def make_item(text: str, data) -> QListWidgetItem:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, data)
            return item

        def add_task(t):
            if t.get("completed") and not show_done:
                return
            st = "✓" if t.get("completed") else "○"
            item = make_item(
                f"    [{st}] {t.get('title')} ({t.get('category')}) "
                f"[{t.get('priority','medium')}] 🍅{t.get('done_pomodoros',0)}/{t.get('estimate_pomodoros',1)}", t)
            self.todos_list.addItem(item)

        # open projects first (in creation order), then ungrouped tasks
        grouped = {t.get("project_id", "") for t in todos}
        for p in self.storage.get_projects():
            if p["id"] in grouped:
                item = make_item(
                    f"📁 {p['name']} — {p['done']}/{p['total']} ({p['pct']}%)",
                    {"id": p["id"], "name": p["name"], "header": True})
                f = item.font()
                f.setBold(True)
                item.setFont(f)
                self.todos_list.addItem(item)
            for t in self.storage.get_project_todos(p["id"]):
                add_task(t)
        has_unassigned = any(t.get("project_id", "") == "" for t in todos)
        if has_unassigned:
            cnt = sum(1 for t in todos if not t.get("project_id") and not t.get("completed"))
            item = make_item(tf("📂 Ungrouped — {n} open", n=cnt), None)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            self.todos_list.addItem(item)
            for t in todos:
                if not t.get("project_id", ""):
                    add_task(t)

        # local updates reload this list themselves; keep the API watcher in sync
        # so it only refreshes for changes made through the HTTP API.
        if getattr(self, "_api_server", None) is not None:
            self._api_fingerprint = self._todos_fingerprint()

    def _add_project(self):
        name, ok = QInputDialog.getText(self, t("New Project"), t("Project name:"))
        if not (ok and (name or "").strip()):
            return
        try:
            p = self.storage.create_project(name)
        except ValueError as e:
            QMessageBox.warning(self, t("New Project"), str(e))
            return
        self._load_todos_list()

    def _delete_project(self):
        pid = self._selected_project_id()
        if not pid:
            QMessageBox.information(self, t("Delete Project"),
                                    t("Select a project header row first (📁 row)."))
            return
        p = self.storage.get_project(pid)
        if p and QMessageBox.question(
                self, t("Delete Project"),
                tf("Delete project '{name}'?\nIts tasks stay but become ungrouped.",
                   name=p['name']),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.storage.delete_project(p["id"])
            self._load_todos_list()

    def _move_selected_to_project(self):
        key = self._selected_todo_key()
        if not key:
            QMessageBox.information(self, t("Move to Project"),
                                    t("Select a task row first (not a project header)."))
            return
        projects = self.storage.get_projects()
        names = [p["name"] for p in projects]
        name, ok = QInputDialog.getItem(
            self, t("Move to Project"), t("Choose project (it stays selected after):"),
            names, 0, True)  # editable → type a new project name
        if not (ok and (name or "").strip()):
            return
        try:
            self.storage.update_todo(key, {"project_id": name.strip()})
        except ValueError as e:
            QMessageBox.warning(self, t("Move to Project"), str(e))
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _add_task(self):
        title = self.new_task_input.text().strip()
        c = self.category_combo.currentData() or self.category_combo.currentText()
        p = self.priority_combo.currentData() or "medium"
        pid = ""
        if hasattr(self, "project_combo"):
            pid = self.project_combo.currentData() or ""
        if title:
            self.storage.add_todo(title, c, priority=p, project_id=pid)
            # Joplin / Google Tasks / Notion are updated by the sync hub
            self.new_task_input.clear()
            self._load_todos_list()
            self._refresh_task_dropdown()

    def _toggle_selected(self):
        key = self._selected_todo_key()
        if not key:
            return
        todos = {t["id"]: t for t in self.storage.get_todos()}
        cur = todos.get(key, {}).get("completed", False)
        self.storage.set_completed(key, not cur)
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _delete_selected(self):
        key = self._selected_todo_key()
        if key:
            self.storage.delete_todo(key)
            self._load_todos_list()
            self._refresh_task_dropdown()

    def _clear_completed(self):
        n = self.storage.clear_completed()
        QMessageBox.information(self, t("Cleared"), tf("Removed {n} completed tasks.", n=n))
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _sync_all_to_joplin(self):
        """Push every open Rakez task into Joplin (skips duplicates)."""
        if not self.joplin.available:
            self.joplin_status_label.setText(t("⚠ Joplin not configured — set JOPLIN_TOKEN"))
            QMessageBox.warning(self, t("Joplin"),
                                t("Joplin is not configured.\nSet JOPLIN_TOKEN in your .env file."))
            return
        self.joplin_status_label.setText(t("⏳ syncing to Joplin..."))
        QApplication.processEvents()
        try:
            res = self.joplin.sync_open_todos(self.storage.get_todos(),
                                              folder_name=self.joplin_folder, tags=self.joplin_tags)
        except Exception as e:
            res = {"created": 0, "skipped": 0, "error": str(e)[:200]}
        if res.get("created") or res.get("updated"):
            self.joplin_status_label.setText(
                tf("✓ {created} added, {updated} fixed, {skipped} ok",
                   created=res['created'], updated=res['updated'],
                   skipped=res['skipped']))
            QMessageBox.information(
                self, t("Joplin Sync"),
                tf("Added {created} task(s), fixed {updated} (tags/due date).\n"
                   "{skipped} already fine.\n"
                   "Check the Joplin notebook + All-Tasks board.",
                   created=res['created'], updated=res['updated'],
                   skipped=res['skipped']))
        elif res.get("error"):
            self.joplin_status_label.setText(
                tf("⚠ Joplin: {err}", err=self.joplin.friendly_error()))
            QMessageBox.warning(self, t("Joplin Sync"),
                                tf("Sync failed:\n{err}", err=self.joplin.friendly_error()))
        else:
            self.joplin_status_label.setText(
                tf("✓ everything already in All-Tasks ({n})", n=res['skipped']))

    def _pull_from_joplin(self, silent: bool = False) -> dict:
        """Import todos created in Joplin into Rakez. Never crashes."""
        if not self.joplin.available:
            if not silent:
                self.joplin_status_label.setText(t("⚠ Joplin not configured — set JOPLIN_TOKEN"))
                QMessageBox.warning(self, t("Joplin"),
                                    t("Joplin is not configured.\nSet JOPLIN_TOKEN in your .env file."))
            return {"added": 0, "skipped": 0}
        if not silent:
            self.joplin_status_label.setText(t("⏳ pulling from Joplin..."))
            QApplication.processEvents()
        try:
            incoming = self.joplin.pull_todos(folder_name=self.joplin_folder)
            res = self.storage.import_todos(incoming)
            if res.get("added"):
                self._load_todos_list()
                self._refresh_task_dropdown()
            if not silent:
                if not incoming and self.joplin.last_error:
                    self.joplin_status_label.setText(
                        tf("⚠ Joplin: {err}", err=self.joplin.friendly_error()))
                else:
                    self.joplin_status_label.setText(
                        tf("✓ Joplin has {n} todos in '{folder}' — pulled {added} ({skipped} already here)",
                           n=len(incoming), folder=self.joplin_folder,
                           added=res['added'], skipped=res['skipped']))
                if res.get("added"):
                    QMessageBox.information(
                        self, t("Joplin Pull"),
                        tf("Imported {n} task(s) from Joplin.", n=res['added']))
                elif not incoming:
                    QMessageBox.information(
                        self, t("Joplin Pull"),
                        tf("No to-dos found in Joplin notebook '{folder}'.\n"
                           "Make sure the to-do is inside that notebook\n"
                           "(not in another notebook) and press Synchronise in Joplin first.",
                           folder=self.joplin_folder))
            return res
        except Exception as e:
            if not silent:
                self.joplin_status_label.setText(tf("⚠ Joplin pull: {err}", err=e))
            return {"added": 0, "skipped": 0}

    def _start_pomodoro(self):
        data = self.task_selector.currentData()
        if not data:
            QMessageBox.warning(self, t("Warning"), t("Please select a task first!"))
            return
        dur = self.duration_spin.value()
        self.floating_widget.set_task(data["title"], data["category"], dur)
        self.floating_widget.show()
        if not self.floating_widget.is_running:
            self.floating_widget.toggle_timer()

    def _on_session_finished(self, session):
        self.storage.log_session(session)
        self._notify(t("Rakez"),
                     tf("Session '{task}' recorded ({min}m).",
                        task=session['task'], min=session['duration_min']))
        if session.get("kind") == "focus":
            # optional: log to Google Calendar (never blocks/crashes)
            try:
                if getattr(self, "cal_check", None) is not None and self.cal_check.isChecked():
                    ev = self.gsync.log_focus_event(session["task"], session.get("duration_min", 25))
                    if ev:
                        self._notify(t("Rakez"), t("Logged to Google Calendar 📅"))
            except Exception:
                pass
            self.cycle_label.setText(
                tf("Cycles completed: {n} (long break every 4)",
                   n=self.floating_widget.cycles_done))
            # auto-suggest break — attached to the widget, fallback to popup
            minutes = self.break_spin.value() if hasattr(self, "break_spin") else DEFAULTS["short_break"]
            if self.floating_widget.cycles_done % 4 == 0:
                self.floating_widget.start_break("long_break", DEFAULTS["long_break"])
                self._widget_or_popup(
                    tf("🎉 Focus '{task}' logged! Long break started.",
                       task=session['task']))
            else:
                self._pending_break_min = minutes
                try:
                    self.floating_widget.notice_answered.disconnect()
                except Exception:
                    pass
                self.floating_widget.notice_answered.connect(self._on_break_answer)
                if not self._widget_or_popup(
                        tf("🎉 Session '{task}' recorded! Start {min}-min break?",
                           task=session['task'], min=minutes),
                        actions=[(t("Yes"), True), (t("No"), False)]):
                    # widget hidden → classic popup already asked; clean up
                    try:
                        self.floating_widget.notice_answered.disconnect()
                    except Exception:
                        pass
        else:
            self._widget_or_popup(t("☕ Break finished! Ready for next focus?"))
        self._load_analytics()
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _widget_or_popup(self, text: str, actions: list | None = None) -> bool:
        """Show text attached to the floating widget; popup fallback if hidden."""
        if self.floating_widget.isVisible():
            self.floating_widget.show_notice(text, actions=actions)
            return True
        if actions:
            reply = QMessageBox.question(self, t("Rakez"), text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            self._on_break_answer(reply == QMessageBox.StandardButton.Yes)
        else:
            QMessageBox.information(self, t("Rakez"), text)
        return False

    def _on_break_answer(self, value):
        try:
            self.floating_widget.notice_answered.disconnect()
        except Exception:
            pass
        if value:
            minutes = getattr(self, "_pending_break_min", DEFAULTS["short_break"])
            self.floating_widget.start_break("short_break", minutes)

    def _plan_morning(self):
        self.coach_output.setPlainText(t("Hermes is thinking... ⏳"))
        QApplication.processEvents()
        self.coach_output.setMarkdown(self.coach.morning_plan(self.storage.get_todos()))

    def _resolve_snag(self):
        excuse, ok = QInputDialog.getText(self, t("Resolve Snag"),
                                          t("What obstacle or excuse are you facing?"))
        if ok and excuse:
            self.coach_output.setPlainText(t("Hermes is thinking... ⏳"))
            QApplication.processEvents()
            self.coach_output.setMarkdown(self.coach.resolve_snag(excuse, self.storage.get_todos()))

    def _daily_review(self):
        self.coach_output.setPlainText(t("Hermes is thinking... ⏳"))
        QApplication.processEvents()
        self.coach_output.setMarkdown(
            self.coach.daily_review(self.storage.get_sessions(), self.storage.get_todos()))

    def _load_analytics(self):
        st = self.storage.stats(days=7)
        lines = [
            tf("Total sessions: {total} | Last 7d: {recent}",
               total=st['total_logged_sessions'], recent=st['recent_sessions']),
            tf("Focus minutes (7d): {minutes}", minutes=st['recent_focus_minutes']),
            tf("Tasks: {done}/{total} done | Open: {open} | Streak: {streak}d",
               done=st['done_tasks'], total=st['total_tasks_count'],
               open=st['open_tasks'], streak=st['streak_days']),
            "",
            t("Minutes by category (7d):"),
        ]
        by_cat = st.get("by_category_min", {})
        if by_cat:
            mx = max(by_cat.values())
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
                bar = "█" * max(1, int(v / mx * 25)) if mx else ""
                lines.append(f"  {k:12s} {v:4d}m {bar}")
        else:
            lines.append("  " + t("(no focus sessions yet)"))
        self.analytics_box.setText("\n".join(lines))

    def closeEvent(self, event):
        # minimize to tray instead of quitting when tray available
        if self.tray is not None and self.tray.isVisible():
            self.hide()
            self.floating_widget.show()
            event.ignore()
        else:
            event.accept()


def main():
    print("🚀 Starting Rakez GUI & Floating Widget...")
    storage = SqliteStorage(data_dir=DATA_DIR)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    try:
        logo = PROJECT_ROOT / "assets" / "logo.svg"
        if logo.exists():
            app.setWindowIcon(QIcon(str(logo)))
    except Exception:
        pass

    window = RakezMainWindow(storage)
    window.show()

    # two-way sync: pull anything added in Joplin while we were away.
    # Deferred so the window paints first; network runs after event loop
    # starts instead of blocking startup.
    QTimer.singleShot(800, lambda: _safe_startup_pull(window))
    # silent update check right after the Joplin pull (network already warm)
    QTimer.singleShot(2000, lambda: _safe_update_check(window))

    window.floating_widget.show()
    window.floating_widget.move(120, 120)

    print("✓ Rakez is now running on your screen!")
    sys.exit(app.exec())


def _safe_startup_pull(window):
    try:
        window._pull_from_joplin(silent=True)
    except Exception:
        pass


def _safe_update_check(window):
    try:
        window._check_for_updates(silent=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
