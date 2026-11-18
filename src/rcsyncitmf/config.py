"""Application paths and settings (TOML-based, XDG-compliant).

Legacy JSON files (settings.json, mounts.json, sync_state.json, *.meta.json) are
migrated automatically to their TOML counterparts on first load, and the old
files are renamed to ``*.json.bak`` so no data is lost.
"""

from __future__ import annotations

import json
import os
import threading
import tomllib
from pathlib import Path

import tomli_w

APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "rcsyncitmf"
PROFILES_DIR = APP_DIR / "profiles"
MOUNTS_FILE = APP_DIR / "mounts.toml"
SETTINGS_FILE = APP_DIR / "settings.toml"
LOG_FILE = APP_DIR / "app.log"

_CONFIG_LOCK = threading.RLock()

# Legacy (JSON) paths kept for one-shot migration.
_LEGACY_SETTINGS_FILE = APP_DIR / "settings.json"
_LEGACY_MOUNTS_FILE = APP_DIR / "mounts.json"

DEFAULT_SETTINGS: dict = {
    "profiles_dir": str(PROFILES_DIR),
    "concurrency": 4,
    "sync_depth": 0,  # 0 = todos los directorios (recursivo completo)
    "rclone_bin": "rclone",
    "auto_sync_interval": 300,
    "language": "auto",
    "mounts_dir": "",
}


_LEGACY_APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "rsyncmf"


def _migrate_legacy_app_dir() -> None:
    if _LEGACY_APP_DIR.exists() and not APP_DIR.exists():
        try:
            _LEGACY_APP_DIR.rename(APP_DIR)
        except OSError:
            try:
                import shutil as _shutil

                _shutil.copytree(_LEGACY_APP_DIR, APP_DIR)
            except OSError:
                pass


def ensure_dirs() -> None:
    _migrate_legacy_app_dir()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_json_to_toml(legacy: Path, target: Path) -> dict | None:
    """If *legacy* JSON exists and *target* TOML does not, migrate and rename.

    Returns the migrated data (or None if no migration happened).
    """
    if not legacy.exists() or target.exists():
        return None
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        ensure_dirs()
        target.write_bytes(tomli_w.dumps(data).encode("utf-8"))
        legacy.rename(legacy.with_suffix(legacy.suffix + ".bak"))
    except (OSError, ValueError, TypeError):
        return None
    return data


def load_toml(path: Path, legacy: Path | None = None) -> dict:
    ensure_dirs()
    if legacy is not None:
        migrated = _migrate_json_to_toml(legacy, path)
        if migrated is not None:
            return migrated
    if path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    return {}


def save_toml(path: Path, data: dict) -> None:
    ensure_dirs()
    with _CONFIG_LOCK:
        path.write_bytes(tomli_w.dumps(data).encode("utf-8"))


def load_settings() -> dict:
    data = load_toml(SETTINGS_FILE, legacy=_LEGACY_SETTINGS_FILE)
    return {**DEFAULT_SETTINGS, **data}


def save_settings(settings: dict) -> None:
    save_toml(SETTINGS_FILE, settings)
