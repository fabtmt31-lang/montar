# SPDX-License-Identifier: GPL-3.0-or-later
"""Squelette de module (montar --new-module), archive (--pack-module), installation."""
import json
import zipfile

import pytest

from montar.plugins import ModuleError, ModuleManager, builtin_modules_dir
from montar.plugins.devtools import TEMPLATES, new_module, pack_module


class _Ctx:
    width, height, fps = 8, 4, 25

    def __init__(self, cache):
        self.cache_dir = cache


def test_skeleton_with_every_type_loads(tmp_path):
    folder = new_module(tmp_path / "Mon Module", kinds=list(TEMPLATES), author="Moi")
    data = json.loads((folder / "module.json").read_text())
    assert data["id"] == "mon-module" and data["api_version"] == "1.4"
    manager = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    info = manager.install_folder(folder)
    assert info.active, info.error
    api = info.loaded
    assert [len(x) for x in (api.effects, api.audio_effects, api.transitions, api.generators,
                             api.graphics, api.export_formats, api.tools)] == [1] * 7
    effect = api.effects[0]
    assert effect.filters(effect.defaults())[0][0] == "avfilter.lutrgb"
    target = tmp_path / "fond.bmp"
    gen = api.generators[0]
    gen.generate(_Ctx(tmp_path), gen.defaults(), target)
    assert target.read_bytes()[:2] == b"BM" and len(target.read_bytes()) == 54 + 4 * 24
    assert api.graphics[0].path.exists()
    with pytest.raises(ModuleError):
        new_module(folder)  # dossier non vide
    with pytest.raises(ModuleError):
        new_module(tmp_path / "x", kinds=["inconnu"])


def test_pack_install_and_linked_development(tmp_path):
    folder = new_module(tmp_path / "demo", kinds=["effet-video"])
    archive = pack_module(folder)
    assert archive.name == "demo-0.1.0.montar-module"
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["demo/__init__.py", "demo/module.json"]
    manager = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    assert manager.install(archive).active

    # module lié : une modification est prise en compte en rechargeant
    linked = manager.install_folder(folder, link=True)
    assert linked.path.is_symlink() and linked.active
    code = (folder / "__init__.py").read_text().replace('name = "Négatif"', 'name = "Inversé"')
    (folder / "__init__.py").write_text(code)
    manager.reload()
    assert manager.modules["demo"].loaded.effects[0].name == "Inversé"
    manager.uninstall("demo")
    assert folder.exists() and "demo" not in manager.modules  # seul le lien est retiré


def test_newer_api_minor_is_refused(tmp_path):
    from montar.api import API_VERSION
    from montar.plugins.manager import read_manifest

    folder = new_module(tmp_path / "futur")
    data = json.loads((folder / "module.json").read_text())
    data["api_version"] = f"{API_VERSION[0]}.{API_VERSION[1] + 1}"
    (folder / "module.json").write_text(json.dumps(data))
    with pytest.raises(ModuleError, match="mettez montar à jour"):
        read_manifest(folder)
