"""Page listing union remotes and offering folder synchronization."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from pathlib import Path

from gi.repository import Adw, Gtk

from ...config import load_settings
from ...i18n import _
from ...services import mount_manager, profile_store, rclone, sync_state, union_sync
from ...ui.async_helper import run_async
from ...ui.dialogs.union_dialog import UnionDialog


class UnionsPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.profile: Path | None = None
        self.unions: list[dict] = []  # list of {name, upstreams, data}
        self._crypt_map: dict[str, str] = {}
        self.set_spacing(0)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_top(4)
        header.set_margin_bottom(6)
        header.set_margin_start(12)
        header.set_margin_end(12)

        title = Gtk.Label(label=_("Unions"), xalign=0)
        title.add_css_class("title-2")
        header.append(title)

        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        self.btn_new = Gtk.Button(label=_("Nuevo union"))
        self.btn_new.add_css_class("suggested-action")
        self.btn_new.connect("clicked", self._on_new)
        self.btn_new.set_sensitive(False)
        header.append(self.btn_new)

        self.btn_refresh = Gtk.Button(label=_("Actualizar"))
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())
        self.btn_refresh.set_sensitive(False)
        header.append(self.btn_refresh)

        header.set_visible(True)
        self.append(header)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self.list_box)

        self.status = Adw.StatusPage(
            title=_("Sin perfil"),
            description=_("Selecciona un perfil en Perfiles."),
            icon_name="folder-remote-symbolic",
        )

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(scrolled, "list")
        self.stack.add_named(self.status, "empty")
        self.append(self.stack)
        self.stack.set_visible_child_name("empty")

        self._rows: dict[Gtk.ListBoxRow, str] = {}

    def set_profile(self, profile: Path | None) -> None:
        self.profile = profile
        if profile is None:
            self.stack.set_visible_child_name("empty")
            self.status.set_title(_("Sin perfil"))
            self.status.set_description(_("Selecciona un perfil en Perfiles."))
            self.btn_new.set_sensitive(False)
            self.btn_refresh.set_sensitive(False)
            return
        self.btn_new.set_sensitive(True)
        self.btn_refresh.set_sensitive(True)
        self.refresh()

    @property
    def _profile(self) -> Path:
        if self.profile is None:
            raise RuntimeError("no profile selected")
        return self.profile

    def refresh(self) -> None:
        if self.profile is None:
            return
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)
        self._rows.clear()

        async def fetch():
            from ...services import profile_store

            pwd = (
                profile_store.get_cached_password(self._profile)
                if self.profile is not None
                else None
            )
            await union_sync.normalize_union_cache_times(self._profile, config_password=pwd)
            dump = await rclone.config_dump(self._profile, config_password=pwd)
            return dump

        def on_success(dump):
            self.unions = []
            crypt_map: dict[str, str] = {}
            if not isinstance(dump, dict):
                dump = {}
            for name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "crypt":
                    parent = str(data.get("remote", "")).rstrip(":").strip()
                    if parent:
                        crypt_map[parent] = name
            self._crypt_map = crypt_map
            for name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "union":
                    self.unions.append({"name": name, "data": data})
            if not self.unions:
                self.status.set_title(_("Sin unions"))
                self.status.set_description(_("Crea un union con el botón 'Nuevo union'."))
                self.stack.set_visible_child_name("empty")
                return
            self.stack.set_visible_child_name("list")
            for u in self.unions:
                self._add_union_row(u)

        def on_error(exc):
            self.window.toast(_("Error cargando unions: {exc}").format(exc=exc))

        run_async(fetch(), on_success=on_success, on_error=on_error)

    def _add_union_row(self, u: dict) -> None:
        name = u["name"]
        upstreams = u["data"].get("upstreams", "")
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name("folder-remote-symbolic")
        top.append(icon)
        display_name = f"{self.profile.stem}: {name}" if self.profile is not None else name
        label = Gtk.Label(label=display_name, xalign=0, hexpand=True)
        label.add_css_class("heading")
        top.append(label)

        btn_sync = Gtk.Button(label=_("Sincronizar carpetas"))
        btn_sync.connect("clicked", lambda _b, n=name: self._on_sync(n))
        top.append(btn_sync)

        mp = (
            mount_manager.default_mountpoint(self._profile, name)
            if self.profile is not None
            else Path.home() / ".local" / "share" / "rcsyncitmf" / "mnt" / name
        )
        initially_mounted = mount_manager.is_mounted(mp)
        btn_sync.set_sensitive(initially_mounted)
        btn_sync.set_tooltip_text(
            _("Disponible solo cuando el union está montado")
            if not initially_mounted
            else _("Sincronizar estructura de carpetas")
        )
        btn_mount = Gtk.Button(label=(_("Desmontar") if initially_mounted else _("Montar")))
        if initially_mounted:
            btn_mount.add_css_class("destructive-action")
        else:
            btn_mount.add_css_class("suggested-action")
        btn_mount.connect(
            "clicked",
            lambda _b, p=self._profile, n=name, b=btn_mount, m=mp: self._toggle_mount(p, n, b, m),
        )
        top.append(btn_mount)

        btn_del = Gtk.Button(icon_name="user-trash-symbolic")
        btn_del.add_css_class("flat")
        btn_del.connect("clicked", lambda _b, n=name: self._on_delete(n))
        top.append(btn_del)

        box.append(top)

        sub = Gtk.Label(label=_("upstreams: {u}").format(u=upstreams), xalign=0)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        sub.set_wrap(True)
        box.append(sub)

        crypt_name = self._crypt_map.get(name)
        if crypt_name:
            csub = Gtk.Label(label=_("encriptado: {n}").format(n=crypt_name), xalign=0)
            csub.add_css_class("dim-label")
            csub.add_css_class("caption")
            box.append(csub)

        action_policy = u["data"].get("action_policy", "?")
        ap = Gtk.Label(label=_("action_policy: {a}").format(a=action_policy), xalign=0)
        ap.add_css_class("dim-label")
        ap.add_css_class("caption")
        box.append(ap)

        last = sync_state.last_sync(self._profile, name) if self.profile is not None else None
        if last:
            sub2 = Gtk.Label(label=_("última sync: {l}").format(l=last), xalign=0)
            sub2.add_css_class("dim-label")
            sub2.add_css_class("caption")
            box.append(sub2)

        row.set_child(box)
        self.list_box.append(row)
        self._rows[row] = name

    def _on_new(self, _btn) -> None:
        profiles = profile_store.list_profiles()
        selected = self.profile

        async def fetch():
            if selected is None:
                return []
            return await rclone.list_remotes(selected)

        def on_success(names):
            dlg = UnionDialog(
                self.window, profiles, selected, list(names or []), on_saved=self.refresh
            )
            dlg.present(self.window)

        def on_error(exc):
            self.window.toast(_("Error: {exc}").format(exc=exc))

        run_async(fetch(), on_success=on_success, on_error=on_error)

    def _on_mount(self, _btn=None) -> None:
        if not self.unions:
            self.window.toast(_("Sin unions"))
            return
        if len(self.unions) > 1:
            self.window.toast(_("Monta el union desde Remotos (varios disponibles)"))
            return
        u = self.unions[0]
        name = u["name"]
        mp = (
            mount_manager.default_mountpoint(self._profile, name)
            if self.profile is not None
            else Path.home() / "mnt" / name
        )

        async def do():
            await mount_manager.mount(self._profile, name, mp)
            return mp

        def ok(mp):
            self.window.toast(f"Montado en {mp}")
            try:
                mount_manager.open_in_file_manager(mp)
            except Exception as exc:
                self.window.toast(f"Error abriendo: {exc}")

        def err(exc):
            self.window.toast(_("Error montando '{name}': {exc}").format(name=name, exc=exc))

        run_async(do(), on_success=ok, on_error=err)

    def _on_explore(self, _btn=None) -> None:
        if not self.unions:
            self.window.toast(_("Sin unions"))
            return
        name = self.unions[0]["name"]
        if self.profile is None:
            self.window.toast(_("Selecciona un perfil"))
            return

        async def do():
            return await rclone.list_dirs(self._profile, name, "", recursive=False)

        def ok(dirs):
            lines = [d.get("Path", "") for d in dirs if d.get("Path")]
            if not lines:
                lines = ["(vacío)"]
            dlg = Adw.AlertDialog.new(f"Contenido: {name}", "")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_margin_top(12)
            box.set_margin_bottom(12)
            box.set_margin_start(12)
            box.set_margin_end(12)
            view = Gtk.TextView()
            view.set_editable(False)
            view.set_monospace(True)
            view.get_buffer().set_text("\n".join(lines))
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_min_content_height(240)
            scrolled.set_min_content_width(400)
            scrolled.set_child(view)
            box.append(scrolled)
            dlg.set_extra_child(box)
            dlg.add_response("close", "Cerrar")
            dlg.set_default_response("close")
            dlg.set_close_response("close")
            dlg.present(self.window)

        def err(exc):
            self.window.toast(f"Error explorando '{name}': {exc}")

        run_async(do(), on_success=ok, on_error=err)

    def _on_delete(self, name: str) -> None:
        dlg = Adw.AlertDialog.new(
            _("Eliminar union"), _("¿Eliminar el union '{name}'?").format(name=name)
        )
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("delete", _("Eliminar"))
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")

        def on_response(d, response):
            if response == "delete":

                async def do():
                    await rclone.delete_remote(self._profile, name)

                def ok(_result):
                    sync_state.delete_state(self._profile, name)
                    try:
                        from ...services import mount_manager

                        mount_manager._invalidate_profile_dump_cache(self._profile)
                    except Exception:
                        pass
                    self.window.toast(_("Union '{name}' eliminado").format(name=name))
                    self.refresh()

                def err(exc):
                    self.window.toast(_("Error: {exc}").format(exc=exc))

                run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_response)
        dlg.present(self.window)

    def _toggle_mount(self, profile: Path, name: str, btn: Gtk.Button, mp: Path) -> None:
        mounted = mount_manager.is_mounted(mp)
        if not mounted:
            btn.set_sensitive(False)
            prev = btn.get_label()
            btn.set_label(_("Montando..."))

            async def do_mount():
                await mount_manager.mount(profile, name, mp)
                return mp

            def ok_mount(_mp):
                btn.set_sensitive(True)
                btn.set_label(_("Desmontar"))
                btn.remove_css_class("suggested-action")
                btn.add_css_class("destructive-action")
                self.window.toast(f"Montado en {mp}")
                self.refresh()
                try:
                    mount_manager.open_in_file_manager(mp)
                except Exception as exc:
                    self.window.toast(f"Error abriendo: {exc}")

            def err_mount(exc):
                btn.set_sensitive(True)
                btn.set_label(prev)
                self.window.toast(_("Error montando '{name}': {exc}").format(name=name, exc=exc))

            run_async(do_mount(), on_success=ok_mount, on_error=err_mount)
        else:
            btn.set_sensitive(False)
            btn.set_label(_("Desmontando..."))

            async def do_unmount():
                await mount_manager.unmount(mp)
                return mp

            def ok_unmount(_mp):
                btn.set_sensitive(True)
                btn.set_label(_("Montar"))
                btn.remove_css_class("destructive-action")
                btn.add_css_class("suggested-action")
                self.window.toast(_("Desmontado {name}").format(name=name))
                self.refresh()

            def err_unmount(exc):
                btn.set_sensitive(True)
                btn.set_label(_("Desmontar"))
                self.window.toast(_("Error desmontando '{name}': {exc}").format(name=name, exc=exc))

            run_async(do_unmount(), on_success=ok_unmount, on_error=err_unmount)

    def _on_sync(self, union_name: str) -> None:
        if self.profile is None:
            return
        mode = "mirror"
        delete_enabled = False
        settings = load_settings()
        raw_depth = int(settings.get("sync_depth", 0) or 0)
        depth = None if raw_depth <= 0 else raw_depth

        async def fetch():
            from ...services import profile_store

            pwd = (
                profile_store.get_cached_password(self._profile)
                if self.profile is not None
                else None
            )
            dump = await rclone.config_dump(self._profile, config_password=pwd)
            data = dump.get(union_name, {}) if isinstance(dump, dict) else {}
            ups = union_sync.parse_upstreams(data.get("upstreams", ""))
            state = sync_state.load_state(self._profile, union_name)
            baseline = None
            previous = None
            if isinstance(state, dict) and state.get("upstreams") == ups:
                previous = state.get("upstreams")
                paths = state.get("paths")
                if isinstance(paths, list):
                    baseline = set(paths)
            plan = await union_sync.build_mirror_plan(
                self._profile,
                ups,
                baseline=baseline,
                previous_upstreams=previous,
                allow_delete=delete_enabled,
                depth=depth,
            )
            return ups, plan

        def on_success(result):
            ups, plan = result
            self._show_preview(union_name, ups, plan, mode, delete_enabled)

        def on_error(exc):
            self.window.toast(_("Error: {exc}").format(exc=exc))

        run_async(fetch(), on_success=on_success, on_error=on_error)

    def _show_preview(self, union_name, ups, plan, mode, delete_enabled: bool = False) -> None:
        delete_enabled = bool(delete_enabled)

        dlg = Adw.AlertDialog.new(_("Vista previa de sincronización"), "")
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        summary.append(Gtk.Label(label=_("Union: {u}").format(u=union_name), xalign=0))
        summary.append(Gtk.Label(label=_("Upstreams: {u}").format(u=", ".join(ups)), xalign=0))
        summary.append(
            Gtk.Label(label=_("Modo: sincronización de estructura (creaciones; borrados deshabilitados por seguridad)"), xalign=0)
        )
        last = sync_state.last_sync(self._profile, union_name)
        if last:
            summary.append(Gtk.Label(label=f"Última sync: {last}", xalign=0))
        outer.append(summary)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(260)
        scrolled.set_min_content_width(520)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scrolled.set_child(content)
        outer.append(scrolled)

        def build_op_list(title: str, items: list, icon_name: str, css_class: str) -> None:
            header = Gtk.Label(label=f"{title} ({len(items)})", xalign=0)
            header.add_css_class("heading")
            content.append(header)
            if not items:
                empty = Gtk.Label(label=_("Sin operaciones"), xalign=0)
                empty.add_css_class("dim-label")
                empty.add_css_class("caption")
                content.append(empty)
                return
            lb = Gtk.ListBox()
            lb.add_css_class("boxed-list")
            for upstream, path in items:
                row = Adw.ActionRow()
                row.set_title(upstream)
                row.set_subtitle(path if path else "(raíz)")
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.add_css_class(css_class)
                row.add_prefix(icon)
                lb.append(row)
            content.append(lb)

        build_op_list("Crear", plan.to_create, "list-add-symbolic", "success")
        build_op_list("Borrar", plan.to_delete, "user-trash-symbolic", "error")

        if plan.errors:
            err_header = Gtk.Label(label=f"Errores ({len(plan.errors)})", xalign=0)
            err_header.add_css_class("heading")
            err_header.add_css_class("error")
            content.append(err_header)
            for e in plan.errors:
                lbl = Gtk.Label(label=f"! {e}", xalign=0)
                lbl.add_css_class("error")
                lbl.set_wrap(True)
                content.append(lbl)

        # Purge option (recursive delete) chosen at apply time.
        purge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        purge_box.set_margin_top(8)
        purge_label = Gtk.Label(label=_("Purge (borrado recursivo)"))
        purge_box.append(purge_label)
        purge_switch = Gtk.Switch()
        purge_switch.set_active(False)
        purge_switch.set_halign(Gtk.Align.END)
        purge_box.append(purge_switch)
        purge_help = Gtk.Label(
            label=_("Activa para borrar directorios con contenido; desactivado solo borra vacíos."),
            xalign=0,
        )
        purge_help.add_css_class("dim-label")
        purge_help.add_css_class("caption")
        outer.append(purge_box)
        outer.append(purge_help)

        # Inform the user how deletions are handled.
        ap = None
        for u in self.unions:
            if u["name"] == union_name:
                ap = u["data"].get("action_policy", "")
                break
        if ap not in ("epall", "all"):
            note = Gtk.Label(
                label=f"action_policy='{ap}': los borrados NO se propagan a todos los upstreams. "
                "Usa 'epall' o 'all' para propagación automática.",
                xalign=0,
            )
            note.add_css_class("dim-label")
            note.add_css_class("error")
            outer.append(note)
        else:
            note = Gtk.Label(
                label="Los borrados se propagan automáticamente según action_policy (epall/all). "
                "Esta sincronización solo propaga creaciones faltantes.",
                xalign=0,
            )
            note.add_css_class("dim-label")
            outer.append(note)

        dlg.set_extra_child(outer)
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("apply", _("Aplicar"))
        dlg.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")

        def on_response(d, response):
            if response == "apply":
                purge = purge_switch.get_active()
                settings = load_settings()
                concurrency = int(settings.get("concurrency", 4))

                async def do():
                    errs = await union_sync.apply_plan(
                        self._profile,
                        plan,
                        concurrency=concurrency,
                        delete=delete_enabled,
                        use_purge=purge,
                    )
                    return errs

                def ok(errs):
                    if errs:
                        self.window.toast(_("Aplicado con {n} errores").format(n=len(errs)))
                    else:
                        self.window.toast(_("Sincronización aplicada"))
                        if plan.baseline is not None:
                            sync_state.save_state(self._profile, union_name, ups, plan.baseline)
                    self.refresh()

                def err(exc):
                    self.window.toast(_("Error: {exc}").format(exc=exc))

                run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_response)
        dlg.present(self.window)
