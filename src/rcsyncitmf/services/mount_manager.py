"""Management of rclone mounts (daemon mode) with persistence."""

from __future__ import annotations

import asyncio
import json
import os
import tomllib
from pathlib import Path

from ..config import MOUNTS_FILE, ensure_dirs, save_toml

_LEGACY_MOUNTS_FILE = MOUNTS_FILE.with_name("mounts.json")


def _migrate_legacy_mounts() -> None:
    if _LEGACY_MOUNTS_FILE.exists() and not MOUNTS_FILE.exists():
        try:
            legacy = json.loads(_LEGACY_MOUNTS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            legacy = None
        if isinstance(legacy, list):
            # Update legacy mountpoint paths to the new data directory name.
            migrated = []
            for rec in legacy:
                if isinstance(rec, dict) and isinstance(rec.get("mountpoint"), str):
                    rec = dict(rec)
                    rec["mountpoint"] = rec["mountpoint"].replace(
                        "/.local/share/rsyncmf/mnt", "/.local/share/rcsyncitmf/mnt"
                    )
                migrated.append(rec)
            try:
                ensure_dirs()
                save_toml(MOUNTS_FILE, {"mounts": migrated})
                _LEGACY_MOUNTS_FILE.rename(_LEGACY_MOUNTS_FILE.with_suffix(".json.bak"))
            except (OSError, ValueError, TypeError):
                pass


def _load() -> list[dict]:
    ensure_dirs()
    _migrate_legacy_mounts()
    if MOUNTS_FILE.exists():
        try:
            with MOUNTS_FILE.open("rb") as f:
                data = tomllib.load(f)
            if isinstance(data, dict):
                mounts = data.get("mounts", [])
                if isinstance(mounts, list):
                    return mounts
        except (OSError, tomllib.TOMLDecodeError):
            return []
    return []


def _save(data: list[dict]) -> None:
    ensure_dirs()
    save_toml(MOUNTS_FILE, {"mounts": data})


def is_mounted(mountpoint: Path) -> bool:
    mp = str(mountpoint)
    # /proc/mounts check
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == mp:
                    return True
    except OSError:
        pass
    # fallback: rclone mount usually shows as fuse.rclone
    return os.path.ismount(mountpoint)


async def mount(
    config: Path, remote: str, mountpoint: Path, extra: list[str] | None = None
) -> dict:
    try:
        mountpoint.parent.mkdir(parents=True, exist_ok=True)
        mountpoint.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        # Fallback to a user-writable location.
        mountpoint = (
            Path.home()
            / ".local"
            / "share"
            / "rcsyncitmf"
            / "mnt"
            / mountpoint.parent.name
            / mountpoint.name
        )
        mountpoint.parent.mkdir(parents=True, exist_ok=True)
        mountpoint.mkdir(parents=True, exist_ok=True)
    args = ["mount", f"{remote}:", str(mountpoint), "--daemon"]

    # Load per-profile VFS options from metadata
    try:
        from .profile_store import load_meta

        meta = load_meta(config)
        vfs = meta.get("vfs", {}) if isinstance(meta, dict) else {}
    except Exception:
        vfs = {}

    cache_mode = vfs.get("cache_mode", "writes")
    args += ["--vfs-cache-mode", str(cache_mode)]
    if vfs.get("cache_max_size"):
        args += ["--vfs-cache-max-size", str(vfs["cache_max_size"])]
    if vfs.get("cache_max_age"):
        args += ["--vfs-cache-max-age", str(vfs["cache_max_age"])]
    if vfs.get("read_chunk_size"):
        args += ["--vfs-read-chunk-size", str(vfs["read_chunk_size"])]
    if vfs.get("buffer_size"):
        args += ["--buffer-size", str(vfs["buffer_size"])]
    if vfs.get("write_back"):
        args += ["--vfs-write-back", str(vfs["write_back"])]
    if vfs.get("dir_cache_time"):
        args += ["--dir-cache-time", str(vfs["dir_cache_time"])]
    if vfs.get("poll_interval"):
        args += ["--poll-interval", str(vfs["poll_interval"])]
    if vfs.get("umask") is not None:
        args += ["--umask", str(vfs["umask"])]

    if extra:
        args += extra
    from .rclone import run

    await run(args, config=config, timeout=60, retries=0)
    rec = {"remote": remote, "mountpoint": str(mountpoint), "config": str(config)}
    data = _load()
    # avoid duplicates
    data = [r for r in data if r.get("mountpoint") != str(mountpoint)]
    data.append(rec)
    _save(data)
    _add_bookmark(mountpoint, remote)
    return rec


async def unmount(mountpoint: Path) -> None:
    # Try fusermount -u, then umount. Only treat as success if one command
    # returned 0; never delete the mountpoint if unmounting failed (data-loss risk).
    success = False
    last_err = ""
    for cmd in (["fusermount", "-u", str(mountpoint)], ["umount", str(mountpoint)]):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _out, err = await proc.communicate()
        except FileNotFoundError:
            last_err = f"{cmd[0]} no encontrado"
            continue
        if proc.returncode == 0:
            success = True
            break
        last_err = err.decode("utf-8", errors="replace").strip() or last_err
    if not success:
        raise RuntimeError(f"no se pudo desmontar {mountpoint}: {last_err}".strip())
    # cleanup mountpoint directory only after a successful unmount
    import shutil

    shutil.rmtree(mountpoint, ignore_errors=True)
    # Remove the (now empty) profile directory so no orphan folder named
    # after the profile is left behind.
    try:
        parent = mountpoint.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    _remove_bookmark(mountpoint)
    # remove from persisted list
    data = [r for r in _load() if r.get("mountpoint") != str(mountpoint)]
    _save(data)


def list_mounts() -> list[dict]:
    return _load()


def remove_stale() -> None:
    data = _load()
    kept = []
    for r in data:
        if not isinstance(r, dict):
            continue
        mp = r.get("mountpoint")
        if not isinstance(mp, str) or not mp:
            continue
        p = Path(mp)
        if p.exists() and is_mounted(p):
            kept.append(r)
    _save(kept)


def default_mountpoint(profile: Path, remote: str) -> Path:
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    base = Path("/run/media") / user / "rcsyncitmf"
    try:
        base.mkdir(parents=True, exist_ok=True)
        if not os.access(base, os.W_OK):
            raise PermissionError
    except (OSError, PermissionError):
        base = Path.home() / ".local" / "share" / "rcsyncitmf" / "mnt"
    return base / profile.stem / remote


def open_in_file_manager(path: Path) -> None:
    import shutil
    import subprocess

    if shutil.which("xdg-open"):
        subprocess.Popen(
            ["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    elif shutil.which("nautilus"):
        subprocess.Popen(
            ["nautilus", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        raise FileNotFoundError("xdg-open/nautilus no encontrado")


def _bookmark_files() -> list[Path]:
    base = Path.home() / ".config"
    return [base / "gtk-3.0" / "bookmarks", base / "gtk-4.0" / "bookmarks"]


def _add_bookmark(mountpoint: Path, name: str) -> None:
    uri = mountpoint.as_uri()
    line = f"{uri} {name}"
    for bf in _bookmark_files():
        try:
            bf.parent.mkdir(parents=True, exist_ok=True)
            lines = bf.read_text(encoding="utf-8").splitlines() if bf.exists() else []
            # remove any existing entry for this uri
            lines = [ln for ln in lines if not ln.startswith(uri + " ") and ln.strip() != uri]
            lines.append(line)
            bf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass


def _remove_bookmark(mountpoint: Path) -> None:
    uri = mountpoint.as_uri()
    for bf in _bookmark_files():
        if not bf.exists():
            continue
        try:
            lines = bf.read_text(encoding="utf-8").splitlines()
            lines = [ln for ln in lines if not ln.startswith(uri + " ") and ln.strip() != uri]
            bf.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        except OSError:
            pass


def crypt_parent(remote: str) -> str | None:
    """Return the underlying remote if *remote* is a crypt, else None."""
    try:
        import asyncio

        from . import profile_store, rclone

        for profile in profile_store.list_profiles():
            try:
                dump = asyncio.run(rclone.config_dump(profile))
            except Exception:
                continue
            if not isinstance(dump, dict):
                continue
            data = dump.get(remote)
            if isinstance(data, dict) and data.get("type") == "crypt":
                return str(data.get("remote", "")).rstrip(":").strip() or None
    except Exception:
        pass
    return None


def related_cache_remotes(remote: str) -> list[str]:
    """Return all cache remotes that must be cleared together with *remote*.

    A crypt remote and its underlying remote share cache behaviour, so
    clearing one should clear the other.
    """
    group = {remote}
    try:
        import asyncio

        from . import profile_store, rclone

        for profile in profile_store.list_profiles():
            try:
                dump = asyncio.run(rclone.config_dump(profile))
            except Exception:
                continue
            if not isinstance(dump, dict):
                continue
            for name, data in dump.items():
                if not (isinstance(data, dict) and data.get("type") == "crypt"):
                    continue
                parent = str(data.get("remote", "")).rstrip(":").strip()
                if name == remote and parent:
                    group.add(parent)
                if parent == remote:
                    group.add(name)
    except Exception:
        pass
    return sorted(group)


async def clear_vfs_cache(remote: str) -> None:
    targets = related_cache_remotes(remote)

    def _remove():
        import shutil

        for name in targets:
            cache_dir = Path.home() / ".cache" / "rclone" / "vfs" / name
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)

    import asyncio

    await asyncio.to_thread(_remove)


def crypt_parents_with_cache(cached: list[str]) -> set[str]:
    """Return cache entries that are underlying remotes of a crypt remote

    that also has its own cache (so they appear as duplicates).
    """
    cached_set = set(cached)
    hidden: set[str] = set()
    try:
        import asyncio

        from . import profile_store, rclone

        for profile in profile_store.list_profiles():
            try:
                dump = asyncio.run(rclone.config_dump(profile))
            except Exception:
                continue
            if not isinstance(dump, dict):
                continue
            for name, data in dump.items():
                if not (isinstance(data, dict) and data.get("type") == "crypt"):
                    continue
                parent = str(data.get("remote", "")).rstrip(":").strip()
                if parent and parent in cached_set and name in cached_set:
                    hidden.add(parent)
    except Exception:
        pass
    return hidden


def list_cached_remotes() -> list[str]:
    cache_root = Path.home() / ".cache" / "rclone" / "vfs"
    if not cache_root.exists():
        return []
    out = []
    for p in cache_root.iterdir():
        if p.is_dir():
            out.append(p.name)
    return sorted(out)


def has_cache(remote: str) -> bool:
    cache_dir = Path.home() / ".cache" / "rclone" / "vfs" / remote
    return cache_dir.exists() and any(cache_dir.iterdir())


def cleanup_bookmarks() -> None:
    for bf in _bookmark_files():
        if not bf.exists():
            continue
        try:
            lines = bf.read_text(encoding="utf-8").splitlines()
            kept = []
            for ln in lines:
                parts = ln.split(None, 1)
                if not parts:
                    continue
                uri = parts[0]
                if uri.startswith("file://"):
                    try:
                        from urllib.parse import unquote, urlparse

                        p = Path(unquote(urlparse(uri).path))
                    except Exception:
                        p = None
                    if p is not None and not is_mounted(p):
                        continue
                kept.append(ln)
            bf.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except OSError:
            pass
