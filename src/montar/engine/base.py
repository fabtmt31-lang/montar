# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface du moteur de rendu, indépendante de Qt et de MLT."""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from montar.core.project import Clip, ColorAdjust, Effects, MediaItem, Project, Transform


class EngineUnavailable(RuntimeError):
    """Le moteur ne peut pas être initialisé (bibliothèque absente)."""


class SourceError(RuntimeError):
    """La timeline ne peut pas être construite (média illisible…)."""


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class ClipSpec:
    path: str
    kind: str  # video | image | audio | text (image PNG transparente)
    start: int
    duration: int
    source_in: int = 0
    speed: float = 1.0
    volume: float = 1.0
    fade_in: int = 0
    fade_out: int = 0
    media_size: tuple[int, int] = (0, 0)
    transform: Transform = field(default_factory=Transform)
    color: ColorAdjust = field(default_factory=ColorAdjust)
    preset: str = ""
    preset_amount: float = 1.0
    effects: Effects = field(default_factory=Effects)
    animation_in: str = "none"  # textes : none | fade | slide
    animation_out: str = "none"
    extra_filters: tuple[tuple[str, dict], ...] = ()  # filtres ajoutés par des modules


@dataclass(frozen=True)
class TransitionSpec:
    left: int  # indice du clip de gauche dans TrackSpec.clips
    kind: str
    duration: int


@dataclass(frozen=True)
class TrackSpec:
    kind: str  # video (pistes vidéo et texte) | audio
    muted: bool
    hidden: bool
    clips: tuple[ClipSpec, ...]
    volume: float = 1.0
    transitions: tuple[TransitionSpec, ...] = ()


@dataclass(frozen=True)
class TimelineSpec:
    """Description immuable de la timeline, transmise au fil de rendu.

    `tracks` va de la piste la plus basse (V1) à la plus haute, puis les pistes audio.
    """

    canvas: Canvas
    tracks: tuple[TrackSpec, ...]

    @property
    def length(self) -> int:
        return max((c.start + c.duration for t in self.tracks for c in t.clips), default=0)


TextImage = Callable[[Clip, int, int], str]  # (clip, largeur, hauteur) -> image PNG


@dataclass(frozen=True)
class ClipOverride:
    """Modifications apportées par les modules à un clip au moment du rendu."""

    path: str | None = None  # autre fichier source (ex. timelapse pré-calculé)
    source_in: int | None = None
    speed: float | None = None
    extra_filters: tuple[tuple[str, dict], ...] = ()


ClipHook = Callable[[Clip, MediaItem], ClipOverride | None]


def _clip_spec(clip: Clip, path: str, kind: str, size: tuple[int, int],
               override: ClipOverride | None = None) -> ClipSpec:
    text = clip.text
    o = override or ClipOverride()
    return ClipSpec(
        o.path or path, kind, clip.start, clip.duration,
        clip.source_in if o.source_in is None else o.source_in,
        clip.speed if o.speed is None else o.speed, clip.volume,
        clip.fade_in, clip.fade_out, size, copy.deepcopy(clip.transform),
        copy.deepcopy(clip.color), clip.preset, clip.preset_amount, copy.deepcopy(clip.effects),
        text.animation_in if text else "none", text.animation_out if text else "none",
        tuple(o.extra_filters))


def timeline_spec(project: Project, text_image: TextImage | None = None,
                  hook: ClipHook | None = None,
                  size: tuple[int, int] | None = None) -> TimelineSpec:
    """Description de la timeline pour le moteur. Sans `text_image`, les textes sont ignorés.
    `size` remplace la taille de la toile (export à une autre résolution)."""
    w, h = size or project.canvas_size
    media = {m.id: m for m in project.media}
    by_kind = {k: [t for t in project.tracks if t.kind == k] for k in ("video", "text", "audio")}
    tracks = []
    for track in [*reversed(by_kind["video"]), *reversed(by_kind["text"]), *by_kind["audio"]]:
        clips: list[ClipSpec] = []
        ids: list[str] = []
        for c in sorted(project.clips, key=lambda c: c.start):
            if c.track_id != track.id:
                continue
            if c.is_text:
                if text_image is None:
                    continue
                spec = _clip_spec(c, text_image(c, w, h), "text", (w, h))
            else:
                m = media.get(c.media_id)
                if m is None or not m.exists:
                    continue
                kind = "audio" if track.kind == "audio" else m.kind
                override = hook(c, m) if hook is not None and c.modules else None
                spec = _clip_spec(c, m.path, kind, (m.width, m.height), override)
            clips.append(spec)
            ids.append(c.id)
        transitions = tuple(
            TransitionSpec(ids.index(t.left_id), t.kind, t.duration)
            for t in project.transitions
            if t.track_id == track.id and t.left_id in ids and t.right_id in ids
            and ids.index(t.right_id) == ids.index(t.left_id) + 1
        )
        tracks.append(TrackSpec("audio" if track.kind == "audio" else "video", track.muted,
                                track.hidden, tuple(clips), track.volume,
                                tuple(sorted(transitions, key=lambda t: t.left))))
    return TimelineSpec(Canvas(w, h, project.fps), tuple(tracks))


class Source(ABC):
    """Timeline prête à être rendue image par image."""

    @property
    @abstractmethod
    def length(self) -> int:
        """Nombre d'images (0 pour une timeline vide)."""

    @abstractmethod
    def render(self, frame: int, width: int, height: int) -> bytes:
        """Image `frame` en RGBA 8 bits, de taille width × height (toile entière)."""

    def update(self, spec: TimelineSpec) -> bool:
        """Applique une timeline de même structure sans reconstruction ; False sinon."""
        return False

    def close(self) -> None:  # noqa: B027 - implémentation facultative
        pass


class AudioOutput(ABC):
    """Lecture du son de la timeline ; sa position sert d'horloge à l'aperçu."""

    @abstractmethod
    def start(self, frame: int) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def position(self) -> int:
        """Image en cours de lecture."""

    def set_volume(self, volume: float) -> None:  # noqa: B027
        """Niveau d'écoute (0 = muet, 1 = normal) ; n'affecte pas l'export."""

    def close(self) -> None:  # noqa: B027
        pass


class ExportJob(ABC):
    """Export d'une timeline vers un fichier, en tâche de fond. Les attributs sont lus
    depuis l'interface pendant que le moteur travaille."""

    total: int = 0  # images à produire
    done: int = 0  # images déjà produites
    finished: bool = False
    error: str = ""  # vide si l'export a réussi (ou est en cours)
    cancelled: bool = False
    used_encoder: str = ""  # encodeur vidéo réellement utilisé

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def cancel(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool:
        """Attend la fin (utile aux tests) ; renvoie `finished`."""
        return self.finished

    @property
    def progress(self) -> float:
        if self.finished and not self.error:
            return 1.0
        return min(1.0, self.done / max(1, self.total))


class Engine(ABC):
    name: str = ""

    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def build(self, spec: TimelineSpec) -> Source:
        """Construit la timeline ; à utiliser depuis un seul fil d'exécution."""

    def export(self, spec: TimelineSpec, settings) -> ExportJob:
        """Prépare l'export (`settings` : `engine.export.ExportSettings`), à lancer par
        `start()` ; la timeline doit être à la taille et à la fréquence de sortie."""
        raise NotImplementedError

    def audio_output(self, spec: TimelineSpec) -> AudioOutput | None:
        """Sortie son, ou None si aucune n'est disponible."""
        return None
