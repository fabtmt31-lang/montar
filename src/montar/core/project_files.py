# SPDX-License-Identifier: GPL-3.0-or-later
"""Opérations sur les dossiers de projet : dupliquer (« Enregistrer sous »), sauvegardes
périodiques, et repérage d'une session interrompue (récupération après plantage)."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from montar.core.project import MEDIA_DIR, PROJECT_SUFFIX, Project, unique_project_folder
from montar.platform.process import alive

BACKUP_DIR = "sauvegardes"
MAX_BACKUPS = 10


def owns_folder(path: Path) -> bool:
    """Le projet a-t-il son propre dossier (et non un dossier partagé) ?"""
    folder = path.parent
    return folder.name == path.stem or (folder / MEDIA_DIR).is_dir()


def duplicate(path: Path, name: str, root: Path) -> Path:
    """Copie complète du projet (fichier et médias ; ni sauvegardes ni exports) sous un
    nouveau nom, dans son propre dossier de `root` ; renvoie le fichier de la copie."""
    target = unique_project_folder(root, name)
    shared = not owns_folder(path)
    if shared:
        target.parent.mkdir(parents=True)
    else:
        shutil.copytree(path.parent, target.parent,
                        ignore=shutil.ignore_patterns(BACKUP_DIR, "exports", "*.part*",
                                                      f"*{PROJECT_SUFFIX}"))
    copy = Project.load(path)
    copy.name = name.strip() or target.stem
    for media in copy.media:  # médias du dossier copié : nouvel emplacement
        try:
            relative = Path(media.path).resolve().relative_to(path.parent.resolve())
        except ValueError:
            continue
        if not shared:
            media.path = str(target.parent / relative)
    copy.save(target)
    return target


def backup(project: Project, every: float = 120.0, keep: int = MAX_BACKUPS) -> Path | None:
    """Copie datée du fichier du projet dans « sauvegardes/ » si la dernière a plus de
    `every` secondes ; seules les `keep` plus récentes sont gardées."""
    if project.path is None or not project.path.exists():
        return None
    folder = project.path.parent / BACKUP_DIR
    existing = sorted(folder.glob(f"*{PROJECT_SUFFIX}")) if folder.is_dir() else []
    if existing and time.time() - existing[-1].stat().st_mtime < every:
        return None
    folder.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H-%M-%S")
    target = folder / f"{project.path.stem} {stamp}{PROJECT_SUFFIX}"
    shutil.copy2(project.path, target)
    for old in sorted(folder.glob(f"*{PROJECT_SUFFIX}"))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def backups(path: Path) -> list[Path]:
    folder = path.parent / BACKUP_DIR
    return sorted(folder.glob(f"*{PROJECT_SUFFIX}"), reverse=True) if folder.is_dir() else []


class Session:
    """Fichier témoin du projet ouvert : s'il existe encore au démarrage suivant alors que
    son processus n'existe plus, montar a été arrêté brutalement."""

    def __init__(self, file: Path) -> None:
        self.file = file

    def open(self, project_path: Path) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps({"project": str(project_path), "pid": os.getpid()}),
                             encoding="utf-8")

    def close(self) -> None:
        self.file.unlink(missing_ok=True)

    def interrupted(self) -> Path | None:
        """Projet de la session précédente si elle ne s'est pas terminée normalement."""
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            pid, project = int(data["pid"]), Path(data["project"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if pid != os.getpid() and alive(pid):
            return None  # une autre fenêtre de montar est ouverte
        return project if project.exists() else None


