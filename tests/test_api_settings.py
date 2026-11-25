"""Settings for the local HTTP API: defaults, clamping, and token cleanup."""
from core.settings import load_settings, save_settings


def test_api_settings_defaults(tmp_path):
    cfg = load_settings(tmp_path)
    assert cfg["api_port"] == 8765
    assert cfg["api_token"] == ""


def test_api_settings_sanitize(tmp_path):
    cfg = load_settings(tmp_path)
    cfg["api_port"] = 80            # below the allowed range
    cfg["api_token"] = "  abc  "    # surrounding whitespace is dropped
    save_settings(tmp_path, cfg)

    again = load_settings(tmp_path)
    assert again["api_port"] == 1024
    assert again["api_token"] == "abc"

    cfg["api_port"] = 99999         # above the allowed range
    save_settings(tmp_path, cfg)
    assert load_settings(tmp_path)["api_port"] == 65535

    cfg["api_port"] = "junk"        # unparsable → default
    save_settings(tmp_path, cfg)
    assert load_settings(tmp_path)["api_port"] == 8765
