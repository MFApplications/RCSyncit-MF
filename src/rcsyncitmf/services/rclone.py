"""Async wrapper around the rclone CLI.

All operations are non-blocking: they run rclone as a subprocess and return
parsed results. The UI must never call these directly from the GTK main thread;
use ``ui.async_helper.run_async`` instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

__all__ = [
    "RcloneError",
    "config_dump",
    "copy",
    "create_remote",
    "delete_file",
    "delete_remote",
    "list_dirs",
    "list_files",
    "list_remotes",
    "mkdir",
    "move",
    "purge",
    "rclone_bin",
    "rmdir",
    "run",
]


class RcloneError(Exception):
    def __init__(self, cmd: list[str], rc: int, stderr: str) -> None:
        super().__init__(f"rclone failed (rc={rc}): {stderr.strip()}")
        self.cmd = cmd
        self.rc = rc
        self.stderr = stderr


def in_flatpak() -> bool:
    """Return True when running inside a Flatpak sandbox."""
    return os.path.exists("/.flatpak-info") or bool(os.environ.get("FLATPAK_ID"))


async def run(
    args: list[str],
    *,
    config: Path | None = None,
    timeout: float = 300.0,
    retries: int = 2,
    config_password: str | None = None,
) -> str:
    """Run rclone with the given args. Returns stdout. Raises RcloneError on failure."""
    last_err: RcloneError | None = None
    for attempt in range(retries + 1):
        cmd = ["flatpak-spawn", "--host", "rclone"] if in_flatpak() else [rclone_bin()]
        if config is not None:
            cmd += ["--config", str(config)]
        cmd += list(args)

        # Resolve password: explicit > cached
        pwd = config_password
        if pwd is None and config is not None:
            try:
                from .profile_store import get_cached_password

                pwd = get_cached_password(config)
            except Exception:
                pwd = None

        env = None
        if pwd:
            import os

            env = dict(os.environ)
            env["RCLONE_CONFIG_PASS"] = pwd

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            import contextlib

            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            last_err = RcloneError(cmd, -1, "timeout")
            if attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise last_err from None

        stdout = out.decode("utf-8", errors="replace")
        stderr = err.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            last_err = RcloneError(cmd, proc.returncode or 0, stderr)
            # Retry on transient errors (rate limits / 5xx / network).
            transient = any(
                token in stderr.lower()
                for token in (
                    "rate limit",
                    "too many requests",
                    "429",
                    "500",
                    "502",
                    "503",
                    "timeout",
                    "connection reset",
                )
            )
            if transient and attempt < retries:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            raise last_err
        return stdout

    if last_err is not None:
        raise last_err
    return ""


async def list_remotes(config: Path) -> list[str]:
    out = await run(["listremotes"], config=config)
    return [line.strip().rstrip(":") for line in out.splitlines() if line.strip()]


async def config_dump(config: Path, config_password: str | None = None) -> dict:
    out = await run(["config", "dump"], config=config, config_password=config_password)
    if not out.strip():
        return {}
    return json.loads(out)


async def create_remote(config: Path, name: str, rtype: str, opts: dict | None = None) -> None:
    opts = opts or {}
    args = ["config", "create", name, rtype, "--non-interactive"]
    for key, value in opts.items():
        args += [str(key), str(value)]
    await run(args, config=config)


async def delete_remote(config: Path, name: str) -> None:
    await run(["config", "delete", name], config=config)


async def update_remote(config: Path, name: str, opts: dict) -> None:
    args = ["config", "update", name, "--non-interactive"]
    for key, value in opts.items():
        args += [str(key), str(value)]
    await run(args, config=config)


async def list_dirs(
    config: Path, remote: str, path: str = "", *, recursive: bool = False
) -> list[dict]:
    target = f"{remote}:{path}" if path else f"{remote}:"
    args = ["lsjson", target, "--dirs-only"]
    if recursive:
        args.append("-R")
    out = await run(args, config=config)
    if not out.strip():
        return []
    data = json.loads(out)
    if isinstance(data, list):
        return data
    return []


async def list_files(
    config: Path, remote: str, path: str = "", *, recursive: bool = False
) -> list[dict]:
    target = f"{remote}:{path}" if path else f"{remote}:"
    args = ["lsjson", target]
    if recursive:
        args.append("-R")
    out = await run(args, config=config)
    if not out.strip():
        return []
    data = json.loads(out)
    if isinstance(data, list):
        return data
    return []


async def delete_file(config: Path, remote: str, path: str) -> None:
    await run(["deletefile", f"{remote}:{path}"], config=config)


async def move(
    config: Path,
    src_remote: str,
    src_path: str,
    dst_remote: str,
    dst_path: str,
) -> None:
    src = f"{src_remote}:{src_path}" if src_path else f"{src_remote}:"
    dst = f"{dst_remote}:{dst_path}" if dst_path else f"{dst_remote}:"
    await run(["moveto", src, dst], config=config)


async def copy(
    config: Path,
    src_remote: str,
    src_path: str,
    dst_remote: str,
    dst_path: str,
) -> None:
    src = f"{src_remote}:{src_path}" if src_path else f"{src_remote}:"
    dst = f"{dst_remote}:{dst_path}" if dst_path else f"{dst_remote}:"
    await run(["copyto", src, dst], config=config)


async def mkdir(config: Path, remote: str, path: str) -> None:
    await run(["mkdir", f"{remote}:{path}"], config=config)


async def rmdir(config: Path, remote: str, path: str) -> None:
    await run(["rmdir", f"{remote}:{path}"], config=config)


async def purge(config: Path, remote: str, path: str) -> None:
    await run(["purge", f"{remote}:{path}"], config=config)


def list_providers() -> list[dict]:
    """Return rclone's config providers (synchronously, fast)."""
    import json as _json
    import subprocess as _subprocess

    try:
        if in_flatpak():
            cmd = ["flatpak-spawn", "--host", "rclone", "config", "providers"]
        else:
            cmd = [rclone_bin(), "config", "providers"]
        proc = _subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = _json.loads(proc.stdout)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


_RCLONE_BIN_CACHE: dict[str, str] = {}


def invalidate_rclone_bin_cache() -> None:
    """Clear the cached rclone binary resolution (call after settings change)."""
    _RCLONE_BIN_CACHE.clear()


def rclone_bin() -> str:
    if in_flatpak():
        return "rclone"
    name = "rclone"
    try:
        from ..config import load_settings

        name = str(load_settings().get("rclone_bin", "rclone") or "rclone")
    except Exception:
        name = "rclone"
    cached = _RCLONE_BIN_CACHE.get(name)
    if cached is not None:
        return cached
    resolved = shutil.which(name) or name
    _RCLONE_BIN_CACHE[name] = resolved
    return resolved
