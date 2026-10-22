# SPDX-License-Identifier: GPL-3.0-or-later
"""Stockage & cache (F-UX-08) : place occupée par le cache et par les sauvegardes des
projets, espace libre, vidage du cache."""
from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

from montar.core.project_files import BACKUP_DIR

# sous-dossiers du cache recréés à la demande ; « logs » (journal en cours) est gardé
CACHE_PARTS = {
    "thumbnails": "Vignettes",
    "waveforms": "Formes d'onde",
    "texts": "Textes",
    "timelapse": "Calculs des modules",
    "lumas": "Transitions",
}
KEEP = ("logs",)


def folder_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def cache_size(cache: Path) -> int:
    """Taille de ce que « Vider le cache » supprimerait."""
    if not cache.is_dir():
        return 0
    total = 0
    for p in cache.iterdir():
        if p.name in KEEP:
            continue
        try:
            total += folder_size(p) if p.is_dir() else p.stat().st_size
        except OSError:
            continue
    return total


def clear_cache(cache: Path) -> int:
    """Supprime le contenu du cache (sauf le journal) ; renvoie le nombre d'octets libérés.
    Vignettes, formes d'onde et calculs des modules sont refaits quand on en a besoin."""
    freed = 0
    if not cache.is_dir():
        return 0
    for p in cache.iterdir():
        if p.name in KEEP:
            continue
        try:
            if p.is_dir() and not p.is_symlink():
                size = folder_size(p)
                shutil.rmtree(p)
            else:
                size = p.stat().st_size
                p.unlink()
        except OSError:
            continue
        freed += size
    return freed


def backups_usage(project_paths: Iterable[Path]) -> tuple[int, int]:
    """(nombre de copies, octets) des dossiers « sauvegardes » des projets donnés."""
    count = size = 0
    seen: set[Path] = set()
    for path in project_paths:
        folder = Path(path).parent / BACKUP_DIR
        if folder in seen or not folder.is_dir():
            continue
        seen.add(folder)
        for f in folder.iterdir():
            try:
                if f.is_file():
                    count += 1
                    size += f.stat().st_size
            except OSError:
                continue
    return count, size


def free_space(path: Path) -> int | None:
    """Espace libre du disque qui contient `path` (ou son premier parent existant)."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None
