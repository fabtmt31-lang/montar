# SPDX-License-Identifier: GPL-3.0-or-later
"""Réglages d'export (cahier des charges §3.10), sans dépendance au moteur : formats,
codecs, qualité, taille estimée et conversion de la timeline vers une autre fréquence."""
from __future__ import annotations

import dataclasses
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache

from montar.engine.base import TimelineSpec

# conteneur → (extension, codecs vidéo proposés) ; codec vidéo vide = audio seul
VIDEO_FORMATS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mp4": (".mp4", ("h264", "h265")),
    "mov": (".mov", ("h264", "h265")),
    "webm": (".webm", ("vp9",)),
    "gif": (".gif", ("gif",)),
}
AUDIO_FORMATS: dict[str, str] = {"mp3": ".mp3", "wav": ".wav", "aac": ".m4a"}
IMAGE_FORMATS: dict[str, str] = {"png": ".png", "jpg": ".jpg"}  # image fixe à la tête de lecture
FORMAT_LABELS = {"mp4": "MP4", "mov": "MOV", "webm": "WebM", "gif": "GIF",
                 "mp3": "MP3", "wav": "WAV", "aac": "AAC", "png": "PNG", "jpg": "JPEG"}
CODEC_LABELS = {"h264": "H.264", "h265": "H.265 (HEVC)", "vp9": "VP9", "gif": "GIF"}
RESOLUTIONS = {"480p": 480, "720p": 720, "1080p": 1080, "4K": 2160}  # petit côté
QUALITIES = ("light", "balanced", "max")
QUALITY_LABELS = {"light": "Légère", "balanced": "Équilibrée", "max": "Maximale"}
RECOMMENDED_QUALITY = "balanced"
GIF_MAX_FPS = 15

_CRF = {"h264": (28, 23, 18), "h265": (30, 26, 22), "vp9": (40, 33, 26)}
_PRESET = ("veryfast", "medium", "slow")
_AUDIO_KBPS = (128, 192, 256)
# débit moyen estimé (Mbit/s) d'une vidéo 1080p à 30 i/s, par codec et qualité
_MBPS_1080 = {"h264": (3.5, 8.0, 16.0), "h265": (2.0, 5.0, 10.0), "vp9": (2.0, 5.0, 10.0),
              "gif": (25.0, 30.0, 35.0)}
_HW_ENCODERS = {"h264": ("h264_nvenc", "h264_vaapi"), "h265": ("hevc_nvenc", "hevc_vaapi")}
VAAPI_DEVICE = "/dev/dri/renderD128"


@dataclass(frozen=True)
class ExportSettings:
    path: str
    format: str = "mp4"  # clé de VIDEO_FORMATS ou d'AUDIO_FORMATS
    codec: str = "h264"
    width: int = 1920
    height: int = 1080
    fps: int = 25
    quality: str = RECOMMENDED_QUALITY
    hardware: bool = False
    # format d'un module : propriétés du consommateur fournies par le module
    custom: tuple[tuple[str, object], ...] = ()
    custom_audio_only: bool = False
    # partie exportée (F-EXP-09), en images du projet ; range_end = 0 : jusqu'à la fin
    range_start: int = 0
    range_end: int = 0

    @property
    def audio_only(self) -> bool:
        return self.format in AUDIO_FORMATS or self.custom_audio_only

    @property
    def level(self) -> int:
        return QUALITIES.index(self.quality) if self.quality in QUALITIES else 1


def export_size(canvas: tuple[int, int], resolution: str) -> tuple[int, int]:
    """Taille de sortie au format de la toile, `resolution` étant le petit côté."""
    w, h = canvas
    short = RESOLUTIONS[resolution]
    if w >= h:
        return _even(short * w / h), short
    return short, _even(short * h / w)


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def estimated_bytes(settings: ExportSettings, frames: int, fps: int) -> int:
    """Taille approximative du fichier (affichée « ≈ 186 Mo »)."""
    if settings.format in IMAGE_FORMATS:
        return int(settings.width * settings.height * (1.5 if settings.format == "png" else 0.3))
    seconds = frames / max(1, fps)
    audio = _AUDIO_KBPS[settings.level] * 1000 / 8
    if settings.format == "wav":
        return int(seconds * 48000 * 2 * 2)
    if settings.audio_only:
        return int(seconds * audio)
    pixels = settings.width * settings.height / (1920 * 1080)
    rate = _MBPS_1080.get(settings.codec, _MBPS_1080["h264"])[settings.level]
    video = rate * 1e6 / 8 * pixels * (min(settings.fps, 60) / 30)
    if settings.format == "gif":
        video *= min(1.0, GIF_MAX_FPS / max(1, settings.fps))
        audio = 0
    return int(seconds * (video + audio))


def human_size(size: int) -> str:
    if size >= 1e9:
        return f"≈ {size / 1e9:.1f} Go".replace(".", ",")
    if size >= 1e6:
        return f"≈ {size / 1e6:.0f} Mo"
    return f"≈ {max(1, round(size / 1e3))} Ko"


def consumer_properties(settings: ExportSettings, encoder: str | None = None) -> dict:
    """Propriétés du consommateur MLT « avformat » ; `encoder` remplace l'encodeur
    logiciel (accélération matérielle)."""
    level = settings.level
    props: dict = {"ar": 48000, "channels": 2, "threads": 0}
    if settings.custom:
        props.update(dict(settings.custom))
        if settings.audio_only:
            props.update(vn=1, video_off=1)
        return props
    if settings.audio_only:
        props.update(vn=1, video_off=1)
        if settings.format == "mp3":
            props.update(f="mp3", acodec="libmp3lame", ab=f"{_AUDIO_KBPS[level]}k")
        elif settings.format == "wav":
            props.update(f="wav", acodec="pcm_s16le")
        else:
            props.update(f="ipod", acodec="aac", ab=f"{_AUDIO_KBPS[level]}k")
        return props
    if settings.format == "gif":
        # intermédiaire sans perte, converti ensuite en GIF par ffmpeg (palette optimisée)
        props.update(f="matroska", vcodec="ffv1", an=1, audio_off=1)
        return props
    codec = settings.codec
    if settings.format == "webm":
        props.update(f="webm", vcodec="libvpx-vp9", crf=_CRF["vp9"][level], vb=0,
                     acodec="libopus", ab=f"{_AUDIO_KBPS[level]}k", deadline="good",
                     **{"cpu-used": 4 - level}, **{"row-mt": 1})
    else:
        props.update(f="mp4" if settings.format == "mp4" else "mov", acodec="aac",
                     ab=f"{_AUDIO_KBPS[level]}k", movflags="+faststart", pix_fmt="yuv420p")
        if encoder is None:
            props.update(vcodec="libx264" if codec == "h264" else "libx265",
                         crf=_CRF[codec][level], preset=_PRESET[level])
            if codec == "h265":
                props["tag"] = "hvc1"  # lisible par les lecteurs Apple
        elif encoder.endswith("_nvenc"):
            props.update(vcodec=encoder, cq=_CRF[codec][level], preset="p5", vb=0)
        else:
            props.update(vcodec=encoder, qp=_CRF[codec][level], vaapi_device=VAAPI_DEVICE,
                         vf="format=nv12,hwupload")
    props["g"] = max(1, settings.fps * 2)
    return props


def gif_command(source: str, target: str, fps: int, width: int) -> list[str]:
    """Conversion de l'intermédiaire en GIF animé (palette calculée sur la vidéo)."""
    fps = min(fps, GIF_MAX_FPS)
    chain = (f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
             "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a")
    return [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", source,
            "-filter_complex", chain, "-loop", "0", target]


@cache
def hardware_encoder(codec: str) -> str | None:
    """Premier encodeur matériel qui fonctionne vraiment ici (essai d'une image)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    for encoder in _HW_ENCODERS.get(codec, ()):
        cmd = [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x144:d=0.2"]
        if encoder.endswith("_vaapi"):
            cmd += ["-vaapi_device", VAAPI_DEVICE, "-vf", "format=nv12,hwupload"]
        cmd += ["-frames:v", "2", "-c:v", encoder, "-f", "null", "-"]
        try:
            if subprocess.run(cmd, capture_output=True, timeout=15).returncode == 0:
                return encoder
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def retime(spec: TimelineSpec, fps: int) -> TimelineSpec:
    """Même timeline à une autre fréquence d'images (positions et durées converties)."""
    old = spec.canvas.fps
    if fps == old:
        return spec

    def conv(frames: int) -> int:
        return round(frames * fps / old)

    tracks = []
    for track in spec.tracks:
        clips = []
        for c in track.clips:
            start, end = conv(c.start), conv(c.start + c.duration)
            clips.append(dataclasses.replace(
                c, start=start, duration=max(1, end - start), source_in=conv(c.source_in),
                media_length=conv(c.media_length),
                fade_in=conv(c.fade_in), fade_out=conv(c.fade_out)))
        transitions = tuple(dataclasses.replace(t, duration=max(1, conv(t.duration)))
                            for t in track.transitions)
        tracks.append(dataclasses.replace(track, clips=tuple(clips), transitions=transitions))
    canvas = dataclasses.replace(spec.canvas, fps=fps)
    return dataclasses.replace(spec, canvas=canvas, tracks=tuple(tracks))
