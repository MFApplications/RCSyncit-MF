"""Page for browsing and managing files on a remote (rclone file manager)."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from pathlib import Path

from gi.repository import Adw, Gtk

from ...i18n import _
from ...services import mount_manager, rclone
from ...ui.async_helper import run_async

logger = logging.getLogger(__name__)


class FilesPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.profile: Path | None = None
        self.targets: list[tuple[Path, str]] = []
        self.active_profile: Path | None = None
        self.active_remote: str | None = None
        self.current_remote: str | None = None
        self.current_path: str = ""
        self._items: list[dict] = []
        self._selected: dict | None = None
        self.set_spacing(0)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_bottom(6)
        title = Gtk.Label(label=_("Archivos"), xalign=0)
        title.add_css_class("title-2")
        header.append(title)
        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        # Remote selector
        self.remote_combo = Gtk.ComboBoxText()
        self.remote_combo.set_tooltip_text(_("Remoto"))
        self.remote_combo.connect("changed", lambda _c: self._on_remote_changed())
        header.append(self.remote_combo)

        self.btn_refresh = Gtk.Button(label=_("Actualizar"))
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())
        header.append(self.btn_refresh)
        self.append(header)

        # Path bar
        pathbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pathbar.set_margin_bottom(6)
        self.btn_up = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_up.set_tooltip_text(_("Subir un nivel"))
        self.btn_up.connect("clicked", lambda _b: self._go_up())
        pathbar.append(self.btn_up)
        self.path_entry = Gtk.Entry(hexpand=True)
        self.path_entry.set_text("/")
        self.path_entry.add_css_class("monospace")
        self.path_entry.connect("activate", self._on_path_activate)
        pathbar.append(self.path_entry)
        self.append(pathbar)

        # List
        self.items_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.items_box.set_vexpand(True)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_vexpand(True)
        scrolled.set_child(self.items_box)

        # Status
        self.status = Adw.StatusPage(
            title=_("Sin perfil"),
            description=_("Selecciona un perfil en Perfiles."),
            icon_name="folder-remote-symbolic",
        )
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(scrolled, "list")
        self.stack.add_named(self.status, "empty")
        # Put the scrolled window inside the stack
        self.append(self.stack)
        self.stack.set_visible_child_name("empty")

        # Action bar
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_margin_top(6)
        for label, cb in [
            (_("Abrir"), self._open_selected),
            (_("Nueva carpeta"), self._new_folder),
            (_("Renombrar"), self._rename),
            (_("Copiar"), self._copy),
            (_("Mover"), self._move),
            (_("Borrar"), self._delete),
            (_("Subir"), self._upload),
            (_("Descargar"), self._download),
        ]:
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            actions.append(b)
        self.append(actions)

        self._rows: dict[object, dict] = {}
        self._list_cache: dict[tuple[str, str, str], list[dict]] = {}
        self._list_token: int = 0
        self._selected_button: Gtk.Button | None = None
        self.remotes: list[str] = []

    def _toast(self, message: str) -> None:
        win = self.window
        if win is not None and hasattr(win, "toast") and callable(getattr(win, "toast", None)):
            try:
                win.toast(str(message))
                return
            except Exception as exc:
                logger.warning("toast failed: %s", exc)
        logger.warning("toast unavailable: %s", message)

    # ------------------------------------------------------------------
    def set_profile(self, profile: Path | None) -> None:
        # Files page browses mounted remotes across profiles; profile selection
        # only triggers a refresh of the mounted targets list.
        self.refresh()

    def refresh(self) -> None:
        self._load_mounted_targets()

    def _load_mounted_targets(self) -> None:
        self.remote_combo.remove_all()
        self.targets = []
        mounted: list[tuple[Path, str, str]] = []
        for rec in mount_manager.list_mounts():
            if not isinstance(rec, dict):
                continue
            mp_raw = rec.get("mountpoint")
            if not isinstance(mp_raw, str) or not mp_raw:
                continue
            mp = Path(mp_raw)
            if not mount_manager.is_mounted(mp):
                continue
            remote = rec.get("remote")
            cfg = rec.get("config")
            if not isinstance(remote, str) or not remote:
                continue
            if not isinstance(cfg, str) or not cfg:
                continue
            profile = Path(cfg)
            mounted.append((profile, remote, mp_raw))
        # de-duplicate by (profile, remote)
        seen: set[tuple[str, str]] = set()
        unique: list[tuple[Path, str, str]] = []
        for profile, remote, mp_raw in mounted:
            key = (str(profile), remote)
            if key in seen:
                continue
            seen.add(key)
            unique.append((profile, remote, mp_raw))
        # build labels, adding mountpoint only when the base label is ambiguous
        base_counts: dict[str, int] = {}
        for profile, remote, _mp in unique:
            base = f"{profile.stem}: {remote}"
            base_counts[base] = base_counts.get(base, 0) + 1
        for profile, remote, mp_raw in unique:
            self.targets.append((profile, remote))
            base = f"{profile.stem}: {remote}"
            label = f"{base}  ({Path(str(mp_raw)).name})" if base_counts.get(base, 0) > 1 else base
            self.remote_combo.append_text(label)
        if self.targets:
            if (
                self.active_profile is not None
                and self.active_remote is not None
                and (self.active_profile, self.active_remote) in self.targets
            ):
                idx = self.targets.index((self.active_profile, self.active_remote))
            else:
                idx = 0
                self.active_profile, self.active_remote = self.targets[0]
                self.profile = self.active_profile
                self.current_remote = self.active_remote
            self.remote_combo.set_active(idx)
            self.stack.set_visible_child_name("list")
            self._list()
        else:
            self.active_profile = None
            self.active_remote = None
            self.profile = None
            self.current_remote = None
            self.stack.set_visible_child_name("empty")
            self.status.set_title(_("Sin remotos montados"))
            self.status.set_description(
                _("Monta un remoto desde Remotos o Unions para explorarlo aquí.")
            )

    def _on_remote_changed(self) -> None:
        idx = self.remote_combo.get_active()
        if 0 <= idx < len(self.targets):
            self.active_profile, self.active_remote = self.targets[idx]
            self.profile = self.active_profile
            self.current_remote = self.active_remote
        self.current_path = ""
        self._list()

    def _list(self) -> None:
        if self.profile is None or not self.current_remote:
            return
        self.path_entry.set_text("/" + self.current_path.strip("/"))
        # clear
        for child in list(self.items_box):
            if child.get_parent() is self.items_box:
                self.items_box.remove(child)
            else:
                child.unparent()
        self._rows.clear()
        self._items.clear()
        if self._selected_button is not None:
            self._selected_button.remove_css_class("selected")
            self._selected_button = None
        self._selected = None

        if self.active_profile is None or self.active_remote is None:
            return
        profile = self.active_profile
        remote = self.active_remote
        path = self.current_path
        cache_key = (str(profile), remote, path)

        # Invalidate pending fetches: only the latest _list may render.
        self._list_token += 1
        token = self._list_token

        # Cache hit: render immediately without rclone.
        cached = self._list_cache.get(cache_key)
        if cached is not None:
            if token != self._list_token:
                return
            self.path_entry.set_text("/" + path.strip("/"))
            for child in list(self.items_box):
                if child.get_parent() is self.items_box:
                    self.items_box.remove(child)
                else:
                    child.unparent()
            self._rows.clear()
            self._items.clear()
            self._selected = None
            items = list(cached)
            for it in items:
                self._add_row(it)
            self._items = items
            self.stack.set_visible_child_name("list")
            self.items_box.set_visible(True)
            self.items_box.queue_draw()
            return

        async def fetch():
            if token != self._list_token:
                return None
            return await rclone.list_files(profile, remote, path)

        def ok(items):
            if token != self._list_token:
                return
            if not isinstance(items, list):
                items = []
            logger.info("list_files returned %d items for %s:%s", len(items), remote, path)
            # clear container before rendering (handles duplicate async fetches)
            for child in list(self.items_box):
                if child.get_parent() is self.items_box:
                    self.items_box.remove(child)
                else:
                    child.unparent()
            self._rows.clear()
            # de-duplicate entries (some backends/upstreams repeat items)
            seen: set[tuple[str, bool]] = set()
            unique: list[dict] = []
            for it in items:
                key = (str(it.get("Path") or it.get("Name") or ""), bool(it.get("IsDir")))
                if key in seen:
                    continue
                seen.add(key)
                unique.append(it)
            items = unique
            # dirs first, then files
            items = sorted(items, key=lambda x: (not bool(x.get("IsDir")), str(x.get("Name", ""))))
            if token != self._list_token:
                return
            self._list_cache[cache_key] = list(items)
            for it in items:
                self._add_row(it)
            self._items = items
            self.stack.set_visible_child_name("list")
            self.items_box.set_visible(True)
            self.items_box.queue_draw()
            if not items:
                self._toast(_("Carpeta vacía o sin acceso"))

        def err(exc):
            if token != self._list_token:
                return
            logger.exception("list_files failed for %s:%s", remote, path)
            self._toast(_("Error listando: {exc}").format(exc=exc))

        run_async(fetch(), on_success=ok, on_error=err)

    def _icon_for(self, item: dict) -> str:
        if bool(item.get("IsDir")):
            return "folder-symbolic"
        mime = str(item.get("MimeType") or "").lower()
        name = str(item.get("Name") or item.get("Path") or "").lower()
        if mime.startswith("image/"):
            return "image-x-generic-symbolic"
        if mime.startswith("video/"):
            return "video-x-generic-symbolic"
        if mime.startswith("audio/"):
            return "audio-x-generic-symbolic"
        if mime == "application/pdf":
            return "x-office-document-symbolic"
        if any(x in mime for x in ("zip", "tar", "gzip", "compressed")):
            return "package-x-generic-symbolic"
        if mime.startswith("text/"):
            return "text-x-generic-symbolic"
        # fallback by extension
        if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp")):
            return "image-x-generic-symbolic"
        if name.endswith((".mp4", ".mkv", ".avi", ".mov", ".webm")):
            return "video-x-generic-symbolic"
        if name.endswith((".mp3", ".wav", ".flac", ".ogg", ".m4a")):
            return "audio-x-generic-symbolic"
        if name.endswith(".pdf"):
            return "x-office-document-symbolic"
        if name.endswith((".zip", ".tar", ".gz", ".7z", ".rar")):
            return "package-x-generic-symbolic"
        return "text-x-generic-symbolic"

    def _add_row(self, item: dict) -> None:
        is_dir = bool(item.get("IsDir"))
        name = str(item.get("Name") or item.get("Path") or "")

        btn = Gtk.Button()
        btn.add_css_class("flat")
        btn.set_halign(Gtk.Align.FILL)
        btn.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(2)
        box.set_margin_bottom(2)
        box.set_margin_start(4)
        box.set_margin_end(4)

        icon = Gtk.Image.new_from_icon_name(self._icon_for(item))
        box.append(icon)

        lbl = Gtk.Label(label=name, xalign=0, hexpand=True)
        box.append(lbl)

        # Show size only for files; directories don't have a meaningful
        # recursive size in `lsjson`.
        size = item.get("Size")
        if (not is_dir) and isinstance(size, int) and size > 0:
            size_lbl = Gtk.Label(label=_human_size(size), xalign=1)
            size_lbl.add_css_class("dim-label")
            size_lbl.add_css_class("caption")
            box.append(size_lbl)

        # Only show modification time for files, not directories.
        mod = item.get("ModTime")
        if (not is_dir) and mod:
            m_lbl = Gtk.Label(label=str(mod)[:19], xalign=1)
            m_lbl.add_css_class("dim-label")
            m_lbl.add_css_class("caption")
            box.append(m_lbl)

        btn.set_child(box)

        def on_click(_b):
            if self._selected_button is not None and self._selected_button is not btn:
                self._selected_button.remove_css_class("selected")
            btn.add_css_class("selected")
            self._selected_button = btn
            self._selected = item

        def on_double(_g, n, x, y):
            if n != 2:
                return
            if is_dir and name:
                self.current_path = (self.current_path.rstrip("/") + "/" + name).strip("/")
                self._list()
            elif not is_dir:
                self._open_file(item)

        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", on_double)
        btn.add_controller(click)
        btn.connect("clicked", on_click)

        self.items_box.append(btn)
        self._rows[btn] = item

    def _on_row_selected(self, _lb, row) -> None:
        self._selected = self._rows.get(row) if row is not None else None

    def _on_row_activated(self, _lb, row) -> None:
        item = self._rows.get(row) if row is not None else None
        if item and item.get("IsDir"):
            name = item.get("Name") or item.get("Path")
            if name:
                self.current_path = (self.current_path.rstrip("/") + "/" + str(name)).strip("/")
                self._list()

    def _invalidate_cache(self, *paths: str) -> None:
        targets = set(paths) if paths else {self.current_path}
        # also invalidate parent
        for p in list(targets):
            parts = p.strip("/").split("/") if p.strip("/") else []
            if parts:
                targets.add("/".join(parts[:-1]))
        for key in list(self._list_cache.keys()):
            if key[2] in targets:
                del self._list_cache[key]

    def _go_up(self) -> None:
        if not self.current_path:
            return
        parts = self.current_path.strip("/").split("/")
        parts = parts[:-1]
        self.current_path = "/".join(parts)
        self._list()

    def _on_path_activate(self, entry) -> None:
        text = entry.get_text().strip().strip("/")
        self.current_path = text
        self._list()

    def _open_selected(self, _b=None) -> None:
        item = self._selected
        if not item:
            self._toast(_("Selecciona un elemento"))
            return
        if item.get("IsDir"):
            name = str(item.get("Name") or item.get("Path"))
            if name:
                self.current_path = (self.current_path.rstrip("/") + "/" + name).strip("/")
                self.path_entry.set_text(self.current_path)
                self._list()
            return
        self._open_file(item)

    def _open_file(self, item: dict) -> None:
        if self.active_profile is None or self.active_remote is None:
            self._toast(_("Selecciona un remoto"))
            return
        profile = self.active_profile
        remote = self.active_remote
        name = str(item.get("Name") or item.get("Path") or "")
        if not name:
            return
        rel = (self.current_path.rstrip("/") + "/" + name).strip("/") if self.current_path else name

        # Try opening from a mounted path first (instant, no download).
        mp = None
        for rec in mount_manager.list_mounts():
            if not isinstance(rec, dict):
                continue
            if rec.get("remote") != remote:
                continue
            if Path(str(rec.get("config", ""))) != profile:
                continue
            mp_raw = rec.get("mountpoint")
            if isinstance(mp_raw, str) and mp_raw:
                candidate = Path(mp_raw)
                if mount_manager.is_mounted(candidate):
                    mp = candidate
                    break
        if mp is not None:
            local = mp.joinpath(*rel.split("/")) if rel else mp
            if local.exists():
                self._launch_local(local)
                return

        # Fallback: download to a temp file and open it.
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp(prefix="rcsyncitmf-"))
        local_dest = tmp_dir / name

        async def do():
            from ...services import profile_store as _ps

            pwd = _ps.get_cached_password(profile)
            src = f"{remote}:{rel}"
            await rclone.run(["copyto", src, str(local_dest)], config=profile, config_password=pwd)

        def ok(_result):
            self._launch_local(local_dest)
            # Clean up the temporary download directory after a grace period.
            import shutil

            from gi.repository import GLib

            def _cleanup() -> bool:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return False

            GLib.timeout_add_seconds(120, _cleanup)

        def err(exc):
            self._toast(_("Error abriendo: {exc}").format(exc=exc))

        self._toast(_("Descargando para abrir..."))
        run_async(do(), on_success=ok, on_error=err)

    def _launch_local(self, path: Path) -> None:
        import shutil
        import subprocess

        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener is None:
            self._toast(_("No hay aplicación para abrir archivos"))
            return
        try:
            if opener.endswith("gio"):
                subprocess.Popen([opener, "open", str(path)])
            else:
                subprocess.Popen([opener, str(path)])
            self._toast(_("Abriendo {name}").format(name=path.name))
        except Exception as exc:
            self._toast(_("Error abriendo: {exc}").format(exc=exc))

    # ---------------------------------------------------------------- actions
    def _require_selection(self) -> dict | None:
        if self._selected is None:
            self._toast(_("Selecciona un elemento"))
            return None
        return self._selected

    def _new_folder(self, _b=None) -> None:
        if self.profile is None or not self.current_remote:
            return
        dlg = Adw.AlertDialog.new(_("Nueva carpeta"), "")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        entry = Gtk.Entry()
        entry.set_placeholder_text(_("nombre de la carpeta"))
        box.append(entry)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("create", _("Crear"))
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("create")
        dlg.set_close_response("cancel")

        def on_resp(d, resp):
            if resp == "create":
                name = entry.get_text().strip()
                if name:
                    if self.profile is None or self.current_remote is None:
                        return
                    profile = self.profile
                    remote = self.current_remote
                    path = (self.current_path.rstrip("/") + "/" + name).strip("/")

                    async def do():
                        await rclone.mkdir(profile, remote, path)

                    def ok(_result):
                        self._toast(_("Carpeta creada"))
                        self._invalidate_cache(self.current_path)
                        self._list()

                    def err(exc):
                        self._toast(_("Error: {exc}").format(exc=exc))

                    run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_resp)
        dlg.present(self.window)

    def _delete(self, _b=None) -> None:
        item = self._require_selection()
        if item is None:
            return
        name = str(item.get("Name") or item.get("Path"))
        path = (
            (self.current_path.rstrip("/") + "/" + name).strip("/") if self.current_path else name
        )
        dlg = Adw.AlertDialog.new(_("Borrar"), _("¿Borrar '{name}'?").format(name=name))
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("delete", _("Borrar"))
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")

        def on_resp(d, resp):
            if resp == "delete":
                if self.profile is None or self.current_remote is None:
                    return
                profile = self.profile
                remote = self.current_remote
                is_dir = bool(item.get("IsDir"))

                async def do():
                    if is_dir:
                        await rclone.purge(profile, remote, path)
                    else:
                        await rclone.delete_file(profile, remote, path)

                def ok(_result):
                    self._toast(_("Borrado"))
                    self._invalidate_cache(self.current_path)
                    self._list()

                def err(exc):
                    self._toast(_("Error: {exc}").format(exc=exc))

                run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_resp)
        dlg.present(self.window)

    def _rename(self, _b=None) -> None:
        item = self._require_selection()
        if item is None:
            return
        old_name = str(item.get("Name") or item.get("Path"))
        old_path = (
            (self.current_path.rstrip("/") + "/" + old_name).strip("/")
            if self.current_path
            else old_name
        )
        dlg = Adw.AlertDialog.new(_("Renombrar"), "")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        entry = Gtk.Entry()
        entry.set_text(old_name)
        box.append(entry)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("ok", _("Aceptar"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def on_resp(d, resp):
            if resp == "ok":
                new_name = entry.get_text().strip()
                if new_name and new_name != old_name:
                    if self.profile is None or self.current_remote is None:
                        return
                    profile = self.profile
                    remote = self.current_remote
                    new_path = (
                        (self.current_path.rstrip("/") + "/" + new_name).strip("/")
                        if self.current_path
                        else new_name
                    )

                    async def do():
                        await rclone.move(
                            profile,
                            remote,
                            old_path,
                            remote,
                            new_path,
                        )

                    def ok(_result):
                        self._toast(_("Renombrado"))
                        self._invalidate_cache(self.current_path)
                        self._list()

                    def err(exc):
                        self._toast(_("Error: {exc}").format(exc=exc))

                    run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_resp)
        dlg.present(self.window)

    def _copy(self, _b=None) -> None:
        item = self._require_selection()
        if item is None:
            return
        name = str(item.get("Name") or item.get("Path"))
        src_path = (
            (self.current_path.rstrip("/") + "/" + name).strip("/") if self.current_path else name
        )
        self._fetch_remotes_then(src_path, move=False, title=_("Copiar"))

    def _move(self, _b=None) -> None:
        item = self._require_selection()
        if item is None:
            return
        name = str(item.get("Name") or item.get("Path"))
        src_path = (
            (self.current_path.rstrip("/") + "/" + name).strip("/") if self.current_path else name
        )
        self._fetch_remotes_then(src_path, move=True, title=_("Mover"))

    def _fetch_remotes_then(self, src_path: str, move: bool, title: str) -> None:
        if self.profile is None:
            self._toast(_("Selecciona un remoto"))
            return

        profile = self.profile
        if profile is None:
            return

        async def fetch():
            return await rclone.list_remotes(profile)

        def ok(names):
            self.remotes = list(names or [])
            if not self.remotes:
                self._toast(_("Sin remotos en el perfil"))
                return
            self._transfer_dialog(title, src_path, move=move)

        def err(exc):
            self._toast(_("Error: {exc}").format(exc=exc))

        run_async(fetch(), on_success=ok, on_error=err)

    def _transfer_dialog(self, title: str, src_path: str, move: bool) -> None:
        if not self.remotes:
            self._toast(_("Sin remotos en el perfil"))
            return
        dlg = Adw.AlertDialog.new(title, "")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        # dest remote
        rbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        rbox.append(Gtk.Label(label=_("Remoto destino"), xalign=0))
        combo = Gtk.ComboBoxText()
        for r in self.remotes:
            combo.append_text(r)
        if self.current_remote in self.remotes:
            combo.set_active(self.remotes.index(self.current_remote))
        elif self.remotes:
            combo.set_active(0)
        combo.set_hexpand(True)
        rbox.append(combo)
        box.append(rbox)

        # dest path
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pbox.append(Gtk.Label(label=_("Ruta destino (carpeta)"), xalign=0))
        entry = Gtk.Entry()
        entry.set_text(self.current_path)
        entry.set_placeholder_text("carpeta/subcarpeta")
        pbox.append(entry)
        box.append(pbox)

        dlg.set_extra_child(box)
        dlg.add_response("cancel", _("Cancelar"))
        dlg.add_response("ok", _("Aceptar"))
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def on_resp(d, resp):
            if resp == "ok":
                idx = combo.get_active()
                if idx < 0 or idx >= len(self.remotes):
                    d.close() if hasattr(d, "close") else None
                    return
                if self.profile is None or self.current_remote is None:
                    return
                profile = self.profile
                src_remote = self.current_remote
                dst_remote = self.remotes[idx]
                dst_folder = entry.get_text().strip().strip("/")
                name = src_path.split("/")[-1]
                dst_path = (dst_folder + "/" + name).strip("/") if dst_folder else name

                async def do():
                    if move:
                        await rclone.move(profile, src_remote, src_path, dst_remote, dst_path)
                    else:
                        await rclone.copy(profile, src_remote, src_path, dst_remote, dst_path)

                def ok(_result):
                    self._toast(_("Hecho"))
                    self._invalidate_cache(self.current_path)
                    self._list()

                def err(exc):
                    self._toast(_("Error: {exc}").format(exc=exc))

                run_async(do(), on_success=ok, on_error=err)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_resp)
        dlg.present(self.window)

    def _upload(self, _b=None) -> None:
        if self.profile is None or not self.current_remote:
            return
        dialog = Gtk.FileDialog(title=_("Subir archivo"))

        def on_open(d, res):
            try:
                f = d.open_finish(res)
            except Exception:
                return
            if f is None:
                return
            if self.profile is None or self.current_remote is None:
                return
            profile = self.profile
            remote = self.current_remote
            local_path = f.get_path()
            name = Path(local_path).name
            dst_path = (
                (self.current_path.rstrip("/") + "/" + name).strip("/")
                if self.current_path
                else name
            )

            # rclone copyto local path -> remote
            async def do():
                src = local_path
                dst = f"{remote}:{dst_path}" if dst_path else f"{remote}:"
                from ...services import profile_store as _ps

                pwd = _ps.get_cached_password(profile)
                await rclone.run(["copyto", src, dst], config=profile, config_password=pwd)

            def ok(_result):
                self._toast(_("Subido"))
                self._invalidate_cache(self.current_path)
                self._list()

            def err(exc):
                self._toast(_("Error: {exc}").format(exc=exc))

            run_async(do(), on_success=ok, on_error=err)

        dialog.open(self.window, None, on_open)

    def _download(self, _b=None) -> None:
        item = self._require_selection()
        if item is None or item.get("IsDir"):
            if item is not None:
                self._toast(_("Selecciona un archivo"))
            return
        if self.profile is None or self.current_remote is None:
            return
        profile = self.profile
        remote = self.current_remote
        name = str(item.get("Name") or item.get("Path"))
        src_path = (
            (self.current_path.rstrip("/") + "/" + name).strip("/") if self.current_path else name
        )
        dialog = Gtk.FileDialog(title=_("Guardar en"))
        dialog.select_folder(
            self.window, None, self._on_download_folder_selected, (profile, remote, src_path, name)
        )

    def _on_download_folder_selected(self, d, res, user_data):
        profile, remote, src_path, name = user_data
        try:
            folder = d.select_folder_finish(res)
        except Exception:
            return
        if folder is None:
            return
        local_dest = str(Path(folder.get_path()) / name)

        async def do():
            src = f"{remote}:{src_path}"
            from ...services import profile_store as _ps

            pwd = _ps.get_cached_password(profile)
            await rclone.run(["copyto", src, local_dest], config=profile, config_password=pwd)

        def ok(_result):
            self._toast(_("Descargado"))

        def err(exc):
            self._toast(_("Error: {exc}").format(exc=exc))

        run_async(do(), on_success=ok, on_error=err)


def _human_size(n: int) -> str:
    size: float = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} PiB"
