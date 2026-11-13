"""Background, automatic synchronization of union directory trees.

Runs as a daemon thread while the application is open. Every cycle it walks all
profiles/unions, computes a bidirectional mirror plan and applies it through
rclone. State is persisted per (profile, union) via ``sync_state``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading

from gi.repository import GLib

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
            wait = interval if interval > 0 else 300
            self._stop.wait(wait)

    async def _cycle(self, settings: dict) -> None:
        concurrency = int(settings.get("concurrency", 4))
        allow_delete = bool(settings.get("auto_sync_allow_delete", False))
        use_purge = bool(settings.get("auto_sync_use_purge", False))
        max_deletions = int(settings.get("auto_sync_max_deletions", 100))

        for profile in profile_store.list_profiles():
            try:
                pwd = profile_store.get_cached_password(profile)
                dump = await rclone.config_dump(profile, config_password=pwd)
            except Exception as exc:
                logger.warning("auto-sync: cannot read profile %s: %s", profile, exc)
                continue
            if not isinstance(dump, dict):
                continue
            for name, data in dump.items():
                if not (isinstance(data, dict) and data.get("type") == "union"):
                    continue
                upstreams = union_sync.parse_upstreams(str(data.get("upstreams", "")))
                if not upstreams:
                    continue

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
                    allow_delete=allow_delete,
                    max_deletions=max_deletions,
                )

                errs = await union_sync.apply_plan(
                    profile,
                    plan,
                    concurrency=concurrency,
                    delete=allow_delete,
                    use_purge=use_purge,
                )
                if errs:
                    for err in errs:

                        def _show(e=err):
                            with contextlib.suppress(Exception):
                                _toast(e)
                            return False

                        with contextlib.suppress(Exception):
                            GLib.idle_add(_show)
                    continue
                if plan.baseline is not None:
                    sync_state.save_state(profile, name, upstreams, plan.baseline)

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
