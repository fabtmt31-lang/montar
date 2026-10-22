# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface en anglais (F-UX-02) : catalogues complets, changement de langue."""
import importlib.util
import json
from pathlib import Path

import pytest

from montar import i18n
from montar.i18n import _

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("fr")


def _extractor():
    spec = importlib.util.spec_from_file_location("i18n_extract",
                                                  ROOT / "scripts" / "i18n_extract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogs_are_complete():
    missing = _extractor().missing()
    assert missing == {}, "chaînes sans traduction (scripts/i18n_extract.py) : " + \
        ", ".join(f"{p.name}: {len(v)}" for p, v in missing.items())


def test_placeholders_are_kept():
    import re
    catalogs = [ROOT / "src/montar/locale/en.json",
                *(ROOT / "src/montar/modules").glob("*/locale/en.json")]
    for catalog in catalogs:
        for source, text in json.loads(catalog.read_text(encoding="utf-8")).items():
            assert set(re.findall(r"\{[^}]*\}", source)) == set(re.findall(r"\{[^}]*\}", text)), \
                source


def test_switch_language(english, tmp_path):
    assert i18n.current_language() == "en"
    assert _("Annuler") == "Cancel" and _("texte inconnu") == "texte inconnu"
    from montar.plugins import ModuleManager, builtin_modules_dir

    ModuleManager(builtin_modules_dir(), tmp_path).load_all()
    assert _("Écho") == "Echo"  # catalogue du module
    i18n.set_language("fr")
    assert _("Annuler") == "Annuler"


def test_system_language(monkeypatch):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.resolve("system") == "fr"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.resolve("system") == "en"
    assert i18n.resolve("fr") == "fr"
