# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalogue de modules en ligne (F-MOD-08)."""
import json
from pathlib import Path

import pytest

from montar.core import catalog

ROOT = Path(__file__).resolve().parent.parent


def _index(**over):
    entry = {"id": "exemple.negatif", "name": "Négatif", "version": "1.1.0",
             "description": "d", "author": "a", "license": "GPL", "api_version": "1.1",
             "url": "modules/x.montar-module", "sha256": "0" * 64}
    entry.update(over)
    return json.dumps({"format": 1, "modules": [entry, {"id": "incomplet"}]}).encode()


def test_parse_index_resolves_urls_and_skips_bad_entries():
    entries = catalog.parse_index(_index(), "https://ex.org/cat/index.json")
    assert [e.id for e in entries] == ["exemple.negatif"]
    assert entries[0].url == "https://ex.org/cat/modules/x.montar-module"
    assert catalog.parse_index(_index(url="http://ex.org/x"), "https://ex.org/i.json") == []
    with pytest.raises(catalog.CatalogError):
        catalog.parse_index(b"{}", "https://ex.org/i.json")
    with pytest.raises(catalog.CatalogError):
        catalog.fetch("http://ex.org/index.json")  # HTTPS obligatoire


def test_status():
    entry = catalog.parse_index(_index(), "https://ex.org/i.json")[0]
    assert catalog.status(entry, {}, (1, 4)) == "available"
    assert catalog.status(entry, {"exemple.negatif": "1.0.0"}, (1, 4)) == "update"
    assert catalog.status(entry, {"exemple.negatif": "1.1.0"}, (1, 4)) == "installed"
    newer = catalog.parse_index(_index(api_version="1.9"), "https://ex.org/i.json")[0]
    assert catalog.status(newer, {}, (1, 4)) == "incompatible"


def test_download_checks_digest(tmp_path, monkeypatch):
    archive = next((ROOT / "catalogue" / "modules").glob("*.montar-module"))
    monkeypatch.setattr(catalog, "_read", lambda url, limit, timeout: archive.read_bytes())
    index = json.loads((ROOT / "catalogue" / "index.json").read_text())
    good = catalog.parse_index(json.dumps(index).encode(), "https://ex.org/index.json")[0]
    path = catalog.download(good, tmp_path)
    assert path.read_bytes() == archive.read_bytes()
    index["modules"][0]["sha256"] = "f" * 64
    bad = catalog.parse_index(json.dumps(index).encode(), "https://ex.org/index.json")[0]
    with pytest.raises(catalog.CatalogError):
        catalog.download(bad, tmp_path / "x")


def test_published_catalogue_is_valid():
    """catalogue/index.json (publié avec montar) correspond à ses archives."""
    import hashlib

    data = (ROOT / "catalogue" / "index.json").read_bytes()
    entries = catalog.parse_index(data, catalog.DEFAULT_URL)
    assert entries
    for entry in entries:
        name = entry.url.rsplit("/", 1)[1]
        archive = ROOT / "catalogue" / "modules" / name
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry.sha256
