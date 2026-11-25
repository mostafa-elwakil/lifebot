"""Offscreen GUI tests for the sectioned settings page (sidebar + API)."""
import json
import os
import socket
import urllib.error
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import run_lifebot as rl  # noqa: E402
from core import i18n  # noqa: E402
from core.storage import SqliteStorage  # noqa: E402

_app = None


def _app_instance():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(base: str, path: str, token: str = ""):
    request = urllib.request.Request(base + path)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode() or "{}")


def test_settings_sidebar_sections_and_api(tmp_path, monkeypatch):
    _app_instance()
    monkeypatch.setattr(rl, "DATA_DIR", tmp_path)
    store = SqliteStorage(data_dir=tmp_path)
    win = rl.RakezMainWindow(store)
    try:
        # --- sidebar wiring ---
        assert len(win._settings_nav_buttons) == 6
        assert win._settings_section_ids == [
            "general", "appearance", "widget", "integrations", "api", "updates"]
        assert win._settings_stack.currentIndex() == 0
        assert win._settings_nav_buttons[0].isChecked()

        win._jump_to_settings("api")
        assert win._settings_stack.currentIndex() == 4
        assert win._settings_nav_buttons[4].isChecked()
        assert not any(btn.isChecked() for i, btn in enumerate(win._settings_nav_buttons)
                       if i != 4)

        # jumping to an unknown section keeps the current one
        win._jump_to_settings("does-not-exist")
        assert win._settings_stack.currentIndex() == 4

        # --- every legacy widget is still built ---
        for name in (
            "theme_combo", "lang_combo", "set_w_spin", "set_h_spin",
            "accent_combo", "design_combo", "bg_combo", "opacity_spin",
            "sound_combo", "gemini_edit", "joplin_token_edit", "joplin_base_edit",
            "joplin_folder_edit", "joplin_tags_edit", "google_id_edit",
            "google_secret_edit", "tg_token_edit", "tg_chat_edit",
            "tg_reports_check", "tg_daily_check", "tg_hour_spin",
            "telegram_status_label", "update_btn", "update_install_btn",
            "update_label", "settings_status", "api_port_spin", "api_token_edit",
            "api_toggle_btn", "api_status_label",
        ):
            assert hasattr(win, name), name

        # --- the API section really serves the app data ---
        port = _free_port()
        win.api_port_spin.setValue(port)
        win.api_token_edit.setText("ui-test-token")
        win._start_api_server()
        try:
            assert win._api_server is not None
            base = f"http://127.0.0.1:{port}"
            status, payload = _get(base, "/health", token="ui-test-token")
            assert status == 200 and payload["ok"] is True
            # the token is enforced
            status, payload = _get(base, "/health")
            assert status == 401
            # status label reflects the running server
            assert str(port) in win.api_status_label.text()
            assert win.api_toggle_btn.text() == i18n.t("⏹ Stop")

            # a task created through the API shows up in the Task tab
            store.add_todo("Created through the API")
            win._api_watch()
            rows = [win.todos_list.item(i).text()
                    for i in range(win.todos_list.count())]
            assert any("Created through the API" in row for row in rows)
        finally:
            win._stop_api_server()
        assert win._api_server is None
        assert win.api_status_label.text() == i18n.t("Status: stopped")

        # --- Arabic rebuild keeps the section and translates the sidebar ---
        win._show_settings_section(4)
        win.lang_combo.setCurrentIndex(win.lang_combo.findData("ar"))
        assert i18n.is_arabic()
        assert win._settings_stack.currentIndex() == 4
        assert win._settings_nav_buttons[0].text() == "⚙️ عام"
        assert win._settings_nav_buttons[4].text() == "🌐 API"
        assert win.api_status_label.text().startswith("الحالة:")
    finally:
        i18n.set_language("en")
        win._stop_api_server()
        win.close()
        store.close()
