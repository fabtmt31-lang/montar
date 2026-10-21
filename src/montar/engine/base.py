# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface du moteur de rendu, indépendante de Qt et de MLT."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Durée d'affichage d'une image fixe ouverte seule dans l'aperçu.
IMAGE_PREVIEW_SECONDS = 5


class EngineUnavailable(RuntimeError):
    """Le moteur ne peut pas être initialisé (bibliothèque absente)."""


class SourceError(RuntimeError):
    """Le média ne peut pas être ouvert par le moteur."""


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    fps: int


class Source(ABC):
    """Un média ouvert, rendu dans la toile du projet."""

    @property
    @abstractmethod
    def length(self) -> int:
        """Nombre d'images."""

    @property
    @abstractmethod
    def fps(self) -> float: ...

    @abstractmethod
    def render(self, frame: int, width: int, height: int) -> bytes:
        """Image `frame` en RGBA 8 bits, de taille width × height (toile entière)."""

    def close(self) -> None:  # noqa: B027 - implémentation facultative
        pass


class Engine(ABC):
    name: str = ""

    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def open(self, path: str, kind: str, canvas: Canvas) -> Source:
        """Ouvre un média ; doit être utilisé depuis un seul fil d'exécution."""
