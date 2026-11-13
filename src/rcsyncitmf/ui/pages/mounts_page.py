"""Page managing rclone mounts (card-based)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from pathlib import Path

from gi.repository import Adw, Gtk, Pango

from ...services import mount_manager, profile_store, rclone
from ...ui.async_helper import run_async


class MountsPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.profile: Path | None = None
        self.set_spacing(0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_top(12)
        header.set_margin_bottom(6)
        header.set_margin_start(12)
        header.set_margin_end(12)

        title = Gtk.Label(label="Mounts", xalign=0)
        title.add_css_class("title-2")
        header.append(title)

        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        self.btn_new = Gtk.Button(label="Nuevo mount")
        self.btn_new.add_css_class("suggested-action")
        self.btn_new.connect("clicked", self._on_new)
        header.append(self.btn_new)

        self.btn_refresh = Gtk.Button(label="Actualizar")
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())
        header.append(self.btn_refresh)

        self.append(header)

        self.cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.cards_box.set_margin_top(12)
        self.cards_box.set_margin_start(12)
        self.cards_box.set_margin_end(12)
        self.cards_box.set_margin_bottom(12)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.cards_box)
        self.append(scrolled)

        self.refresh()

    def set_profile(self, profile: Path | None) -> None:
        self.profile = profile

    def refresh(self) -> None:
        mounts = [
            m for m in mount_manager.list_mounts() if isinstance(m, dict) and m.get("mountpoint")
        ]
        # Optionally filter by selected profile.
        if self.profile is not None:
            mounts = [m for m in mounts if m.get("config") == str(self.profile)]
        try:
            cached = mount_manager.list_cached_remotes()
            hidden = mount_manager.crypt_parents_with_cache(cached)
            cached = [r for r in cached if r not in hidden]
        except Exception:
            cached = []
            hidden = set()

        while (child := self.cards_box.get_first_child()) is not None:
            self.cards_box.remove(child)

        persisted_remotes = {m.get("remote") for m in mounts}

        if not mounts and not cached:
            empty = Adw.StatusPage(
                title="Sin mounts",
                description="Monta un remoto con el botón 'Nuevo mount'.",
                icon_name="drive-harddisk-symbolic",
            )
            self.cards_box.append(empty)
            return

        for m in mounts:
            try:
                self._add_mount_card(m)
            except Exception:
                continue

        # Cache residual without a persisted mount
        for remote in cached:
            if remote in persisted_remotes:
                continue
            try:
                self._add_cache_card(remote)
            except Exception:
                continue

    def _add_mount_card(self, m: dict) -> None:
        mp_raw = m.get("mountpoint")
        if not mp_raw:
            return
        mp = Path(mp_raw)
        mounted = mount_manager.is_mounted(mp)
        remote = m.get("remote", "?")
        try:
            has_cache = mount_manager.has_cache(remote) if remote != "?" else False
        except Exception:
            has_cache = False

        frame = Gtk.Frame()
        frame.add_css_class("card")
        frame.set_margin_bottom(6)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if not mounted:
            top.set_opacity(0.5)
        icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        top.append(icon)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        name_label = Gtk.Label(label=remote, xalign=0)
        name_label.add_css_class("heading")
        info.append(name_label)
        parent = mount_manager.crypt_parent(remote)
        if parent:
            crypt_label = Gtk.Label(label=f"(crypt sobre {parent})", xalign=0)
            crypt_label.add_css_class("dim-label")
            crypt_label.add_css_class("caption")
            info.append(crypt_label)
        path_label = Gtk.Label(label=str(mp), xalign=0)
        path_label.add_css_class("dim-label")
        path_label.add_css_class("caption")
        path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        info.append(path_label)
        top.append(info)

        status_text = (
            "montado" if mounted else ("desmontado (cache)" if has_cache else "desmontado")
        )
        status = Gtk.Label(label=status_text)
        status.add_css_class("dim-label")
        top.append(status)

        box.append(top)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_row.set_halign(Gtk.Align.END)

        if mounted:
            btn = Gtk.Button(label="Desmontar")
            btn.add_css_class("destructive-action")
            btn.connect("clicked", lambda _b, mm=m: self._unmount(mm))
            btn_row.append(btn)

            open_btn = Gtk.Button(icon_name="folder-open-symbolic")
            open_btn.set_tooltip_text("Abrir en explorador")
            open_btn.connect("clicked", lambda _b, mm=m: self._open(mm))
            btn_row.append(open_btn)
        else:
            btn = Gtk.Button(label="Montar")
            btn.add_css_class("suggested-action")
            btn.connect("clicked", lambda _b, mm=m: self._mount(mm))
            btn_row.append(btn)

        if has_cache:
            cache_btn = Gtk.Button(icon_name="user-trash-symbolic")
            cache_btn.set_tooltip_text("Limpiar cache")
            cache_btn.connect("clicked", lambda _b, r=remote: self._clear_cache(r))
            btn_row.append(cache_btn)

        box.append(btn_row)
        frame.set_child(box)
        self.cards_box.append(frame)

    def _add_cache_card(self, remote: str) -> None:
        frame = Gtk.Frame()
        frame.add_css_class("card")
        frame.set_margin_bottom(6)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_opacity(0.5)
        icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        top.append(icon)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        name_label = Gtk.Label(label=f"{remote} (cache)", xalign=0)
        name_label.add_css_class("heading")
        info.append(name_label)
        parent = mount_manager.crypt_parent(remote)
        if parent:
            crypt_label = Gtk.Label(label=f"(crypt sobre {parent})", xalign=0)
            crypt_label.add_css_class("dim-label")
            crypt_label.add_css_class("caption")
            info.append(crypt_label)
        path_label = Gtk.Label(label="cache residual", xalign=0)
        path_label.add_css_class("dim-label")
        path_label.add_css_class("caption")
        info.append(path_label)
        top.append(info)

        status = Gtk.Label(label="desmontado (cache)")
        status.add_css_class("dim-label")
        top.append(status)

        box.append(top)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_row.set_halign(Gtk.Align.END)

        cache_btn = Gtk.Button(icon_name="user-trash-symbolic")
        cache_btn.set_tooltip_text("Limpiar cache")
        cache_btn.connect("clicked", lambda _b, r=remote: self._clear_cache(r))
        btn_row.append(cache_btn)

        box.append(btn_row)
        frame.set_child(box)
        self.cards_box.append(frame)

    def _open(self, m: dict) -> None:
        mp = Path(m["mountpoint"])
        try:
            mount_manager.open_in_file_manager(mp)
        except Exception as exc:
            self.window.toast(f"Error abriendo: {exc}")

    def _unmount(self, m: dict) -> None:
        mp_raw = m.get("mountpoint")
        if not mp_raw:
            self.window.toast("Registro de mount inválido")
            return
        mp = Path(mp_raw)

        async def do():
            await mount_manager.unmount(mp)

        def ok(_):
            self.window.toast("Desmontado")
            self.refresh()

        def err(exc):
            self.window.toast(f"Error: {exc}")

        run_async(do(), on_success=ok, on_error=err)

    def _mount(self, m: dict) -> None:
        mp = Path(m.get("mountpoint", ""))
        cfg = Path(m.get("config", ""))
        remote = m.get("remote", "")
        if not (mp and cfg and remote):
            self.window.toast("Registro de mount inválido")
            return

        async def do():
            await mount_manager.mount(cfg, remote, mp)

        def ok(_):
            self.window.toast("Montado")
            self.refresh()

        def err(exc):
            self.window.toast(f"Error: {exc}")

        run_async(do(), on_success=ok, on_error=err)

    def _clear_cache(self, remote: str) -> None:
        async def do():
            await mount_manager.clear_vfs_cache(remote)

        def ok(_):
            self.window.toast(f"Cache de {remote} limpiado")
            self.refresh()

        def err(exc):
            self.window.toast(f"Error limpiando cache: {exc}")

        run_async(do(), on_success=ok, on_error=err)

    def _on_new(self, _btn) -> None:
        dlg = Adw.AlertDialog.new("Nuevo mount", "")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        prof_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prof_row.append(Gtk.Label(label="Perfil", xalign=0))
        prof_combo = Gtk.ComboBoxText()
        profiles = profile_store.list_profiles()
        for p in profiles:
            prof_combo.append_text(p.stem)
        if profiles:
            prof_combo.set_active(0)
        prof_combo.set_hexpand(True)
        prof_row.append(prof_combo)
        box.append(prof_row)

        remote_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        remote_row.append(Gtk.Label(label="Remoto", xalign=0))
        remote_combo = Gtk.ComboBoxText()
        remote_combo.set_hexpand(True)
        remote_row.append(remote_combo)
        box.append(remote_row)

        mp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        mp_row.append(Gtk.Label(label="Mountpoint", xalign=0))
        mp_entry = Gtk.Entry()
        mp_entry.set_hexpand(True)
        mp_row.append(mp_entry)
        box.append(mp_row)

        def load_remotes(*_):
            remote_combo.remove_all()
            idx = prof_combo.get_active()
            if idx < 0 or idx >= len(profiles):
                return
            prof = profiles[idx]

            async def fetch():
                return await rclone.list_remotes(prof)

            def on_success(names):
                for n in names:
                    remote_combo.append_text(n)
                if names:
                    remote_combo.set_active(0)
                    suggest()

            def on_error(exc):
                self.window.toast(f"Error: {exc}")

            run_async(fetch(), on_success=on_success, on_error=on_error)

        def suggest(*_):
            idx = prof_combo.get_active()
            if idx < 0 or idx >= len(profiles):
                return
            prof = profiles[idx]
            remote = remote_combo.get_active_text()
            if not remote:
                return
            mp = mount_manager.default_mountpoint(prof, remote)
            if not mp_entry.get_text().strip():
                mp_entry.set_text(str(mp))

        prof_combo.connect("changed", load_remotes)
        remote_combo.connect("changed", suggest)
        if self.profile is not None:
            for i, p in enumerate(profiles):
                if p == self.profile:
                    prof_combo.set_active(i)
                    break
        if prof_combo.get_active() < 0 and profiles:
            prof_combo.set_active(0)
        load_remotes()

        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("mount", "Montar")
        dlg.set_response_appearance("mount", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("mount")
        dlg.set_close_response("cancel")

        def on_response(d, response):
            if response != "mount":
                d.close() if hasattr(d, "close") else None
                return
            idx = prof_combo.get_active()
            if idx < 0 or idx >= len(profiles):
                self.window.toast("Selecciona un perfil")
                return
            prof = profiles[idx]
            remote = remote_combo.get_active_text()
            if not remote:
                self.window.toast("Selecciona un remoto")
                return
            mp_text = mp_entry.get_text().strip()
            if not mp_text:
                self.window.toast("Indica un mountpoint")
                return
            mp = Path(mp_text).expanduser()

            async def do():
                await mount_manager.mount(prof, remote, mp)

            def ok(_):
                self.window.toast(f"Montado {remote} en {mp}")
                self.refresh()
                d.close() if hasattr(d, "close") else None

            def err(exc):
                self.window.toast(f"Error: {exc}")

            run_async(do(), on_success=ok, on_error=err)

        dlg.connect("response", on_response)
        dlg.present(self.window)
