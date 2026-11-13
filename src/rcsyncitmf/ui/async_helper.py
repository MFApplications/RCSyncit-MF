"""Bridge between asyncio coroutines and the GTK main loop.

rclone calls are async; GTK widgets must only be touched on the main thread.
``run_async`` schedules a coroutine on a background event loop and delivers
the result (or exception) to the UI via ``GLib.idle_add``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from gi.repository import GLib


def run_async(
    coro: Coroutine[Any, Any, Any],
    *,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Run *coro* off the UI thread and call back on the main thread."""

    def worker() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(coro)
        except BaseException as exc:
            if on_error is not None:
                GLib.idle_add(lambda e=exc: (on_error(e), False)[1])
            return
        finally:
            loop.close()
        if on_success is not None:
            GLib.idle_add(lambda r=result: (on_success(r), False)[1])

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
