# RCSyncitMF

GNOME (libadwaita) manager for **rclone** with support for multiple configuration files (profiles), remotes, unions, and mounts, including synchronization of the directory structure between a union's upstreams.

## Features

- **Profiles**: create, import, rename, and delete rclone `.conf` files.
- **Remotes**: create/edit/delete remotes (local, drive, s3, dropbox, onedrive, union, etc.) and test connections.
- **Unions**: create unions by selecting upstreams; sync folders between upstreams (dry-run by default).
- **Mounts**: mount/unmount remotes with `rclone mount --daemon`, with configurable VFS options.
- **Settings**: concurrency, depth, rclone binary, language, auto-sync interval.
- **Theme**: automatic light/dark theme (libadwaita).
- **Flatpak**: sandboxed execution using the host's `rclone` via `flatpak-spawn`.

## Requirements

- Python >= 3.11
- PyGObject (GTK 4 + libadwaita)
- rclone >= 1.60
- (For mounts) FUSE (`/dev/fuse`) and `fusermount`/`fusermount3`

## Installation (development)

```bash
python -m pip install -e .
rcsyncitmf
```

## Installation as a desktop app

```bash
./install.sh
```

## Flatpak

```bash
flatpak-builder --user --install --force-clean build com.rcsyncitmf.app.yml
flatpak run com.rcsyncitmf.app
```

The app uses the host's `rclone`. Make sure it is installed and available in `PATH`.

### Recommended Flatseal permissions

| Permission | Why | Where to enable |
|---|---|---|
| Network | rclone accesses clouds/HTTP | Network → Access network |
| Home folder | Profiles, config, mounts, and cache live in `~` | Filesystem → Home folder |
| All devices | Access to `/dev/fuse` for mounts | Device → All devices |
| D-Bus `org.freedesktop.Flatpak` | `flatpak-spawn --host` to run rclone/fusermount | (Advanced) Talk to D-Bus / Flatpak portal |
| XDG config/cache (optional) | Extra access to `~/.config` and `~/.cache` | Filesystem → xdg-config, xdg-cache |

**Host prerequisites (Flatpak):**
- `rclone` installed.
- FUSE available (`/dev/fuse`, `fusermount`/`fusermount3`).
- Mount points are created under `~/.local/share/rcsyncitmf/mnt`.

## Quick start

1. **Profiles**: create or import rclone `.conf` files.
2. **Remotes**: create/edit/delete remotes within a profile.
3. **Unions**: create a union by selecting upstreams; use “Sync folders” (dry-run by default).
4. **Mounts**: mount a remote with `rclone mount --daemon`; unmount with `fusermount -u`.
5. **Settings**: concurrency, mode, depth, default dry-run, rclone binary, language.

## Project structure

```
src/rcsyncitmf/
  application.py   # Adw.Application
  window.py        # main window (sidebar + stack)
  config.py        # XDG paths and TOML settings
  services/        # rclone wrapper, profiles, union sync, mounts
  ui/pages/        # profiles, remotes, unions, mounts, settings
  ui/dialogs/      # remote, union
  resources/       # CSS
  locales/         # i18n JSON
```

## Development

```bash
python -m pip install -e ".[dev]"
ruff check src tests
mypy src/rcsyncitmf
pytest -q
```

## Releases

Releases are generated automatically with **semantic-release** from conventional commits (`feat:`, `fix:`, `BREAKING CHANGE:`) pushed to `main`.

## License

GPL-3.0-or-later.