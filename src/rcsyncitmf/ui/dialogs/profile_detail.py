"""Modal detail window for a profile: accounts + VFS/cache settings."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from pathlib import Path

from gi.repository import Adw, Gtk

from ...i18n import _
from ...services import mount_manager, profile_store, rclone
from ...ui.async_helper import run_async
from ...ui.dialogs.remote_dialog import RemoteDialog

VFS_CACHE_MODES = ["off", "minimal", "writes", "full"]

VFS_PRESETS = {
    "Personalizado": None,
    "Rendimiento máximo": {
        "cache_mode": "full",
        "cache_max_size": 4096,
        "cache_max_age": 7200,
        "read_chunk_size": 256,
        "buffer_size": 128,
        "write_back": 30,
        "dir_cache_time": 3600,
        "poll_interval": 300,
    },
    "Medio": {
        "cache_mode": "writes",
        "cache_max_size": 1024,
        "cache_max_age": 3600,
        "read_chunk_size": 128,
        "buffer_size": 16,
        "write_back": 5,
        "dir_cache_time": 300,
        "poll_interval": 60,
    },
    "Bajo": {
        "cache_mode": "minimal",
        "cache_max_size": 256,
        "cache_max_age": 300,
        "read_chunk_size": 16,
        "buffer_size": 4,
        "write_back": 1,
        "dir_cache_time": 60,
        "poll_interval": 15,
    },
}


class ProfileDetailDialog(Adw.Dialog):
    def __init__(self, window, profile: Path) -> None:
        super().__init__()
        self.window = window
        self.profile = profile
        self.set_title(_("Perfil: {n}").format(n=profile.stem))
        self.set_content_width(860)
        self.set_content_height(640)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=profile.stem, xalign=0)
        title.add_css_class("title-2")
        header.append(title)
        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)
        close_btn = Gtk.Button(label=_("Cerrar"))
        close_btn.connect("clicked", lambda _b: self.close())
        header.append(close_btn)
        outer.append(header)

        # View switcher + stack
        self.stack = Adw.ViewStack()
        self.stack.set_vexpand(True)
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        outer.append(switcher)
        outer.append(self.stack)

        # Page 1: accounts
        self.accounts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.accounts_list = Gtk.ListBox()
        self.accounts_list.add_css_class("boxed-list")
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.accounts_list)
        self.accounts_box.append(scrolled)
        acc_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        new_btn = Gtk.Button(label=_("Nuevo remoto"))
        new_btn.add_css_class("suggested-action")
        new_btn.connect("clicked", lambda _b: self._new_remote())
        acc_btns.append(new_btn)
        refresh_btn = Gtk.Button(label=_("Actualizar"))
        refresh_btn.connect("clicked", lambda _b: self._load_accounts())
        acc_btns.append(refresh_btn)
        self.accounts_box.append(acc_btns)
        self.stack.add_titled(self.accounts_box, "accounts", _("Cuentas"))

        # Page 2: VFS / cache
        self.vfs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._build_vfs_form()
        self.stack.add_titled(self.vfs_box, "vfs", _("VFS / Cache"))

        self.set_child(outer)
        self._load_accounts()
        self._load_vfs()

    # ---------- Accounts ----------
    def _load_accounts(self) -> None:
        while True:
            r = self.accounts_list.get_row_at_index(0)
            if r is None:
                break
            self.accounts_list.remove(r)

        async def fetch():
            from ...services import profile_store

            pwd = profile_store.get_cached_password(self.profile)
            return await rclone.config_dump(self.profile, config_password=pwd)

        def ok(dump):
            if not isinstance(dump, dict) or not dump:
                empty = Adw.StatusPage(
                    title=_("Sin remotos"),
                    description=_("Crea tu primer remoto."),
                    icon_name="network-server-symbolic",
                )
                self.accounts_list.append(empty)
                return
            # group crypts
            crypt_map = {}
            for name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "crypt":
                    parent = str(data.get("remote", "")).rstrip(":").strip()
                    if parent:
                        crypt_map[parent] = name
            visible = [
                n
                for n in dump
                if not (
                    isinstance(dump[n], dict)
                    and dump[n].get("type") == "crypt"
                    and str(dump[n].get("remote", "")).rstrip(":").strip() in dump
                )
            ]
            for name in sorted(visible):
                data = dump.get(name, {})
                rtype = data.get("type", "?") if isinstance(data, dict) else "?"
                if rtype == "crypt":
                    row = Adw.ActionRow()
                    row.set_title(name)
                    row.set_subtitle(f"type: {rtype}")
                    lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
                    row.add_prefix(lock)
                else:
                    row = Adw.ExpanderRow() if name in crypt_map else Adw.ActionRow()
                    row.set_title(name)
                    row.set_subtitle(f"type: {rtype}")
                    if name in crypt_map:
                        crypt_name = crypt_map[name]
                        sub = Adw.ActionRow()
                        sub.set_title(f"Encriptado ({crypt_name})")
                        sub.set_subtitle(_("type: crypt"))
                        lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
                        sub.add_prefix(lock)
                        edit_crypt = Gtk.Button(icon_name="document-edit-symbolic")
                        edit_crypt.add_css_class("flat")
                        edit_crypt.connect("clicked", lambda _b, n=crypt_name: self._edit_remote(n))
                        sub.add_suffix(edit_crypt)
                        row.add_row(sub)
                row._remote = name
                # action buttons
                edit_btn = Gtk.Button(icon_name="document-edit-symbolic")
                edit_btn.add_css_class("flat")
                edit_btn.set_tooltip_text("Editar")
                edit_btn.connect("clicked", lambda _b, n=name: self._edit_remote(n))
                row.add_suffix(edit_btn)

                del_btn = Gtk.Button(icon_name="user-trash-symbolic")
                del_btn.add_css_class("flat")
                del_btn.set_tooltip_text("Eliminar")
                del_btn.connect("clicked", lambda _b, n=name: self._delete_remote(n))
                row.add_suffix(del_btn)

                self.accounts_list.append(row)

        def err(exc):
            from ...services import profile_store

            if (
                profile_store.is_encrypted(self.profile)
                and profile_store.get_cached_password(self.profile) is None
            ):
                self.window.ask_profile_password(self.profile, lambda _p: self._load_accounts())
            else:
                self.window.toast(_("Error: {exc}").format(exc=exc))

        run_async(fetch(), on_success=ok, on_error=err)

    def _edit_remote(self, name: str) -> None:
        dlg = RemoteDialog(self.window, self.profile, name, on_saved=self._load_accounts)
        dlg.present(self.window)

    def _new_remote(self) -> None:
        dlg = RemoteDialog(self.window, self.profile, None, on_saved=self._load_accounts)
        dlg.present(self.window)

    def _mount_remote(self, name: str) -> None:
        mp = mount_manager.default_mountpoint(self.profile, name)

        async def do():
            await mount_manager.mount(self.profile, name, mp)
            return mp

        def ok(mp):
            self.window.toast(f"Montado en {mp}")
            try:
                mount_manager.open_in_file_manager(mp)
            except Exception as exc:
                self.window.toast(f"Error abriendo: {exc}")

        def err(exc):
            self.window.toast(f"Error montando '{name}': {exc}")

        run_async(do(), on_success=ok, on_error=err)

    def _delete_remote(self, name: str) -> None:
        dlg = Adw.AlertDialog.new("Eliminar remoto", f"¿Eliminar '{name}'?")
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("delete", "Eliminar")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")

        def on_resp(d, resp):
            if resp == "delete":

                async def do():
                    await rclone.delete_remote(self.profile, name)

                def ok(_result):
                    self.window.toast(f"Eliminado {name}")
                    self._load_accounts()

                def err(exc):
                    self.window.toast(_("Error: {exc}").format(exc=exc))

                run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_resp)
        dlg.present(self.window)

    # ---------- VFS / Cache ----------
    def _build_vfs_form(self) -> None:
        group = Adw.PreferencesGroup(title="Opciones de mount (VFS)")
        vfs_scrolled = Gtk.ScrolledWindow(vexpand=True)
        vfs_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        vfs_scrolled.set_max_content_height(400)
        vfs_scrolled.set_propagate_natural_height(True)
        vfs_scrolled.set_child(group)
        self.vfs_box.append(vfs_scrolled)

        self._applying_preset = False

        self.preset_row = Adw.ComboRow()
        self.preset_row.set_title(_("Preset de cache"))
        preset_model = Gtk.StringList.new(list(VFS_PRESETS.keys()))
        self.preset_row.set_model(preset_model)
        self.preset_row.set_selected(2)  # Medio
        group.add(self.preset_row)

        self.cache_mode_row = Adw.ComboRow()
        self.cache_mode_row.set_title(_("VFS cache mode"))
        model = Gtk.StringList.new(VFS_CACHE_MODES)
        self.cache_mode_row.set_model(model)
        group.add(self.cache_mode_row)

        def make_scale_row(
            title: str, minv: float, maxv: float, step: float, marks: list[tuple[float, str]]
        ) -> tuple[Adw.ActionRow, Gtk.Scale]:
            row = Adw.ActionRow()
            row.set_title(title)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minv, maxv, step)
            scale.set_draw_value(True)
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            scale.set_digits(0)
            scale.set_hexpand(False)
            scale.set_halign(Gtk.Align.CENTER)
            scale.set_size_request(560, -1)
            scale.set_margin_start(12)
            scale.set_margin_end(12)
            scale.set_margin_top(6)
            scale.set_margin_bottom(12)
            for value, label in marks:
                scale.add_mark(value, Gtk.PositionType.BOTTOM, label)
            row.add_suffix(scale)
            group.add(row)
            return row, scale

        self.cache_max_size_row, self.cache_max_size_scale = make_scale_row(
            "Cache max size (MB)",
            128,
            8192,
            128,
            [(512, "512"), (1024, "1G"), (4096, "4G")],
        )

        self.cache_max_age_row, self.cache_max_age_scale = make_scale_row(
            "Cache max age (s)",
            60,
            7200,
            60,
            [(300, "5m"), (3600, "1h")],
        )

        self.read_chunk_row, self.read_chunk_scale = make_scale_row(
            "Read chunk size (MB)",
            4,
            256,
            4,
            [(16, "16"), (64, "64"), (128, "128")],
        )

        self.buffer_row, self.buffer_scale = make_scale_row(
            "Buffer size (MB)",
            4,
            128,
            4,
            [(16, "16"), (64, "64")],
        )

        self.write_back_row, self.write_back_scale = make_scale_row(
            "Write back (s)",
            0,
            60,
            1,
            [(0, "0"), (5, "5"), (60, "60")],
        )

        self.dir_cache_row, self.dir_cache_scale = make_scale_row(
            "Dir cache time (s)",
            60,
            3600,
            60,
            [(60, "1m"), (300, "5m"), (1800, "30m")],
        )

        self.poll_row, self.poll_scale = make_scale_row(
            "Poll interval (s)",
            15,
            300,
            15,
            [(15, "15"), (60, "60"), (300, "5m")],
        )

        self.umask_row = Adw.EntryRow()
        self.umask_row.set_title(_("Umask (octal)"))
        self.umask_row.set_input_purpose(Gtk.InputPurpose.NUMBER)
        self.umask_row.set_text("022")

        def _validate_umask(entry):
            text = entry.get_text()
            cleaned = "".join(ch for ch in text if ch.isdigit())
            if cleaned != text:
                entry.set_text(cleaned)

        self.umask_row.connect("changed", _validate_umask)
        group.add(self.umask_row)

        # Mount options (Fase A) mixed into the VFS group
        self.read_only_row = Adw.SwitchRow()
        self.read_only_row.set_title(_("Solo lectura"))
        self.read_only_row.set_subtitle(_("Monta el remoto en modo read-only"))
        group.add(self.read_only_row)

        self.allow_other_row = Adw.SwitchRow()
        self.allow_other_row.set_title(_("Permitir otros usuarios"))
        self.allow_other_row.set_subtitle(_("Requiere user_allow_other en /etc/fuse.conf"))
        group.add(self.allow_other_row)

        self.network_mode_row = Adw.SwitchRow()
        self.network_mode_row.set_title(_("Modo red"))
        self.network_mode_row.set_subtitle(_("Marca el mount como unidad de red"))
        group.add(self.network_mode_row)

        self.attr_timeout_row = Adw.SpinRow.new_with_range(0, 60, 1)
        self.attr_timeout_row.set_title(_("Attr timeout (s)"))
        self.attr_timeout_row.set_subtitle(_("Cache de atributos (0 = sin cache)"))
        self.attr_timeout_row.set_value(1)
        group.add(self.attr_timeout_row)

        self.vfs_read_ahead_row = Adw.SpinRow.new_with_range(0, 256, 1)
        self.vfs_read_ahead_row.set_title(_("VFS read-ahead (MB)"))
        self.vfs_read_ahead_row.set_subtitle(_("Prelectura de archivos"))
        self.vfs_read_ahead_row.set_value(0)
        group.add(self.vfs_read_ahead_row)

        self.vfs_fast_fingerprint_row = Adw.SwitchRow()
        self.vfs_fast_fingerprint_row.set_title(_("Fast fingerprint"))
        self.vfs_fast_fingerprint_row.set_subtitle(_("Usa size+modtime en vez de hash"))
        group.add(self.vfs_fast_fingerprint_row)

        # Connect preset handling
        self.preset_row.connect("notify::selected", lambda *_: self._apply_preset())

        def _mark_custom(*_args):
            if self._applying_preset:
                return
            self.preset_row.set_selected(0)

        self.cache_mode_row.connect("notify::selected", _mark_custom)
        for scale in (
            self.cache_max_size_scale,
            self.cache_max_age_scale,
            self.read_chunk_scale,
            self.buffer_scale,
            self.write_back_scale,
            self.dir_cache_scale,
            self.poll_scale,
        ):
            scale.connect("value-changed", _mark_custom)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_margin_top(8)
        save_btn = Gtk.Button(label=_("Guardar"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda _b: self._save_vfs())
        btn_box.append(save_btn)
        reset_btn = Gtk.Button(label=_("Restaurar defaults"))
        reset_btn.connect("clicked", lambda _b: self._reset_vfs())
        btn_box.append(reset_btn)
        self.vfs_box.append(btn_box)

    @staticmethod
    def _size_to_mb(value: str, default: int = 1024) -> int:
        value = (value or "").strip().upper()
        if not value:
            return default
        if value.endswith("G"):
            try:
                return int(float(value[:-1]) * 1024)
            except ValueError:
                return default
        if value.endswith("M"):
            try:
                return int(float(value[:-1]))
            except ValueError:
                return default
        if value.endswith("K"):
            try:
                return max(1, int(float(value[:-1]) / 1024))
            except ValueError:
                return default
        try:
            return int(float(value))
        except ValueError:
            return default

    @staticmethod
    def _time_to_seconds(value: str, default: int = 60) -> int:
        import re

        value = (value or "").strip()
        if not value:
            return default
        total = 0
        for num, unit in re.findall(r"(\\d+)([HMS])", value.upper()):
            n = int(num)
            if unit == "H":
                total += n * 3600
            elif unit == "M":
                total += n * 60
            elif unit == "S":
                total += n
        if total == 0:
            try:
                total = int(float(value))
            except ValueError:
                return default
        return total

    def _apply_preset(self) -> None:
        item = self.preset_row.get_selected_item()
        name = item.get_string() if item is not None else "Personalizado"
        preset = VFS_PRESETS.get(name)
        if not preset:
            return
        self._applying_preset = True
        self.cache_mode_row.set_selected(VFS_CACHE_MODES.index(str(preset["cache_mode"])))
        self.cache_max_size_scale.set_value(preset["cache_max_size"])
        self.cache_max_age_scale.set_value(preset["cache_max_age"])
        self.read_chunk_scale.set_value(preset["read_chunk_size"])
        self.buffer_scale.set_value(preset["buffer_size"])
        self.write_back_scale.set_value(preset["write_back"])
        self.dir_cache_scale.set_value(preset["dir_cache_time"])
        self.poll_scale.set_value(preset["poll_interval"])
        self._applying_preset = False

    def _load_vfs(self) -> None:
        meta = profile_store.load_meta(self.profile)
        vfs = meta.get("vfs", {}) if isinstance(meta, dict) else {}
        # cache mode
        cm = vfs.get("cache_mode", "writes")
        idx = VFS_CACHE_MODES.index(cm) if cm in VFS_CACHE_MODES else 2
        self.cache_mode_row.set_selected(idx)
        self.cache_max_size_scale.set_value(self._size_to_mb(vfs.get("cache_max_size", "1G"), 1024))
        self.cache_max_age_scale.set_value(
            self._time_to_seconds(vfs.get("cache_max_age", "1h0m0s"), 3600)
        )
        self.read_chunk_scale.set_value(self._size_to_mb(vfs.get("read_chunk_size", "128M"), 128))
        self.buffer_scale.set_value(self._size_to_mb(vfs.get("buffer_size", "16M"), 16))
        self.write_back_scale.set_value(self._time_to_seconds(vfs.get("write_back", "5s"), 5))
        self.dir_cache_scale.set_value(
            self._time_to_seconds(vfs.get("dir_cache_time", "5m0s"), 300)
        )
        self.poll_scale.set_value(self._time_to_seconds(vfs.get("poll_interval", "1m0s"), 60))
        umask_str = str(vfs.get("umask", "022"))

        self._applying_preset = True
        preset_name = vfs.get("preset", "Personalizado")
        if preset_name in VFS_PRESETS:
            self.preset_row.set_selected(list(VFS_PRESETS.keys()).index(preset_name))
        self._applying_preset = False
        self.umask_row.set_text(umask_str if umask_str else "022")

        self.read_only_row.set_active(bool(vfs.get("read_only", False)))
        self.allow_other_row.set_active(bool(vfs.get("allow_other", False)))
        self.network_mode_row.set_active(bool(vfs.get("network_mode", False)))
        self.attr_timeout_row.set_value(float(vfs.get("attr_timeout", 1)))
        self.vfs_read_ahead_row.set_value(float(vfs.get("vfs_read_ahead", 0)))
        self.vfs_fast_fingerprint_row.set_active(bool(vfs.get("vfs_fast_fingerprint", False)))

    def _save_vfs(self) -> None:
        meta = profile_store.load_meta(self.profile)
        meta["vfs"] = {
            "preset": self.preset_row.get_selected_item().get_string()
            if self.preset_row.get_selected_item()
            else "Personalizado",
            "cache_mode": VFS_CACHE_MODES[self.cache_mode_row.get_selected()],
            "cache_max_size": f"{int(self.cache_max_size_scale.get_value())}M",
            "cache_max_age": f"{int(self.cache_max_age_scale.get_value())}s",
            "read_chunk_size": f"{int(self.read_chunk_scale.get_value())}M",
            "buffer_size": f"{int(self.buffer_scale.get_value())}M",
            "write_back": f"{int(self.write_back_scale.get_value())}s",
            "dir_cache_time": f"{int(self.dir_cache_scale.get_value())}s",
            "poll_interval": f"{int(self.poll_scale.get_value())}s",
            "umask": (self.umask_row.get_text().strip() or "022"),
            "read_only": bool(self.read_only_row.get_active()),
            "allow_other": bool(self.allow_other_row.get_active()),
            "network_mode": bool(self.network_mode_row.get_active()),
            "attr_timeout": int(self.attr_timeout_row.get_value()),
            "vfs_read_ahead": f"{int(self.vfs_read_ahead_row.get_value())}M",
            "vfs_fast_fingerprint": bool(self.vfs_fast_fingerprint_row.get_active()),
        }
        profile_store.save_meta(self.profile, meta)
        self.window.toast(_("Opciones VFS guardadas"))
        self.close()

    def _reset_vfs(self) -> None:
        defaults = {
            "preset": "Medio",
            "cache_mode": "writes",
            "cache_max_size": "1G",
            "cache_max_age": "1h0m0s",
            "read_chunk_size": "128M",
            "buffer_size": "16M",
            "write_back": "5s",
            "dir_cache_time": "5m0s",
            "poll_interval": "1m0s",
            "umask": "022",
            "read_only": False,
            "allow_other": False,
            "network_mode": False,
            "attr_timeout": 1,
            "vfs_read_ahead": "0M",
            "vfs_fast_fingerprint": False,
        }
        meta = profile_store.load_meta(self.profile)
        meta["vfs"] = defaults
        profile_store.save_meta(self.profile, meta)
        self._load_vfs()
        self.window.toast(_("Valores por defecto restaurados"))
