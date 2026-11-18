#!/usr/bin/env bash
set -euo pipefail

# Install RCSyncitMF as a desktop application (non-Flatpak).
pipx install . 2>/dev/null || python3 -m pip install --user .

mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp data/io.github.MFApplications.RCSyncitMF.desktop ~/.local/share/applications/
cp data/icons/hicolor/scalable/apps/io.github.MFApplications.RCSyncitMF.svg ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "RCSyncitMF installed. Launch from app grid or run: rcsyncitmf"