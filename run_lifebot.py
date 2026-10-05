import sys
import os
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QAction, QIcon, QCursor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox, QMessageBox,
    QInputDialog, QSystemTrayIcon, QMenu,
    QCheckBox, QSizePolicy, QSizeGrip, QProgressBar, QGridLayout, QFrame,
    QScrollArea
)

from core.storage import SqliteStorage, CATEGORIES
from core.coach import HermesCoach
from core.joplin import JoplinClient, DEFAULT_FOLDER as JOPLIN_DEFAULT_FOLDER
from core.settings import load_settings, save_settings, ACCENTS, DEFAULTS as SETTINGS_DEFAULTS
from core.settings import SOUND_NAMES, DESIGNS, BACKGROUNDS, valid_hex
from core.google_sync import GoogleSync

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
            QLabel {{ color: #c0caf5; font-family: 'Segoe UI', Arial; }}
            QPushButton {{
                background-color: #24283b;
                border: 1px solid {a};
                border-radius: 8px;
                color: {a};
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {a}; color: #1a1b26; }}
            QLineEdit, QComboBox {{
                background-color: #24283b;
                border: 1px solid #414868;
                border-radius: 6px;
                color: #c0caf5;
                padding: 5px;
            }}
            QProgressBar {{
                background-color: #24283b;
                border: 1px solid #414868;
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
    DESIGN_DEFAULT_SIZES = {"pill": (390, 150), "neon": (430, 150), "split": (470, 120),
                            "retro": (380, 480)}

    def set_design(self, design: str):
        self.design = design if design in ("pill", "neon", "split", "retro") else "pill"
        self._build_design()
        mw, mh = self.DESIGN_MIN_SIZES[self.design]
        self.setMinimumSize(mw, mh)
        w, h = self.DESIGN_DEFAULT_SIZES[self.design]
        self.resize(max(mw, w), max(mh, h))
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
        self.inline_category.addItems(_CATS)
        frow.addWidget(self.inline_category, stretch=2)
        ok_btn = QPushButton("Add")
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
            todo = self.storage.add_todo(title, self.inline_category.currentText())
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
        self.task_label = QLabel(self.current_task)
        self.task_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.task_label.setStyleSheet(f"color: {self.accent};")
        self.task_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_label.setToolTip("Click to switch task")
        self.task_label.mousePressEvent = lambda _e: self._switch_task_menu()

        self.cat_label = QLabel(f"🏷️ {self.current_category}")
        self.cat_label.setFont(QFont("Segoe UI", 8))
        self.cat_label.setStyleSheet("color: #bb9af7;")

        self.mode_label = QLabel("🎯 FOCUS")
        self.mode_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.mode_label.setStyleSheet("color: #9ece6a;")

        self.time_label = QLabel(f"{DEFAULTS['focus']:02d}:00")
        self.time_label.setFont(QFont("Consolas", time_size, QFont.Weight.Bold))
        self.time_label.setStyleSheet("color: #9ece6a;")
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
        self.ring = None
        self.bar = None
        {"pill": self._build_pill, "neon": self._build_neon,
         "split": self._build_split, "retro": self._build_retro}[self.design](lay)
        self._refresh_progress()

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
        left.setStyleSheet(
            f"QFrame {{ background-color: rgba(0,0,0,0.25); "
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
        for t in todos:
            c = t.get("category", "Deep Work")
            if c not in groups:
                groups[c] = []
                order.append(c)
            groups[c].append(t)
        n_done = sum(1 for t in todos if t.get("completed"))
        for cat in order:
            head = QLabel(f"PHASE: {cat.upper()}")
            head.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            head.setStyleSheet(f"color: {self.RETRO_RED};")
            lay.addWidget(head)
            for t in groups[cat]:
                done = bool(t.get("completed"))
                box = "☒" if done else "☐"
                cb = QCheckBox(f"{box}  {t.get('title')}")
                cb.setFont(QFont("Consolas", 9))
                cb.setChecked(done)
                cb.setStyleSheet(
                    f"QCheckBox {{ color: {self.RETRO_INK}; spacing: 4px; }}")
                cb.setProperty("todo_id", t.get("id"))
                cb.toggled.connect(self._toggle_retro_task)
                lay.addWidget(cb)
        lay.addStretch()
        total = len(todos)
        self.retro_count.setText(f"{n_done}/{total} done" if total else "no tasks yet")
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
            self.show_notice("No task selected — pick one first.")
            return
        try:
            done_ok = self.storage.set_completed(name, True)
        except Exception:
            done_ok = False
        if not done_ok:
            self.show_notice(f"⚠ Could not complete '{name}'.")
            return
        self.show_notice(f"✓ '{name}' completed!")
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
            act = menu.addAction("(no open tasks)")
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
        self.cat_label.setText(f"🏷️ {category}")
        self.mode_label.setText("🎯 FOCUS")
        self.total_seconds = duration_min * 60
        self.remaining_seconds = self.total_seconds
        self._update_time_display()
        self._refresh_retro_list()

    def start_break(self, kind="short_break", minutes: int | None = None):
        if minutes is None:
            minutes = DEFAULTS["short_break"] if kind == "short_break" else DEFAULTS["long_break"]
        self.mode = kind
        label = "☕ SHORT BREAK" if kind == "short_break" else "🌴 LONG BREAK"
        self.mode_label.setText(label)
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
        if self.is_running:
            self.timer.stop()
            self.is_running = False
            self.toggle_btn.setText("▶")
            self.time_label.setStyleSheet("color: #e0af68;")
        else:
            if self.remaining_seconds <= 0:
                # expired timer: restart the same interval instead of
                # instantly emitting a duplicate DONE session
                self.remaining_seconds = self.total_seconds
                self._update_time_display()
            self.timer.start(1000)
            self.is_running = True
            self.toggle_btn.setText("⏸")
            self.time_label.setStyleSheet("color: #9ece6a;")

    def _tick(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self._update_time_display()
        else:
            self.timer.stop()
            self.is_running = False
            self.toggle_btn.setText("▶")
            self.time_label.setText("DONE!")
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
        self.setWindowTitle("Rakez ركّز - AI Coach & Pomodoro")
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

        self._apply_theme()
        self._init_ui()
        self._init_tray()

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1a1b26; color: #c0caf5; font-family: 'Segoe UI', sans-serif; }
            QTabWidget::pane { border: 1px solid #292e42; background-color: #1f2335; border-radius: 8px; }
            QTabBar::tab { background-color: #1a1b26; color: #7aa2f7; padding: 10px 18px; font-weight: bold; }
            QTabBar::tab:selected { background-color: #1f2335; color: #bb9af7; border-bottom: 2px solid #7aa2f7; }
            QPushButton { background-color: #24283b; border: 1px solid #414868; border-radius: 6px; color: #7aa2f7; padding: 8px 14px; font-weight: bold; }
            QPushButton:hover { background-color: #7aa2f7; color: #1a1b26; }
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox { background-color: #24283b; border: 1px solid #414868; border-radius: 6px; color: #c0caf5; padding: 6px; }
        """)

    def _init_ui(self):
        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        header = QHBoxLayout()
        title = QLabel("🤖 Rakez ركّز Productivity System")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #7aa2f7;")

        toggle_float_btn = QPushButton("📌 Show/Hide Floating")
        toggle_float_btn.clicked.connect(self.toggle_floating)

        header.addWidget(title)
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
        layout.addWidget(tabs)

        self.setCentralWidget(main_widget)

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

        add_layout = QHBoxLayout()
        self.new_task_input = QLineEdit()
        self.new_task_input.setPlaceholderText("New task title... (Enter to add)")
        self.new_task_input.returnPressed.connect(self._add_task)
        self.category_combo = QComboBox()
        self.category_combo.addItems(CATEGORIES)
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["low", "medium", "high"])
        self.priority_combo.setCurrentText("medium")
        add_btn = QPushButton("➕ Add")
        add_btn.clicked.connect(self._add_task)

        add_layout.addWidget(self.new_task_input, stretch=3)
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

    def _create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        s = self.app_settings

        # --- widget size ---
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

        # --- accent color ---
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

        # --- widget design + background ---
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

        # --- transparency ---
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

        # --- notification sound ---
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

        # --- API keys (no .env needed) ---
        layout.addWidget(QLabel("🔑 API keys (saved locally, applied instantly):"))
        self.gemini_edit = QLineEdit()
        self.gemini_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_edit.setPlaceholderText("GEMINI_API_KEY (empty = offline coach)")
        self.gemini_edit.setText(s.get("gemini_key", "") or os.getenv("GEMINI_API_KEY", ""))
        layout.addWidget(self.gemini_edit)

        self.joplin_token_edit = QLineEdit()
        self.joplin_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.joplin_token_edit.setPlaceholderText("JOPLIN_TOKEN (Joplin → Web Clipper)")
        self.joplin_token_edit.setText(s.get("joplin_token", ""))
        layout.addWidget(self.joplin_token_edit)

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

        # --- Google (Calendar + Tasks) ---
        layout.addWidget(QLabel("📅 Google Calendar + Tasks (OAuth client from Google Cloud Console):"))
        grow = QHBoxLayout()
        grow.addWidget(QLabel("Client ID:"))
        self.google_id_edit = QLineEdit()
        self.google_id_edit.setPlaceholderText("...apps.googleusercontent.com")
        self.google_id_edit.setText(s.get("google_client_id", ""))
        grow.addWidget(self.google_id_edit, stretch=2)
        grow.addWidget(QLabel("Secret:"))
        self.google_secret_edit = QLineEdit()
        self.google_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_secret_edit.setText(s.get("google_client_secret", ""))
        grow.addWidget(self.google_secret_edit, stretch=2)
        auth_btn = QPushButton("🔓 Authorize")
        auth_btn.setToolTip("Open browser once to grant access")
        auth_btn.clicked.connect(self._authorize_google)
        grow.addWidget(auth_btn)
        layout.addLayout(grow)

        save_btn = QPushButton("💾 Save settings")
        save_btn.setStyleSheet("background-color: #9ece6a; color: #1a1b26; font-size: 13px; padding: 10px;")
        save_btn.clicked.connect(self._save_settings)
        layout.addWidget(save_btn)
        self.settings_status = QLabel("")
        self.settings_status.setFont(QFont("Segoe UI", 8))
        layout.addWidget(self.settings_status)
        layout.addStretch()
        return tab

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

    def _save_settings(self):
        s = self.app_settings
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
        self.gsync.client_id = s["google_client_id"]
        self.gsync.client_secret = s["google_client_secret"]
        self.gsync._cal = self.gsync._tasks = None
        self.google_status_label.setText(f"Google: {self.gsync.status()}")
        self.floating_widget.set_accent(s["accent"])
        self.floating_widget.set_size(s["widget_w"], s["widget_h"])
        self.floating_widget.set_sound(s["sound"])
        self.floating_widget.set_design(s["design"])
        self.floating_widget.set_background(s["background"])
        self.floating_widget.set_opacity(s["opacity"])
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setValue(int(s["opacity"]))
        self.opacity_spin.blockSignals(False)
        mode = "🟢 Gemini AI" if self.coach.online else "🟡 Offline coach"
        self.status_label.setText(f"{mode}  •  Joplin: {self.joplin.status()}")
        self.settings_status.setText("✓ saved to settings.json" if ok else "⚠ save failed")

    def _authorize_google(self):
        self.google_status_label.setText("⏳ opening browser for Google authorization...")
        QApplication.processEvents()
        if self.gsync.authorize():
            self.google_status_label.setText("✓ Google connected")
            QMessageBox.information(self, "Google", "Connected! Tokens saved locally.")
        else:
            self.google_status_label.setText(f"⚠ Google: {self.gsync.last_error}")
            QMessageBox.warning(self, "Google", f"Authorization failed:\n{self.gsync.last_error}")

    def _push_selected_to_google(self):
        key = self._selected_todo_key()
        if not key:
            return
        todos = {t["id"]: t for t in self.storage.get_todos()}
        t = todos.get(key)
        if not t:
            return
        res = self.gsync.push_task(t["title"], f"Category: {t.get('category','')}")
        self.google_status_label.setText("✓ in Google Tasks" if res
                                         else f"⚠ Google: {self.gsync.last_error or self.gsync.status()}")

    def _pull_from_google(self):
        incoming = self.gsync.pull_tasks()
        if not incoming and self.gsync.last_error:
            self.google_status_label.setText(f"⚠ Google: {self.gsync.last_error}")
            return
        res = self.storage.import_todos(incoming)
        if res.get("added"):
            self._load_todos_list()
            self._refresh_task_dropdown()
        self.google_status_label.setText(
            f"✓ Google has {len(incoming)} open — pulled {res['added']}")

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
                show_act = QAction("Show Dashboard", self)
                show_act.triggered.connect(self.show_dashboard)
                quit_act = QAction("Quit", self)
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
        """Refresh lists when a task is quick-added from the floating widget."""
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
        return data.get("id") if isinstance(data, dict) else None

    def _load_todos_list(self):
        show_done = self.show_done_check.isChecked() if hasattr(self, "show_done_check") else False
        self.todos_list.clear()
        for t in self.storage.get_todos():
            if t.get("completed") and not show_done:
                continue
            st = "✓" if t.get("completed") else "○"
            item = QListWidgetItem(f"[{st}] {t.get('title')} ({t.get('category')}) [{t.get('priority','medium')}] 🍅{t.get('done_pomodoros',0)}/{t.get('estimate_pomodoros',1)}")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.todos_list.addItem(item)

    def _add_task(self):
        t = self.new_task_input.text().strip()
        c = self.category_combo.currentText()
        p = self.priority_combo.currentText()
        if t:
            self.storage.add_todo(t, c, priority=p)
            # إضافة المهمة لـ Joplin تلقائياً — must never crash the GUI
            try:
                created = self.joplin.create_todo(title=t, body=f"Category: {c}\nPriority: {p}",
                                                  folder_name=self.joplin_folder, tags=self.joplin_tags)
                if created is None and self.joplin.available:
                    print(f"[joplin] failed: {self.joplin.last_error}")
                    self.joplin_status_label.setText(f"⚠ Joplin: {self.joplin.friendly_error()}")
                elif created is not None:
                    self.joplin_status_label.setText("✓ in Joplin All-Tasks")
            except Exception as e:
                print(f"[joplin] error: {e}")

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
        QMessageBox.information(self, "Cleared", f"Removed {n} completed tasks.")
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _sync_all_to_joplin(self):
        """Push every open Rakez task into Joplin (skips duplicates)."""
        if not self.joplin.available:
            self.joplin_status_label.setText("⚠ Joplin not configured — set JOPLIN_TOKEN")
            QMessageBox.warning(self, "Joplin", "Joplin is not configured.\nSet JOPLIN_TOKEN in your .env file.")
            return
        self.joplin_status_label.setText("⏳ syncing to Joplin...")
        QApplication.processEvents()
        try:
            res = self.joplin.sync_open_todos(self.storage.get_todos(),
                                              folder_name=self.joplin_folder, tags=self.joplin_tags)
        except Exception as e:
            res = {"created": 0, "skipped": 0, "error": str(e)[:200]}
        if res.get("created") or res.get("updated"):
            self.joplin_status_label.setText(
                f"✓ {res['created']} added, {res['updated']} fixed, {res['skipped']} ok")
            QMessageBox.information(self, "Joplin Sync",
                f"Added {res['created']} task(s), fixed {res['updated']} (tags/due date).\n"
                f"{res['skipped']} already fine.\n"
                "Check the Joplin notebook + All-Tasks board.")
        elif res.get("error"):
            self.joplin_status_label.setText(f"⚠ Joplin: {self.joplin.friendly_error()}")
            QMessageBox.warning(self, "Joplin Sync", f"Sync failed:\n{self.joplin.friendly_error()}")
        else:
            self.joplin_status_label.setText(f"✓ everything already in All-Tasks ({res['skipped']})")

    def _pull_from_joplin(self, silent: bool = False) -> dict:
        """Import todos created in Joplin into Rakez. Never crashes."""
        if not self.joplin.available:
            if not silent:
                self.joplin_status_label.setText("⚠ Joplin not configured — set JOPLIN_TOKEN")
                QMessageBox.warning(self, "Joplin", "Joplin is not configured.\nSet JOPLIN_TOKEN in your .env file.")
            return {"added": 0, "skipped": 0}
        if not silent:
            self.joplin_status_label.setText("⏳ pulling from Joplin...")
            QApplication.processEvents()
        try:
            incoming = self.joplin.pull_todos(folder_name=self.joplin_folder)
            res = self.storage.import_todos(incoming)
            if res.get("added"):
                self._load_todos_list()
                self._refresh_task_dropdown()
            if not silent:
                if not incoming and self.joplin.last_error:
                    self.joplin_status_label.setText(f"⚠ Joplin: {self.joplin.friendly_error()}")
                else:
                    self.joplin_status_label.setText(
                        f"✓ Joplin has {len(incoming)} todos in '{self.joplin_folder}' — "
                        f"pulled {res['added']} ({res['skipped']} already here)")
                if res.get("added"):
                    QMessageBox.information(self, "Joplin Pull",
                        f"Imported {res['added']} task(s) from Joplin.")
                elif not incoming:
                    QMessageBox.information(self, "Joplin Pull",
                        f"No to-dos found in Joplin notebook '{self.joplin_folder}'.\n"
                        "Make sure the to-do is inside that notebook\n"
                        "(not in another notebook) and press Synchronise in Joplin first.")
            return res
        except Exception as e:
            if not silent:
                self.joplin_status_label.setText(f"⚠ Joplin pull: {e}")
            return {"added": 0, "skipped": 0}

    def _start_pomodoro(self):
        data = self.task_selector.currentData()
        if not data:
            QMessageBox.warning(self, "Warning", "Please select a task first!")
            return
        dur = self.duration_spin.value()
        self.floating_widget.set_task(data["title"], data["category"], dur)
        self.floating_widget.show()
        if not self.floating_widget.is_running:
            self.floating_widget.toggle_timer()

    def _on_session_finished(self, session):
        self.storage.log_session(session)
        self._notify("Rakez", f"Session '{session['task']}' recorded ({session['duration_min']}m).")
        if session.get("kind") == "focus":
            # optional: log to Google Calendar (never blocks/crashes)
            try:
                if getattr(self, "cal_check", None) is not None and self.cal_check.isChecked():
                    ev = self.gsync.log_focus_event(session["task"], session.get("duration_min", 25))
                    if ev:
                        self._notify("Rakez", "Logged to Google Calendar 📅")
            except Exception:
                pass
            self.cycle_label.setText(f"Cycles completed: {self.floating_widget.cycles_done} (long break every 4)")
            # auto-suggest break — attached to the widget, fallback to popup
            minutes = self.break_spin.value() if hasattr(self, "break_spin") else DEFAULTS["short_break"]
            if self.floating_widget.cycles_done % 4 == 0:
                self.floating_widget.start_break("long_break", DEFAULTS["long_break"])
                self._widget_or_popup(
                    f"🎉 Focus '{session['task']}' logged! Long break started.")
            else:
                self._pending_break_min = minutes
                try:
                    self.floating_widget.notice_answered.disconnect()
                except Exception:
                    pass
                self.floating_widget.notice_answered.connect(self._on_break_answer)
                if not self._widget_or_popup(
                        f"🎉 Session '{session['task']}' recorded! Start {minutes}-min break?",
                        actions=[("Yes", True), ("No", False)]):
                    # widget hidden → classic popup already asked; clean up
                    try:
                        self.floating_widget.notice_answered.disconnect()
                    except Exception:
                        pass
        else:
            self._widget_or_popup("☕ Break finished! Ready for next focus?")
        self._load_analytics()
        self._load_todos_list()
        self._refresh_task_dropdown()

    def _widget_or_popup(self, text: str, actions: list | None = None) -> bool:
        """Show text attached to the floating widget; popup fallback if hidden."""
        if self.floating_widget.isVisible():
            self.floating_widget.show_notice(text, actions=actions)
            return True
        if actions:
            reply = QMessageBox.question(self, "Rakez", text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            self._on_break_answer(reply == QMessageBox.StandardButton.Yes)
        else:
            QMessageBox.information(self, "Rakez", text)
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
        self.coach_output.setPlainText("Hermes is thinking... ⏳")
        QApplication.processEvents()
        self.coach_output.setMarkdown(self.coach.morning_plan(self.storage.get_todos()))

    def _resolve_snag(self):
        excuse, ok = QInputDialog.getText(self, "Resolve Snag", "What obstacle or excuse are you facing?")
        if ok and excuse:
            self.coach_output.setPlainText("Hermes is thinking... ⏳")
            QApplication.processEvents()
            self.coach_output.setMarkdown(self.coach.resolve_snag(excuse, self.storage.get_todos()))

    def _daily_review(self):
        self.coach_output.setPlainText("Hermes is thinking... ⏳")
        QApplication.processEvents()
        self.coach_output.setMarkdown(
            self.coach.daily_review(self.storage.get_sessions(), self.storage.get_todos()))

    def _load_analytics(self):
        st = self.storage.stats(days=7)
        lines = [
            f"Total sessions: {st['total_logged_sessions']} | Last 7d: {st['recent_sessions']}",
            f"Focus minutes (7d): {st['recent_focus_minutes']}",
            f"Tasks: {st['done_tasks']}/{st['total_tasks_count']} done | Open: {st['open_tasks']} | Streak: {st['streak_days']}d",
            "",
            "Minutes by category (7d):",
        ]
        by_cat = st.get("by_category_min", {})
        if by_cat:
            mx = max(by_cat.values())
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
                bar = "█" * max(1, int(v / mx * 25)) if mx else ""
                lines.append(f"  {k:12s} {v:4d}m {bar}")
        else:
            lines.append("  (no focus sessions yet)")
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

    window.floating_widget.show()
    window.floating_widget.move(120, 120)

    print("✓ Rakez is now running on your screen!")
    sys.exit(app.exec())


def _safe_startup_pull(window):
    try:
        window._pull_from_joplin(silent=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
