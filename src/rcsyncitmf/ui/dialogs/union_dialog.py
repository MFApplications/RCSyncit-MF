"""Dialog to create a rclone 'union' remote from selected upstreams."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, Gtk

from ...i18n import _
from ...services import rclone
from ...ui.async_helper import run_async

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

POLICY_HINTS = {
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

FILENAME_ENCRYPTIONS = ["standard", "obfuscate", "off"]
DIRECTORY_ENCRYPTIONS = ["true", "false"]


class UnionDialog(Adw.AlertDialog):
    def __init__(
        self,
        window,
        profiles: list[Path],
        selected_profile: Path | None,
        available_remotes: list[str],
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(title="Nuevo union", body=None)
        try:
            self.set_content_width(760)
            self.set_content_height(620)
            self.set_resizable(True)
        except Exception:
            pass
        self.window = window
        self.profiles = list(profiles)
        self.profile = selected_profile
        self.available = list(available_remotes or [])
        self.on_saved = on_saved

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_hexpand(True)
        box.set_size_request(760, -1)

        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(560)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_child(box)

        # Profile selector
        prof_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prof_row.append(Gtk.Label(label=_("Perfil"), xalign=0))
        self.profile_combo = Gtk.ComboBoxText()
        for p in self.profiles:
            self.profile_combo.append_text(p.stem)
        if self.profile is not None and self.profile in self.profiles:
            idx = self.profiles.index(self.profile)
            self.profile_combo.set_active(idx)
        elif self.profiles:
            self.profile_combo.set_active(0)
            self.profile = self.profiles[0]
        self.profile_combo.set_hexpand(True)
        self.profile_combo.connect("changed", self._on_profile_changed)
        prof_row.append(self.profile_combo)
        box.append(prof_row)

        # Name
        name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_row.append(Gtk.Label(label=_("Nombre"), xalign=0))
        self.name_entry = Gtk.Entry()
        self.name_entry.set_hexpand(True)
        name_row.append(self.name_entry)
        box.append(name_row)

        # Upstreams
        box.append(Gtk.Label(label=_("Upstreams (remoto:/carpeta)"), xalign=0))
        help_lbl = Gtk.Label(
            label=_(
                "Añade uno o más upstreams. Cada uno puede apuntar a una carpeta concreta (ej. Almacen1:/almacen)."
            ),
            xalign=0,
        )
        help_lbl.add_css_class("dim-label")
        help_lbl.add_css_class("caption")
        help_lbl.set_wrap(True)
        box.append(help_lbl)

        self._union_upstream_rows: list[dict] = []
        self._union_refreshing = False
        self._union_upstream_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._union_upstream_box)

        add_btn = Gtk.Button(label=_("Añadir upstream"))
        add_btn.connect("clicked", lambda _b: self._add_union_upstream_row())
        box.append(add_btn)

        if self.available:
            self._add_union_upstream_row()

        # Policies
        for label, attr, default in [
            ("Action policy", "action_combo", "epall"),
            ("Create policy", "create_combo", "epmfs"),
            ("Search policy", "search_combo", "ff"),
        ]:
            r = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            r.append(Gtk.Label(label=f"{label} ({attr.replace('_combo', '_policy')})", xalign=0))
            combo = Gtk.ComboBoxText()
            for pol in POLICIES:
                combo.append_text(pol)
            combo.set_active(POLICIES.index(default) if default in POLICIES else 0)
            combo.set_hexpand(True)
            r.append(combo)
            hint = Gtk.Label(
                label=_(", ").join(f"{k}={v}" for k, v in POLICY_HINTS.items()), xalign=0
            )
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            hint.set_wrap(True)
            r.append(hint)
            box.append(r)
            setattr(self, attr, combo)

        # Optional encryption
        self.encrypt_check = Gtk.CheckButton(label=_("Encriptar este union"))
        box.append(self.encrypt_check)

        self.crypt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.crypt_box.set_visible(False)

        crypt_name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        crypt_name_row.append(Gtk.Label(label=_("Nombre del crypt"), xalign=0))
        self.crypt_name_entry = Gtk.Entry()
        self.crypt_name_entry.set_hexpand(True)
        self.crypt_name_entry.set_placeholder_text("ej. miunion_crypt")
        crypt_name_row.append(self.crypt_name_entry)
        self.crypt_box.append(crypt_name_row)

        fn_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        fn_row.append(Gtk.Label(label=_("Filename encryption"), xalign=0))
        self.fn_combo = Gtk.ComboBoxText()
        for v in FILENAME_ENCRYPTIONS:
            self.fn_combo.append_text(v)
        self.fn_combo.set_active(0)
        self.fn_combo.set_hexpand(True)
        fn_row.append(self.fn_combo)
        fn_help = Gtk.Label(
            label=_(
                "standard: cifra nombres; obfuscate: ofusca; off: no cifra nombres (directory_name_encryption no tiene efecto)."
            ),
            xalign=0,
        )
        fn_help.add_css_class("dim-label")
        fn_help.add_css_class("caption")
        fn_help.set_wrap(True)
        fn_row.append(fn_help)
        self.crypt_box.append(fn_row)

        dn_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        dn_row.append(Gtk.Label(label=_("Directory name encryption"), xalign=0))
        self.dn_combo = Gtk.ComboBoxText()
        for v in DIRECTORY_ENCRYPTIONS:
            self.dn_combo.append_text(v)
        self.dn_combo.set_active(0)
        self.dn_combo.set_hexpand(True)
        dn_row.append(self.dn_combo)
        dn_help = Gtk.Label(
            label=_("true: cifra nombres de carpetas; false: los deja intactos."), xalign=0
        )
        dn_help.add_css_class("dim-label")
        dn_help.add_css_class("caption")
        dn_help.set_wrap(True)
        dn_row.append(dn_help)
        self.crypt_box.append(dn_row)

        pwd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pwd_row.append(Gtk.Label(label=_("Contraseña"), xalign=0))
        self.crypt_pwd_entry = Gtk.Entry()
        self.crypt_pwd_entry.set_visibility(False)
        self.crypt_pwd_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.crypt_pwd_entry.set_hexpand(True)
        pwd_row.append(self.crypt_pwd_entry)
        self.crypt_box.append(pwd_row)

        pwd2_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pwd2_row.append(Gtk.Label(label=_("Contraseña 2 (salt, opcional)"), xalign=0))
        self.crypt_pwd2_entry = Gtk.Entry()
        self.crypt_pwd2_entry.set_visibility(False)
        self.crypt_pwd2_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.crypt_pwd2_entry.set_hexpand(True)
        pwd2_row.append(self.crypt_pwd2_entry)
        self.crypt_box.append(pwd2_row)

        salt_help = Gtk.Label(
            label=_(
                "La segunda contraseña (salt) fortalece la derivación de claves. Si la usas, debes recordarla siempre."
            ),
            xalign=0,
        )
        salt_help.add_css_class("dim-label")
        salt_help.add_css_class("caption")
        salt_help.set_wrap(True)
        self.crypt_box.append(salt_help)

        box.append(self.crypt_box)

        def _toggle_crypt(_btn):
            self.crypt_box.set_visible(self.encrypt_check.get_active())
            if self.encrypt_check.get_active() and not self.crypt_name_entry.get_text().strip():
                base = self.name_entry.get_text().strip() or "union"
                self.crypt_name_entry.set_text(f"{base}_crypt")

        self.encrypt_check.connect("toggled", _toggle_crypt)

        self.set_extra_child(scrolled)
        self.add_response("cancel", "Cancelar")
        self.add_response("create", "Crear")
        self.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("create")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)

    # ---------- upstream helpers ----------
    def _union_remotes(self) -> list[str]:
        return list(self.available)

    def _add_union_upstream_row(self, remote: str = "", path: str = "") -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        combo = Gtk.ComboBoxText()
        combo.set_hexpand(True)
        for name in self._union_remotes():
            combo.append_text(name)
        if remote and remote in self._union_remotes():
            combo.set_active(self._union_remotes().index(remote))
        elif self._union_remotes():
            combo.set_active(0)
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

    def _remove_union_upstream_row(self, row: Gtk.Box) -> None:
        self._union_upstream_box.remove(row)
        self._union_upstream_rows = [r for r in self._union_upstream_rows if r["row"] != row]

    # ---------- profile change ----------
    def _on_profile_changed(self, combo) -> None:
        idx = combo.get_active()
        if idx < 0 or idx >= len(self.profiles):
            return
        self.profile = self.profiles[idx]
        profile = self.profile
        if profile is None:
            return

        async def fetch():
            return await rclone.list_remotes(profile)

        def on_success(names):
            self.available = list(names or [])
            # rebuild upstream rows
            for item in list(self._union_upstream_rows):
                self._union_upstream_box.remove(item["row"])
            self._union_upstream_rows.clear()
            if self.available:
                self._add_union_upstream_row()

        def on_error(exc):
            self.window.toast(_("Error: {exc}").format(exc=exc))

        run_async(fetch(), on_success=on_success, on_error=on_error)

    # ---------- response ----------
    def _collect_upstreams(self) -> list[str]:
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
        return parts

    def _on_response(self, _dlg, response) -> None:
        if response != "create":
            self.close()
            return
        if self.profile is None:
            self.window.toast(_("Selecciona un perfil"))
            return
        profile = self.profile
        name = self.name_entry.get_text().strip()
        if not name:
            self.window.toast(_("El nombre es obligatorio"))
            return
        parts = self._collect_upstreams()
        if not parts:
            self.window.toast(_("Añade al menos un upstream"))
            return

        opts = {
            "upstreams": " ".join(parts),
            "action_policy": self.action_combo.get_active_text() or "epall",
            "create_policy": self.create_combo.get_active_text() or "epmfs",
            "search_policy": self.search_combo.get_active_text() or "ff",
        }

        encrypt = self.encrypt_check.get_active()
        crypt_name = self.crypt_name_entry.get_text().strip() if encrypt else ""
        if encrypt:
            if not crypt_name:
                crypt_name = f"{name}_crypt"
                self.crypt_name_entry.set_text(crypt_name)
            pwd = self.crypt_pwd_entry.get_text()
            if not pwd:
                self.window.toast(_("La contraseña es obligatoria para encriptar"))
                return
            pwd2 = self.crypt_pwd2_entry.get_text().strip()
            fn_enc = self.fn_combo.get_active_text() or "standard"
            dn_enc = self.dn_combo.get_active_text() or "true"

        async def do():
            await rclone.create_remote(profile, name, "union", opts)
            if encrypt:
                crypt_opts = {
                    "remote": f"{name}:",
                    "filename_encryption": fn_enc,
                    "directory_name_encryption": dn_enc,
                    "password": pwd,
                }
                if pwd2:
                    crypt_opts["password2"] = pwd2
                await rclone.create_remote(profile, crypt_name, "crypt", crypt_opts)

        def ok(_result):
            try:
                from ...services import mount_manager

                mount_manager._invalidate_profile_dump_cache(self.profile)
            except Exception:
                pass
            if encrypt:
                self.window.toast(f"Union '{name}' y crypt '{crypt_name}' creados")
            else:
                self.window.toast(f"Union '{name}' creado")
            if self.on_saved:
                self.on_saved()
            self.close()

        def err(exc):
            self.window.toast(_("Error: {exc}").format(exc=exc))

        run_async(do(), on_success=ok, on_error=err)
