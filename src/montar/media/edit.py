# SPDX-License-Identifier: GPL-3.0-or-later
"""Édition d'un média avant le montage : rogner, recadrer, pivoter, retourner, couleur,
filtres, vitesse, son et Timelapse, appliqués par ffmpeg pour produire un nouveau fichier
(vidéo quasi sans perte, image PNG, son WAV). Sans dépendance à Qt."""
from __future__ import annotations

import dataclasses
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from montar.core.project import ColorAdjust, MediaItem
from montar.engine.looks import Filters, color_filters, preset_filters
from montar.media import ffmpeg_run

MAX_CROP = 0.45
ROTATIONS = (0, 90, 180, 270)  # sens horaire


@dataclass
class MediaEdit:
    trim_in: float = 0.0  # secondes
    trim_out: float | None = None  # secondes (None = jusqu'à la fin)
    crop_left: float = 0.0  # fractions de l'image, 0 à 0.45
    crop_right: float = 0.0
    crop_top: float = 0.0
    crop_bottom: float = 0.0
    rotation: int = 0  # 0, 90, 180, 270
    flip_h: bool = False
    flip_v: bool = False
    color: ColorAdjust = field(default_factory=ColorAdjust)
    preset: str = ""
    preset_amount: float = 1.0
    speed: float = 1.0
    volume: float = 1.0
    mute: bool = False
    timelapse: dict | None = None  # réglages du module Timelapse (facteur, méthode…)

    def is_identity(self) -> bool:
        return self == MediaEdit()

    def segment(self, media: MediaItem) -> tuple[float, float]:
        """Début et fin (secondes source) de la partie gardée."""
        end = media.duration if self.trim_out is None else min(media.duration, self.trim_out)
        start = max(0.0, min(self.trim_in, end))
        return start, end

    def crops(self) -> tuple[float, float, float, float]:
        return tuple(max(0.0, min(MAX_CROP, v)) for v in (
            self.crop_left, self.crop_right, self.crop_top, self.crop_bottom))  # type: ignore

    def output_size(self, media: MediaItem) -> tuple[int, int]:
        """Taille de l'image produite (recadrage puis rotation), en pixels pairs."""
        left, right, top, bottom = self.crops()
        w = media.width * (1 - left - right)
        h = media.height * (1 - top - bottom)
        if self.rotation in (90, 270):
            w, h = h, w
        return max(2, int(w) // 2 * 2), max(2, int(h) // 2 * 2)

    def duration(self, media: MediaItem) -> float:
        start, end = self.segment(media)
        return (end - start) / max(0.01, self.speed)


def _ffmpeg_filters(filters: Filters) -> list[str]:
    """Filtres « avfilter.x » de MLT (looks.py) traduits en filtres ffmpeg."""
    out = []
    for name, props in filters:
        if not name.startswith("avfilter."):
            continue
        args = ":".join(f"{k[3:]}={v}" for k, v in props.items() if k.startswith("av."))
        out.append(f"{name[9:]}={args}" if args else name[9:])
    return out


def video_filters(edit: MediaEdit, include_geometry: bool = True,
                  include_timing: bool = True) -> list[str]:
    chain: list[str] = []
    if include_geometry:
        left, right, top, bottom = edit.crops()
        if left or right or top or bottom:
            chain.append(f"crop=iw*{1 - left - right:.6f}:ih*{1 - top - bottom:.6f}:"
                         f"iw*{left:.6f}:ih*{top:.6f}")
        chain += {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}.get(
            edit.rotation % 360, [])
        if edit.flip_h:
            chain.append("hflip")
        if edit.flip_v:
            chain.append("vflip")
    chain += _ffmpeg_filters(color_filters(edit.color)
                             + preset_filters(edit.preset, edit.preset_amount))
    if include_timing and edit.speed != 1.0:
        chain.append(f"setpts=PTS/{edit.speed:.6f}")
    chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")  # dimensions paires (H.264)
    return chain


def _atempo(speed: float) -> list[str]:
    parts = []
    while speed > 100:
        parts.append("atempo=100")
        speed /= 100
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    parts.append(f"atempo={speed:.6f}")
    return parts


def audio_filters(edit: MediaEdit) -> list[str]:
    chain = []
    if edit.speed != 1.0:
        chain += _atempo(edit.speed)
    if edit.volume != 1.0:
        chain.append(f"volume={max(0.0, edit.volume):.4f}")
    return chain


def output_suffix(media: MediaItem) -> str:
    return {"image": ".png", "audio": ".wav"}.get(media.kind, ".mp4")


def command(source: str, target: str, media: MediaItem, edit: MediaEdit) -> list[str]:
    """Commande ffmpeg de l'édition (sans le Timelapse, appliqué ensuite)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-v", "error", "-nostats", "-progress", "pipe:1", "-y"]
    if media.kind == "image":
        return cmd + ["-i", source, "-vf", ",".join(video_filters(edit, include_timing=False)),
                      "-frames:v", "1", "-update", "1", target]
    start, end = edit.segment(media)
    cmd += ["-ss", f"{start:.6f}", "-t", f"{end - start:.6f}", "-i", source]
    keep_audio = media.has_audio and not edit.mute
    if media.kind == "audio":
        af = audio_filters(edit)
        return cmd + (["-af", ",".join(af)] if af else []) + ["-vn", "-c:a", "pcm_s16le",
                                                              "-ar", "48000", target]
    cmd += ["-vf", ",".join(video_filters(edit)), "-c:v", "libx264", "-preset", "medium",
            "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if keep_audio:
        af = audio_filters(edit)
        cmd += (["-af", ",".join(af)] if af else []) + ["-c:a", "aac", "-b:a", "256k"]
    else:
        cmd += ["-an"]
    return cmd + ["-f", "mp4", target]


def apply(source: str, target: Path, media: MediaItem, edit: MediaEdit,
          progress=lambda ratio: None, cancelled=lambda: False, timelapse_render=None) -> Path:
    """Produit le média modifié dans `target` (écrit d'abord en fichier temporaire).
    `timelapse_render` : fonction de calcul du module Timelapse, si `edit.timelapse`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".part" + target.suffix)
    duration = max(0.04, edit.duration(media))
    timelapse = edit.timelapse and media.kind == "video" and timelapse_render is not None
    share = 0.5 if timelapse else 1.0

    def on_progress(key: str, value: str) -> None:
        if key == "out_time_us":
            try:
                progress(share * min(1.0, int(value) / 1e6 / duration))
            except ValueError:
                pass

    try:
        ffmpeg_run.run(command(source, str(tmp), media, edit), on_progress, cancelled)
        if share < 1.0:
            tmp = _timelapse(timelapse_render, tmp, target, media, edit,
                             lambda r: progress(share + (1 - share) * r), cancelled)
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        target.with_name(target.stem + ".tl.part.mp4").unlink(missing_ok=True)
        raise
    progress(1.0)
    return target


def _timelapse(render, base: Path, target: Path, media: MediaItem, edit: MediaEdit,
               progress, cancelled) -> Path:
    """Timelapse sur tout le média déjà modifié (calcul du module Timelapse)."""
    fps = max(1, round(media.fps or 25))
    data = dict(edit.timelapse or {})
    data["source_frames"] = max(1, math.floor(edit.duration(media) * fps))
    out = target.with_name(target.stem + ".tl.part.mp4")
    try:
        render(str(base), out, 0, data, fps, progress, cancelled)
    finally:
        base.unlink(missing_ok=True)
    return out


def updated_media(media: MediaItem, probed: MediaItem, path: Path) -> MediaItem:
    """Média du projet après édition (mêmes identifiant et origine, nouvelles mesures)."""
    return dataclasses.replace(probed, id=media.id, path=str(path),
                               original_path=media.original_path)
