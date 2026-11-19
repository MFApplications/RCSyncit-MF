"""Settings page backed by ~/.config/rcsyncitmf/settings.toml."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import contextlib
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, Gtk

from ... import __version__
from ...config import load_settings, save_settings
from ...i18n import _
from ...services import mount_manager

LANGUAGES = ["Automático", "Español", "Inglés"]
LANGUAGE_CODES = ["auto", "es", "en"]


class SettingsPage(Gtk.Box):
    """Tabbed settings view (General / Auto-sync / Storage / Language)."""

    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.settings = load_settings()
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_spacing(8)

        switcher = Adw.ViewSwitcher()
        stack = Adw.ViewStack()
        stack.set_vexpand(True)
        switcher.set_stack(stack)
        self.append(switcher)
        self.append(stack)

        # ---------- Generales ----------
        general_page = Adw.PreferencesPage()
        general_page.set_title(_("Generales"))

        lang_group = Adw.PreferencesGroup(title=_("Idioma"))
        general_page.add(lang_group)
        self.language_row = Adw.ComboRow()
        self.language_row.set_title(_("Idioma de la interfaz"))
        self.language_row.set_subtitle(_("Automático usa la configuración del sistema"))
        model = Gtk.StringList.new(LANGUAGES)
        self.language_row.set_model(model)
        code = str(self.settings.get("language", "auto"))
        idx = LANGUAGE_CODES.index(code) if code in LANGUAGE_CODES else 0
        self.language_row.set_selected(idx)
        lang_group.add(self.language_row)

        general_group = Adw.PreferencesGroup(title=_("General"))
        general_page.add(general_group)
        self.rclone_bin_row = Adw.EntryRow()
        self.rclone_bin_row.set_title(_("Binario de rclone"))
        self.rclone_bin_row.set_text(str(self.settings.get("rclone_bin", "rclone")))
        general_group.add(self.rclone_bin_row)

        storage_group = Adw.PreferencesGroup(title=_("Almacenamiento"))
        general_page.add(storage_group)
        self.profiles_dir_row = Adw.EntryRow()
        self.profiles_dir_row.set_title(_("Directorio de perfiles"))
        self.profiles_dir_row.set_text(str(self.settings.get("profiles_dir", "")))
        browse_btn = Gtk.Button(label=_("Examinar"))
        browse_btn.add_css_class("flat")
        browse_btn.connect("clicked", self._browse_profiles_dir)
        self.profiles_dir_row.add_suffix(browse_btn)
        storage_group.add(self.profiles_dir_row)

        mounts_group = Adw.PreferencesGroup(title=_("Mounts"))
        general_page.add(mounts_group)

        _is_default = not str(self.settings.get("mounts_dir", "") or "").strip()

        self.mounts_default_switch = Adw.SwitchRow()
        self.mounts_default_switch.set_title(_("Usar ubicación por defecto"))
        self.mounts_default_switch.set_subtitle(_("Ubicación estándar del sistema"))
        self.mounts_default_switch.set_active(_is_default)
        mounts_group.add(self.mounts_default_switch)

        self.mounts_dir_row = Adw.EntryRow()
        self.mounts_dir_row.set_title(_("Directorio personalizado"))
        self.mounts_dir_row.set_text(str(self.settings.get("mounts_dir", "")))
        with contextlib.suppress(Exception):
            self.mounts_dir_row.set_placeholder_text(str(mount_manager.default_mounts_base()))
        browse_btn = Gtk.Button(label=_("Examinar"))
        browse_btn.add_css_class("flat")
        browse_btn.connect("clicked", self._browse_mounts_dir)
        self.mounts_dir_row.add_suffix(browse_btn)
        reset_btn = Gtk.Button(label=_("Restaurar default"))
        reset_btn.add_css_class("flat")
        reset_btn.connect("clicked", self._restore_default_mounts_dir)
        self.mounts_dir_row.add_suffix(reset_btn)
        mounts_group.add(self.mounts_dir_row)

        self.mounts_effective_row = Adw.ActionRow()
        self.mounts_effective_row.set_title(_("Ubicación efectiva"))
        self.mounts_effective_row.set_subtitle(str(mount_manager.default_mounts_base()))
        mounts_group.add(self.mounts_effective_row)

        self.mounts_dir_row.set_sensitive(not _is_default)
        self.mounts_default_switch.connect("notify::active", self._on_mounts_default_toggled)
        self.mounts_dir_row.connect("changed", self._update_mounts_effective)
        self._update_mounts_effective()

        stack.add_titled(general_page, "general", _("Generales"))

        # ---------- Sincronización ----------
        sync_page = Adw.PreferencesPage()
        sync_page.set_title(_("Sincronización"))

        sync_group = Adw.PreferencesGroup(title=_("Sincronización"))
        sync_page.add(sync_group)
        self.concurrency_row = Adw.SpinRow.new_with_range(1, 32, 1)
        self.concurrency_row.set_title(_("Concurrencia"))
        self.concurrency_row.set_subtitle(_("Operaciones paralelas contra las nubes"))
        self.concurrency_row.set_value(self.settings.get("concurrency", 4))
        sync_group.add(self.concurrency_row)

        self.depth_row = Adw.SpinRow.new_with_range(0, 10, 1)
        self.depth_row.set_title(_("Profundidad"))
        self.depth_row.set_subtitle(_("0 = todos los directorios; >0 = niveles a sincronizar"))
        self.depth_row.set_value(self.settings.get("sync_depth", 0))
        sync_group.add(self.depth_row)

        autosync_group = Adw.PreferencesGroup(title=_("Sincronización automática"))
        sync_page.add(autosync_group)
        self.autosync_interval_row = Adw.SpinRow.new_with_range(0, 1440, 1)
        self.autosync_interval_row.set_title(_("Intervalo (minutos)"))
        self.autosync_interval_row.set_subtitle(_("0 desactiva la sincronización automática"))
        self.autosync_interval_row.set_value(
            int(self.settings.get("auto_sync_interval", 300)) // 60
        )
        autosync_group.add(self.autosync_interval_row)

        stack.add_titled(sync_page, "sync", _("Sincronización"))

        # ---------- Info ----------
        info_page = Adw.PreferencesPage()
        info_page.set_title(_("Info"))

        icon_group = Adw.PreferencesGroup()
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_margin_top(12)
        icon_box.set_margin_bottom(12)
        from pathlib import Path as _Path

        _logo_path = (
            _Path(__file__).resolve().parent.parent.parent / "resources" / "RCSyncitMF-logo.png"
        )
        if _logo_path.exists():
            icon_label = Gtk.Picture.new_for_filename(str(_logo_path))
            icon_label.set_size_request(128, 128)
            icon_label.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
            icon_label.set_can_shrink(True)
        else:
            icon_label = Gtk.Label(label="R")
            icon_label.add_css_class("title-1")
        icon_box.append(icon_label)
        name_label = Gtk.Label(label="RCSyncitMF")
        name_label.add_css_class("title-3")
        icon_box.append(name_label)
        version_label = Gtk.Label(label=str(__version__))
        version_label.add_css_class("dim-label")
        icon_box.append(version_label)
        icon_group.add(icon_box)
        info_page.add(icon_group)

        about_group = Adw.PreferencesGroup(title=_("Acerca de"))
        info_page.add(about_group)

        app_row = Adw.ActionRow()
        app_row.set_title(_("Aplicación"))
        app_row.set_subtitle("RCSyncitMF")
        about_group.add(app_row)

        version_row = Adw.ActionRow()
        version_row.set_title(_("Versión"))
        version_row.set_subtitle(str(__version__))
        about_group.add(version_row)

        dev_row = Adw.ActionRow()
        dev_row.set_title(_("Desarrollado por"))
        dev_row.set_subtitle("Sbtn_MF@MFApplications")
        about_group.add(dev_row)

        # Botón extra de Ko-fi centrado debajo de "Acerca de".
        support_group = Adw.PreferencesGroup(title=_("Soporte"))
        info_page.add(support_group)

        ko_fi_path = (
            Path(__file__).resolve().parent.parent.parent
            / "resources"
            / "support_me_on_kofi_badge_blue.png"
        )
        if ko_fi_path.exists():
            # Mostrar la imagen con su tamaño original (sin reescalar) y sin botón.
            support_image = Gtk.Picture.new_for_filename(str(ko_fi_path))
            support_image.set_can_shrink(True)
            support_image.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        else:
            support_image = Gtk.Image.new_from_icon_name("heart-outline-symbolic")

        support_image.set_size_request(272, 144)
        support_image.set_overflow(Gtk.Overflow.VISIBLE)
        support_image.set_halign(Gtk.Align.CENTER)
        support_image.set_margin_top(4)
        support_image.set_margin_bottom(4)
        support_image.set_tooltip_text(_("Apoyar en Ko-fi"))

        click = Gtk.GestureClick()
        click.connect(
            "pressed",
            lambda *_args: Gio.AppInfo.launch_default_for_uri(
                "https://ko-fi.com/mfapplications", None
            ),
        )
        support_image.add_controller(click)
        with contextlib.suppress(Exception):
            support_image.set_cursor(Gdk.Cursor.new_from_name("pointer"))

        support_group.add(support_image)

        stack.add_titled(info_page, "info", _("Info"))

        # ---------- Apply button ----------
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(12)
        btn_box.set_margin_bottom(12)
        btn_box.set_margin_start(12)
        btn_box.set_margin_end(12)
        apply_btn = Gtk.Button(label=_("Aplicar"))
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._apply)
        btn_box.append(apply_btn)
        self.append(btn_box)

    def _browse_profiles_dir(self, _btn=None) -> None:
        dialog = Gtk.FileDialog(title=_("Seleccionar directorio de perfiles"))

        def on_folder(d, res):
            try:
                folder = d.select_folder_finish(res)
            except Exception:
                return
            if folder is not None and folder.get_path():
                self.profiles_dir_row.set_text(folder.get_path())

        dialog.select_folder(self.window, None, on_folder)

    def _browse_mounts_dir(self, _btn=None) -> None:
        dialog = Gtk.FileDialog(title=_("Seleccionar directorio de mounts"))

        def on_folder(d, res):
            try:
                folder = d.select_folder_finish(res)
            except Exception:
                return
            if folder is not None and folder.get_path():
                self.mounts_dir_row.set_text(folder.get_path())

        dialog.select_folder(self.window, None, on_folder)

    def _restore_default_mounts_dir(self, *_args) -> None:
        self.mounts_dir_row.set_text("")
        self.mounts_default_switch.set_active(True)

    def _on_mounts_default_toggled(self, *_args) -> None:
        active = self.mounts_default_switch.get_active()
        self.mounts_dir_row.set_sensitive(not active)
        if active:
            self.mounts_dir_row.set_text("")
        self._update_mounts_effective()

    def _update_mounts_effective(self, *_args) -> None:
        raw = self.mounts_dir_row.get_text().strip() if self.mounts_dir_row.get_sensitive() else ""
        if raw:
            from pathlib import Path as _P

            cand = _P(raw).expanduser()
            eff = str(cand)
        else:
            eff = str(mount_manager.default_mounts_base())
        self.mounts_effective_row.set_subtitle(eff)

    def _apply(self, *_args) -> None:
        old_lang = str(self.settings.get("language", "auto"))
        self.settings["concurrency"] = int(self.concurrency_row.get_value())
        self.settings["sync_depth"] = int(self.depth_row.get_value())
        self.settings["rclone_bin"] = self.rclone_bin_row.get_text().strip() or "rclone"
        raw_profiles = self.profiles_dir_row.get_text().strip()
        if not raw_profiles:
            from ...config import PROFILES_DIR as _DEFAULT_PROFILES_DIR

            raw_profiles = str(_DEFAULT_PROFILES_DIR)
        self.settings["profiles_dir"] = raw_profiles
        if self.mounts_default_switch.get_active():
            self.settings["mounts_dir"] = ""
        else:
            self.settings["mounts_dir"] = self.mounts_dir_row.get_text().strip()
        self.settings["auto_sync_interval"] = int(self.autosync_interval_row.get_value()) * 60
        lang_idx = self.language_row.get_selected()
        new_lang = old_lang
        if 0 <= lang_idx < len(LANGUAGE_CODES):
            new_lang = LANGUAGE_CODES[lang_idx]
            self.settings["language"] = new_lang
        save_settings(self.settings)
        try:
            from ...services import rclone as _rclone

            _rclone.invalidate_rclone_bin_cache()
        except Exception:
            pass
        if new_lang != old_lang:
            dlg = Adw.AlertDialog.new(
                _("Idioma cambiado"),
                _("Es necesario reiniciar la aplicación para aplicar el nuevo idioma."),
            )
            dlg.add_response("later", _("Más tarde"))
            dlg.add_response("quit", _("Cerrar ahora"))
            dlg.set_response_appearance("quit", Adw.ResponseAppearance.SUGGESTED)
            dlg.set_default_response("later")
            dlg.set_close_response("later")

            def on_resp(d, resp):
                if resp == "quit":
                    app = self.window.get_application()
                    if app is not None:
                        app.quit()
                d.close() if hasattr(d, "close") else None

            dlg.connect("response", on_resp)
            dlg.present(self.window)
        else:
            self.window.toast(_("Ajustes aplicados"))
