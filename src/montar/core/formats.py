# SPDX-License-Identifier: GPL-3.0-or-later
"""Formats d'image, résolutions et fréquences proposés à la création d'un projet."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class AspectRatio:
    id: str
    label: str
    width: int
    height: int

    @property
    def ratio(self) -> Fraction:
        return Fraction(self.width, self.height)


ASPECT_RATIOS: tuple[AspectRatio, ...] = (
    AspectRatio("16:9", "Paysage", 16, 9),
    AspectRatio("9:16", "Vertical", 9, 16),
    AspectRatio("1:1", "Carré", 1, 1),
    AspectRatio("4:5", "Portrait", 4, 5),
    AspectRatio("21:9", "Cinéma", 21, 9),
)

# Résolution = longueur du petit côté de la toile.
RESOLUTIONS: dict[str, int] = {"720p": 720, "1080p": 1080, "4K": 2160}
FRAME_RATES: tuple[int, ...] = (24, 25, 30, 60)

DEFAULT_ASPECT = "16:9"
DEFAULT_RESOLUTION = "1080p"
DEFAULT_FPS = 25


def aspect_ratio(aspect_id: str) -> AspectRatio:
    for ar in ASPECT_RATIOS:
        if ar.id == aspect_id:
            return ar
    raise ValueError(f"format inconnu : {aspect_id}")


def _even(value: Fraction) -> int:
    """Arrondit à l'entier pair le plus proche (exigé par la plupart des codecs)."""
    return int(round(value / 2)) * 2


def canvas_size(aspect_id: str, resolution: str) -> tuple[int, int]:
    """Taille de la toile en pixels, ex. ("16:9", "1080p") -> (1920, 1080)."""
    ar = aspect_ratio(aspect_id)
    short = RESOLUTIONS[resolution]
    if ar.width >= ar.height:
        return _even(short * ar.ratio), short
    return short, _even(short / ar.ratio)


# Format libre : la toile prend une taille donnée (celle d'un média, en général).
CUSTOM = "custom"
MIN_SIDE, MAX_SIDE = 16, 8192


def custom_size(width: int, height: int) -> tuple[int, int]:
    """Taille d'une toile libre : bornée et paire (exigé par la plupart des codecs)."""
    w = max(MIN_SIDE, min(MAX_SIDE, int(width)))
    h = max(MIN_SIDE, min(MAX_SIDE, int(height)))
    return w - w % 2, h - h % 2


def format_for(width: int, height: int,
               tolerance: float = 0.02) -> tuple[str, str, tuple[int, int]]:
    """Format de projet qui épouse une image de `width` × `height` : un format connu (16:9,
    9:16…) quand ses proportions et sa taille correspondent à `tolerance` près (1920 × 1080 →
    16:9 en 1080p), sinon le format libre à cette taille exacte. Renvoie (format,
    résolution, taille de la toile)."""
    if width <= 0 or height <= 0:
        raise ValueError("taille inconnue")
    for ar in ASPECT_RATIOS:
        for resolution in RESOLUTIONS:
            w, h = canvas_size(ar.id, resolution)
            if abs(width / w - 1) <= tolerance and abs(height / h - 1) <= tolerance:
                return ar.id, resolution, (w, h)
    return CUSTOM, DEFAULT_RESOLUTION, custom_size(width, height)


def label(aspect_id: str, size: tuple[int, int]) -> str:
    """Nom court du format : « 16:9 », ou la taille pour un format libre."""
    return f"{size[0]} × {size[1]}" if aspect_id == CUSTOM else aspect_id
