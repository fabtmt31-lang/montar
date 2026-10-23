# SPDX-License-Identifier: GPL-3.0-or-later
"""API publique des modules montar (version 1.3).

Un module est un dossier contenant `module.json` et un paquet Python dont le fichier
`__init__.py` définit `register(api: ModuleAPI)`. Voir docs/MODULES.md.

Points d'extension :
- `VideoEffect` : effet réglable appliqué à l'image d'un clip (filtres MLT / FFmpeg) ;
- `AudioEffect` : effet réglable appliqué au son d'un clip (1.2) ;
- `Transition` : transition vidéo entre deux clips (transition MLT) (1.2) ;
- `Generator` : crée un média (fond, motif…) ajouté au projet (1.2) ;
- `ExportFormat` : format de fichier supplémentaire à l'export (1.2) ;
- `Tool` : action sur un clip (menu contextuel, inspecteur) ;
- `ClipSource` : remplace la source d'un clip au rendu (ex. timelapse pré-calculé).

Les réglages d'un module pour un clip sont stockés dans `clip.modules[<id du module>]`.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

API_VERSION = (1, 3)

# Pseudo-filtre (1.3) qu'un `VideoEffect` peut renvoyer : zoom animé du cadre du clip autour
# de son centre. Propriétés : start, end (facteurs, 1 = normal), seconds (0 = tout le clip),
# ease (« smooth » ou « linear »).
ZOOM = "montar.zoom"

Filters = list[tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class Param:
    """Paramètre réglable ; l'inspecteur génère le contrôle correspondant."""

    key: str
    label: str
    kind: str = "float"  # float | int | bool | choice | color (1.2, « #RRGGBB »)
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

    @classmethod
    def color(cls, key: str, label: str, default: str = "#FFFFFF") -> Param:
        return cls(key, label, "color", default)


class VideoEffect:
    """Effet vidéo d'un module. `filters` reçoit les valeurs des paramètres du clip."""

    id: str = ""
    name: str = ""
    description: str = ""  # phrase affichée dans « Appliquer un effet ou un module » (1.1)
    icon: str = "sparkles"  # (1.1)
    params: Sequence[Param] = ()

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params}

    def filters(self, values: dict[str, Any]) -> Filters:
        return []


class AudioEffect(VideoEffect):
    """Effet sur le son d'un clip (vidéo avec son ou audio). `filters` renvoie des filtres
    audio MLT (« volume », « avfilter.aecho »…) (1.2)."""

    icon: str = "music"


class Transition:
    """Transition vidéo proposée dans le panneau Transitions (1.2). `transition` renvoie le
    service MLT et ses propriétés pour une transition de `duration` images ; préférez des
    propriétés sans images clés (la durée change si l'export se fait à une autre fréquence)."""

    id: str = ""  # identifiant avec un point (« monmodule.cercle ») : il est stocké au projet
    name: str = ""
    description: str = ""
    icon: str = "blend"

    def transition(self, context: RenderContext, duration: int) -> tuple[str, dict[str, Any]]:
        return "luma", {}


class Generator:
    """Crée un média (image ou vidéo) à partir de réglages : fond uni, dégradé, motif… Le
    fichier est écrit dans le dossier des médias du projet puis importé (1.2)."""

    id: str = ""
    name: str = ""
    description: str = ""
    icon: str = "image"
    suffix: str = ".png"  # extension du fichier créé
    params: Sequence[Param] = ()

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params}

    def generate(self, context: GeneratorContext, values: dict[str, Any], target: Path) -> None:
        """Écrit le média dans `target` (qui porte l'extension `suffix`)."""
        raise NotImplementedError


class ExportFormat:
    """Format de fichier supplémentaire proposé à l'export (1.2). `properties` renvoie les
    propriétés du consommateur MLT « avformat » (f, vcodec, acodec, crf…) ; la taille, la
    fréquence et le chemin sont réglés par montar."""

    id: str = ""
    name: str = ""
    extension: str = ".mkv"
    description: str = ""
    audio_only: bool = False

    def properties(self, settings: Any) -> dict[str, Any]:
        return {}


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
    description: str = ""  # phrase affichée dans « Appliquer un effet ou un module » (1.1)

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


class GeneratorContext(RenderContext, Protocol):
    """Taille de la toile du projet, pour les générateurs."""

    width: int
    height: int


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
    audio_effects: list[AudioEffect] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    generators: list[Generator] = field(default_factory=list)
    export_formats: list[ExportFormat] = field(default_factory=list)

    def add_video_effect(self, effect: VideoEffect | type[VideoEffect]) -> None:
        self.effects.append(effect() if isinstance(effect, type) else effect)

    def add_tool(self, tool: Tool | type[Tool]) -> None:
        self.tools.append(tool() if isinstance(tool, type) else tool)

    def add_clip_source(self, source: ClipSource | type[ClipSource]) -> None:
        self.sources.append(source() if isinstance(source, type) else source)

    def add_audio_effect(self, effect: AudioEffect | type[AudioEffect]) -> None:
        self.audio_effects.append(effect() if isinstance(effect, type) else effect)

    def add_transition(self, transition: Transition | type[Transition]) -> None:
        self.transitions.append(transition() if isinstance(transition, type) else transition)

    def add_generator(self, generator: Generator | type[Generator]) -> None:
        self.generators.append(generator() if isinstance(generator, type) else generator)

    def add_export_format(self, fmt: ExportFormat | type[ExportFormat]) -> None:
        self.export_formats.append(fmt() if isinstance(fmt, type) else fmt)
