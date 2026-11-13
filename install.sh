#!/usr/bin/env bash
set -euo pipefail

# Install RCSyncitMF as a desktop application (non-Flatpak).
pipx install . 2>/dev/null || python3 -m pip install --user .

mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp data/com.rcsyncitmf.app.desktop ~/.local/share/applications/
cp data/icons/hicolor/scalable/apps/com.rcsyncitmf.app.svg ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "RCSyncitMF installed. Launch from app grid or run: rcsyncitmf"