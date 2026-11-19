"""Management of rclone mounts (daemon mode) with persistence."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import tomllib
from pathlib import Path

from ..config import APP_DIR, MOUNTS_FILE, ensure_dirs, save_toml
from ..i18n import _
from .rclone import in_flatpak

_LEGACY_MOUNTS_FILE = MOUNTS_FILE.with_name("mounts.json")

_MOUNTS_LOCK = threading.RLock()


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


def _load_unlocked() -> list[dict]:
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


def _save_unlocked(data: list[dict]) -> None:
    ensure_dirs()
    save_toml(MOUNTS_FILE, {"mounts": data})


def _load() -> list[dict]:
    with _MOUNTS_LOCK:
        return _load_unlocked()


def _save(data: list[dict]) -> None:
    with _MOUNTS_LOCK:
        _save_unlocked(data)


def is_mounted(mountpoint: Path) -> bool:
    mp = str(mountpoint)
    if in_flatpak():
        # The mount lives on the host; check there.
        try:
            import subprocess as _sp

            proc = _sp.run(
                ["flatpak-spawn", "--host", "mountpoint", mp],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return True
        except (OSError, FileNotFoundError):
            pass
        # Safe fallback: read /proc/mounts from the host and parse in Python
        # (no shell interpolation of the mountpoint path).
        try:
            import subprocess as _sp

            proc = _sp.run(
                ["flatpak-spawn", "--host", "cat", "/proc/mounts"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == mp:
                        return True
        except (OSError, FileNotFoundError):
            pass
        return False
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
    # Repair unions whose cache_time is stored as a non-integer (e.g. "5m").
    try:
        from . import profile_store, union_sync

        pwd = profile_store.get_cached_password(config)
        await union_sync.normalize_union_cache_times(config, config_password=pwd)
    except Exception:
        pass
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
    # Per-mount verbose log (INFO level) for diagnostics.
    import contextlib

    log_dir = APP_DIR / "logs"
    with contextlib.suppress(OSError):
        log_dir.mkdir(parents=True, exist_ok=True)
    safe_remote = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(remote))
    log_path = log_dir / f"{config.stem}-{safe_remote}.log"
    with contextlib.suppress(OSError):
        log_path.unlink(missing_ok=True)

    args = [
        "mount",
        f"{remote}:",
        str(mountpoint),
        "--daemon",
        "--log-level",
        "INFO",
        "--log-file",
        str(log_path),
    ]

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

    # Persist the effective rclone command for diagnostics.
    try:
        with open(log_path, "a", encoding="utf-8") as _lf:
            _lf.write("COMMAND: " + " ".join(args) + "\n")
    except OSError:
        pass

    # Mount options (Fase A)
    if vfs.get("read_only"):
        args += ["--read-only"]
    if vfs.get("allow_other"):
        args += ["--allow-other"]
    if vfs.get("network_mode"):
        args += ["--network-mode"]
    if vfs.get("attr_timeout") is not None:
        args += ["--attr-timeout", f"{int(vfs['attr_timeout'])}s"]
    if vfs.get("vfs_read_ahead"):
        args += ["--vfs-read-ahead", str(vfs["vfs_read_ahead"])]
    if vfs.get("vfs_fast_fingerprint"):
        args += ["--vfs-fast-fingerprint"]

    if extra:
        args += extra

    # `rclone mount --daemon` forks a child that keeps the stdout/stderr pipes
    # open, so rclone.run() (which calls communicate()) would hang until the
    # timeout. Run it as a plain subprocess instead and capture stderr.
    import asyncio as _asyncio
    import subprocess as _subprocess

    if in_flatpak():
        cmd = ["flatpak-spawn", "--host", "rclone", "--config", str(config), *list(args)]
    else:
        from .rclone import rclone_bin

        cmd = [rclone_bin(), "--config", str(config), *list(args)]

    # Resolve cached password for encrypted profiles.
    env = None
    try:
        from . import profile_store

        pwd = profile_store.get_cached_password(config)
        if pwd:
            import os as _os

            env = dict(_os.environ)
            env["RCLONE_CONFIG_PASS"] = pwd
    except Exception:
        env = None

    def _do_mount() -> _subprocess.CompletedProcess:
        return _subprocess.run(
            cmd,
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL,
            timeout=60,
            env=env,
        )

    try:
        result = await _asyncio.to_thread(_do_mount)
    except _subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"rclone mount timeout: {exc}") from None

    if result.returncode != 0:
        err_text = ""
        try:
            err_text = read_mount_log({"log": str(log_path)}, lines=40)
        except Exception:
            err_text = ""
        from .rclone import RcloneError

        raise RcloneError(cmd, result.returncode, err_text or "mount failed")
    rec = {
        "remote": remote,
        "mountpoint": str(mountpoint),
        "config": str(config),
        "log": str(log_path),
    }
    with _MOUNTS_LOCK:
        data = _load_unlocked()
        data = [r for r in data if r.get("mountpoint") != str(mountpoint)]
        data.append(rec)
        _save_unlocked(data)
    _add_bookmark(mountpoint, remote)
    return rec


async def unmount(mountpoint: Path) -> None:
    # Try fusermount -u, then umount. Only treat as success if one command
    # returned 0; never delete the mountpoint if unmounting failed (data-loss risk).
    success = False
    last_err = ""
    cmds = (
        ["fusermount3", "-u", str(mountpoint)],
        ["fusermount", "-u", str(mountpoint)],
        ["umount", str(mountpoint)],
    )
    if in_flatpak():
        cmds = (
            ["flatpak-spawn", "--host", "fusermount3", "-u", str(mountpoint)],
            ["flatpak-spawn", "--host", "fusermount", "-u", str(mountpoint)],
            ["flatpak-spawn", "--host", "umount", str(mountpoint)],
        )
    for cmd in cmds:
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
        raise RuntimeError(
            _("no se pudo desmontar {mp}: {err}").format(mp=mountpoint, err=last_err).strip()
        )
    # cleanup mountpoint directory only after a successful unmount
    import shutil

    for _i in range(5):
        shutil.rmtree(mountpoint, ignore_errors=True)
        if not mountpoint.exists():
            break
        await asyncio.sleep(0.5)
    # Remove empty parent directories up to the mounts base so no orphan
    # folders (profile/remote) are left behind (security: no stale dirs).
    import contextlib

    with contextlib.suppress(Exception):
        _remove_empty_parents(mountpoint, default_mounts_base())
    _remove_bookmark(mountpoint)
    # Aggressive bookmark cleanup: also drop entries whose path no longer exists.
    cleanup_bookmarks()
    # remove from persisted list
    with _MOUNTS_LOCK:
        data = [r for r in _load_unlocked() if r.get("mountpoint") != str(mountpoint)]
        _save_unlocked(data)


def list_mounts() -> list[dict]:
    return _load()


def _safe_remote(name: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(name))


def read_mount_log(mount: dict, lines: int = 300) -> str:
    """Return the tail of the verbose log associated with a mount record."""
    log_path_raw = mount.get("log") if isinstance(mount, dict) else None
    if not log_path_raw:
        # Fallback for records created before logging was added.
        cfg = mount.get("config") if isinstance(mount, dict) else None
        remote = mount.get("remote") if isinstance(mount, dict) else None
        if cfg and remote:
            try:
                log_path_raw = str(
                    APP_DIR / "logs" / f"{Path(cfg).stem}-{_safe_remote(str(remote))}.log"
                )
            except Exception:
                log_path_raw = None
    if not log_path_raw:
        return "(sin log disponible)"
    p = Path(str(log_path_raw))
    if not p.exists():
        return "(log todavía no generado)"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error leyendo log: {exc}"
    all_lines = text.splitlines()
    if len(all_lines) > lines:
        all_lines = all_lines[-lines:]
    return "\n".join(all_lines) if all_lines else "(log vacío)"


def remove_stale() -> None:
    with _MOUNTS_LOCK:
        data = _load_unlocked()
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
        _save_unlocked(kept)
    import contextlib

    with contextlib.suppress(Exception):
        cleanup_empty_mount_dirs()


def _custom_mounts_dir() -> Path | None:
    try:
        from ..config import load_settings

        raw = str(load_settings().get("mounts_dir", "") or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return None
    p = Path(raw).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if not p.is_dir() or not os.access(p, os.W_OK):
        return None
    return p


def default_mounts_base() -> Path:
    """Return the effective base directory for mounts (custom or system default)."""
    custom = _custom_mounts_dir()
    if custom is not None:
        return custom
    if in_flatpak():
        return Path.home() / ".local" / "share" / "rcsyncitmf" / "mnt"
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    base = Path("/run/media") / user / "rcsyncitmf"
    try:
        base.mkdir(parents=True, exist_ok=True)
        if not os.access(base, os.W_OK):
            raise PermissionError
    except (OSError, PermissionError):
        base = Path.home() / ".local" / "share" / "rcsyncitmf" / "mnt"
    return base


def default_mountpoint(profile: Path, remote: str) -> Path:
    return default_mounts_base() / profile.stem / remote


def _remove_empty_parents(path: Path, stop: Path) -> None:
    """Remove empty parent directories of *path* up to (excluding) *stop*."""
    try:
        stop_resolved = stop.resolve()
    except Exception:
        stop_resolved = stop
    cur = path.parent
    while True:
        try:
            if cur.resolve() == stop_resolved or cur == cur.parent:
                break
        except Exception:
            if cur == cur.parent:
                break
        if not cur.exists():
            cur = cur.parent
            continue
        try:
            if any(cur.iterdir()):
                break
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def cleanup_empty_mount_dirs() -> int:
    """Remove empty directories under the mounts base. Returns count removed."""
    base = default_mounts_base()
    if not base.exists() or not base.is_dir():
        return 0
    removed = 0
    try:
        for root, _dirs, _files in os.walk(str(base), topdown=False):
            root_path = Path(root)
            if root_path == base:
                continue
            try:
                if root_path.exists() and not any(root_path.iterdir()):
                    root_path.rmdir()
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


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
        raise FileNotFoundError(_("xdg-open/nautilus no encontrado"))


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


_PROFILE_DUMP_CACHE: dict[str, tuple[float, dict]] = {}
_PROFILE_DUMP_LOCK = threading.RLock()
_DUMP_TTL = 15.0


def _invalidate_profile_dump_cache(profile: Path | None = None) -> None:
    with _PROFILE_DUMP_LOCK:
        if profile is None:
            _PROFILE_DUMP_CACHE.clear()
        else:
            _PROFILE_DUMP_CACHE.pop(str(profile), None)


def _dump_for_profile(profile: Path) -> dict:
    key = str(profile)
    now = time.monotonic()
    with _PROFILE_DUMP_LOCK:
        entry = _PROFILE_DUMP_CACHE.get(key)
        if entry is not None and now - entry[0] < _DUMP_TTL:
            return entry[1]
    try:
        import asyncio as _asyncio

        from . import profile_store, rclone

        pwd = profile_store.get_cached_password(profile)
        loop = _asyncio.new_event_loop()
        try:
            dump = loop.run_until_complete(rclone.config_dump(profile, config_password=pwd))
        finally:
            loop.close()
    except Exception:
        dump = {}
    if not isinstance(dump, dict):
        dump = {}
    with _PROFILE_DUMP_LOCK:
        _PROFILE_DUMP_CACHE[key] = (time.monotonic(), dump)
    return dump


def _all_profile_dumps() -> list[tuple[Path, dict]]:
    from . import profile_store

    out: list[tuple[Path, dict]] = []
    for profile in profile_store.list_profiles():
        out.append((profile, _dump_for_profile(profile)))
    return out


async def async_dump_for_profile(profile: Path) -> dict:
    key = str(profile)
    now = time.monotonic()
    with _PROFILE_DUMP_LOCK:
        entry = _PROFILE_DUMP_CACHE.get(key)
        if entry is not None and now - entry[0] < _DUMP_TTL:
            return entry[1]
    try:
        from . import profile_store, rclone

        pwd = profile_store.get_cached_password(profile)
        dump = await rclone.config_dump(profile, config_password=pwd)
    except Exception:
        dump = {}
    if not isinstance(dump, dict):
        dump = {}
    with _PROFILE_DUMP_LOCK:
        _PROFILE_DUMP_CACHE[key] = (time.monotonic(), dump)
    return dump


async def async_related_cache_remotes(remote: str) -> list[str]:
    group = {remote}
    dumps = []
    try:
        from . import profile_store

        for profile in profile_store.list_profiles():
            try:
                dump = await async_dump_for_profile(profile)
            except Exception:
                continue
            dumps.append((profile, dump))
    except Exception:
        pass
    for _profile, dump in dumps:
        for name, data in (dump or {}).items():
            if not (isinstance(data, dict) and data.get("type") == "crypt"):
                continue
            parent = str(data.get("remote", "")).rstrip(":").strip()
            if name == remote and parent:
                group.add(parent)
            if parent == remote:
                group.add(name)
    return sorted(group)


def crypt_parent(remote: str) -> str | None:
    """Return the underlying remote if *remote* is a crypt, else None."""
    for _profile, dump in _all_profile_dumps():
        data = dump.get(remote)
        if isinstance(data, dict) and data.get("type") == "crypt":
            return str(data.get("remote", "")).rstrip(":").strip() or None
    return None


def related_cache_remotes(remote: str) -> list[str]:
    """Return all cache remotes that must be cleared together with *remote*.

    A crypt remote and its underlying remote share cache behaviour, so
    clearing one should clear the other.
    """
    group = {remote}
    for _profile, dump in _all_profile_dumps():
        for name, data in dump.items():
            if not (isinstance(data, dict) and data.get("type") == "crypt"):
                continue
            parent = str(data.get("remote", "")).rstrip(":").strip()
            if name == remote and parent:
                group.add(parent)
            if parent == remote:
                group.add(name)
    return sorted(group)


async def clear_vfs_cache(remote: str) -> None:
    targets = await async_related_cache_remotes(remote)

    def _remove():
        import shutil

        for name in targets:
            cache_dir = Path.home() / ".cache" / "rclone" / "vfs" / name
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)

    import asyncio

    await asyncio.to_thread(_remove)


async def async_crypt_parent_map() -> dict[str, str | None]:
    """Return a mapping remote -> underlying parent for crypt remotes (async)."""
    result: dict[str, str | None] = {}
    try:
        from . import profile_store, rclone

        for profile in profile_store.list_profiles():
            try:
                pwd = profile_store.get_cached_password(profile)
                dump = await rclone.config_dump(profile, config_password=pwd)
            except Exception:
                continue
            if not isinstance(dump, dict):
                continue
            for name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "crypt":
                    parent = str(data.get("remote", "")).rstrip(":").strip() or None
                    result[name] = parent
    except Exception:
        pass
    return result


async def async_crypt_parents_with_cache(cached: list[str]) -> set[str]:
    """Async variant of ``crypt_parents_with_cache`` (avoids blocking the UI)."""
    cached_set = set(cached)
    hidden: set[str] = set()
    try:
        from . import profile_store, rclone

        for profile in profile_store.list_profiles():
            try:
                pwd = profile_store.get_cached_password(profile)
                dump = await rclone.config_dump(profile, config_password=pwd)
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


def crypt_parents_with_cache(cached: list[str]) -> set[str]:
    """Return cache entries that are underlying remotes of a crypt remote

    that also has its own cache (so they appear as duplicates).
    """
    cached_set = set(cached)
    hidden: set[str] = set()
    for _profile, dump in _all_profile_dumps():
        for name, data in dump.items():
            if not (isinstance(data, dict) and data.get("type") == "crypt"):
                continue
            parent = str(data.get("remote", "")).rstrip(":").strip()
            if parent and parent in cached_set and name in cached_set:
                hidden.add(parent)
    return hidden


def list_cached_remotes() -> list[str]:
    cache_root = Path.home() / ".cache" / "rclone" / "vfs"
    if not cache_root.exists():
        return []
    out = []
    for p in cache_root.iterdir():
        if p.is_dir() and any(p.iterdir()):
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
