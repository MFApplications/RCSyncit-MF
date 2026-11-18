# RCSyncitMF

![RCSyncitMF logo](data/icons/hicolor/scalable/apps/io.github.MFApplications.RCSyncitMF.svg)

GNOME/libadwaita manager for rclone with multi-profile support.

## What it does

- Manage profiles, remotes, unions, and mounts from a GTK4 UI.
- Sync a union's upstreams; dry-run by default.
- Mount remotes with `rclone mount --daemon`.
- Run host `rclone` from the Flatpak via `flatpak-spawn`.

## Requirements

- Python 3.11+
- PyGObject (GTK4 + libadwaita)
- rclone 1.60+
- FUSE and `fusermount`/`fusermount3` (mounts only)

## Install

Development:

    python -m pip install -e .
    rcsyncitmf

Desktop:

    ./install.sh

Flatpak:

    flatpak-builder --user --install --force-clean build io.github.MFApplications.RCSyncitMF.yml
    flatpak run io.github.MFApplications.RCSyncitMF

The Flatpak uses the host's `rclone`. Install it and add it to `PATH`.

## Quick start

1. Create or import a profile.
2. Add remotes.
3. Create a union and sync folders (dry-run by default).
4. Mount and unmount remotes.
5. Adjust settings (concurrency, depth, language, auto-sync).

## Flatpak permissions

| Permission | Why |
|---|---|
| Network | Cloud and HTTP access |
| Home folder | Profiles, config, mounts, cache |
| All devices | `/dev/fuse` for mounts |
| D-Bus `org.freedesktop.Flatpak` | Run host `rclone`/`fusermount` |

Host prerequisites: `rclone`, FUSE, `fusermount`/`fusermount3`. Mount points live under `~/.local/share/rcsyncitmf/mnt`.

## Development

    python -m pip install -e ".[dev]"
    ruff check src tests
    ruff format --check src tests
    mypy src/rcsyncitmf
    pytest -q

## Project layout

    src/rcsyncitmf/
      application.py   Adw.Application
      window.py        main window
      config.py        XDG paths and TOML settings
      services/        rclone, profiles, union sync, mounts
      ui/pages/        profiles, remotes, unions, mounts, settings
      ui/dialogs/      remote, union
      resources/       CSS
      locales/         i18n JSON

## Releases

Automated with semantic-release from conventional commits on `main`.

## License

GPL-3.0-or-later
