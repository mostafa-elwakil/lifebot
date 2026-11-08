"""Update checker — compares APP_VERSION against GitHub releases/tags.

The project ships releases via GitHub (tags like v1.9.0 / releases). The
checker asks the GitHub API for the latest release first, falls back to the
newest tag when the repo has no formal release. Network failures never raise:
they are reported in the result dict so the GUI can show a friendly message.
"""
from __future__ import annotations
import re

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

APP_VERSION = "2.0.0"
GITHUB_REPO = "mostafa-elwakil/lifebot"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
API_TAGS = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
REQUEST_TIMEOUT = 10  # seconds


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.9.0' -> (1, 9, 0); tolerates extra suffixes like '1.10.0-beta'."""
    m = re.search(r"(\d+(?:\.\d+)+)", (text or "").strip())
    if not m:
        return ()
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a) and bool(b) and a > b


def _tag_name(name: str) -> str:
    return (name or "").strip().lstrip("vV")


def check_latest(current: str = APP_VERSION, timeout: int = REQUEST_TIMEOUT) -> dict:
    """Check GitHub for a newer version. Never raises.

    Returns: {ok, update_available, current, latest, url, error}
    """
    result = {
        "ok": False,
        "update_available": False,
        "current": current,
        "latest": "",
        "url": RELEASES_URL,
        "error": "",
    }
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Rakez-Updater"}
    try:
        if requests is None:
            result["error"] = "requests library not installed"
            return result
        r = requests.get(API_LATEST, headers=headers, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            result["ok"] = True
            result["latest"] = _tag_name(data.get("tag_name") or data.get("name") or "")
            result["url"] = data.get("html_url") or RELEASES_URL
        else:
            # no formal release — fall back to the newest semantic tag
            r2 = requests.get(API_TAGS, headers=headers, timeout=timeout)
            if r2.status_code == 200:
                tags = r2.json() or []
                best, best_ver = "", ()
                for t in tags:
                    ver = parse_version(_tag_name(t.get("name", "")))
                    if ver > best_ver:
                        best, best_ver = _tag_name(t.get("name", "")), ver
                result["ok"] = True
                result["latest"] = best
                result["url"] = f"https://github.com/{GITHUB_REPO}/releases"
            else:
                result["error"] = _api_error(r.status_code, r2.status_code)
    except Exception as e:
        result["error"] = _friendly_network_error(e)
    if result["ok"]:
        result["update_available"] = is_newer(result["latest"], current)
    return result


def _api_error(release_code: int, tag_code: int) -> str:
    if release_code == 403 or tag_code == 403:
        return "GitHub API rate limit reached — try again later"
    return f"GitHub API HTTP {release_code or tag_code}"


def _friendly_network_error(e: Exception) -> str:
    msg = str(e)
    # requests wraps urllib errors; try to classify the common ones
    try:
        from urllib.error import URLError
        if isinstance(e.__cause__ or e, URLError):
            msg = str(e.__cause__ or e)
    except Exception:
        pass
    low = msg.lower()
    if "nodename nor servname" in low or "name or service not known" in low or "getaddrinfo failed" in low:
        return "No internet connection"
    if "timed out" in low or "timeout" in low:
        return "Connection timed out"
    if "connection" in low or "getaddrinfo" in low or "unreachable" in low:
        return f"Connection error: {msg}" if "internet" not in low else "No internet connection"
    return f"Update check failed: {msg}"


if __name__ == "__main__":
    info = check_latest()
    print(info)
