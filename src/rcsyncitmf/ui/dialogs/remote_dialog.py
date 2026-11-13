"""Dialog to create and edit a rclone remote with typed fields.

Fields are generated dynamically from `rclone config providers`, so every
backend supported by the installed rclone (including mega, drive, s3, ...)
is handled and existing remotes are edited with their real type instead of
being misdetected as "local".
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gi.repository import Adw, Gtk

from ...services import rclone
from ...ui.async_helper import run_async

# Important fields that should be shown even if rclone marks them as advanced.
IMPORTANT_FIELDS = {
    "token",
    "pass",
    "password",
    "password2",
    "user",
    "2fa",
    "remote",
    "upstreams",
    "host",
    "url",
    "access_key_id",
    "secret_access_key",
    "region",
    "endpoint",
    "username",
    "master_key",
    "session_id",
}

# Curated fallback (used only if `rclone config providers` is unavailable).
REMOTE_TYPES_FALLBACK = [
    "drive",
    "s3",
    "dropbox",
    "onedrive",
    "box",
    "ftp",
    "sftp",
    "http",
    "webdav",
    "chunker",
    "combine",
    "alias",
    "crypt",
    "union",
    "mega",
]

POLICIES = [
    "ff",
    "all",
    "lfs",
    "mfs",
    "newest",
    "rand",
    "epall",
    "epff",
    "eplfs",
    "eplfu",
    "eppmfs",
    "epmfs",
    "epnewest",
]


class RemoteDialog(Adw.AlertDialog):
    def __init__(
        self,
        window,
        profile: Path,
        remote_name: str | None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(title="Remoto" if remote_name else "Nuevo remoto", body="")
        self.window = window
        self.profile = profile
        self.remote_name = remote_name
        self.on_saved = on_saved
        self.editing = remote_name is not None
        self._initial: dict = {}

        # Available backends (exclude "local": the app does not manage local remotes).
        providers = rclone.list_providers()
        self._providers = providers if providers else []
        prefixes = []
        for p in self._providers:
            pref = p.get("Prefix")
            # Unions are managed exclusively in the Unions section.
            if pref and pref not in ("local", "union"):
                prefixes.append(pref)
        if not prefixes:
            prefixes = [t for t in REMOTE_TYPES_FALLBACK if t not in ("local", "union")]
        self.type_list = sorted(set(prefixes))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Width is driven by content; keep a sane minimum via the container.
        box.set_size_request(500, -1)

        # Name
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name_box.append(Gtk.Label(label="Nombre", xalign=0))
        self.name_entry = Gtk.Entry()
        self.name_entry.set_hexpand(True)
        if remote_name:
            self.name_entry.set_text(remote_name)
        name_box.append(self.name_entry)
        box.append(name_box)

        # Type
        type_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        type_box.append(Gtk.Label(label="Tipo", xalign=0))
        self.type_combo = Gtk.ComboBoxText()
        for t in self.type_list:
            self.type_combo.append_text(t)
        self.type_combo.set_active(0)
        self.type_combo.set_hexpand(True)
        if remote_name:
            self.type_combo.set_sensitive(False)
        type_box.append(self.type_combo)
        box.append(type_box)

        # Dynamic fields (scrollable, larger area)
        self.fields_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        fields_scrolled = Gtk.ScrolledWindow(vexpand=True)
        fields_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        fields_scrolled.set_max_content_height(420)
        fields_scrolled.set_propagate_natural_height(True)
        fields_scrolled.set_max_content_width(760)
        fields_scrolled.set_propagate_natural_width(True)
        fields_scrolled.set_child(self.fields_box)
        box.append(fields_scrolled)
        self.field_rows: dict[str, Gtk.Entry | Gtk.ComboBoxText] = {}
        self._cached_dump: dict[str, Any] | None = None
        self._union_upstream_rows: list[dict[str, Any]] = []
        self._union_upstream_box: Gtk.Box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._union_refreshing: bool = False

        self.type_combo.connect("changed", self._on_type_changed)
        self._on_type_changed(self.type_combo)

        self.set_extra_child(box)
        self.add_response("cancel", "Cancelar")
        self.add_response("save", "Guardar")
        self.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("save")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)

        if self.editing:
            self._load_existing()

    # ---------- helpers ----------
    def _provider_for(self, ptype: str):
        for p in self._providers:
            if p.get("Prefix") == ptype:
                return p
        return None

    def _ensure_dump(self) -> dict[str, Any]:
        if self._cached_dump is not None:
            return self._cached_dump
        import asyncio

        from ...services import profile_store

        pwd = profile_store.get_cached_password(self.profile)
        try:
            dump = asyncio.run(rclone.config_dump(self.profile, config_password=pwd))
        except Exception:
            dump = {}
        if not isinstance(dump, dict):
            dump = {}
        self._cached_dump = dump
        return dump

    def _fields_for(self, ptype: str) -> list[tuple[str, str, str]]:
        prov = self._provider_for(ptype)
        if prov is None:
            return []
        out = []
        for o in prov.get("Options", []):
            if o.get("Hide", 0) != 0:
                continue
            name = o.get("Name")
            if not name:
                continue
            advanced = bool(o.get("Advanced", False))
            required = bool(o.get("Required", False))
            if advanced and not required and name not in IMPORTANT_FIELDS:
                continue
            kind = "password" if o.get("IsPassword") else "text"
            label = name.replace("_", " ").title()
            out.append((name, label, kind))
        return out

    def _on_type_changed(self, combo) -> None:
        t = combo.get_active_text() or (self.type_list[0] if self.type_list else "")
        while (c := self.fields_box.get_first_child()) is not None:
            self.fields_box.remove(c)
        self.field_rows.clear()

        if t == "union":
            self._build_union_fields()
            return

        if t == "crypt":
            self._build_crypt_fields()
            return

        for key, label, kind in self._fields_for(t):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            lbl = Gtk.Label(label=label, xalign=0)
            row.append(lbl)
            if kind == "password":
                entry = Gtk.Entry()
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            else:
                entry = Gtk.Entry()
            entry.set_hexpand(True)
            row.append(entry)
            self.fields_box.append(row)
            self.field_rows[key] = entry

    def _crypt_parents(self) -> set[str]:
        dump = self._ensure_dump()
        parents: set[str] = set()
        if isinstance(dump, dict):
            for _name, data in dump.items():
                if isinstance(data, dict) and data.get("type") == "crypt":
                    p = str(data.get("remote", "")).rstrip(":").strip()
                    if p:
                        parents.add(p)
        return parents

    def _crypt_candidates(self) -> list[str]:
        dump = self._ensure_dump()
        parents = self._crypt_parents()
        out = []
        if isinstance(dump, dict):
            for name, data in dump.items():
                if (
                    not (isinstance(data, dict) and data.get("type") == "crypt")
                    and name not in parents
                ):
                    out.append(name)
        return sorted(out)

    def _union_remotes(self) -> list[str]:
        dump = self._ensure_dump()
        if not isinstance(dump, dict):
            return []
        return sorted(
            n for n in dump if not (isinstance(dump[n], dict) and dump[n].get("type") == "union")
        )

    def _union_selected_remotes(self, exclude_combo=None) -> set[str]:
        used: set[str] = set()
        for item in getattr(self, "_union_upstream_rows", []):
            combo = item["combo"]
            if combo is exclude_combo:
                continue
            text = combo.get_active_text()
            if text:
                used.add(text)
        return used

    def _populate_union_combo(self, combo: Gtk.ComboBoxText, preferred: str = "") -> None:
        used = self._union_selected_remotes(exclude_combo=combo)
        available = [r for r in self._union_remotes() if r not in used or r == preferred]
        # rebuild
        # Gtk.ComboBoxText has remove_all
        combo.remove_all()
        for name in available:
            combo.append_text(name)
        if preferred and preferred in available:
            combo.set_active(available.index(preferred))
        elif available:
            combo.set_active(0)

    def _refresh_union_combos(self) -> None:
        if getattr(self, "_union_refreshing", False):
            return
        self._union_refreshing = True
        for item in getattr(self, "_union_upstream_rows", []):
            combo = item["combo"]
            preferred = combo.get_active_text() or ""
            used = set()
            for other in getattr(self, "_union_upstream_rows", []):
                if other is item:
                    continue
                t = other["combo"].get_active_text()
                if t:
                    used.add(t)
            available = [r for r in self._union_remotes() if r not in used or r == preferred]
            combo.remove_all()
            for name in available:
                combo.append_text(name)
            if preferred and preferred in available:
                combo.set_active(available.index(preferred))
            elif available:
                combo.set_active(0)
        self._union_refreshing = False

    def _add_union_upstream_row(self, remote: str = "", path: str = "") -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        combo = Gtk.ComboBoxText()
        combo.set_hexpand(True)
        combo.connect("changed", lambda _c: self._refresh_union_combos())
        row.append(combo)

        path_entry = Gtk.Entry()
        path_entry.set_placeholder_text("carpeta (ej. almacen)")
        path_entry.set_text(path)
        path_entry.set_hexpand(True)
        row.append(path_entry)

        remove_btn = Gtk.Button(icon_name="list-remove-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.connect("clicked", lambda _b, r=row: self._remove_union_upstream_row(r))
        row.append(remove_btn)

        self._union_upstream_box.append(row)
        self._union_upstream_rows.append({"combo": combo, "entry": path_entry, "row": row})
        path_entry.set_text(path)
        self._refresh_union_combos()
        if remote:
            for item in self._union_upstream_rows:
                if item["row"] is row:
                    cb = item["combo"]
                    for i in range(len(cb.get_model())):
                        if cb.get_model()[i][0] == remote:
                            cb.set_active(i)
                            break

    def _remove_union_upstream_row(self, row: Gtk.Box) -> None:
        self._union_upstream_box.remove(row)
        self._union_upstream_rows = [r for r in self._union_upstream_rows if r["row"] != row]
        self._refresh_union_combos()

    def _build_union_fields(self) -> None:
        self._union_upstream_rows = []
        self._union_refreshing = False

        # Upstreams
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label="Upstreams (remoto:/carpeta)", xalign=0))
        help_lbl = Gtk.Label(
            label="Ejemplo: nube1:/almacen nube2:/almacen. Cada upstream puede tener su propia carpeta.",
            xalign=0,
        )
        help_lbl.add_css_class("dim-label")
        help_lbl.add_css_class("caption")
        help_lbl.set_wrap(True)
        box.append(help_lbl)

        self._union_upstream_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._union_upstream_box)

        add_btn = Gtk.Button(label="Añadir upstream")
        add_btn.connect("clicked", lambda _b: self._add_union_upstream_row())
        box.append(add_btn)
        if not self.editing:
            self._add_union_upstream_row()
        self.fields_box.append(box)

        # action policy
        policy_hints = {
            "ff": "primer encontrado",
            "all": "todos los upstreams",
            "lfs": "menos espacio libre",
            "mfs": "más espacio libre",
            "newest": "más reciente",
            "rand": "aleatorio",
            "epall": "todos (ep)",
            "epff": "primer encontrado (ep)",
            "eplfs": "menos espacio (ep)",
            "eplfu": "menos usado (ep)",
            "eppmfs": "más espacio (ep)",
            "epmfs": "más espacio (ep)",
            "epnewest": "más reciente (ep)",
        }
        for key, title, desc, default in [
            (
                "action_policy",
                "Action policy",
                "Política de acción al leer/escribir. "
                + ", ".join(f"{k}={v}" for k, v in policy_hints.items())
                + ".",
                "epall",
            ),
            (
                "create_policy",
                "Create policy",
                "Política de creación de archivos. "
                + ", ".join(f"{k}={v}" for k, v in policy_hints.items())
                + ".",
                "epmfs",
            ),
            (
                "search_policy",
                "Search policy",
                "Política de búsqueda. "
                + ", ".join(f"{k}={v}" for k, v in policy_hints.items())
                + ".",
                "ff",
            ),
        ]:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            row.append(Gtk.Label(label=f"{title} ({key})", xalign=0))
            combo = Gtk.ComboBoxText()
            for p in POLICIES:
                combo.append_text(p)
            combo.set_active(POLICIES.index(default) if default in POLICIES else 0)
            combo.set_hexpand(True)
            row.append(combo)
            help_lbl = Gtk.Label(label=desc, xalign=0)
            help_lbl.add_css_class("dim-label")
            help_lbl.add_css_class("caption")
            help_lbl.set_wrap(True)
            row.append(help_lbl)
            self.fields_box.append(row)
            self.field_rows[key] = combo

        # cache_time
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.append(Gtk.Label(label="Cache time", xalign=0))
        entry = Gtk.Entry()
        entry.set_placeholder_text("ej. 5m")
        entry.set_text("5m")
        entry.set_hexpand(True)
        row.append(entry)
        help_lbl = Gtk.Label(label="Tiempo de cache de directorios del union.", xalign=0)
        help_lbl.add_css_class("dim-label")
        help_lbl.add_css_class("caption")
        row.append(help_lbl)
        self.fields_box.append(row)
        self.field_rows["cache_time"] = entry

        # min_free_space
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.append(Gtk.Label(label="Min free space", xalign=0))
        entry = Gtk.Entry()
        entry.set_placeholder_text("ej. 1G")
        entry.set_text("1G")
        entry.set_hexpand(True)
        row.append(entry)
        self.fields_box.append(row)
        self.field_rows["min_free_space"] = entry

    def _build_crypt_fields(self) -> None:
        if not self.editing:
            # Creation: full crypt configuration.
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            row.append(Gtk.Label(label="Remote (upstream)", xalign=0))
            remote_combo = Gtk.ComboBoxText()
            for name in self._crypt_candidates():
                remote_combo.append_text(name)
            if remote_combo.get_model() is not None and len(remote_combo.get_model()) > 0:
                remote_combo.set_active(0)
            remote_combo.set_hexpand(True)
            row.append(remote_combo)
            self.fields_box.append(row)
            self.field_rows["remote"] = remote_combo

            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            row.append(Gtk.Label(label="Filename Encryption", xalign=0))
            fe_combo = Gtk.ComboBoxText()
            for val in ("standard", "obfuscate", "off"):
                fe_combo.append_text(val)
            fe_combo.set_active(0)
            fe_combo.set_hexpand(True)
            row.append(fe_combo)
            help_lbl = Gtk.Label(
                label="standard: cifra nombres; obfuscate: ofusca; off: no cifra nombres.", xalign=0
            )
            help_lbl.add_css_class("dim-label")
            help_lbl.add_css_class("caption")
            help_lbl.set_wrap(True)
            row.append(help_lbl)
            self.fields_box.append(row)
            self.field_rows["filename_encryption"] = fe_combo

            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            row.append(Gtk.Label(label="Directory Name Encryption", xalign=0))
            de_combo = Gtk.ComboBoxText()
            for val in ("true", "false"):
                de_combo.append_text(val)
            de_combo.set_active(0)
            de_combo.set_hexpand(True)
            row.append(de_combo)
            help_lbl = Gtk.Label(
                label="true: cifra nombres de carpetas; false: los deja intactos.", xalign=0
            )
            help_lbl.add_css_class("dim-label")
            help_lbl.add_css_class("caption")
            help_lbl.set_wrap(True)
            row.append(help_lbl)
            self.fields_box.append(row)
            self.field_rows["directory_name_encryption"] = de_combo
        else:
            # Editing: only password-related fields are editable.
            info = Gtk.Label(
                label="Edición segura: solo se pueden cambiar las contraseñas. "
                "El upstream y el modo de cifrado no son editables para no dañar los datos.",
                xalign=0,
            )
            info.add_css_class("dim-label")
            info.add_css_class("caption")
            info.set_wrap(True)
            self.fields_box.append(info)

            if self._initial.get("remote"):
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                row.append(Gtk.Label(label="Remote (upstream, solo lectura)", xalign=0))
                lbl = Gtk.Label(label=str(self._initial.get("remote")), xalign=0)
                lbl.add_css_class("monospace")
                row.append(lbl)
                self.fields_box.append(row)

            if self._initial.get("filename_encryption") or self._initial.get(
                "directory_name_encryption"
            ):
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                row.append(Gtk.Label(label="Modo de cifrado (solo lectura)", xalign=0))
                fe = self._initial.get("filename_encryption", "")
                de = self._initial.get("directory_name_encryption", "")
                lbl = Gtk.Label(label=f"filename={fe}, directory={de}", xalign=0)
                lbl.add_css_class("monospace")
                row.append(lbl)
                self.fields_box.append(row)

        # password (optional) - always editable
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.append(Gtk.Label(label="Password (opcional)", xalign=0))
        pw_entry = Gtk.Entry()
        pw_entry.set_visibility(False)
        pw_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        pw_entry.set_hexpand(True)
        row.append(pw_entry)
        help_lbl = Gtk.Label(label="Deja en blanco para mantener la actual / omitir.", xalign=0)
        help_lbl.add_css_class("dim-label")
        help_lbl.add_css_class("caption")
        row.append(help_lbl)
        self.fields_box.append(row)
        self.field_rows["password"] = pw_entry

        # password2 (optional) - always editable
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.append(Gtk.Label(label="Password 2 (opcional)", xalign=0))
        pw2_entry = Gtk.Entry()
        pw2_entry.set_visibility(False)
        pw2_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        pw2_entry.set_hexpand(True)
        row.append(pw2_entry)
        help_lbl = Gtk.Label(
            label="Salt opcional. Deja en blanco para mantener la actual / omitir.", xalign=0
        )
        help_lbl.add_css_class("dim-label")
        help_lbl.add_css_class("caption")
        row.append(help_lbl)
        self.fields_box.append(row)
        self.field_rows["password2"] = pw2_entry

    def _load_existing(self) -> None:
        async def fetch():
            from ...services import profile_store

            pwd = profile_store.get_cached_password(self.profile)
            return await rclone.config_dump(self.profile, config_password=pwd)

        def on_success(dump):
            data = dump.get(self.remote_name, {}) if isinstance(dump, dict) else {}
            self._initial = dict(data) if isinstance(data, dict) else {}
            rtype = data.get("type", "") if isinstance(data, dict) else ""
            if rtype and rtype in self.type_list:
                idx = self.type_list.index(rtype)
                self.type_combo.set_active(idx)
            elif rtype:
                self.type_list.append(rtype)
                self.type_combo.append_text(rtype)
                self.type_combo.set_active(len(self.type_list) - 1)
            self._on_type_changed(self.type_combo)
            # union upstreams -> rows
            if rtype == "union":
                upstreams_str = str(data.get("upstreams", "")).strip()
                tokens = upstreams_str.split() if upstreams_str else []
                for token in tokens:
                    token = token.strip()
                    if not token:
                        continue
                    if ":" in token:
                        remote, path = token.split(":", 1)
                        self._add_union_upstream_row(remote.strip(), path.strip())
                    else:
                        self._add_union_upstream_row(token.strip(), "")
                if not tokens:
                    self._add_union_upstream_row()
                if not tokens:
                    self._add_union_upstream_row()
            for key, widget in self.field_rows.items():
                if key not in data:
                    continue
                val = str(data[key])
                if isinstance(widget, Gtk.ComboBoxText):
                    if key == "remote":
                        val = val.rstrip(":").strip()
                    matched = False
                    for i in range(len(widget.get_model())):
                        if widget.get_model()[i][0] == val:
                            widget.set_active(i)
                            matched = True
                            break
                    if not matched:
                        widget.append_text(val)
                        widget.set_active(len(widget.get_model()) - 1)
                else:
                    widget.set_text(val)

        def on_error(exc):
            self.window.toast(f"Error cargando remoto: {exc}")

        run_async(fetch(), on_success=on_success, on_error=on_error)

    def _collect_opts(self) -> dict:
        opts = {}
        t = self.type_combo.get_active_text() or ""
        if t == "union":
            parts = []
            for item in getattr(self, "_union_upstream_rows", []):
                combo = item["combo"]
                entry = item["entry"]
                rname = combo.get_active_text()
                if not rname:
                    continue
                path = entry.get_text().strip()
                if path:
                    parts.append(f"{rname}:{path}")
                else:
                    parts.append(f"{rname}:")
            if parts:
                opts["upstreams"] = " ".join(parts)
        for key, widget in self.field_rows.items():
            if isinstance(widget, Gtk.ComboBoxText):
                val = widget.get_active_text()
                val = val.strip() if val else ""
            else:
                val = widget.get_text().strip()
            if val and key == "remote" and t == "crypt" and not val.endswith(":"):
                val = val + ":"
            if val:
                opts[key] = val
        return opts

    def _on_response(self, _dlg, response) -> None:
        if response != "save":
            self.close()
            return
        name = self.name_entry.get_text().strip()
        if not name:
            self.window.toast("El nombre es obligatorio")
            return
        rtype = self.type_combo.get_active_text() or ""
        opts = self._collect_opts()

        old_name = self.remote_name

        async def do():
            if self.editing and old_name:
                from ...services import profile_store as _ps

                _pwd = _ps.get_cached_password(self.profile)
                dump = await rclone.config_dump(self.profile, config_password=_pwd)
                base = dump.get(old_name, {}) if isinstance(dump, dict) else {}
                base_type = base.get("type", rtype) if isinstance(base, dict) else rtype
                # Preserve existing fields not shown in the form.
                merged = {}
                if isinstance(base, dict):
                    merged = {k: v for k, v in base.items() if k != "type"}
                # Drop unchanged values (avoids re-obscuring passwords).
                for k in list(opts.keys()):
                    if str(base.get(k, "")) == opts[k]:
                        del opts[k]
                merged.update(opts)
                if name != old_name:
                    await rclone.delete_remote(self.profile, old_name)
                    await rclone.create_remote(self.profile, name, base_type, merged)
                else:
                    if merged:
                        await rclone.update_remote(self.profile, name, merged)
            else:
                await rclone.create_remote(self.profile, name, rtype, opts)

        def ok(_):
            self.window.toast(f"Remoto '{name}' guardado")
            if self.on_saved:
                self.on_saved()
            self.close()

        def err(exc):
            self.window.toast(f"Error: {exc}")

        run_async(do(), on_success=ok, on_error=err)
