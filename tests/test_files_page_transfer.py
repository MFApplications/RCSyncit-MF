from rcsyncitmf.ui.pages.files_page import FilesPage


class _Window:
    def toast(self, message):
        pass


def test_files_page_has_remotes_attribute():
    page = FilesPage(_Window())
    assert hasattr(page, "remotes")
    assert isinstance(page.remotes, list)


def test_transfer_dialog_does_not_raise(monkeypatch):
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    monkeypatch.setattr(Adw.AlertDialog, "present", lambda self, *a, **k: None)
    page = FilesPage(_Window())
    page.profile = None
    page.current_remote = "r1"
    page.remotes = ["r1", "r2"]
    page.current_path = ""
    # Should not raise AttributeError
    page._transfer_dialog("Copiar", "foo/bar", move=False)
