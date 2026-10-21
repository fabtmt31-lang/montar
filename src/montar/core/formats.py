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
