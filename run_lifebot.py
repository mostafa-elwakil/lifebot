import sys
import os
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox, QMessageBox,
    QGraphicsDropShadowEffect, QInputDialog, QSystemTrayIcon, QMenu,
    QCheckBox
)

from core.storage import SqliteStorage, CATEGORIES
from core.coach import HermesCoach
from core.joplin import JoplinClient, DEFAULT_FOLDER as JOPLIN_DEFAULT_FOLDER

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


def play_done_sound(app: QApplication | None = None):
    """Cross-platform done beep: winsound on Windows, else Qt beep."""
    try:
        import winsound
        winsound.Beep(880, 300)
        winsound.Beep(660, 300)
        return
    except Exception:
        pass
    try:
        if app is not None:
            app.beep()
    except Exception:
        pass


class FloatingTimerWidget(QWidget):
    open_dashboard_requested = pyqtSignal()
    session_completed = pyqtSignal(dict)

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
        self.remaining_seconds = DEFAULTS["focus"] * 60
        self.total_seconds = DEFAULTS["focus"] * 60
        self.is_running = False
        self.current_task = "Select a Task"
        self.current_category = "Deep Work"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._init_ui()

    def _init_ui(self):
        self.setFixedSize(370, 96)
        container = QWidget(self)
        container.setObjectName("container")
        container.setStyleSheet("""
            QWidget#container {
                background-color: rgba(26, 27, 38, 0.95);
                border: 2px solid #7aa2f7;
                border-radius: 16px;
            }
            QLabel { color: #c0caf5; font-family: 'Segoe UI', Arial; }
            QPushButton {
                background-color: #24283b;
                border: 1px solid #7aa2f7;
                border-radius: 8px;
                color: #7aa2f7;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #7aa2f7; color: #1a1b26; }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 180))
        container.setGraphicsEffect(shadow)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(15, 10, 15, 10)

        info_layout = QVBoxLayout()
        self.task_label = QLabel(self.current_task)
        self.task_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.task_label.setStyleSheet("color: #7aa2f7;")

        self.cat_label = QLabel(f"🏷️ {self.current_category}")
        self.cat_label.setFont(QFont("Segoe UI", 8))
        self.cat_label.setStyleSheet("color: #bb9af7;")

        self.mode_label = QLabel("🎯 FOCUS")
        self.mode_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.mode_label.setStyleSheet("color: #9ece6a;")

        info_layout.addWidget(self.task_label)
        info_layout.addWidget(self.cat_label)
        info_layout.addWidget(self.mode_label)
        layout.addLayout(info_layout, stretch=3)

        self.time_label = QLabel(f"{DEFAULTS['focus']:02d}:00")
        self.time_label.setFont(QFont("Consolas", 15, QFont.Weight.Bold))
        self.time_label.setStyleSheet("color: #9ece6a;")
        layout.addWidget(self.time_label, stretch=2)

        btn_layout = QVBoxLayout()
        row1 = QHBoxLayout()
        self.toggle_btn = QPushButton("▶")
        self.toggle_btn.setFixedSize(34, 34)
        self.toggle_btn.setToolTip("Start/Pause")
        self.toggle_btn.clicked.connect(self.toggle_timer)

        self.expand_btn = QPushButton("⛶")
        self.expand_btn.setFixedSize(34, 34)
        self.expand_btn.setToolTip("Open dashboard")
        self.expand_btn.clicked.connect(self.open_dashboard_requested.emit)
        row1.addWidget(self.toggle_btn)
        row1.addWidget(self.expand_btn)

        row2 = QHBoxLayout()
        self.break_btn = QPushButton("☕")
        self.break_btn.setFixedSize(34, 28)
        self.break_btn.setToolTip("Start short break")
        self.break_btn.clicked.connect(lambda: self.start_break("short_break"))
        self.reset_btn = QPushButton("↺")
        self.reset_btn.setFixedSize(34, 28)
        self.reset_btn.setToolTip("Reset timer")
        self.reset_btn.clicked.connect(self.reset_timer)
        row2.addWidget(self.break_btn)
        row2.addWidget(self.reset_btn)

        btn_layout.addLayout(row1)
        btn_layout.addLayout(row2)
        layout.addLayout(btn_layout)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)

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
            play_done_sound(QApplication.instance())
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

    def _update_time_display(self):
        mins = self.remaining_seconds // 60
        secs = self.remaining_seconds % 60
        self.time_label.setText(f"{mins:02d}:{secs:02d}")

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
        self.coach = HermesCoach(model=_ai_cfg.get("model", "gemini-2.5-flash"))
        self.joplin = JoplinClient(
            base_url=_joplin_cfg.get("base_url", "http://127.0.0.1:41184"),
            token=os.getenv("JOPLIN_TOKEN", _joplin_cfg.get("token", "")),
        )
        self.joplin_folder = _joplin_cfg.get("folder_name", JOPLIN_DEFAULT_FOLDER) or JOPLIN_DEFAULT_FOLDER
        self.joplin_tags = _joplin_cfg.get("tags", "task,lifebot") or "task,lifebot"
        self.setWindowTitle("Rakez ركّز - AI Coach & Pomodoro")
        self.resize(880, 640)

        self.floating_widget = FloatingTimerWidget(self.storage)
        self.floating_widget.open_dashboard_requested.connect(self.show_dashboard)
        self.floating_widget.session_completed.connect(self._on_session_finished)

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

    def _init_tray(self):
        self.tray = None
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = QSystemTrayIcon(self)
                self.tray.setToolTip("Rakez ركّز")
                menu = QMenu()
                show_act = QAction("Show Dashboard", self)
                show_act.triggered.connect(self.show_dashboard)
                quit_act = QAction("Quit", self)
                quit_act.triggered.connect(QApplication.instance().quit)
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
            self.cycle_label.setText(f"Cycles completed: {self.floating_widget.cycles_done} (long break every 4)")
            # auto-suggest break
            minutes = self.break_spin.value() if hasattr(self, "break_spin") else DEFAULTS["short_break"]
            if self.floating_widget.cycles_done % 4 == 0:
                self.floating_widget.start_break("long_break", DEFAULTS["long_break"])
                QMessageBox.information(self, "Completed 🎉", f"Focus '{session['task']}' logged! Long break started.")
            else:
                reply = QMessageBox.question(self, "Completed 🎉",
                    f"Session '{session['task']}' recorded! Start {minutes}-min break?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.floating_widget.start_break("short_break", minutes)
        else:
            QMessageBox.information(self, "Break over", "Break finished! Ready for next focus?")
        self._load_analytics()
        self._load_todos_list()
        self._refresh_task_dropdown()

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
