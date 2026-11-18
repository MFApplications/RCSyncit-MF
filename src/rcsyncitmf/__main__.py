"""Entry point for `python -m rcsyncitmf` and the `rcsyncitmf` console script."""

from __future__ import annotations

import os
import sys

# Apply language preference before importing GTK (best-effort).
try:
    from .config import load_settings

    _lang = str(load_settings().get("language", "auto") or "auto")
    if _lang and _lang != "auto":
        _locale = f"{_lang}_{_lang.upper()}.UTF-8"
        os.environ.setdefault("LANG", _locale)
        os.environ.setdefault("LANGUAGE", _lang)
except Exception:
    pass

# Initialize i18n (JSON-backed) before importing the app.
try:
    from .config import load_settings as _load_settings
    from .i18n import init as _i18n_init

    _i18n_init(str(_load_settings().get("language", "auto") or "auto"))
except Exception:
    pass

from .application import RCSyncitMFApplication


def main() -> int:
    app = RCSyncitMFApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
