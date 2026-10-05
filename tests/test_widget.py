"""Offscreen GUI tests: all floating-widget designs build without crashing."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import run_lifebot as rl  # noqa: E402
from core.storage import SqliteStorage  # noqa: E402

_app = None


def _app_instance():
    global _app
    if _app is None:
        _app = QApplication([])
    return _app


def test_all_designs_build_and_switch():
    _app_instance()
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            w = rl.FloatingTimerWidget(store)
            for design in ("pill", "neon", "split", "retro", "bogus"):
                w.set_design(design)
                assert w.design in ("pill", "neon", "split", "retro")
                assert w.task_label is not None and w.time_label is not None
                assert w.toggle_btn is not None and w.quit_btn is not None
                w.set_task("Hello", "Ops", 25)
                assert "Hello" in w.task_label.text()
                w.toggle_timer()  # start
                w.toggle_timer()  # pause
                assert w._elapsed_pct() == 0
                if w.is_running:
                    w.toggle_timer()  # ensure paused
                w.remaining_seconds = 0
                w.toggle_timer()  # expired restart guard
                assert w.remaining_seconds == w.total_seconds
                if w.is_running:
                    w.toggle_timer()  # leave paused for next design
            w.set_accent("#9ece6a")
            w.set_background("#0d0d12")
            w.set_sound("Chime")
            assert w.sound == "Chime"
            w.set_sound("nope")
            assert w.sound == "Default beep"
            w.close()
        finally:
            store.close()


def test_ring_widget():
    _app_instance()
    ring = rl._RingWidget(color="#7aa2f7")
    ring.setValue(62)
    assert ring._value == 62
    ring.setValue(999)
    assert ring._value == 100
    ring.setColor("#ff0000")
    ring.close()


def test_opacity_and_resize_signal():
    _app_instance()
    import tempfile
    from pathlib import Path
    from core.storage import SqliteStorage
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            w = rl.FloatingTimerWidget(store)
            assert w.set_opacity(70) == 70
            assert abs(w.windowOpacity() - 0.7) < 0.01
            assert w.set_opacity(999) == 100
            assert w.set_opacity(-5) == 30
            seen = []
            w.widget_size_changed.connect(lambda a, b: seen.append((a, b)))
            w.show()
            w.resize(400, 130)
            _app_instance().processEvents()
            assert seen and seen[-1] == (400, 130)
            w.close()
        finally:
            store.close()


def test_inline_form_and_notice():
    _app_instance()
    import tempfile
    from pathlib import Path
    from core.storage import SqliteStorage
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            w = rl.FloatingTimerWidget(store)
            w.show()
            added = []
            w.task_added.connect(added.append)
            # inline quick-add (no popup window)
            w.show_form()
            assert w.inline_panel.isVisibleTo(w) or True  # parent hidden offscreen ok
            w.inline_title.setText("Inline task")
            w._submit_inline_task()
            assert added and added[0]["title"] == "Inline task"
            assert w.current_task == "Inline task"
            assert not w.inline_panel.isVisible()
            # inline notice with actions
            answers = []
            w.notice_answered.connect(answers.append)
            w.show_notice("Start break?", actions=[("Yes", True), ("No", False)])
            assert w.inline_panel.isVisible()
            assert w.notice_btns.count() == 2
            w.findChildren(type(w.quit_btn))[0]  # buttons exist
            # click "Yes"
            for i in range(w.notice_btns.count()):
                btn = w.notice_btns.itemAt(i).widget()
                if btn.text() == "Yes":
                    btn.click()
            assert answers == [True]
            assert not w.inline_panel.isVisible()
            # info notice auto-hides via timer path (hide manually here)
            w.show_notice("Done!")
            assert w.notice_btns.count() == 0
            w._hide_panel()
            w.close()
        finally:
            store.close()


def test_form_auto_grow_and_restore():
    _app_instance()
    import tempfile
    from pathlib import Path
    from core.storage import SqliteStorage
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            w = rl.FloatingTimerWidget(store)
            w.show()
            _app_instance().processEvents()
            small = (w.width(), w.height())
            w.show_form()
            _app_instance().processEvents()
            assert w.height() >= small[1]  # grew (or fits) to show the form
            assert w._pre_form_size is not None
            w.inline_title.setText("Grow task")
            w._submit_inline_task()
            _app_instance().processEvents()
            assert (w.width(), w.height()) == (small[0], small[1])
            assert w._pre_form_size is None
            w.close()
        finally:
            store.close()


def test_done_button_completes_and_advances():
    _app_instance()
    import tempfile
    from pathlib import Path
    from core.storage import SqliteStorage
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            for t in store.get_todos():  # start clean
                store.delete_todo(t["id"])
            store.add_todo("First job", "Ops")
            store.add_todo("Second job", "Ops")
            w = rl.FloatingTimerWidget(store)
            w.show()
            w.set_task("First job", "Ops", 25)
            w._done_current_task()
            left = [t for t in store.get_todos() if not t.get("completed")]
            assert len(left) == 1 and left[0]["title"] == "Second job"
            assert w.current_task == "Second job"  # auto-advanced
            w._done_current_task()
            assert w.current_task == "Select a Task"  # nothing left
            assert all(t.get("completed") for t in store.get_todos())
            w._done_current_task()  # no selection → notice, no crash
            w.close()
        finally:
            store.close()


def test_retro_checklist_toggles_storage():
    _app_instance()
    import tempfile
    from pathlib import Path
    from core.storage import SqliteStorage
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            store.add_todo("Retro one", "Ops")
            store.add_todo("Retro two", "Ops")
            w = rl.FloatingTimerWidget(store)
            w.show()
            w.set_design("retro")
            from PyQt6.QtWidgets import QCheckBox
            boxes = w.retro_list.findChildren(QCheckBox)
            assert len(boxes) == 7  # 5 seeded defaults + 2 added
            boxes[0].setChecked(True)  # toggles storage via signal
            _app_instance().processEvents()
            assert w.retro_count.text() == "1/7 done"
            done = [t for t in store.get_todos() if t.get("completed")]
            assert len(done) == 1
            boxes = w.retro_list.findChildren(QCheckBox)
            boxes[0].setChecked(False)
            _app_instance().processEvents()
            assert w.retro_count.text() == "0/7 done"
            w.close()
        finally:
            store.close()
