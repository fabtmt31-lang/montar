# SPDX-License-Identifier: GPL-3.0-or-later
"""Extraction d'une image d'une vidéo (image fixe, F-EDT-09)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class FrameError(Exception):
    pass


def extract_frame(path: str, seconds: float, target: Path, timeout: float = 60.0) -> Path:
    """Image PNG de la vidéo `path` à `seconds` secondes."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FrameError("ffmpeg est introuvable")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part.png")
    cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", path,
           "-frames:v", "1", "-update", "1", str(tmp)]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrameError(str(exc)) from exc
    if done.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        lines = done.stderr.strip().splitlines()
        raise FrameError(lines[-1] if lines else "aucune image extraite")
    tmp.replace(target)
    return target


def source_seconds(clip, frame: int, fps: int) -> float:
    """Instant du média montré par `clip` à l'image `frame` de la timeline."""
    offset = min(max(0, frame - clip.start), clip.duration - 1)
    if clip.reverse:
        source = clip.source_in + (clip.duration - 1 - offset) * clip.speed
    else:
        source = clip.source_in + offset * clip.speed
    return source / fps
