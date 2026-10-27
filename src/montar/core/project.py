# SPDX-License-Identifier: GPL-3.0-or-later
"""Modèle d'un projet montar et sa persistance en JSON (fichier .montar)."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from montar.core import formats
from montar.i18n import _

if TYPE_CHECKING:
    from montar.core.mastering import Mastering

FORMAT_VERSION = 4  # 2 : clips ; 3 : réglages, textes, transitions ; 4 : réglages de modules
PROJECT_SUFFIX = ".montar"
MEDIA_DIR = "medias"
EXPORT_DIR = "exports"


class ProjectError(Exception):
    pass


@dataclass
class MediaItem:
    """Média importé dans le projet : une copie du fichier, rangée dans le dossier « medias »
    du projet (le fichier d'origine n'est jamais modifié)."""

    path: str  # chemin absolu en mémoire ; relatif au projet dans le fichier quand possible
    kind: str = "video"  # video | audio | image
    duration: float = 0.0  # secondes (0 pour une image)
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    original_path: str = ""  # fichier d'origine de la copie (évite d'importer deux fois)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()

    def length_frames(self, fps: int) -> int | None:
        """Nombre d'images disponibles à la fréquence du projet ; None pour une image fixe."""
        if self.kind == "image":
            return None
        return max(1, round(self.duration * fps))


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Track:
    kind: str  # video | audio | text
    name: str
    muted: bool = False
    hidden: bool = False  # pistes vidéo et texte : image masquée
    locked: bool = False  # clips protégés contre toute modification
    volume: float = 1.0  # gain linéaire de la piste (0 à 2)
    voice: bool = False  # piste de voix : les sons « s'effacent sous la voix » baissent dessous
    id: str = field(default_factory=new_id)


@dataclass
class Marker:
    """Repère sur la timeline (F-TL-03) ; sans effet sur le rendu."""

    frame: int
    name: str = ""
    color: str = "#E8A33D"
    id: str = field(default_factory=new_id)


@dataclass
class Subtitle:
    """Sous-titre (F-TXT-05) : texte affiché de `start` à `end` (exclu), en images."""

    start: int
    end: int
    text: str = ""
    id: str = field(default_factory=new_id)


@dataclass
class Transform:
    """Taille, position et orientation d'un clip dans la toile."""

    x: float = 0.0  # décalage du centre, en fraction de la largeur de la toile
    y: float = 0.0  # décalage du centre, en fraction de la hauteur de la toile
    scale: float = 1.0
    rotation: float = 0.0  # degrés, sens horaire
    opacity: float = 1.0
    flip_h: bool = False
    flip_v: bool = False
    fit: str = "fit"  # fit (ajuster) | fill (remplir) | stretch (étirer)
    crop_left: float = 0.0  # fractions de l'image source retirées sur chaque bord
    crop_right: float = 0.0
    crop_top: float = 0.0
    crop_bottom: float = 0.0

    def is_identity(self) -> bool:
        return self == Transform()


@dataclass
class ColorAdjust:
    """Réglages de couleur, chacun de -1 à 1 (0 = inchangé)."""

    brightness: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    temperature: float = 0.0  # > 0 : plus chaud
    exposure: float = 0.0

    def is_identity(self) -> bool:
        return self == ColorAdjust()


@dataclass
class Grade:
    """Étalonnage avancé : roues (position x, y dans le disque, et niveau de -1 à 1) pour
    les ombres (lift), les tons moyens (gamma) et les hautes lumières (gain), courbes,
    teinte, vibrance et LUT."""

    lift: list[float] = field(default_factory=lambda: [0.0, 0.0])
    lift_level: float = 0.0
    gamma: list[float] = field(default_factory=lambda: [0.0, 0.0])
    gamma_level: float = 0.0
    gain: list[float] = field(default_factory=lambda: [0.0, 0.0])
    gain_level: float = 0.0
    # courbes : "master", "red", "green", "blue" → points [entrée, sortie] de 0 à 1
    curves: dict[str, list[list[float]]] = field(default_factory=dict)
    hue: float = 0.0  # rotation de teinte, en degrés
    vibrance: float = 0.0  # -1 à 1 : saturation des couleurs ternes surtout
    lut: str = ""  # fichier .cube, relatif au dossier du projet

    def is_identity(self) -> bool:
        return self == Grade()


@dataclass
class Effects:
    """Effets simples, chacun de 0 (absent) à 1."""

    blur: float = 0.0
    sharpen: float = 0.0
    vignette: float = 0.0

    def is_identity(self) -> bool:
        return self == Effects()


@dataclass
class AudioAdjust:
    """Réglages du son d'un clip (F-AUD-05 / 06 et options avancées)."""

    denoise: float = 0.0  # réduction de bruit, 0 à 1
    normalize: bool = False  # volume régulier (normalisation dynamique)
    duck: bool = False  # baisse automatiquement sous les pistes de voix
    duck_depth: float = 12.0  # atténuation sous la voix, en dB
    bass: float = 0.0  # égaliseur, en dB (-12 à +12)
    mid: float = 0.0
    treble: float = 0.0
    highpass: float = 0.0  # coupe-bas, en Hz (0 = aucun)
    lowpass: float = 0.0  # coupe-haut, en Hz (0 = aucun)
    compress: float = 0.0  # compresseur, 0 à 1
    pitch: float = 0.0  # hauteur, en demi-tons (-12 à +12)
    pan: float = 0.0  # panoramique, -1 (gauche) à 1 (droite)
    echo: float = 0.0  # écho, 0 à 1
    reverb: float = 0.0  # réverbération, 0 à 1

    def is_identity(self) -> bool:
        return self == AudioAdjust()


@dataclass
class TextStyle:
    """Contenu et mise en forme d'un clip de texte (tailles pour une toile de 1080 px)."""

    content: str = "Titre"
    preset: str = "title"
    family: str = "Manrope"
    size: float = 96.0
    weight: int = 700
    italic: bool = False
    underline: bool = False
    uppercase: bool = False
    color: str = "#17261E"
    align: str = "center"  # left | center | right
    letter_spacing: float = 0.0  # pixels
    outline_color: str = "#FFFFFF"
    outline_width: float = 0.0
    shadow: bool = False
    shadow_color: str = "#66000000"
    background: str = ""  # couleur du bandeau, vide = aucun
    pill: bool = False  # bandeau aux bords entièrement arrondis
    x: float = 0.5  # centre du bloc de texte, en fraction de la toile
    y: float = 0.5
    # entrée : none | fade | slide (par le bas) | slide_top | slide_left | slide_right | zoom
    # | pop | typewriter ; sortie : les mêmes, sans la machine à écrire
    animation_in: str = "none"
    animation_out: str = "none"
    animation_in_duration: float = 0.5  # secondes
    animation_out_duration: float = 0.5
    typing_speed: float = 18.0  # machine à écrire : caractères par seconde
    line_height: float = 1.0  # interligne (× hauteur de ligne de la police)
    background_opacity: float = 1.0  # opacité du bandeau


@dataclass
class Clip:
    """Portion d'un média (ou texte) placée sur une piste. Valeurs en images du projet."""

    media_id: str  # vide pour un clip de texte
    track_id: str
    start: int  # position sur la timeline
    duration: int
    source_in: int = 0  # première image utilisée dans le média (à vitesse normale)
    speed: float = 1.0
    reverse: bool = False  # lecture inversée (la plage source_in… est lue à l'envers)
    volume: float = 1.0  # gain linéaire (0 = muet, 2 = +6 dB)
    fade_in: int = 0  # images
    fade_out: int = 0
    transform: Transform = field(default_factory=Transform)
    color: ColorAdjust = field(default_factory=ColorAdjust)
    preset: str = ""  # filtre prédéfini (noir et blanc, sépia…)
    preset_amount: float = 1.0
    effects: Effects = field(default_factory=Effects)
    audio: AudioAdjust = field(default_factory=AudioAdjust)
    grade: Grade = field(default_factory=Grade)
    text: TextStyle | None = None
    # Réglages propres aux modules, par identifiant de module (ex. "timelapse").
    # Un module absent est ignoré au rendu mais ses réglages sont conservés.
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    # images clés : propriété (x, y, scale, rotation, opacity) → [[image, valeur], …]
    keyframes: dict[str, list[list[float]]] = field(default_factory=dict)
    id: str = field(default_factory=new_id)

    @property
    def end(self) -> int:
        return self.start + self.duration

    @property
    def is_text(self) -> bool:
        return self.text is not None


@dataclass
class Transition:
    """Transition entre deux clips consécutifs d'une piste.

    Le clip de droite chevauche les `duration` dernières images du clip de gauche."""

    track_id: str
    left_id: str
    right_id: str
    kind: str = "dissolve"
    duration: int = 25
    id: str = field(default_factory=new_id)


_NESTED = {"transform": Transform, "color": ColorAdjust, "effects": Effects, "text": TextStyle,
           "audio": AudioAdjust, "grade": Grade}


def default_subtitle_style() -> TextStyle:
    """Blanc sur bandeau sombre, en bas de l'image."""
    return TextStyle("", "subtitle", "Manrope", 44, 600, color="#FFFFFF",
                     background="#D917261E", y=0.88)


def _build(cls, data: dict[str, Any]):
    """Instancie une dataclass en ignorant les champs inconnus (fichiers plus récents)."""
    known = {f.name for f in fields(cls)}
    values = {}
    for key, value in data.items():
        if key not in known:
            continue
        nested = _NESTED.get(key)
        if nested is not None and isinstance(value, dict):
            value = _build(nested, value)
        values[key] = value
    return cls(**values)


@dataclass
class Project:
    name: str
    aspect: str = formats.DEFAULT_ASPECT
    resolution: str = formats.DEFAULT_RESOLUTION
    fps: int = formats.DEFAULT_FPS
    media: list[MediaItem] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)  # de haut en bas, comme affiché
    clips: list[Clip] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    subtitles: list[Subtitle] = field(default_factory=list)
    subtitle_style: TextStyle = field(default_factory=lambda: default_subtitle_style())
    subtitles_shown: bool = True  # affichés dans l'aperçu
    # finition pro (étalonnage et mastering de tout le projet, à l'export)
    mastering: Mastering = field(default_factory=lambda: _new_mastering())
    path: Path | None = None  # emplacement du fichier .montar, non sérialisé

    def __post_init__(self) -> None:
        formats.aspect_ratio(self.aspect)  # valide le format
        if self.resolution not in formats.RESOLUTIONS:
            raise ValueError(f"résolution inconnue : {self.resolution}")
        if not self.tracks:
            self.tracks = [Track("video", _("Vidéo")), Track("audio", _("Musique"))]

    @property
    def canvas_size(self) -> tuple[int, int]:
        return formats.canvas_size(self.aspect, self.resolution)

    def find_media(self, media_id: str) -> MediaItem | None:
        return next((m for m in self.media if m.id == media_id), None)

    @property
    def media_dir(self) -> Path | None:
        """Dossier des copies des médias, à côté du fichier du projet."""
        return self.path.parent / MEDIA_DIR if self.path is not None else None

    def has_media_path(self, path: str | os.PathLike[str]) -> bool:
        """Le fichier (ou sa copie) est-il déjà dans le projet ?"""
        target = os.path.abspath(path)
        return any(target in (os.path.abspath(m.path),
                              os.path.abspath(m.original_path) if m.original_path else "")
                   for m in self.media)

    # --- sérialisation ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        base = self.path.parent if self.path else None
        media = []
        for m in self.media:
            d = asdict(m)
            d["path"] = _portable_path(m.path, base)
            media.append(d)
        return {
            "format_version": FORMAT_VERSION,
            "name": self.name,
            "aspect": self.aspect,
            "resolution": self.resolution,
            "fps": self.fps,
            "media": media,
            "tracks": [asdict(t) for t in self.tracks],
            "clips": [asdict(c) for c in self.clips],
            "transitions": [asdict(t) for t in self.transitions],
            "markers": [asdict(m) for m in self.markers],
            "subtitles": [asdict(s) for s in self.subtitles],
            "subtitle_style": asdict(self.subtitle_style),
            "subtitles_shown": self.subtitles_shown,
            "mastering": self.mastering.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> Project:
        version = data.get("format_version")
        if not isinstance(version, int) or version > FORMAT_VERSION:
            raise ProjectError(
                f"version de projet non prise en charge : {version!r} "
                f"(maximum {FORMAT_VERSION})"
            )
        base = path.parent if path else None
        media = []
        for raw in data.get("media", []):
            values = {k: v for k, v in raw.items() if k in MediaItem.__dataclass_fields__}
            values["path"] = _resolve_path(values.get("path", ""), base)
            media.append(MediaItem(**values))
        try:
            tracks = [_build(Track, t) for t in data.get("tracks", [])]
            clips = [_build(Clip, c) for c in data.get("clips", [])]
            transitions = [_build(Transition, t) for t in data.get("transitions", [])]
            markers = [_build(Marker, m) for m in data.get("markers", [])]
            subtitles = [_build(Subtitle, s) for s in data.get("subtitles", [])]
            subtitle_style = _build(TextStyle, data["subtitle_style"]) \
                if isinstance(data.get("subtitle_style"), dict) else default_subtitle_style()
        except (TypeError, AttributeError) as exc:
            raise ProjectError(f"projet invalide : {exc}") from exc
        try:
            return cls(
                name=data["name"],
                aspect=data.get("aspect", formats.DEFAULT_ASPECT),
                resolution=data.get("resolution", formats.DEFAULT_RESOLUTION),
                fps=int(data.get("fps", formats.DEFAULT_FPS)),
                media=media,
                tracks=tracks,
                clips=clips,
                transitions=transitions,
                markers=markers,
                subtitles=subtitles,
                subtitle_style=subtitle_style,
                subtitles_shown=bool(data.get("subtitles_shown", True)),
                mastering=_load_mastering(data.get("mastering")),
                path=path,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ProjectError(f"projet invalide : {exc}") from exc

    def save(self, path: Path | None = None) -> Path:
        """Enregistre de façon atomique (fichier temporaire puis renommage)."""
        if path is not None:
            self.path = Path(path)
        if self.path is None:
            raise ProjectError("aucun emplacement d'enregistrement")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(
            prefix=".", suffix=".tmp", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return self.path

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Project:
        path = Path(path).resolve()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"impossible de lire {path} : {exc}") from exc
        if not isinstance(data, dict):
            raise ProjectError(f"{path} n'est pas un projet montar")
        return cls.from_dict(data, path)


def _new_mastering() -> Mastering:
    from montar.core.mastering import Mastering

    return Mastering()


def _load_mastering(data: Any) -> Mastering:
    from montar.core.mastering import Mastering

    return Mastering.from_dict(data)


def _portable_path(path: str, base: Path | None) -> str:
    """Chemin relatif au dossier du projet quand le média est dans son arborescence."""
    p = Path(path)
    if base is not None:
        try:
            return p.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            pass
    return str(p)


def _resolve_path(path: str, base: Path | None) -> str:
    p = Path(path)
    if not p.is_absolute() and base is not None:
        p = base / p
    return str(p)


def _safe_name(name: str) -> str:
    return "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "Sans titre"


def unique_project_path(directory: Path, name: str) -> Path:
    """Chemin libre « <nom>.montar », « <nom> 2.montar »… dans le dossier donné."""
    safe = _safe_name(name)
    candidate = directory / f"{safe}{PROJECT_SUFFIX}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{safe} {n}{PROJECT_SUFFIX}"
        n += 1
    return candidate


def unique_project_folder(directory: Path, name: str) -> Path:
    """Fichier d'un nouveau projet dans son propre dossier : « <nom>/<nom>.montar »
    (« <nom> 2/<nom> 2.montar »… si le dossier existe déjà)."""
    safe = _safe_name(name)
    label, n = safe, 2
    while (directory / label).exists():
        label = f"{safe} {n}"
        n += 1
    return directory / label / f"{label}{PROJECT_SUFFIX}"
