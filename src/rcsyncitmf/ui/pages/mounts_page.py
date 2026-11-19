"""Page managing rclone mounts (card-based)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import contextlib
from pathlib import Path

from gi.repository import Adw, Gdk, Gtk, Pango

from ...i18n import _
from ...services import mount_manager
from ...ui.async_helper import run_async


class MountsPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.profile: Path | None = None
        self._crypt_parents: dict[str, str | None] = {}
        self.set_spacing(0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_top(12)
        header.set_margin_bottom(6)
        header.set_margin_start(12)
        header.set_margin_end(12)

        title = Gtk.Label(label=_("Mounts"), xalign=0)
        title.add_css_class("title-2")
        header.append(title)

        self.base_label = Gtk.Label(xalign=0)
        self.base_label.add_css_class("dim-label")
        self.base_label.add_css_class("caption")
        try:
            self.base_label.set_text(_("Base: {p}").format(p=mount_manager.default_mounts_base()))
        except Exception:
            self.base_label.set_text("")
        header.append(self.base_label)

        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        self.btn_refresh = Gtk.Button(label=_("Actualizar"))
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())
        header.append(self.btn_refresh)

        clean_btn = Gtk.Button(label=_("Limpiar carpetas vacías"))
        clean_btn.connect("clicked", lambda _b: self._clean_empty_dirs())
        header.append(clean_btn)

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
        cached_sync = mount_manager.list_cached_remotes()

        async def fetch_hidden():
            hidden = await mount_manager.async_crypt_parents_with_cache(cached_sync)
            cmap = await mount_manager.async_crypt_parent_map()
            return hidden, cmap

        def render(cached):
            while (child := self.cards_box.get_first_child()) is not None:
                self.cards_box.remove(child)

            persisted_remotes = {m.get("remote") for m in mounts}

            if not mounts and not cached:
                empty = Adw.StatusPage(
                    title=_("Sin mounts"),
                    description=_(
                        "Monta un remoto desde Remotos o Unions; aquí solo se desmontan."
                    ),
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

        def on_hidden(result):
            hidden, cmap = result if isinstance(result, tuple) else (result, {})
            self._crypt_parents = cmap or {}
            try:
                cached = [r for r in cached_sync if r not in hidden and mount_manager.has_cache(r)]
            except Exception:
                cached = [r for r in cached_sync if mount_manager.has_cache(r)]
            render(cached)

        def on_error(_exc):
            self._crypt_parents = {}
            render([r for r in cached_sync if mount_manager.has_cache(r)])

        from ...ui.async_helper import run_async

        run_async(fetch_hidden(), on_success=on_hidden, on_error=on_error)

    def _clean_empty_dirs(self) -> None:
        try:
            n = mount_manager.cleanup_empty_mount_dirs()
            self.window.toast(_("Carpetas vacías eliminadas: {n}").format(n=n))
        except Exception as exc:
            self.window.toast(_("Error: {exc}").format(exc=exc))
        self.refresh()

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
        parent = (
            self._crypt_parents.get(remote)
            if hasattr(self, "_crypt_parents")
            else mount_manager.crypt_parent(remote)
        )
        if parent:
            crypt_label = Gtk.Label(label=_("crypt sobre {parent}").format(parent=parent), xalign=0)
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
            _("montado") if mounted else (_("desmontado (cache)") if has_cache else _("desmontado"))
        )
        status = Gtk.Label(label=status_text)
        status.add_css_class("dim-label")
        top.append(status)

        box.append(top)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_row.set_halign(Gtk.Align.END)

        if mounted:
            btn = Gtk.Button(label=_("Desmontar"))
            btn.add_css_class("destructive-action")
            btn.add_css_class("compact-btn")
            btn.connect("clicked", lambda _b, mm=m: self._unmount(mm))
            btn_row.append(btn)

            open_btn = Gtk.Button(icon_name="folder-open-symbolic")
            open_btn.set_tooltip_text(_("Abrir en explorador"))
            open_btn.add_css_class("compact-btn")
            open_btn.connect("clicked", lambda _b, mm=m: self._open(mm))
            btn_row.append(open_btn)
        logs_btn = Gtk.Button(icon_name="utilities-terminal-symbolic")
        logs_btn.set_tooltip_text(_("Ver logs del mount"))
        logs_btn.add_css_class("compact-btn")
        logs_btn.connect("clicked", lambda _b, mm=m: self._show_logs(mm))
        btn_row.append(logs_btn)

        if has_cache:
            cache_btn = Gtk.Button(icon_name="user-trash-symbolic")
            cache_btn.set_tooltip_text(_("Limpiar cache"))
            cache_btn.add_css_class("compact-btn")
            cache_btn.connect("clicked", lambda _b, r=remote: self._clear_cache(r))
            btn_row.append(cache_btn)

        box.append(btn_row)
        frame.set_child(box)
        self.cards_box.append(frame)

    def _show_logs(self, m: dict) -> None:
        text = mount_manager.read_mount_log(m)

        dlg = Adw.AlertDialog.new(_("Logs del mount"), "")
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.get_buffer().set_text(text)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(320)
        scrolled.set_min_content_width(640)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(view)
        outer.append(scrolled)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_row.set_halign(Gtk.Align.END)

        def _refresh(_b):
            new_text = mount_manager.read_mount_log(m)
            view.get_buffer().set_text(new_text)

        def _copy_all(_b):
            buf = view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            Gdk.Display.get_default().get_clipboard().set_text(text)

        def _copy_selection(_b):
            buf = view.get_buffer()
            if buf.get_has_selection():
                start, end = buf.get_selection_bounds()
                text = buf.get_text(start, end, False)
                Gdk.Display.get_default().get_clipboard().set_text(text)

        copy_all_btn = Gtk.Button(label=_("Copiar todo"))
        copy_all_btn.connect("clicked", _copy_all)
        btn_row.append(copy_all_btn)

        copy_sel_btn = Gtk.Button(label=_("Copiar selección"))
        copy_sel_btn.connect("clicked", _copy_selection)
        btn_row.append(copy_sel_btn)

        refresh_btn = Gtk.Button(label=_("Actualizar"))
        refresh_btn.connect("clicked", _refresh)
        btn_row.append(refresh_btn)
        outer.append(btn_row)

        dlg.set_extra_child(outer)
        dlg.add_response("close", _("Cerrar"))
        dlg.set_default_response("close")
        dlg.set_close_response("close")
        dlg.present(self.window)

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
        parent = (
            self._crypt_parents.get(remote)
            if hasattr(self, "_crypt_parents")
            else mount_manager.crypt_parent(remote)
        )
        if parent:
            crypt_label = Gtk.Label(label=_("crypt sobre {parent}").format(parent=parent), xalign=0)
            crypt_label.add_css_class("dim-label")
            crypt_label.add_css_class("caption")
            info.append(crypt_label)
        path_label = Gtk.Label(label=_("cache residual"), xalign=0)
        path_label.add_css_class("dim-label")
        path_label.add_css_class("caption")
        info.append(path_label)
        top.append(info)

        status = Gtk.Label(label=_("desmontado (cache)"))
        status.add_css_class("dim-label")
        top.append(status)

        box.append(top)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_row.set_halign(Gtk.Align.END)

        cache_btn = Gtk.Button(icon_name="user-trash-symbolic")
        cache_btn.set_tooltip_text(_("Limpiar cache"))
        cache_btn.add_css_class("compact-btn")
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
            self.window.toast(_("Registro de mount inválido"))
            return
        mp = Path(mp_raw)

        async def do():
            await mount_manager.unmount(mp)

        def ok(_result):
            self.window.toast(_("Desmontado"))
            self.refresh()
            with contextlib.suppress(Exception):
                self.window.unions_page.refresh()

        def err(exc):
            self.window.toast(_("Error: {exc}").format(exc=exc))

        run_async(do(), on_success=ok, on_error=err)

    def _clear_cache(self, remote: str) -> None:
        async def do():
            await mount_manager.clear_vfs_cache(remote)

        def ok(_result):
            self.window.toast(_("Cache de {r} limpiado").format(r=remote))
            self.refresh()

        def err(exc):
            self.window.toast(_("Error limpiando cache: {exc}").format(exc=exc))

        run_async(do(), on_success=ok, on_error=err)
