# SPDX-License-Identifier: GPL-3.0-or-later
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from montar.plugins import ModuleError, ModuleManager, builtin_modules_dir

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "modules" / "negatif"


def make_archive(folder: Path, out: Path) -> Path:
    with zipfile.ZipFile(out, "w") as zf:
        for f in folder.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                zf.write(f, Path(folder.name) / f.relative_to(folder))
    return out


def write_module(base: Path, module_id: str, code: str, api="1.0") -> Path:
    folder = base / module_id
    folder.mkdir(parents=True)
    (folder / "module.json").write_text(json.dumps(
        {"id": module_id, "name": module_id, "version": "0.1", "api_version": api}))
    (folder / "__init__.py").write_text(code)
    return folder


@pytest.fixture
def manager(tmp_path):
    return ModuleManager(builtin_modules_dir(), tmp_path / "user")


def test_builtin_timelapse_is_loaded(manager):
    manager.load_all()
    info = manager.modules["timelapse"]
    assert info.builtin and info.active
    assert {t.id for _m, t in manager.tools()} >= {"timelapse.apply", "timelapse.remove"}
    assert "timelapse" in [m for m, _s in manager.sources()]


def test_install_example_module_from_archive(manager, tmp_path):
    manager.load_all()
    archive = make_archive(EXAMPLE, tmp_path / "negatif.montar-module")
    assert manager.inspect_archive(archive)["name"] == "Négatif"
    info = manager.install(archive)
    assert info.active and not info.builtin
    found = manager.effect("exemple.negatif")
    assert found is not None
    filters = found[1].filters({"intensite": 1.0})
    assert filters[0][0] == "avfilter.lutrgb"
    manager.uninstall("exemple.negatif")
    assert "exemple.negatif" not in manager.modules


def test_broken_module_is_isolated(tmp_path):
    user = tmp_path / "user"
    write_module(user, "casse", "raise RuntimeError('boum')")
    write_module(user, "sans_register", "x = 1")
    write_module(user, "futur", "def register(api): pass", api="2.0")
    write_module(user, "bon", "def register(api): pass")
    manager = ModuleManager(tmp_path / "rien", user)
    manager.load_all()  # aucune exception
    assert "boum" in manager.modules["casse"].error
    assert "register" in manager.modules["sans_register"].error
    assert "API 2.0" in manager.modules["futur"].error
    assert manager.modules["bon"].active


def test_runtime_failure_disables_module(tmp_path):
    user = tmp_path / "user"
    write_module(user, "fragile", "def register(api): pass")
    manager = ModuleManager(tmp_path / "rien", user)
    manager.load_all()

    def boom():
        raise ValueError("erreur du module")

    assert manager.guarded("fragile", boom, "défaut") == "défaut"
    assert not manager.modules["fragile"].active and "erreur du module" in \
        manager.modules["fragile"].error


def test_enable_disable(manager):
    manager.load_all()
    calls = []
    manager.listeners.append(lambda: calls.append(1))
    manager.set_enabled("timelapse", False)
    assert all(m != "timelapse" for m, _t in manager.tools())
    assert "timelapse" in manager.disabled
    manager.set_enabled("timelapse", True)
    assert manager.is_active("timelapse") and len(calls) == 2
    reloaded = ModuleManager(builtin_modules_dir(), manager.user_dir, ["timelapse"])
    reloaded.load_all()
    assert not reloaded.is_active("timelapse")


def test_archive_safety(manager, tmp_path):
    evil = tmp_path / "evil.montar-module"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../evil.py", "x")
    with pytest.raises(ModuleError):
        manager.install(evil)
    not_zip = tmp_path / "pas_zip.montar-module"
    not_zip.write_text("bonjour")
    with pytest.raises(ModuleError):
        manager.install(not_zip)
    builtin_copy = tmp_path / "timelapse"
    shutil.copytree(builtin_modules_dir() / "timelapse", builtin_copy)
    manager.load_all()
    with pytest.raises(ModuleError):  # un module intégré ne se remplace pas
        manager.install(make_archive(builtin_copy, tmp_path / "tl.montar-module"))
