"""Management of rclone config profiles (multiple .conf files)."""

from __future__ import annotations

import contextlib
import json
import shutil
import threading
from pathlib import Path

from ..config import PROFILES_DIR, ensure_dirs
from ..i18n import _

_META_LOCK = threading.RLock()
_PASSWORD_LOCK = threading.RLock()


def list_profiles() -> list[Path]:
    ensure_dirs()
    return sorted(PROFILES_DIR.glob("*.conf"))


def create_profile(name: str) -> Path:
    """Create an empty rclone config file. Raises FileExistsError if present."""
    ensure_dirs()
    safe = name.strip()
    if not safe or "/" in safe or safe.startswith("."):
        raise ValueError(_("invalid profile name"))
    if not safe.endswith(".conf"):
        safe = safe + ".conf"
    path = PROFILES_DIR / safe
    if path.exists():
        raise FileExistsError(safe)
    path.write_text("", encoding="utf-8")
    return path


def delete_profile(path: Path) -> None:
    path.unlink(missing_ok=True)
    meta_path(path).unlink(missing_ok=True)
    try:
        from . import mount_manager

        mount_manager._invalidate_profile_dump_cache(path)
    except Exception:
        pass


def import_profile(src: Path) -> Path:
    ensure_dirs()
    dst = PROFILES_DIR / src.name
    if not src.name.endswith(".conf"):
        dst = PROFILES_DIR / (src.name + ".conf")
    shutil.copyfile(src, dst)
    return dst


def import_profile_unique(src: Path) -> Path:
    """Import a profile, renaming if a file with the same name already exists."""
    ensure_dirs()
    base = src.stem
    if not base:
        base = "profile"
    candidate = PROFILES_DIR / f"{base}.conf"
    if candidate.exists():
        i = 1
        while (PROFILES_DIR / f"{base}-{i}.conf").exists():
            i += 1
        candidate = PROFILES_DIR / f"{base}-{i}.conf"
    shutil.copyfile(src, candidate)
    try:
        from . import mount_manager

        mount_manager._invalidate_profile_dump_cache()
    except Exception:
        pass
    return candidate


def detect_default_config() -> Path | None:
    """Detect ~/.config/rclone/rclone.conf if present."""
    default = Path.home() / ".config" / "rclone" / "rclone.conf"
    if default.exists() and default.is_file():
        return default
    return None


def rename_profile(path: Path, new_name: str) -> Path:
    ensure_dirs()
    safe = new_name.strip()
    if not safe or "/" in safe or safe.startswith("."):
        raise ValueError(_("invalid profile name"))
    if not safe.endswith(".conf"):
        safe = safe + ".conf"
    dst = PROFILES_DIR / safe
    if dst.exists() and dst != path:
        raise FileExistsError(safe)
    path.rename(dst)
    try:
        from . import mount_manager

        mount_manager._invalidate_profile_dump_cache(path)
        mount_manager._invalidate_profile_dump_cache(dst)
    except Exception:
        pass
    # Migrate metadata alongside the profile.
    old_meta = meta_path(path)
    new_meta = meta_path(dst)
    if old_meta.exists() and not new_meta.exists():
        with contextlib.suppress(OSError):
            old_meta.rename(new_meta)
    return dst


# ---------------------------------------------------------------------------
# Profile metadata (encrypted flag, etc.)
# ---------------------------------------------------------------------------

import tomllib

from ..config import save_toml


def meta_path(path: Path) -> Path:
    return path.with_suffix(".meta.toml")


def _legacy_meta_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def _load_meta_unlocked(path: Path) -> dict:
    mp = meta_path(path)
    legacy = _legacy_meta_path(path)
    # one-shot migration from JSON
    if legacy.exists() and not mp.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            try:
                save_toml(mp, data)
                legacy.rename(legacy.with_suffix(".json.bak"))
            except (OSError, ValueError, TypeError):
                pass
    if mp.exists():
        try:
            with mp.open("rb") as f:
                data = tomllib.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    return {}


def _save_meta_unlocked(path: Path, meta: dict) -> None:
    save_toml(meta_path(path), meta)


def save_meta(path: Path, meta: dict) -> None:
    with _META_LOCK:
        _save_meta_unlocked(path, meta)


def is_encrypted(path: Path) -> bool:
    meta = load_meta(path)
    if "encrypted" in meta:
        return bool(meta["encrypted"])
    # Try rclone without password
    import asyncio

    from .rclone import RcloneError, run

    async def check():
        try:
            await run(["config", "dump"], config=path, timeout=15, retries=0)
            return False
        except RcloneError as e:
            low = (e.stderr or "").lower()
            return bool("password" in low or "encrypted" in low)

    try:
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(check())
        loop.close()
        return res
    except Exception:
        return False


# ---------------------------------------------------------------------------
# In-memory password cache (never persisted)
# ---------------------------------------------------------------------------

_PASSWORD_CACHE: dict[str, str] = {}


def cache_password(path: Path, password: str) -> None:
    with _PASSWORD_LOCK:
        _PASSWORD_CACHE[str(path)] = password
    meta = load_meta(path)
    meta["encrypted"] = True
    save_meta(path, meta)


def get_cached_password(path: Path) -> str | None:
    with _PASSWORD_LOCK:
        return _PASSWORD_CACHE.get(str(path))


def clear_cached_password(path: Path) -> None:
    with _PASSWORD_LOCK:
        _PASSWORD_CACHE.pop(str(path), None)

    meta = load_meta(path)
    meta["encrypted"] = False
    save_meta(path, meta)


def encrypted_flag(path: Path) -> bool | None:
    """Return the persisted encrypted flag without running rclone.

    Returns ``None`` when unknown (no metadata). Non-blocking.
    """
    meta = load_meta(path)
    if "encrypted" in meta:
        return bool(meta["encrypted"])
    return None


def load_meta(path: Path) -> dict:
    with _META_LOCK:
        return _load_meta_unlocked(path)
