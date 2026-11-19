"""Shared test setup: every test starts in English.

The GUI translation layer is global state, so a test that switches to Arabic
must never leak into the next one.
"""
import pytest

from core import i18n


@pytest.fixture(autouse=True)
def _force_english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")
