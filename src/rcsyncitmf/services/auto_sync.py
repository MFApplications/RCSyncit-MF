"""Background, automatic synchronization of union directory trees.

Runs as a daemon thread while the application is open. Every cycle it walks all
profiles/unions, computes a bidirectional mirror plan and applies it through
rclone. State is persisted per (profile, union) via ``sync_state``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from ..config import load_settings
from . import profile_store, rclone, sync_state, union_sync

logger = logging.getLogger(__name__)


class AutoSyncManager:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rcsyncitmf-autosync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            settings = load_settings()
            interval = int(settings.get("auto_sync_interval", 0) or 0)
            if interval > 0:
                try:
                    asyncio.run(self._cycle(settings))
                except Exception:
                    logger.exception("auto-sync cycle failed")
            # Re-check settings periodically even when disabled, so a later
            # change to auto_sync_interval takes effect without restart.
            wait = interval if interval > 0 else 60
            self._stop.wait(wait)

    async def _cycle(self, settings: dict) -> None:
        concurrency = int(settings.get("concurrency", 4))
        raw_depth = int(settings.get("sync_depth", 0) or 0)
        depth = None if raw_depth <= 0 else raw_depth

        profiles = profile_store.list_profiles()

        async def sync_profile(profile: Path) -> None:
            try:
                pwd = profile_store.get_cached_password(profile)
                dump = await rclone.config_dump(profile, config_password=pwd)
            except Exception as exc:
                logger.warning("auto-sync: cannot read profile %s: %s", profile, exc)
                return
            if not isinstance(dump, dict):
                return
            unions = [
                (name, data)
                for name, data in dump.items()
                if isinstance(data, dict) and data.get("type") == "union"
            ]

            async def sync_union(name: str, data: dict) -> None:
                upstreams = union_sync.parse_upstreams(str(data.get("upstreams", "")))
                if not upstreams:
                    return
                state = sync_state.load_state(profile, name)
                baseline = None
                previous = None
                if isinstance(state, dict):
                    previous = state.get("upstreams")
                    if previous == upstreams:
                        paths = state.get("paths")
                        if isinstance(paths, list):
                            baseline = set(paths)
                plan = await union_sync.build_mirror_plan(
                    profile,
                    upstreams,
                    baseline=baseline,
                    previous_upstreams=previous,
                    depth=depth,
                    allow_delete=False,
                    max_deletions=0,
                )
                errs = await union_sync.apply_plan(
                    profile,
                    plan,
                    concurrency=concurrency,
                    delete=False,
                    use_purge=False,
                )
                if errs:
                    for err in errs:
                        logger.warning("auto-sync: %s", err)
                    return
                if plan.baseline is not None:
                    sync_state.save_state(profile, name, upstreams, plan.baseline)

            await asyncio.gather(
                *[sync_union(name, data) for name, data in unions],
                return_exceptions=True,
            )

        results = await asyncio.gather(*[sync_profile(p) for p in profiles], return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.exception("auto-sync: profile sync failed", exc_info=res)

    def _toast(self, message: str) -> bool:
        # Resolved lazily to avoid import cycles.
        import contextlib

        with contextlib.suppress(Exception):
            from ..window import MainWindow  # noqa: F401
        return False


def _toast(message: str) -> None:
    # Best-effort: find the active window through the default application.
    try:
        from gi.repository import Gio

        app = Gio.Application.get_default()
        if app is not None and hasattr(app, "get_active_window"):
            win = app.get_active_window()
            if win is not None and hasattr(win, "toast"):
                win.toast(message)
    except Exception:
        pass
