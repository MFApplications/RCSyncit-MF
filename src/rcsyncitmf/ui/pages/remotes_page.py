"""Page listing profiles and their remotes (mount-only)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from pathlib import Path

from gi.repository import Adw, Gtk

from ...services import mount_manager, profile_store, rclone
from ...ui.async_helper import run_async


class RemotesPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.profile: Path | None = None
        self.set_spacing(0)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_bottom(6)

        title = Gtk.Label(label="Remotos", xalign=0)
        title.add_css_class("title-2")
        header.append(title)

        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        self.btn_refresh = Gtk.Button(label="Actualizar")
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())
        header.append(self.btn_refresh)

        self.append(header)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.list_box)

        self.status = Adw.StatusPage(
            title="Sin perfiles",
            description="Crea o importa un perfil en la sección Perfiles.",
            icon_name="folder-remote-symbolic",
        )
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(scrolled, "list")
        self.stack.add_named(self.status, "empty")
        self.append(self.stack)
        self.stack.set_visible_child_name("empty")

        self._rows: list = []

    def set_profile(self, profile: Path | None) -> None:
        self.profile = profile
        self.refresh()

    def refresh(self) -> None:
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)
        self._rows.clear()

        profiles = profile_store.list_profiles()
        if not profiles:
            self.status.set_title("Sin perfiles")
            self.status.set_description("Crea o importa un perfil en la sección Perfiles.")
            self.stack.set_visible_child_name("empty")
            return

        self.stack.set_visible_child_name("list")
        for path in profiles:
            self._add_profile_row(path)

    def _add_profile_row(self, path: Path) -> None:
        expander = Adw.ExpanderRow()
        expander.set_title(path.stem)
        expander.set_subtitle(str(path))
        expander._profile = path
        expander._loaded = False
        expander._loading = False

        def on_expanded_notify(obj, _pspec):
            if obj.get_expanded() and not obj._loaded and not obj._loading:
                self._load_remotes_for(obj)

        expander.connect("notify::expanded", on_expanded_notify)
        self.list_box.append(expander)
        self._rows.append(expander)

    def _load_remotes_for(self, expander: Adw.ExpanderRow) -> None:
        expander._loading = True
        profile = expander._profile

        async def fetch():
            from ...services import profile_store

            pwd = profile_store.get_cached_password(profile)
            return await rclone.config_dump(profile, config_password=pwd)

        def ok(dump):
            expander._loading = False
            expander._loaded = True
            if not isinstance(dump, dict) or not dump:
                empty = Adw.ActionRow()
                empty.set_title("Sin remotos")
                empty.set_subtitle("Este perfil no tiene remotos.")
                expander.add_row(empty)
                return
            # crypt map: parent -> crypt name
            crypt_map: dict[str, str] = {}
            for name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "crypt":
                    p = str(data.get("remote", "")).rstrip(":").strip()
                    if p:
                        crypt_map[p] = name

            # hide crypt children (grouped) -> show only non-crypt parents and orphan crypts
            visible = []
            for name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "union":
                    continue
                if isinstance(data, dict) and data.get("type") == "crypt":
                    p = str(data.get("remote", "")).rstrip(":").strip()
                    if p and p in dump:
                        continue
                visible.append(name)
            if not visible:
                empty = Adw.ActionRow()
                empty.set_title("Sin remotos")
                empty.set_subtitle("Este perfil solo tiene unions (ver sección Unions).")
                expander.add_row(empty)
                return
            for name in sorted(visible):
                data = dump.get(name, {})
                rtype = data.get("type", "?") if isinstance(data, dict) else "?"
                mount_name = crypt_map.get(name, name)
                row = Adw.ActionRow()
                row.set_title(name)
                row.set_subtitle(
                    f"type: {rtype}" + (f" (crypt: {crypt_map[name]})" if name in crypt_map else "")
                )
                mp = mount_manager.default_mountpoint(
                    profile, str(mount_name) if mount_name is not None else name
                )
                initially_mounted = mp.exists() and __import__("os").path.ismount(str(mp))
                btn = Gtk.Button(
                    label=(
                        "Desmontar"
                        if initially_mounted
                        else ("Montar (crypt)" if name in crypt_map else "Montar")
                    )
                )
                if initially_mounted:
                    btn.add_css_class("destructive-action")
                else:
                    btn.add_css_class("suggested-action")
                btn.connect(
                    "clicked",
                    lambda _b, p=profile, n=mount_name, b=btn, m=mp: self._toggle_mount(p, n, b, m),
                )
                row.add_suffix(btn)
                expander.add_row(row)

        def err(exc):
            expander._loading = False
            expander._loaded = True
            row = Adw.ActionRow()
            row.set_title("Error")
            row.set_subtitle(str(exc))
            expander.add_row(row)

        run_async(fetch(), on_success=ok, on_error=err)

    def _toggle_mount(self, profile: Path, name: str, btn: Gtk.Button, mp: Path) -> None:
        import os

        mounted = mp.exists() and os.path.ismount(str(mp))
        if not mounted:
            # show loading
            btn.set_sensitive(False)
            prev_label = btn.get_label()
            btn.set_label("Montando...")
            # keep button label; spinner as tooltip not added to avoid layout changes

            async def do_mount():
                await mount_manager.mount(profile, name, mp)
                return mp

            def ok_mount(_mp):
                btn.set_sensitive(True)
                btn.set_label("Desmontar")
                btn.remove_css_class("suggested-action")
                btn.add_css_class("destructive-action")
                self.window.toast(f"Montado en {mp}")
                try:
                    mount_manager.open_in_file_manager(mp)
                except Exception as exc:
                    self.window.toast(f"Error abriendo: {exc}")

            def err_mount(exc):
                btn.set_sensitive(True)
                btn.set_label(prev_label)
                self.window.toast(f"Error montando '{name}': {exc}")

            run_async(do_mount(), on_success=ok_mount, on_error=err_mount)
        else:
            btn.set_sensitive(False)
            btn.set_label("Desmontando...")

            async def do_unmount():
                await mount_manager.unmount(mp)
                return mp

            def ok_unmount(_mp):
                btn.set_sensitive(True)
                btn.set_label("Montar")
                btn.remove_css_class("destructive-action")
                btn.add_css_class("suggested-action")
                self.window.toast(f"Desmontado {name}")

            def err_unmount(exc):
                btn.set_sensitive(True)
                btn.set_label("Desmontar")
                self.window.toast(f"Error desmontando '{name}': {exc}")

            run_async(do_unmount(), on_success=ok_unmount, on_error=err_unmount)
