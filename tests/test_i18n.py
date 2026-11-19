"""Tests for the bilingual layer (core/i18n.py) and its Qt translator."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from core import i18n  # noqa: E402


def test_switching_language():
    assert i18n.get_language() == "en"
    assert i18n.t("Tasks") == "Tasks"
    assert i18n.set_language("ar") == "ar"
    assert i18n.is_arabic() is True
    assert i18n.t("Tasks") == "المهام"
    assert i18n.set_language("fr") == "en"  # unknown code falls back


def test_unknown_and_non_string_pass_through():
    i18n.set_language("ar")
    assert i18n.t("some string nobody translated") == "some string nobody translated"
    assert i18n.t(42) == 42
    assert i18n.t(None) is None


def test_tf_formats_placeholders():
    i18n.set_language("ar")
    assert i18n.tf("✓ '{name}' completed!", name="تقرير") == "✓ تم إنجاز 'تقرير'!"
    # missing placeholder must not raise
    assert i18n.tf("✓ '{name}' completed!", other=1) == "✓ تم إنجاز '{name}'!"
    i18n.set_language("en")
    assert i18n.tf("✓ '{name}' completed!", name="x") == "✓ 'x' completed!"


def test_detect_language_returns_valid_code(monkeypatch):
    monkeypatch.delenv("LANG", raising=False)
    assert i18n.detect_language() in ("en", "ar")


def test_translate_tree_roundtrip_and_idempotence():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

    app = QApplication.instance() or QApplication([])
    root = QWidget()
    label = QLabel("Tasks", root)
    btn = QPushButton("Add", root)
    dynamic = QLabel("My own task title", root)

    i18n.set_language("ar")
    i18n.translate_tree(root)
    i18n.translate_tree(root)  # idempotent
    assert label.text() == "المهام"
    assert btn.text() == "إضافة"
    assert dynamic.text() == "My own task title"  # unknown text untouched

    i18n.set_language("en")
    i18n.translate_tree(root)
    assert label.text() == "Tasks"
    assert btn.text() == "Add"
    app.processEvents()
    root.close()


def test_translate_tree_ignores_combo_keys():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication, QComboBox, QWidget

    app = QApplication.instance() or QApplication([])
    root = QWidget()
    combo = QComboBox(root)
    combo.addItem("Dark (Tokyo Night)", "dark")
    i18n.set_language("ar")
    i18n.translate_tree(root)
    # combo boxes store keys, so their text must stay untouched
    assert combo.itemText(0) == "Dark (Tokyo Night)"
    app.processEvents()
    root.close()


def test_language_is_persisted_in_settings():
    import tempfile

    from core.settings import load_settings, save_settings

    with tempfile.TemporaryDirectory() as td:
        cfg = load_settings(td)
        assert cfg["language"] == ""          # first run → detect
        cfg["language"] = "ar"
        save_settings(td, cfg)
        assert load_settings(td)["language"] == "ar"
        save_settings(td, {**cfg, "language": "de"})
        assert load_settings(td)["language"] == ""   # unknown code dropped


def test_widget_design_survives_arabic():
    pytest.importorskip("PyQt6")
    import tempfile
    from pathlib import Path

    from core.storage import SqliteStorage
    import run_lifebot as rl
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStorage(data_dir=Path(td))
        try:
            i18n.set_language("ar")
            w = rl.FloatingTimerWidget(store)
            for design in ("pill", "neon", "split", "retro"):
                w.set_design(design)
                assert w.task_label is not None
            w.set_task("مراجعة", "Deep Work", 25)
            assert "مراجعة" in w.task_label.text()
            w.start_break("short_break", 5)
            assert w.mode_label.text() == "☕ بريك قصير"
            i18n.set_language("en")
            w.set_design("pill")
            w.set_task("Review", "Deep Work", 25)
            assert w.mode_label.text() == "🎯 FOCUS"
            app.processEvents()
            w.close()
        finally:
            store.close()
