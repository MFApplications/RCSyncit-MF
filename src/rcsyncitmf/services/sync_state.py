"""Persistence of per-union synchronization baselines (TOML).

State is keyed by (profile path, union name) so that several unions in the same
profile -- or unions with identical names in different profiles -- never share
or overwrite each other's baseline.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from ..config import APP_DIR, ensure_dirs, load_toml, save_toml

STATE_FILE = APP_DIR / "sync_state.toml"
_LEGACY_STATE_FILE = APP_DIR / "sync_state.json"

_STATE_LOCK = threading.RLock()


def _key(profile: Path, union_name: str) -> str:
    return f"{Path(profile).resolve()!s}::{union_name}"


def _load_all_unlocked() -> dict:
    ensure_dirs()
    data = load_toml(STATE_FILE, legacy=_LEGACY_STATE_FILE)
    if not isinstance(data, dict):
        return {"states": {}}
    if "states" not in data or not isinstance(data["states"], dict):
        data["states"] = {}
    return data


def _save_all_unlocked(data: dict) -> None:
    ensure_dirs()
    save_toml(STATE_FILE, data)


def _load_all() -> dict:
    with _STATE_LOCK:
        return _load_all_unlocked()


def _save_all(data: dict) -> None:
    with _STATE_LOCK:
        _save_all_unlocked(data)


def load_state(profile: Path, union_name: str) -> dict | None:
    data = _load_all()
    entry = data["states"].get(_key(profile, union_name))
    if not isinstance(entry, dict):
        return None
    return entry


def save_state(profile: Path, union_name: str, upstreams: list[str], paths: set[str]) -> None:
    with _STATE_LOCK:
        data = _load_all_unlocked()
        data["states"][_key(profile, union_name)] = {
            "upstreams": list(upstreams),
            "paths": sorted(paths),
            "last_sync": datetime.now().isoformat(timespec="seconds"),
        }
        _save_all_unlocked(data)


def delete_state(profile: Path, union_name: str) -> None:
    with _STATE_LOCK:
        data = _load_all_unlocked()
        data["states"].pop(_key(profile, union_name), None)
        _save_all_unlocked(data)


def last_sync(profile: Path, union_name: str) -> str | None:
    st = load_state(profile, union_name)
    if not isinstance(st, dict):
        return None
    value = st.get("last_sync")
    return str(value) if value else None
