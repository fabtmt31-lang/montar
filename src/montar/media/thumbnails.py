# SPDX-License-Identifier: GPL-3.0-or-later
"""Vignettes des médias, mises en cache sur disque."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from montar.core.project import MediaItem

THUMB_WIDTH = 320


def thumbnail_path(cache: Path, media_path: str) -> Path:
    p = Path(media_path)
    try:
        stamp = f"{p.stat().st_mtime_ns}:{p.stat().st_size}"
    except OSError:
        stamp = "missing"
    key = hashlib.sha1(f"{p.resolve()}|{stamp}".encode()).hexdigest()
    return cache / "thumbnails" / f"{key}.jpg"


def make_thumbnail(cache: Path, item: MediaItem) -> Path | None:
    """Crée (si besoin) la vignette d'une vidéo ou d'une image ; None pour l'audio."""
    if item.kind == "audio":
        return None
    out = thumbnail_path(cache, item.path)
    if out.exists():
        return out
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.jpg")
    cmd = [ffmpeg, "-v", "error", "-y"]
    if item.kind == "video":  # -ss sur une image fixe ne produit aucune image
        cmd += ["-ss", f"{min(1.0, item.duration / 3):.3f}"]
    cmd += ["-i", item.path, "-frames:v", "1", "-update", "1",
            "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "4", str(tmp)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        if tmp.stat().st_size == 0:
            raise OSError("vignette vide")
        tmp.replace(out)
    except (OSError, subprocess.SubprocessError):
        tmp.unlink(missing_ok=True)
        return None
    return out


FILMSTRIP_FRAMES = 12  # images de l'aperçu au survol (F-MED-03)
FILMSTRIP_HEIGHT = 90


def filmstrip_path(cache: Path, media_path: str) -> Path:
    return cache / "filmstrips" / thumbnail_path(cache, media_path).name


def make_filmstrip(cache: Path, item: MediaItem, count: int = FILMSTRIP_FRAMES) -> Path | None:
    """Bande de `count` images réparties sur la vidéo, côte à côte (aperçu au survol)."""
    if item.kind != "video" or item.duration <= 0:
        return None
    out = filmstrip_path(cache, item.path)
    if out.exists():
        return out
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.jpg")
    # une entrée par instant, chacune avec une recherche rapide : même une longue vidéo
    # n'est pas décodée en entier
    cmd = [ffmpeg, "-v", "error", "-y"]
    for i in range(count):
        cmd += ["-ss", f"{item.duration * (i + 0.5) / count:.3f}", "-i", item.path]
    scaled = ";".join(f"[{i}:v]scale=-2:{FILMSTRIP_HEIGHT},setsar=1[v{i}]"
                      for i in range(count))
    stack = "".join(f"[v{i}]" for i in range(count)) + f"hstack=inputs={count}"
    cmd += ["-filter_complex", f"{scaled};{stack}", "-frames:v", "1", "-q:v", "5", str(tmp)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        if tmp.stat().st_size == 0:
            raise OSError("bande vide")
        tmp.replace(out)
    except (OSError, subprocess.SubprocessError):
        tmp.unlink(missing_ok=True)
        return None
    return out
