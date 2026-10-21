# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface du moteur de rendu, indépendante de Qt et de MLT."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from montar.core.project import Project


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
    kind: str  # video | image | audio
    start: int
    duration: int
    source_in: int


@dataclass(frozen=True)
class TrackSpec:
    kind: str  # video | audio
    muted: bool
    hidden: bool
    clips: tuple[ClipSpec, ...]


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


def timeline_spec(project: Project) -> TimelineSpec:
    w, h = project.canvas_size
    media = {m.id: m for m in project.media}
    videos = [t for t in project.tracks if t.kind == "video"]
    audios = [t for t in project.tracks if t.kind == "audio"]
    tracks = []
    for track in [*reversed(videos), *audios]:
        clips = tuple(
            ClipSpec(media[c.media_id].path, media[c.media_id].kind, c.start, c.duration,
                     c.source_in)
            for c in sorted(project.clips, key=lambda c: c.start)
            if c.track_id == track.id and c.media_id in media and media[c.media_id].exists
        )
        tracks.append(TrackSpec(track.kind, track.muted, track.hidden, clips))
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

    def close(self) -> None:  # noqa: B027
        pass


class Engine(ABC):
    name: str = ""

    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def build(self, spec: TimelineSpec) -> Source:
        """Construit la timeline ; à utiliser depuis un seul fil d'exécution."""

    def audio_output(self, spec: TimelineSpec) -> AudioOutput | None:
        """Sortie son, ou None si aucune n'est disponible."""
        return None
