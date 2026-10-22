# SPDX-License-Identifier: GPL-3.0-or-later
"""Traduction des textes de l'interface (F-UX-02).

Les chaînes sources sont en français. Une langue est un catalogue JSON
`montar/locale/<langue>.json` (texte français → texte traduit) ; un module peut fournir le
sien dans `<module>/locale/<langue>.json`. Une chaîne absente du catalogue reste en
français. `N_()` marque une chaîne traduite plus tard (tables de libellés) sans la traduire.
"""
from __future__ import annotations

import json
import locale
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

SOURCE_LANGUAGE = "fr"
LANGUAGES = {"fr": "Français", "en": "English"}
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

_catalog: dict[str, str] = {}
_language = SOURCE_LANGUAGE


def _(text: str) -> str:
    return _catalog.get(text, text)


def N_(text: str) -> str:  # noqa: N802 - nom consacré (gettext)
    return text


def system_language() -> str:
    """Langue du système si montar la connaît, sinon l'anglais."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX"):
            code = value.split(":")[0][:2].lower()
            return code if code in LANGUAGES else "en"
    try:
        code = (locale.getlocale()[0] or "")[:2].lower()
    except ValueError:
        code = ""
    return code if code in LANGUAGES else SOURCE_LANGUAGE


def resolve(setting: str) -> str:
    """Langue effective d'un réglage (« system », « fr », « en »)."""
    return setting if setting in LANGUAGES else system_language()


def read_catalog(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("traductions illisibles (%s) : %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def set_language(language: str) -> str:
    """Active une langue (« system » accepté) ; renvoie la langue effective."""
    global _language
    _language = resolve(language)
    _catalog.clear()
    if _language != SOURCE_LANGUAGE:
        _catalog.update(read_catalog(LOCALE_DIR / f"{_language}.json"))
    return _language


def current_language() -> str:
    return _language


def add_module_translations(module_dir: Path) -> None:
    """Traductions fournies par un module, pour la langue active."""
    if _language == SOURCE_LANGUAGE:
        return
    path = module_dir / "locale" / f"{_language}.json"
    if path.exists():
        for key, value in read_catalog(path).items():
            _catalog.setdefault(key, value)
