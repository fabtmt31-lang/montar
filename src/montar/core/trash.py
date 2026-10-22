# SPDX-License-Identifier: GPL-3.0-or-later
"""Corbeille des projets (F-PRJ-07) : un projet supprimé y est déplacé avec son dossier et
peut être restauré ; il est supprimé définitivement après 30 jours ou en vidant la corbeille."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from montar.core.project import Project, ProjectError
from montar.core.project_files import owns_folder

RETENTION_DAYS = 30
_INFO = "corbeille.json"


@dataclass
class TrashEntry:
    folder: Path  # dossier dans la corbeille
    name: str
    original: Path  # fichier .montar d'origine
    deleted: float  # horodatage

    @property
    def size(self) -> int:
        return sum(p.stat().st_size for p in self.folder.rglob("*") if p.is_file())


class Trash:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def put(self, project_path: Path) -> TrashEntry:
        """Déplace le projet (son dossier s'il en a un, sinon son seul fichier)."""
        try:
            name = Project.load(project_path).name
        except ProjectError:
            name = project_path.stem
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / f"{time.strftime('%Y%m%d-%H%M%S')} {project_path.stem}"
        n = 2
        while target.exists():
            target = target.with_name(f"{target.name} {n}")
            n += 1
        own = owns_folder(project_path)
        if own:
            shutil.move(str(project_path.parent), target)
        else:
            target.mkdir()
            shutil.move(str(project_path), target / project_path.name)
        info = {"name": name, "original": str(project_path), "file": project_path.name,
                "deleted": time.time(), "own_folder": own}
        (target / _INFO).write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        return TrashEntry(target, name, project_path, info["deleted"])

    def entries(self) -> list[TrashEntry]:
        result = []
        if not self.folder.is_dir():
            return result
        for folder in self.folder.iterdir():
            try:
                info = json.loads((folder / _INFO).read_text(encoding="utf-8"))
                result.append(TrashEntry(folder, info["name"], Path(info["original"]),
                                         float(info["deleted"])))
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda e: e.deleted, reverse=True)

    def restore(self, entry: TrashEntry) -> Path:
        """Remet le projet à son emplacement d'origine (ou à côté s'il est occupé)."""
        info = json.loads((entry.folder / _INFO).read_text(encoding="utf-8"))
        (entry.folder / _INFO).unlink()
        original = entry.original
        if info.get("own_folder"):
            destination = original.parent
            n = 2
            while destination.exists():
                destination = destination.with_name(f"{original.parent.name} ({n})")
                n += 1
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry.folder), destination)
            return destination / info["file"]
        destination = original
        n = 2
        while destination.exists():
            destination = original.with_name(f"{original.stem} ({n}){original.suffix}")
            n += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry.folder / info["file"]), destination)
        shutil.rmtree(entry.folder, ignore_errors=True)
        return destination

    def delete(self, entry: TrashEntry) -> None:
        shutil.rmtree(entry.folder, ignore_errors=True)

    def empty(self) -> None:
        for entry in self.entries():
            self.delete(entry)

    def purge(self, days: int = RETENTION_DAYS, now: float | None = None) -> int:
        """Supprime les projets restés plus de `days` jours ; renvoie leur nombre."""
        limit = (now or time.time()) - days * 86400
        old = [e for e in self.entries() if e.deleted < limit]
        for entry in old:
            self.delete(entry)
        return len(old)
