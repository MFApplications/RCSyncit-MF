"""Adw.Application subclass: owns the app lifecycle and the main window."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib

from . import APP_ID
from .config import LOG_FILE, ensure_dirs
from .services.auto_sync import AutoSyncManager
from .window import MainWindow


def _setup_logging() -> None:
    ensure_dirs()
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class RCSyncitMFApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        _setup_logging()
        self.auto_sync: AutoSyncManager | None = None
        self._shutdown_connected: bool = False
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: Adw.Application) -> None:
        window = MainWindow(application=self)
        window.present()
        # Graceful checks (after present so toasts render)
        if shutil.which("rclone") is None:
            window.toast("rclone no encontrado en PATH")
            logging.error("rclone not found in PATH")
        if not Path("/dev/fuse").exists():
            window.toast("FUSE no disponible: mounts deshabilitados")
            logging.warning("/dev/fuse not present")
        # Drop stale mount entries (only those still mounted are kept).
        try:
            from .services import mount_manager

            mount_manager.remove_stale()
            mount_manager.cleanup_bookmarks()
        except Exception:
            logging.exception("mount cleanup failed")
        # Auto-detect default rclone.conf after window is visible
        GLib.idle_add(window.check_default_rclone_config)
        # Background automatic union sync (only once per app instance)
        if not hasattr(self, "auto_sync") or self.auto_sync is None:
            self.auto_sync = AutoSyncManager()
            self.auto_sync.start()

        def _on_shutdown(_app):
            mgr = getattr(self, "auto_sync", None)
            if mgr is not None:
                mgr.stop()
                self.auto_sync = None

        if not getattr(self, "_shutdown_connected", False):
            self.connect("shutdown", _on_shutdown)
            self._shutdown_connected = True
