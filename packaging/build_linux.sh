#!/usr/bin/env bash
# Build the Rakez Linux release (GUI, no terminal window).
# Run on a Linux machine:  bash packaging/build_linux.sh
# Output: dist/Rakez  (+ optional .deb/.AppImage via tools below)
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --quiet pyinstaller pillow pyyaml python-dotenv requests typer rich google-generativeai PyQt6
python3 assets/make_icon.py

python3 -m PyInstaller \
  run_lifebot.py \
  --name Rakez \
  --onefile \
  --windowed \
  --icon assets/icon-512.png \
  --add-data "config:config" \
  --add-data "assets/icon-512.png:assets" \
  --add-data "assets/icon-256.png:assets" \
  --add-data "assets/logo.svg:assets" \
  --hidden-import google.generativeai \
  --collect-submodules google.generativeai \
  --noconfirm --clean

echo "Done: dist/Rakez"
echo "Install desktop entry: sudo cp packaging/rakeze.desktop /usr/share/applications/ && sudo cp assets/icon-512.png /usr/share/icons/rakeze.png"
