# SPDX-License-Identifier: GPL-3.0-or-later
"""Découverte, chargement isolé, installation et désactivation des modules."""
from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sys
import tempfile
import types
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from montar.api import (
    API_VERSION,
    AudioEffect,
    ClipSource,
    ExportFormat,
    Generator,
    Graphic,
    ModuleAPI,
    Tool,
    Transition,
    VideoEffect,
)
from montar.i18n import add_module_translations

log = logging.getLogger(__name__)

MANIFEST = "module.json"
_PARENT = "montar_modules"
ARCHIVE_SUFFIX = ".montar-module"
_REQUIRED = ("id", "name", "version", "api_version")
T = TypeVar("T")


class ModuleError(Exception):
    pass


@dataclass
class ModuleInfo:
    id: str
    name: str
    version: str
    path: Path
    builtin: bool
    author: str = ""
    description: str = ""
    license: str = ""
    api_version: str = "1.0"
    permissions: list[str] = field(default_factory=list)
    enabled: bool = True
    error: str = ""  # erreur de chargement ou d'exécution (le module est alors désactivé)
    loaded: ModuleAPI | None = None

    @property
    def active(self) -> bool:
        return self.enabled and not self.error and self.loaded is not None


def read_manifest(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModuleError(f"manifeste illisible ({MANIFEST}) : {exc}") from exc
    if not isinstance(data, dict):
        raise ModuleError("manifeste invalide")
    missing = [k for k in _REQUIRED if not isinstance(data.get(k), str) or not data[k]]
    if missing:
        raise ModuleError("champs manquants dans le manifeste : " + ", ".join(missing))
    if not data["id"].replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise ModuleError(f"identifiant de module invalide : {data['id']}")
    try:
        parts = [int(x) for x in data["api_version"].split(".")[:2]]
        major, minor = parts[0], (parts[1] if len(parts) > 1 else 0)
    except (ValueError, IndexError) as exc:
        raise ModuleError(f"version d'API invalide : {data['api_version']}") from exc
    if major == API_VERSION[0] and minor > API_VERSION[1]:
        raise ModuleError(f"ce module demande l'API {data['api_version']} : mettez montar à "
                          f"jour (il fournit l'API {API_VERSION[0]}.{API_VERSION[1]})")
    if major != API_VERSION[0]:
        raise ModuleError(f"API {data['api_version']} non prise en charge "
                          f"(montar fournit l'API {API_VERSION[0]}.{API_VERSION[1]})")
    if not (folder / "__init__.py").exists():
        raise ModuleError("__init__.py manquant")
    return data


class ModuleManager:
    """Modules intégrés (dans montar) et modules de l'utilisateur (installés localement)."""

    def __init__(self, builtin_dir: Path, user_dir: Path,
                 disabled: Iterable[str] = ()) -> None:
        self.builtin_dir, self.user_dir = builtin_dir, user_dir
        self.disabled = set(disabled)
        self.modules: dict[str, ModuleInfo] = {}
        self.listeners: list[Callable[[], None]] = []
        self.failure_listeners: list[Callable[[str, str], None]] = []  # module, erreur

    # --- chargement ---------------------------------------------------------------

    def load_all(self) -> None:
        self.modules = {}
        for folder, builtin in self._folders():
            try:
                data = read_manifest(folder)
            except ModuleError as exc:
                log.warning("module ignoré (%s) : %s", folder.name, exc)
                info = ModuleInfo(folder.name, folder.name, "?", folder, builtin, error=str(exc),
                                  enabled=False)
                self.modules.setdefault(info.id, info)
                continue
            if data["id"] in self.modules:
                continue  # un module intégré prime sur un module du même nom
            info = ModuleInfo(
                data["id"], data["name"], data["version"], folder, builtin,
                str(data.get("author", "")), str(data.get("description", "")),
                str(data.get("license", "")), data["api_version"],
                [str(p) for p in data.get("permissions", []) if isinstance(p, str)],
                enabled=data["id"] not in self.disabled)
            self.modules[info.id] = info
            if info.enabled:
                self._load(info)
        self._notify()

    def _folders(self) -> list[tuple[Path, bool]]:
        found = []
        for base, builtin in ((self.builtin_dir, True), (self.user_dir, False)):
            if base.is_dir():
                found += [(p, builtin) for p in sorted(base.iterdir())
                          if p.is_dir() and not p.name.startswith((".", "_"))]
        return found

    def _load(self, info: ModuleInfo) -> None:
        if _PARENT not in sys.modules:  # paquet parent des modules (imports relatifs)
            parent = types.ModuleType(_PARENT)
            parent.__path__ = []  # type: ignore[attr-defined]
            sys.modules[_PARENT] = parent
        name = f"{_PARENT}.{info.id.replace('-', '_').replace('.', '_')}"
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]
        if not info.builtin:  # module en développement : jamais de code compilé périmé
            for cache in list(info.path.rglob("__pycache__")):
                shutil.rmtree(cache, ignore_errors=True)
            importlib.invalidate_caches()
        try:
            spec = importlib.util.spec_from_file_location(
                name, info.path / "__init__.py", submodule_search_locations=[str(info.path)])
            if spec is None or spec.loader is None:
                raise ModuleError("module Python introuvable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise ModuleError("fonction register(api) absente")
            api = ModuleAPI(info.id, info.path)
            register(api)
            add_module_translations(info.path)
            info.loaded, info.error = api, ""
        except Exception as exc:  # un module défectueux ne doit pas bloquer montar
            log.exception("échec du chargement du module %s", info.id)
            info.loaded, info.error = None, f"{type(exc).__name__} : {exc}"
            sys.modules.pop(name, None)

    def _notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:  # une fenêtre en défaut ne doit pas bloquer les autres
                log.exception("mise à jour après changement des modules")

    # --- état ---------------------------------------------------------------------------

    def set_enabled(self, module_id: str, enabled: bool) -> None:
        info = self.modules[module_id]
        info.enabled = enabled
        if enabled:
            self.disabled.discard(module_id)
            info.error = ""
            self._load(info)
        else:
            self.disabled.add(module_id)
            info.loaded = None
        self._notify()

    def report_failure(self, module_id: str, exc: BaseException) -> None:
        """Une erreur à l'exécution désactive le module jusqu'au prochain démarrage."""
        info = self.modules.get(module_id)
        if info is None or info.error:
            return
        log.error("module %s désactivé après une erreur : %s", module_id, exc)
        info.error = f"{type(exc).__name__} : {exc}"
        info.loaded = None
        for listener in list(self.failure_listeners):
            listener(info.name, info.error)
        self._notify()

    def guarded(self, module_id: str, call: Callable[[], T], default: T) -> T:
        try:
            return call()
        except Exception as exc:
            self.report_failure(module_id, exc)
            return default

    def active(self) -> list[ModuleInfo]:
        return [m for m in self.modules.values() if m.active]

    def is_active(self, module_id: str) -> bool:
        info = self.modules.get(module_id)
        return info is not None and info.active

    def effects(self) -> list[tuple[str, VideoEffect]]:
        return [(m.id, e) for m in self.active() for e in m.loaded.effects]

    def tools(self) -> list[tuple[str, Tool]]:
        return [(m.id, t) for m in self.active() for t in m.loaded.tools]

    def sources(self) -> list[tuple[str, ClipSource]]:
        return [(m.id, s) for m in self.active() for s in m.loaded.sources]

    def effect(self, effect_id: str) -> tuple[str, VideoEffect] | None:
        return next(((mid, e) for mid, e in self.effects() if e.id == effect_id), None)

    def audio_effects(self) -> list[tuple[str, AudioEffect]]:
        return [(m.id, e) for m in self.active() for e in m.loaded.audio_effects]

    def transitions(self) -> list[tuple[str, Transition]]:
        return [(m.id, t) for m in self.active() for t in m.loaded.transitions]

    def transition(self, kind: str) -> tuple[str, Transition] | None:
        return next(((mid, t) for mid, t in self.transitions() if t.id == kind), None)

    def generators(self) -> list[tuple[str, Generator]]:
        return [(m.id, g) for m in self.active() for g in m.loaded.generators]

    def graphics(self) -> list[tuple[str, Graphic]]:
        return [(m.id, g) for m in self.active() for g in m.loaded.graphics]

    def export_formats(self) -> list[tuple[str, ExportFormat]]:
        return [(m.id, f) for m in self.active() for f in m.loaded.export_formats]

    def export_format(self, format_id: str) -> tuple[str, ExportFormat] | None:
        return next(((mid, f) for mid, f in self.export_formats() if f.id == format_id), None)

    # --- installation -------------------------------------------------------------------

    def inspect_archive(self, archive: Path) -> dict[str, Any]:
        """Lit le manifeste d'une archive sans l'installer (pour la confirmation)."""
        with tempfile.TemporaryDirectory() as tmp:
            return read_manifest(self._extract(archive, Path(tmp)))

    def install(self, archive: Path) -> ModuleInfo:
        """Installe un module depuis une archive `.montar-module` (ou `.zip`), ou depuis un
        dossier qui contient `module.json`."""
        if Path(archive).is_dir():
            return self.install_folder(Path(archive))
        with tempfile.TemporaryDirectory() as tmp:
            return self._install_from(self._extract(archive, Path(tmp)))

    def install_folder(self, folder: Path, link: bool = False) -> ModuleInfo:
        """Copie le dossier d'un module ; avec `link`, un lien vers lui est créé à la place
        (développement : les modifications sont prises en compte en rechargeant)."""
        return self._install_from(Path(folder).resolve(), link)

    def _install_from(self, folder: Path, link: bool = False) -> ModuleInfo:
        data = read_manifest(folder)
        existing = self.modules.get(data["id"])
        if existing is not None and existing.builtin:
            raise ModuleError(f"« {data['id']} » est un module intégré à montar")
        target = self.user_dir / data["id"]
        self.user_dir.mkdir(parents=True, exist_ok=True)
        # nouvelle version copiée à côté d'abord (dossier caché, ignoré au chargement) :
        # si l'ancienne ne peut pas être retirée, elle reste intacte et utilisable
        staging = self.user_dir / f".{data['id']}.nouveau"
        _remove(staging)
        if not link:
            shutil.copytree(folder, staging, ignore=shutil.ignore_patterns("__pycache__"))
        try:
            _remove(target)
        except OSError as exc:
            _remove(staging)
            raise ModuleError(f"l'ancienne version de « {data['id']} » ne peut pas être "
                              f"remplacée (fichier ouvert ?) : {exc}") from exc
        if link:
            target.symlink_to(folder, target_is_directory=True)
        else:
            staging.rename(target)
        self.disabled.discard(data["id"])
        self.load_all()
        return self.modules[data["id"]]

    def uninstall(self, module_id: str) -> None:
        info = self.modules.get(module_id)
        if info is None or info.builtin:
            raise ModuleError("seuls les modules installés peuvent être supprimés")
        _remove(info.path)  # un module lié : seul le lien est retiré
        self.load_all()

    def reload(self) -> None:
        """Recharge tous les modules (après modification d'un module en développement)."""
        self.load_all()

    @staticmethod
    def _extract(archive: Path, into: Path) -> Path:
        try:
            with zipfile.ZipFile(archive) as zf:
                root = into.resolve()
                for member in zf.namelist():
                    target = (into / member).resolve()
                    if root not in target.parents and target != root:
                        raise ModuleError(f"chemin interdit dans l'archive : {member}")
                zf.extractall(into)
        except zipfile.BadZipFile as exc:
            raise ModuleError(f"archive invalide : {exc}") from exc
        if (into / MANIFEST).exists():
            return into
        folders = [p for p in into.iterdir() if p.is_dir() and (p / MANIFEST).exists()]
        if len(folders) != 1:
            raise ModuleError(f"l'archive doit contenir un seul module ({MANIFEST})")
        return folders[0]


def _remove(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
