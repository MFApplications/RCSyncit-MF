"""Settings page backed by ~/.config/rcsyncitmf/settings.toml."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw

from ...config import load_settings, save_settings


class SettingsPage(Adw.PreferencesPage):
    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self.set_title("Ajustes")
        self.set_icon_name("preferences-system-symbolic")

        self.settings = load_settings()

        group = Adw.PreferencesGroup(title="Sincronización")
        self.add(group)

        # Concurrency
        self.concurrency_row = Adw.SpinRow.new_with_range(1, 32, 1)
        self.concurrency_row.set_title("Concurrencia")
        self.concurrency_row.set_subtitle("Operaciones paralelas contra las nubes")
        self.concurrency_row.set_value(self.settings.get("concurrency", 4))
        self.concurrency_row.connect("changed", self._save)
        group.add(self.concurrency_row)

        # Depth
        self.depth_row = Adw.SpinRow.new_with_range(1, 10, 1)
        self.depth_row.set_title("Profundidad")
        self.depth_row.set_subtitle("Niveles de carpetas a sincronizar")
        self.depth_row.set_value(self.settings.get("sync_depth", 1))
        self.depth_row.connect("changed", self._save)
        group.add(self.depth_row)

        # Dry run default
        self.dryrun_row = Adw.SwitchRow()
        self.dryrun_row.set_title("Dry-run por defecto")
        self.dryrun_row.set_subtitle("Mostrar vista previa antes de aplicar")
        self.dryrun_row.set_active(bool(self.settings.get("dry_run_default", True)))
        self.dryrun_row.connect("notify::active", self._save)
        group.add(self.dryrun_row)

        # Profiles dir
        g2 = Adw.PreferencesGroup(title="Almacenamiento")
        self.add(g2)
        self.profiles_row = Adw.ActionRow()
        self.profiles_row.set_title("Directorio de perfiles")
        self.profiles_row.set_subtitle(str(self.settings.get("profiles_dir")))
        g2.add(self.profiles_row)

        # Auto-sync
        g3 = Adw.PreferencesGroup(title="Sincronización automática")
        self.add(g3)

        self.autosync_interval_row = Adw.SpinRow.new_with_range(0, 1440, 1)
        self.autosync_interval_row.set_title("Intervalo (minutos)")
        self.autosync_interval_row.set_subtitle("0 desactiva la sincronización automática")
        self.autosync_interval_row.set_value(
            int(self.settings.get("auto_sync_interval", 300)) // 60
        )
        self.autosync_interval_row.connect("changed", self._save)
        g3.add(self.autosync_interval_row)

        self.autosync_delete_row = Adw.SwitchRow()
        self.autosync_delete_row.set_title("Propagar borrados")
        self.autosync_delete_row.set_subtitle("Borra en todos los upstreams al faltar en uno")
        self.autosync_delete_row.set_active(
            bool(self.settings.get("auto_sync_allow_delete", False))
        )
        self.autosync_delete_row.connect("notify::active", self._save)
        g3.add(self.autosync_delete_row)

        self.autosync_purge_row = Adw.SwitchRow()
        self.autosync_purge_row.set_title("Usar purge en borrados")
        self.autosync_purge_row.set_subtitle(
            "Borrado recursivo; desactivado usa rmdir (más seguro)"
        )
        self.autosync_purge_row.set_active(bool(self.settings.get("auto_sync_use_purge", False)))
        self.autosync_purge_row.connect("notify::active", self._save)
        g3.add(self.autosync_purge_row)

        self.autosync_maxdel_row = Adw.SpinRow.new_with_range(1, 10000, 1)
        self.autosync_maxdel_row.set_title("Máximo de borrados por ciclo")
        self.autosync_maxdel_row.set_value(int(self.settings.get("auto_sync_max_deletions", 100)))
        self.autosync_maxdel_row.connect("changed", self._save)
        g3.add(self.autosync_maxdel_row)

    def _save(self, *_args) -> None:
        self.settings["concurrency"] = int(self.concurrency_row.get_value())
        self.settings["sync_depth"] = int(self.depth_row.get_value())
        self.settings["dry_run_default"] = bool(self.dryrun_row.get_active())
        self.settings["auto_sync_interval"] = int(self.autosync_interval_row.get_value()) * 60
        self.settings["auto_sync_allow_delete"] = bool(self.autosync_delete_row.get_active())
        self.settings["auto_sync_use_purge"] = bool(self.autosync_purge_row.get_active())
        self.settings["auto_sync_max_deletions"] = int(self.autosync_maxdel_row.get_value())
        save_settings(self.settings)
        self.window.toast("Ajustes guardados")
