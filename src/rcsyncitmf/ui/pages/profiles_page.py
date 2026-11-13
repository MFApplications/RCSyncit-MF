"""Page listing rclone config profiles (.conf files)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from pathlib import Path

from gi.repository import Adw, Gtk

from ...services import profile_store
from ...ui.async_helper import run_async


class ProfilesPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.set_spacing(0)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Header with actions
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_top(12)
        header.set_margin_bottom(6)
        header.set_margin_start(12)
        header.set_margin_end(12)

        title = Gtk.Label(label="Perfiles", xalign=0)
        title.add_css_class("title-2")
        header.append(title)

        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        self.btn_new = Gtk.Button(label="Nuevo perfil")
        self.btn_new.add_css_class("suggested-action")
        self.btn_new.connect("clicked", self._on_new)
        header.append(self.btn_new)

        self.btn_import = Gtk.Button(label="Importar")
        self.btn_import.connect("clicked", self._on_import)
        header.append(self.btn_import)

        # (delete button moved to bottom bar)

        header.set_visible(False)
        self.append(header)

        # List
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.set_activate_on_single_click(False)
        self.list_box.connect("row-selected", self._on_row_selected)
        self.list_box.connect("row-activated", self._on_row_activated)
        self.list_box.add_css_class("boxed-list")
        scrolled.set_child(self.list_box)
        self.append(scrolled)

        # Bottom action bar (visible, bottom-right)
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bottom.set_margin_top(6)
        bottom.set_margin_bottom(6)
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        spacer = Gtk.Box(hexpand=True)
        bottom.append(spacer)
        btn_new = Gtk.Button(label="Nuevo perfil")
        btn_new.add_css_class("suggested-action")
        btn_new.connect("clicked", self._on_new)
        bottom.append(btn_new)

        self.btn_delete = Gtk.Button(label="Eliminar perfil")
        self.btn_delete.add_css_class("destructive-action")
        self.btn_delete.connect("clicked", self._on_delete)
        self.btn_delete.set_sensitive(False)
        bottom.append(self.btn_delete)
        self.append(bottom)

        self._rows: dict[Gtk.ListBoxRow, Path] = {}
        self.refresh()

    def refresh(self) -> None:
        # Clear
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)
        self._rows.clear()

        profiles = profile_store.list_profiles()
        if not profiles:
            empty = Adw.StatusPage(
                title="Sin perfiles",
                description="Crea tu primer perfil de rclone (.conf).",
                icon_name="document-new-symbolic",
            )
            btn = Gtk.Button(label="Crear primer perfil")
            btn.add_css_class("suggested-action")
            btn.set_halign(Gtk.Align.CENTER)
            btn.connect("clicked", self._on_new)
            empty.set_child(btn)
            self.list_box.append(empty)
            return

        for path in profiles:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(12)
            row_box.set_margin_end(12)

            enc = profile_store.encrypted_flag(path)
            icon_name = "channel-secure-symbolic" if enc is True else "text-x-generic-symbolic"
            icon = Gtk.Image.new_from_icon_name(icon_name)
            row_box.append(icon)

            label = Gtk.Label(label=path.stem, xalign=0, hexpand=True)
            row_box.append(label)

            sub = Gtk.Label(label=str(path), xalign=0)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            row_box.append(sub)

            row.set_child(row_box)
            self.list_box.append(row)
            self._rows[row] = path

    def _selected_path(self) -> Path | None:
        row = self.list_box.get_selected_row()
        if row is None:
            return None
        return self._rows.get(row)

    def _on_row_activated(self, _lb, row) -> None:
        path = self._rows.get(row) if row is not None else None
        if path is None:
            return
        from ..dialogs.profile_detail import ProfileDetailDialog

        dlg = ProfileDetailDialog(self.window, path)
        dlg.present(self.window)

    def _on_row_selected(self, _lb, row) -> None:
        self.btn_delete.set_sensitive(row is not None and row in self._rows)
        if row is not None and row in self._rows:
            path = self._rows[row]
            self.window.set_current_profile(path)

    def _on_new(self, _btn) -> None:
        dlg = Adw.AlertDialog.new("Nuevo perfil", "")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        entry = Gtk.Entry()
        entry.set_placeholder_text("nombre del perfil")
        box.append(entry)

        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("create", "Crear")
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("create")
        dlg.set_close_response("cancel")

        def on_response(d, response):
            if response == "create":
                name = entry.get_text().strip()
                if name:
                    try:
                        profile_store.create_profile(name)
                        self.window.toast(f"Perfil '{name}' creado")
                    except Exception as exc:
                        self.window.toast(f"Error: {exc}")
                    self.refresh()
            d.close()

        dlg.connect("response", on_response)
        dlg.present(self.window)

    def _on_import(self, _btn) -> None:
        dialog = Gtk.FileDialog(title="Importar perfil rclone")
        dialog.set_filters([Gtk.FileFilter.new()])  # placeholder

        def on_open(d, res):
            try:
                f = d.open_finish(res)
            except Exception:
                return
            if f is None:
                return
            try:
                self.window._import_profile(Path(f.get_path()))
                self.refresh()
            except Exception as exc:
                self.window.toast(f"Error: {exc}")

        dialog.open(self.window, None, on_open)

    def _on_view_config(self, _btn=None) -> None:
        path = self._selected_path()
        if path is None:
            self.window.toast("Selecciona un perfil")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.window.toast(f"Error leyendo: {exc}")
            return
        dlg = Adw.AlertDialog.new(f"Config: {path.name}", "")
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.get_buffer().set_text(text if text.strip() else "(vacío)")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(240)
        scrolled.set_min_content_width(480)
        scrolled.set_child(view)
        dlg.set_extra_child(scrolled)
        dlg.add_response("close", "Cerrar")
        dlg.set_default_response("close")
        dlg.set_close_response("close")
        dlg.present(self.window)

    def _on_inspect(self, _btn=None) -> None:
        path = self._selected_path()
        if path is None:
            self.window.toast("Selecciona un perfil")
            return

        from ...services import rclone

        async def fetch():
            pwd = profile_store.get_cached_password(path)
            return await rclone.config_dump(path, config_password=pwd)

        def on_success(dump):
            lines = []
            if isinstance(dump, dict):
                for name, data in dump.items():
                    lines.append(f"[{name}]")
                    if isinstance(data, dict):
                        for k, v in data.items():
                            lines.append(f"  {k} = {v}")
                    lines.append("")
            if not lines:
                lines = ["(sin remotos)"]
            dlg = Adw.AlertDialog.new(f"Inspector: {path.stem}", "")
            view = Gtk.TextView()
            view.set_editable(False)
            view.set_monospace(True)
            view.get_buffer().set_text("\n".join(lines))
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_min_content_height(240)
            scrolled.set_min_content_width(480)
            scrolled.set_child(view)
            dlg.set_extra_child(scrolled)
            dlg.add_response("close", "Cerrar")
            dlg.set_default_response("close")
            dlg.set_close_response("close")
            dlg.present(self.window)

        def on_error(exc):
            if profile_store.is_encrypted(path) and profile_store.get_cached_password(path) is None:
                self.window.ask_profile_password(path, lambda _p: self._on_inspect(None))
            else:
                self.window.toast(f"Error: {exc}")

        run_async(fetch(), on_success=on_success, on_error=on_error)

    def _on_toggle_encrypt(self, _btn=None) -> None:
        path = self._selected_path()
        if path is None:
            self.window.toast("Selecciona un perfil")
            return
        if profile_store.is_encrypted(path):
            profile_store.clear_cached_password(path)
            self.window.toast(f"{path.stem} marcado como no encriptado")
            self.refresh()
        else:
            self.window.ask_profile_password(path, lambda pwd: self._finish_encrypt(path, pwd))

    def _finish_encrypt(self, path, pwd) -> None:
        from ...services import profile_store

        profile_store.cache_password(path, pwd)
        self.window.toast(f"{path.stem} marcado como encriptado")
        self.refresh()

    def _on_delete(self, _btn) -> None:
        path = self._selected_path()
        if path is None:
            return
        dlg = Adw.AlertDialog.new(
            "Eliminar perfil",
            f"¿Eliminar el perfil '{path.stem}'? El archivo .conf se borrará.",
        )
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("delete", "Eliminar")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")

        def on_response(d, response):
            if response == "delete":
                profile_store.delete_profile(path)
                self.window.toast(f"Perfil '{path.stem}' eliminado")
                if self.window.current_profile == path:
                    self.window.set_current_profile(None)
                self.refresh()
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_response)
        dlg.present(self.window)
