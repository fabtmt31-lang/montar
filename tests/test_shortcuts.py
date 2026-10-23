# SPDX-License-Identifier: GPL-3.0-or-later
"""Raccourcis clavier personnalisables (F-UX-07)."""
import json

from montar.core import shortcuts
from montar.core.settings import Settings


def test_defaults_aliases_and_overrides():
    assert shortcuts.keys_for({}, "redo") == ["Ctrl+Shift+Z", "Ctrl+Y"]
    assert shortcuts.keys_for({"redo": "Ctrl+R"}, "redo") == ["Ctrl+R"]
    assert shortcuts.keys_for({"split": ""}, "split") == []
    assert shortcuts.current({"split": ""}, "split") == ""
    assert not shortcuts.conflicts({})  # les touches par défaut sont toutes distinctes
    assert shortcuts.conflicts({"split": "M"}) == {"m": ["split", "marker"]}


def test_settings_keep_only_valid_overrides(tmp_path):
    file = tmp_path / "s.json"
    file.write_text(json.dumps({"shortcuts": {"split": "X", "inconnu": "Y", "save": 3,
                                              "export": "Ctrl+E"}}))
    assert Settings.load(file).shortcuts == {"split": "X"}
    s = Settings(shortcuts={"marker": "Ctrl+M"})
    s.save(file)
    assert Settings.load(file).shortcuts == {"marker": "Ctrl+M"}
