# SPDX-License-Identifier: GPL-3.0-or-later
"""API publique des modules montar (version 1).

Un module est un dossier contenant `module.json` et un paquet Python dont le fichier
`__init__.py` définit `register(api: ModuleAPI)`. Voir docs/MODULES.md.

Points d'extension :
- `VideoEffect` : effet réglable appliqué à un clip (filtres MLT / FFmpeg) ;
- `Tool` : action sur un clip (menu contextuel, inspecteur) ;
- `ClipSource` : remplace la source d'un clip au rendu (ex. timelapse pré-calculé).

Les réglages d'un module pour un clip sont stockés dans `clip.modules[<id du module>]`.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

API_VERSION = (1, 0)

Filters = list[tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class Param:
    """Paramètre réglable ; l'inspecteur génère le contrôle correspondant."""

    key: str
    label: str
    kind: str = "float"  # float | int | bool | choice
    default: Any = 0.0
    minimum: float = 0.0
    maximum: float = 1.0
    choices: tuple[tuple[str, str], ...] = ()  # (valeur, libellé) pour « choice »
    unit: str = ""

    @classmethod
    def float(cls, key: str, label: str, minimum: float = 0.0, maximum: float = 1.0,
              default: float = 0.0, unit: str = "") -> Param:
        return cls(key, label, "float", default, minimum, maximum, unit=unit)

    @classmethod
    def choice(cls, key: str, label: str, choices: Sequence[tuple[str, str]],
               default: str | None = None) -> Param:
        return cls(key, label, "choice", default or choices[0][0], choices=tuple(choices))

    @classmethod
    def bool(cls, key: str, label: str, default: bool = False) -> Param:
        return cls(key, label, "bool", default)


class VideoEffect:
    """Effet vidéo d'un module. `filters` reçoit les valeurs des paramètres du clip."""

    id: str = ""
    name: str = ""
    params: Sequence[Param] = ()

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params}

    def filters(self, values: dict[str, Any]) -> Filters:
        return []


@dataclass(frozen=True)
class SourceOverride:
    """Source de remplacement d'un clip au rendu (chemin, image d'entrée, vitesse)."""

    path: str
    source_in: int = 0
    speed: float = 1.0
    kind: str = "video"


class ClipSource:
    """Remplace la source des clips portant les réglages de ce module."""

    def resolve(self, context: RenderContext, clip: Any, media: Any) -> SourceOverride | None:
        return None

    def badge(self, settings: dict[str, Any]) -> str | None:
        """Court libellé affiché sur le clip dans la timeline (ex. « TL ×16 »)."""
        return None


class Tool:
    """Action proposée pour un clip. `section` = "speed" la place dans l'onglet Vitesse."""

    id: str = ""
    name: str = ""
    icon: str = "sparkles"
    section: str = ""

    def available(self, editor: EditorContext, clip: Any) -> bool:
        return True

    def run(self, editor: EditorContext, clip: Any) -> None:
        raise NotImplementedError


class RenderContext(Protocol):
    """Services offerts aux modules pendant la préparation du rendu."""

    fps: int
    cache_dir: Path

    def schedule_job(self, key: str, title: str,
                     work: Callable[[Callable[[float], None], Callable[[], bool]], None]) -> None:
        """Lance une tâche de fond (une seule par clé). `work(progress, cancelled)`."""


class EditorContext(RenderContext, Protocol):
    """Services offerts aux outils : projet, timeline, modification annulable, fenêtre."""

    project: Any
    timeline: Any
    playhead: int
    selection_range: tuple[str, int, int] | None  # (clip, début, fin) marqués avec I / O
    parent: Any  # widget parent pour les dialogues

    def edit(self, label: str, operation: Callable[[Any], Any]) -> Any: ...

    def error(self, message: str) -> None: ...


@dataclass
class ModuleAPI:
    """Objet transmis à `register(api)`."""

    module_id: str
    module_dir: Path
    api_version: tuple[int, int] = API_VERSION
    effects: list[VideoEffect] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    sources: list[ClipSource] = field(default_factory=list)

    def add_video_effect(self, effect: VideoEffect | type[VideoEffect]) -> None:
        self.effects.append(effect() if isinstance(effect, type) else effect)

    def add_tool(self, tool: Tool | type[Tool]) -> None:
        self.tools.append(tool() if isinstance(tool, type) else tool)

    def add_clip_source(self, source: ClipSource | type[ClipSource]) -> None:
        self.sources.append(source() if isinstance(source, type) else source)
