# SPDX-License-Identifier: GPL-3.0-or-later
"""Analyse des fichiers médias avec ffprobe."""
from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from montar.core.project import MediaItem

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".mpg",
                    ".mpeg", ".wmv", ".flv", ".3gp", ".ogv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".oga", ".opus", ".wma"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS

# Codecs « vidéo » qui correspondent en réalité à une image fixe.
_IMAGE_CODECS = {"mjpeg", "png", "webp", "bmp", "tiff", "gif"}


class ProbeError(Exception):
    pass


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def _fps(rate: str | None) -> float:
    try:
        value = Fraction(rate or "0")
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(value) if value > 0 else 0.0


def probe(path: str | Path) -> MediaItem:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise ProbeError("ffprobe est introuvable (paquet ffmpeg)")
    path = Path(path).resolve()
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeError(str(exc)) from exc
    if result.returncode != 0:
        raise ProbeError(result.stderr.strip() or f"fichier illisible : {path.name}")
    return parse_probe(path, json.loads(result.stdout or "{}"))


def parse_probe(path: Path, data: dict) -> MediaItem:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next(
        (s for s in streams if s.get("codec_type") == "video"
         and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise ProbeError(f"aucun flux audio ou vidéo : {path.name}")

    try:
        duration = float(fmt.get("duration") or (video or audio or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0

    if video is not None:
        codec = video.get("codec_name", "")
        frames = int(video.get("nb_frames") or 0)
        is_image = path.suffix.lower() in IMAGE_EXTENSIONS and (
            codec in _IMAGE_CODECS and (frames <= 1 or codec != "gif")
        )
        kind = "image" if is_image else "video"
        return MediaItem(
            path=str(path),
            kind=kind,
            duration=0.0 if kind == "image" else duration,
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            fps=0.0 if kind == "image" else _fps(video.get("avg_frame_rate")
                                                   or video.get("r_frame_rate")),
            has_audio=audio is not None,
            video_codec=codec,
            audio_codec=(audio or {}).get("codec_name", ""),
        )
    return MediaItem(
        path=str(path), kind="audio", duration=duration, has_audio=True,
        audio_codec=audio.get("codec_name", ""),
    )
