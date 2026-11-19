"""Update checker — compares APP_VERSION against GitHub releases/tags.

The project ships releases via GitHub (tags like v1.9.0 / releases). The
checker asks the GitHub API for the latest release first, falls back to the
newest tag when the repo has no formal release. Network failures never raise:
they are reported in the result dict so the GUI can show a friendly message.
"""
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

APP_VERSION = "2.1.0"
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

    Returns: {ok, update_available, current, latest, url, error,
              asset_url, asset_name, asset_size}
    """
    result = {
        "ok": False,
        "update_available": False,
        "current": current,
        "latest": "",
        "url": RELEASES_URL,
        "error": "",
        "asset_url": "",
        "asset_name": "",
        "asset_size": 0,
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
            asset = _pick_installer_asset(data.get("assets") or [])
            if asset:
                result["asset_url"] = asset.get("browser_download_url") or ""
                result["asset_name"] = asset.get("name") or ""
                result["asset_size"] = int(asset.get("size") or 0)
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


def _pick_installer_asset(assets: list) -> dict | None:
    """Prefer Rakez-Setup-*.exe, then any .exe asset from the release."""
    exes = [a for a in assets if (a.get("name") or "").lower().endswith(".exe")]
    for a in exes:
        if "setup" in (a.get("name") or "").lower():
            return a
    return exes[0] if exes else None


def download_installer(url: str, dest_dir: str | Path, filename: str = "",
                       progress=None, timeout: int = 120) -> dict:
    """Stream the installer to dest_dir. Never raises.

    progress(pct, downloaded, total) is called while downloading; pct is -1
    when the server does not report Content-Length.
    Returns: {ok, path, error}
    """
    out = {"ok": False, "path": "", "error": ""}
    if requests is None:
        out["error"] = "requests library not installed"
        return out
    if not (url or "").strip():
        out["error"] = "No installer attached to this release"
        return out
    try:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        name = (filename or url.rsplit("/", 1)[-1] or "Rakez-Setup.exe").split("?")[0]
        target = dest / name
        part = target.with_name(target.name + ".part")
        with requests.get(url, stream=True, timeout=timeout,
                          headers={"User-Agent": "Rakez-Updater"}) as r:
            r.raise_for_status()
            try:
                total = int(r.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(int(done / total * 100) if total else -1, done, total)
        part.replace(target)  # atomic: a partial file never replaces the exe
        out.update(ok=True, path=str(target))
    except Exception as e:
        out["error"] = _friendly_download_error(e)
    return out


def run_installer(path: str | Path, delay_seconds: int = 3) -> bool:
    """Launch the downloaded setup detached, after our app has time to exit.

    The delay lets the running (locked) Rakez.exe unload before Setup replaces
    it. Inno Setup runs silently; Windows may still show a progress bar.
    """
    try:
        path = str(path)
        if not Path(path).exists():
            return False
        if os.name == "nt":
            cmd = f'ping -n {int(delay_seconds) + 1} 127.0.0.1 >nul & "{path}" /SILENT /NORESTART'
            subprocess.Popen(cmd, shell=True,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            subprocess.Popen([path, "/SILENT", "/NORESTART"], start_new_session=True)
        return True
    except Exception:
        return False


def cleanup_downloads(dest_dir: str | Path, keep: str = "") -> None:
    """Delete old installer files from previous update attempts."""
    try:
        keep_path = Path(keep).resolve() if keep else None
        for f in Path(dest_dir).glob("Rakez-Setup-*.exe*"):
            if keep_path is None or f.resolve() != keep_path:
                try:
                    f.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _friendly_download_error(e: Exception) -> str:
    low = str(e).lower()
    if "404" in low:
        return "Installer file not found on GitHub (404) — the release may be incomplete"
    if "403" in low:
        return "GitHub refused the download (403) — try again later"
    if "timed out" in low or "timeout" in low:
        return "Download timed out — check your connection and retry"
    if "connection" in low or "getaddrinfo" in low:
        return "No internet connection"
    return f"Download failed: {str(e)[:160]}"


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
