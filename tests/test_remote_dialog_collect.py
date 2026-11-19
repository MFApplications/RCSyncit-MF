import tempfile
from pathlib import Path

from rcsyncitmf.ui.dialogs.remote_dialog import RemoteDialog


class _Window:
    def toast(self, message):
        pass


def test_collect_opts_returns_dict():
    profile = Path(tempfile.mkdtemp()) / "p.conf"
    profile.write_text("", encoding="utf-8")
    dlg = RemoteDialog(_Window(), profile, None)
    # Switch to crypt type to exercise _build_crypt_fields.
    if "crypt" in dlg.type_list:
        dlg.type_combo.set_active(dlg.type_list.index("crypt"))
    opts = dlg._collect_opts()
    assert isinstance(opts, dict)
