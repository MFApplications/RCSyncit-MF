"""Lightweight internationalization helpers (JSON-backed)."""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent / "locales"
_TRANSLATIONS: dict[str, str] = {}
_CURRENT = "auto"


def _resolve_language(language: str) -> str:
    if language and language != "auto":
        return language
    # Detect from environment / system.
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val:
            code = val.split("_")[0].split(".")[0].lower()
            if code in ("es", "en"):
                return code
    try:
        code = (locale.getlocale()[0] or "").split("_")[0].lower()
    except Exception:
        code = ""
    if code in ("es", "en"):
        return code
    return "es"


def init(language: str = "auto") -> str:
    global _CURRENT, _TRANSLATIONS
    _CURRENT = _resolve_language(language)
    path = _LOCALES_DIR / f"{_CURRENT}.json"
    if not path.exists():
        path = _LOCALES_DIR / "es.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _TRANSLATIONS = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        _TRANSLATIONS = {}
    return _CURRENT


def _(text: str) -> str:
    return _TRANSLATIONS.get(text, text)


def current_language() -> str:
    return _CURRENT
