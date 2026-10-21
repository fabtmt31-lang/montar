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
