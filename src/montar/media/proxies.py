# SPDX-License-Identifier: GPL-3.0-or-later
"""Proxys (F-MED-05) : copies légères des vidéos très haute définition (4K…), utilisées
par l'aperçu pour rester fluide ; l'export lit toujours le fichier d'origine."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from montar.core.project import MediaItem

PROXY_SHORT_SIDE = 540  # petit côté du proxy, en pixels
THRESHOLD = 1440  # au-delà de ce petit côté, la vidéo reçoit un proxy


def needs_proxy(media: MediaItem) -> bool:
    return media.kind == "video" and min(media.width, media.height) > THRESHOLD


def proxy_size(width: int, height: int) -> tuple[int, int]:
    """Taille du proxy : même format, petit côté PROXY_SHORT_SIDE, dimensions paires."""
    short = min(width, height)
    if short <= 0:
        return width, height
    k = PROXY_SHORT_SIDE / short
    w, h = round(width * k / 2) * 2, round(height * k / 2) * 2
    return (w, PROXY_SHORT_SIDE) if width >= height else (PROXY_SHORT_SIDE, h)


def proxy_path(cache: Path, media_path: str) -> Path:
    p = Path(media_path)
    try:
        stamp = f"{p.stat().st_mtime_ns}:{p.stat().st_size}"
    except OSError:
        stamp = "missing"
    key = hashlib.sha1(f"{p.resolve()}|{stamp}|{PROXY_SHORT_SIDE}".encode()).hexdigest()
    return cache / "proxies" / f"{key}.mp4"


def existing_proxy(cache: Path, media: MediaItem) -> Path | None:
    path = proxy_path(cache, media.path)
    return path if path.exists() else None


def make_proxy(media: MediaItem, out: Path, stopping: Callable[[], bool] = lambda: False,
               timeout: float = 3600) -> bool:
    """Encode le proxy (H.264 rapide, images clés rapprochées pour se déplacer vite)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    w, h = proxy_size(media.width, media.height)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.mp4")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", media.path, "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", f"scale={w}:{h}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
           "-g", "12", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(tmp)]
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
    except OSError:
        return False
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if stopping() or time.monotonic() > deadline:
            process.kill()
            process.wait()
            tmp.unlink(missing_ok=True)
            return False
        time.sleep(0.1)
    if process.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(out)
    return True


def clear(cache: Path) -> None:
    shutil.rmtree(cache / "proxies", ignore_errors=True)
