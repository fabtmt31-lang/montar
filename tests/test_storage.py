# SPDX-License-Identifier: GPL-3.0-or-later
"""Stockage & cache, réglages de sauvegarde."""
import json

from montar.core import storage
from montar.core.settings import Settings


def test_cache_size_and_clear(tmp_path):
    cache = tmp_path / "cache"
    (cache / "thumbnails").mkdir(parents=True)
    (cache / "thumbnails" / "a.jpg").write_bytes(b"x" * 1000)
    (cache / "timelapse").mkdir()
    (cache / "timelapse" / "b.mp4").write_bytes(b"y" * 3000)
    (cache / "logs").mkdir()
    (cache / "logs" / "montar.log").write_bytes(b"z" * 500)
    assert storage.cache_size(cache) == 4000
    assert storage.clear_cache(cache) == 4000
    assert storage.cache_size(cache) == 0
    assert sorted(p.name for p in cache.iterdir()) == ["logs"]  # journal gardé
    assert storage.clear_cache(tmp_path / "absent") == 0


def test_backups_usage_and_free_space(tmp_path):
    a = tmp_path / "A" / "A.montar"
    (a.parent / "sauvegardes").mkdir(parents=True)
    for i in range(3):
        (a.parent / "sauvegardes" / f"A {i}.montar").write_bytes(b"{}" * 50)
    b = tmp_path / "B" / "B.montar"
    b.parent.mkdir()
    assert storage.backups_usage([a, b, a]) == (3, 300)
    assert storage.free_space(tmp_path / "pas" / "encore") > 0


def test_settings_backup_interval(tmp_path):
    file = tmp_path / "s.json"
    file.write_text(json.dumps({"autosave": False, "backup_minutes": 7,
                                "preview_volume": 3.0}))
    s = Settings.load(file)
    assert (s.autosave, s.backup_minutes, s.preview_volume) == (False, 2, 1.0)
    file.write_text(json.dumps({"backup_minutes": 5}))
    assert Settings.load(file).backup_minutes == 5
