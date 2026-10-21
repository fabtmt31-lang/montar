# SPDX-License-Identifier: GPL-3.0-or-later
"""Copie des médias dans le dossier du projet : le projet ne dépend plus des fichiers
d'origine (déplacés, renommés ou supprimés), et se sauvegarde d'un seul bloc."""
from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path

CHUNK = 4 * 1024 * 1024
_PART = ".part"


class CopyCancelled(Exception):
    pass


def is_inside(path: str | os.PathLike[str], folder: Path) -> bool:
    try:
        Path(path).resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _fingerprint(path: Path) -> tuple[int, str]:
    """Taille et empreinte du début et de la fin du fichier (rapide, même pour 10 Go)."""
    size = path.stat().st_size
    digest = hashlib.sha1()
    with path.open("rb") as f:
        digest.update(f.read(CHUNK))
        if size > 2 * CHUNK:
            f.seek(-CHUNK, os.SEEK_END)
            digest.update(f.read(CHUNK))
    return size, digest.hexdigest()


def _candidates(folder: Path, name: str):
    stem, suffix = Path(name).stem, Path(name).suffix
    yield folder / name
    n = 2
    while True:
        yield folder / f"{stem} ({n}){suffix}"
        n += 1


def copy_media(source: str | os.PathLike[str], folder: Path,
               progress: Callable[[float], None] = lambda r: None,
               cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Copie `source` dans `folder` et renvoie le chemin de la copie.

    Un fichier déjà dans le dossier est gardé tel quel ; une copie identique déjà faite
    est réutilisée ; un autre fichier de même nom reçoit un nom « nom (2).ext ». La copie
    passe par un fichier temporaire : une copie interrompue ne laisse rien derrière elle."""
    src = Path(source)
    if is_inside(src, folder):
        return src
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(src)
    for target in _candidates(folder, src.name):
        if not target.exists():
            break
        if _fingerprint(target) == fingerprint:
            progress(1.0)
            return target
    tmp = target.with_name(target.name + _PART)
    total, done = max(1, fingerprint[0]), 0
    try:
        with src.open("rb") as fin, tmp.open("wb") as fout:
            while chunk := fin.read(CHUNK):
                if cancelled():
                    raise CopyCancelled()
                fout.write(chunk)
                done += len(chunk)
                progress(min(1.0, done / total))
            fout.flush()
            os.fsync(fout.fileno())
        shutil.copystat(src, tmp)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    progress(1.0)
    return target
