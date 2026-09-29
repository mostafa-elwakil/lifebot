"""Build the Rakez Windows release (GUI, no terminal window).

Usage:
    python packaging/build_windows.py
Output:
    dist/Rakez.exe   (windowed, icon + publisher metadata embedded)
"""
import sys
from pathlib import Path

from PyInstaller.__main__ import run

ROOT = Path(__file__).resolve().parent.parent

args = [
    str(ROOT / "run_lifebot.py"),
    "--name", "Rakez",
    "--onefile",
    "--windowed",          # <-- no terminal/console window
    "--icon", str(ROOT / "assets" / "icon.ico"),
    "--version-file", str(ROOT / "packaging" / "version_info.txt"),
    "--add-data", f"{ROOT / 'config'}{';'}config",
    "--add-data", f"{ROOT / 'assets' / 'icon.ico'}{';'}assets",
    "--add-data", f"{ROOT / 'assets' / 'icon-256.png'}{';'}assets",
    "--add-data", f"{ROOT / 'assets' / 'logo.svg'}{';'}assets",
    "--hidden-import", "google.generativeai",  # imported lazily in coach.py
    "--collect-submodules", "google.generativeai",
    "--noconfirm",
    "--clean",
]

print("Building Rakez for Windows ...")
run(args)
print("Done: dist/Rakez.exe")

if __name__ == "__main__":
    sys.exit(0)
