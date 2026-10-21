# SPDX-License-Identifier: GPL-3.0-or-later
"""Modèle d'un projet montar et sa persistance en JSON (fichier .montar)."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from montar.core import formats

FORMAT_VERSION = 1
PROJECT_SUFFIX = ".montar"


class ProjectError(Exception):
    pass


@dataclass
class MediaItem:
    """Média importé dans le projet. Le fichier source n'est jamais copié ni modifié."""

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

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()


@dataclass
class Track:
    kind: str  # video | audio | text
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class Project:
    name: str
    aspect: str = formats.DEFAULT_ASPECT
    resolution: str = formats.DEFAULT_RESOLUTION
    fps: int = formats.DEFAULT_FPS
    media: list[MediaItem] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    path: Path | None = None  # emplacement du fichier .montar, non sérialisé

    def __post_init__(self) -> None:
        formats.aspect_ratio(self.aspect)  # valide le format
        if self.resolution not in formats.RESOLUTIONS:
            raise ValueError(f"résolution inconnue : {self.resolution}")
        if not self.tracks:
            self.tracks = [Track("video", "Vidéo"), Track("audio", "Musique")]

    @property
    def canvas_size(self) -> tuple[int, int]:
        return formats.canvas_size(self.aspect, self.resolution)

    def find_media(self, media_id: str) -> MediaItem | None:
        return next((m for m in self.media if m.id == media_id), None)

    def has_media_path(self, path: str | os.PathLike[str]) -> bool:
        target = os.path.abspath(path)
        return any(os.path.abspath(m.path) == target for m in self.media)

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
            fields = {k: v for k, v in raw.items() if k in MediaItem.__dataclass_fields__}
            fields["path"] = _resolve_path(fields.get("path", ""), base)
            media.append(MediaItem(**fields))
        tracks = [
            Track(**{k: v for k, v in t.items() if k in Track.__dataclass_fields__})
            for t in data.get("tracks", [])
        ]
        try:
            return cls(
                name=data["name"],
                aspect=data.get("aspect", formats.DEFAULT_ASPECT),
                resolution=data.get("resolution", formats.DEFAULT_RESOLUTION),
                fps=int(data.get("fps", formats.DEFAULT_FPS)),
                media=media,
                tracks=tracks,
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


def unique_project_path(directory: Path, name: str) -> Path:
    """Chemin libre « <nom>.montar », « <nom> 2.montar »… dans le dossier donné."""
    safe = "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "Sans titre"
    candidate = directory / f"{safe}{PROJECT_SUFFIX}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{safe} {n}{PROJECT_SUFFIX}"
        n += 1
    return candidate
