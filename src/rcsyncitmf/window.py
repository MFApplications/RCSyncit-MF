"""Main application window (GNOME HIG layout, sidebar-driven)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from pathlib import Path

from gi.repository import Adw, Gdk, Gtk

from .ui.pages.mounts_page import MountsPage
from .ui.pages.profiles_page import ProfilesPage
from .ui.pages.remotes_page import RemotesPage
from .ui.pages.settings_page import SettingsPage
from .ui.pages.unions_page import UnionsPage


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title("RCSyncitMF")
        self.set_default_size(1100, 720)

        # Load custom CSS
        from pathlib import Path as _Path

        css_path = _Path(__file__).parent / "resources" / "style.css"
        if css_path.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(css_path))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        self.current_profile: Path | None = None
        self.toast_overlay = Adw.ToastOverlay()

        toolbar_view = Adw.ToolbarView()

        # Headerbar (top): title (left) + window buttons (right)
        header = Adw.HeaderBar()
        self.title_label = Gtk.Label(label="Perfiles", xalign=0)
        self.title_label.add_css_class("title")
        header.pack_start(self.title_label)
        toolbar_view.add_top_bar(header)

        # Content stack
        self.stack = Adw.ViewStack()

        self.profiles_page = ProfilesPage(self)
        self.remotes_page = RemotesPage(self)
        self.unions_page = UnionsPage(self)
        self.mounts_page = MountsPage(self)
        self.settings_page = SettingsPage(self)
        self.stack.add_titled(self.profiles_page, "profiles", "Perfiles")
        self.stack.add_titled(self.remotes_page, "remotes", "Remotos")
        self.stack.add_titled(self.unions_page, "unions", "Unions")
        self.stack.add_titled(self.mounts_page, "mounts", "Mounts")
        self.stack.add_titled(self.settings_page, "settings", "Ajustes")

        # Drag & drop: import .conf files
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        # Sidebar
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sidebar_box.add_css_class("navigation-sidebar")
        sidebar_box.set_margin_top(8)
        sidebar_box.set_margin_bottom(12)
        sidebar_box.set_margin_start(8)
        sidebar_box.set_margin_end(8)

        # Top row: hamburger menu
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        top_row.set_halign(Gtk.Align.START)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("Menú")
        popover = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu_box.set_margin_top(6)
        menu_box.set_margin_bottom(6)
        menu_box.set_margin_start(6)
        menu_box.set_margin_end(6)

        def make_menu_item(label: str, callback) -> Gtk.Button:
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.set_halign(Gtk.Align.FILL)
            b.connect("clicked", callback)
            return b

        menu_box.append(make_menu_item("Nuevo perfil", lambda _b: self._menu_new_profile()))
        menu_box.append(
            make_menu_item("Importar rclone.conf", lambda _b: self._menu_import_default())
        )
        menu_box.append(make_menu_item("Preferencias", lambda _b: self._menu_preferences()))
        menu_box.append(make_menu_item("Atajos de teclado", lambda _b: self._menu_shortcuts()))
        menu_box.append(make_menu_item("Acerca de", lambda _b: self._menu_about()))
        popover.set_child(menu_box)
        menu_btn.set_popover(popover)
        top_row.append(menu_btn)

        sidebar_box.append(top_row)

        self.profile_label = Gtk.Label(label="Sin perfil activo", xalign=0)
        self.profile_label.add_css_class("dim-label")
        self.profile_label.add_css_class("caption")
        sidebar_box.append(self.profile_label)

        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.add_css_class("navigation-sidebar")
        sections = [
            ("profiles", "Perfiles", "document-properties-symbolic"),
            ("remotes", "Remotos", "network-server-symbolic"),
            ("unions", "Unions", "folder-remote-symbolic"),
            ("mounts", "Mounts", "drive-harddisk-symbolic"),
            ("settings", "Ajustes", "preferences-system-symbolic"),
        ]
        for key, label, icon in sections:
            row = Gtk.ListBoxRow()
            rb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            rb.set_margin_top(6)
            rb.set_margin_bottom(6)
            rb.set_margin_start(8)
            rb.set_margin_end(8)
            img = Gtk.Image.new_from_icon_name(icon)
            rb.append(img)
            lbl = Gtk.Label(label=label, xalign=0, hexpand=True)
            rb.append(lbl)
            row.set_child(rb)
            row._key = key
            self.sidebar_list.append(row)

        # Sidebar list (sections) takes available space
        self.sidebar_list.set_vexpand(True)
        sidebar_box.append(self.sidebar_list)

        self.sidebar_list.connect("row-selected", self._on_sidebar_selected)
        first = self.sidebar_list.get_row_at_index(0)
        if first is not None:
            self.sidebar_list.select_row(first)

        # Wrap sidebar in WindowHandle for dragging the window
        window_handle = Gtk.WindowHandle()
        window_handle.set_child(sidebar_box)

        sidebar_page = Adw.NavigationPage.new(window_handle, "Navegación")

        split = Adw.OverlaySplitView()
        split.set_sidebar(sidebar_page)
        split.set_content(self.stack)
        split.set_sidebar_width_fraction(0.20)
        split.set_show_sidebar(True)

        toolbar_view.set_content(split)
        self.toast_overlay.set_child(toolbar_view)
        self.set_content(self.toast_overlay)

        # Keyboard shortcut: Ctrl+Q
        controller = Gtk.ShortcutController()
        trigger_q = Gtk.ShortcutTrigger.parse_string("<Control>q")
        shortcut_q = Gtk.Shortcut.new(
            trigger_q,
            Gtk.CallbackAction.new(lambda _w, _v: self.close() or True),
        )
        controller.add_shortcut(shortcut_q)
        self.add_controller(controller)
        _ = Gdk.Display.get_default()

    # --- Drag & drop handler ---
    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = []
        if isinstance(value, Gdk.FileList):
            files = list(value.get_files())
        elif isinstance(value, list):
            files = value
        for f in files:
            path = Path(f.get_path()) if hasattr(f, "get_path") else Path(str(f))
            if path.suffix.lower() != ".conf":
                continue
            try:
                self._import_profile(path)
            except Exception as exc:
                self.toast(f"Error importando {path.name}: {exc}")
        self.profiles_page.refresh()
        return True

    def _import_profile(self, src: Path) -> None:
        import asyncio

        from .services import profile_store, rclone

        dst = profile_store.import_profile_unique(src)
        # Detect accounts/unions
        try:
            loop = asyncio.new_event_loop()
            dump = loop.run_until_complete(rclone.config_dump(dst))
            loop.close()
            remotes = list(dump.keys()) if isinstance(dump, dict) else []
            unions = [
                n for n, d in dump.items() if isinstance(d, dict) and d.get("type") == "union"
            ]
            self.toast(f"Importado {dst.name}: {len(remotes)} remotos, {len(unions)} unions")
        except Exception:
            self.toast(f"Importado {dst.name}")

    # --- Default rclone.conf detection (called from application) ---
    def check_default_rclone_config(self) -> None:
        from .services import profile_store

        default = profile_store.detect_default_config()
        if default is None:
            return
        # Ask user
        dlg = Adw.AlertDialog.new(
            "rclone.conf detectado",
            f"Se encontró {default}. ¿Importarlo como perfil?",
        )
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("import", "Importar")
        dlg.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("import")
        dlg.set_close_response("cancel")

        def on_response(d, response):
            if response == "import":
                try:
                    self._import_profile(default)
                    self.profiles_page.refresh()
                except Exception as exc:
                    self.toast(f"Error: {exc}")
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_response)
        dlg.present(self)

    def _on_sidebar_selected(self, _lb, row) -> None:
        if row is None:
            return
        key = getattr(row, "_key", None)
        if key is not None:
            self.stack.set_visible_child_name(key)
            if key == "mounts":
                self.mounts_page.refresh()
            # Update headerbar title
            labels = {
                "profiles": "Perfiles",
                "remotes": "Remotos",
                "unions": "Unions",
                "mounts": "Mounts",
                "settings": "Ajustes",
            }
            self.title_label.set_text(labels.get(key, key))

    def set_current_profile(self, profile: Path | None) -> None:
        self.current_profile = profile
        if profile is None:
            self.profile_label.set_text("Sin perfil activo")
        else:
            self.profile_label.set_text(profile.stem)
        self.remotes_page.set_profile(profile)
        self.unions_page.set_profile(profile)
        self.mounts_page.set_profile(profile)
        self.mounts_page.refresh()

    def toast(self, message: str) -> None:
        t = Adw.Toast(title=message)
        self.toast_overlay.add_toast(t)

    def ask_profile_password(self, profile: Path, on_ok) -> None:
        from .services import profile_store

        dlg = Adw.AlertDialog.new(f"Contraseña para {profile.stem}", "El perfil está encriptado.")
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.set_placeholder_text("contraseña")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.append(entry)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("ok", "Aceptar")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")

        def on_resp(d, resp):
            if resp == "ok":
                pwd = entry.get_text()
                profile_store.cache_password(profile, pwd)
                on_ok(pwd)
            d.close() if hasattr(d, "close") else None

        dlg.connect("response", on_resp)
        dlg.present(self)

    # --- Hamburger menu actions ---
    def _menu_new_profile(self) -> None:
        self.profiles_page._on_new(None)

    def _menu_import_default(self) -> None:
        self.check_default_rclone_config()

    def _menu_preferences(self) -> None:
        self.stack.set_visible_child_name("settings")
        i = 0
        while True:
            r = self.sidebar_list.get_row_at_index(i)
            if r is None:
                break
            if getattr(r, "_key", None) == "settings":
                self.sidebar_list.select_row(r)
                break
            i += 1

    def _menu_shortcuts(self) -> None:
        dlg = Adw.AlertDialog.new(
            "Atajos de teclado",
            "Ctrl+Q — Salir",
        )
        dlg.add_response("ok", "OK")
        dlg.present(self)

    def _menu_about(self) -> None:
        dlg = Adw.AboutDialog.new()
        dlg.set_application_name("RCSyncitMF")
        dlg.set_application_icon("com.rcsyncitmf.app")
        dlg.set_version("0.1.0")
        dlg.set_developer_name("RCSyncitMF")
        dlg.set_comments("Gestor GNOME para rclone con multi-config y union sync.")
        dlg.present(self)
