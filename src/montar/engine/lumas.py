# SPDX-License-Identifier: GPL-3.0-or-later
"""Motifs des transitions « luma » (balayages, stores, ouvertures, cercle…).

Un motif donne, pour chaque point de l'image, l'instant (0 à 1) où la seconde vidéo y
apparaît : les zones sombres passent d'abord. Le moteur les écrit en images PGM pour la
transition « luma » de MLT ; le panneau Transitions s'en sert pour ses vignettes."""
from __future__ import annotations

import math
from collections.abc import Callable

# (u, v) dans [0, 1], largeur / hauteur de l'image → instant dans [0, 1]
Pattern = Callable[[float, float, float], float]


def _clock(u: float, v: float, a: float) -> float:
    angle = math.atan2((u - 0.5) * a, -(v - 0.5))  # 0 en haut, sens des aiguilles
    return (angle % (2 * math.pi)) / (2 * math.pi)


def _circle(u: float, v: float, a: float) -> float:
    return min(1.0, math.hypot((u - 0.5) * a, v - 0.5) / math.hypot(0.5 * a, 0.5))


def _diamond(u: float, v: float, a: float) -> float:
    return (abs(u - 0.5) * a + abs(v - 0.5)) / (0.5 * a + 0.5)


def _thirds(u: float, v: float, a: float) -> float:
    band = min(2, int(u * 3))  # trois bandes verticales, l'une après l'autre
    return (band + v) / 3


# identifiant → (motif, douceur du bord)
PATTERNS: dict[str, tuple[Pattern, float]] = {
    "wipe_right": (lambda u, v, a: u, 0.15),
    "wipe_left": (lambda u, v, a: 1 - u, 0.15),
    "wipe_down": (lambda u, v, a: v, 0.15),
    "wipe_up": (lambda u, v, a: 1 - v, 0.15),
    "wipe_diagonal": (lambda u, v, a: (u + v) / 2, 0.15),
    "soft_wipe_right": (lambda u, v, a: u, 0.6),
    "soft_wipe_left": (lambda u, v, a: 1 - u, 0.6),
    "soft_wipe_down": (lambda u, v, a: v, 0.6),
    "soft_wipe_up": (lambda u, v, a: 1 - v, 0.6),
    "blinds": (lambda u, v, a: (u * 6) % 1.0, 0.05),
    "barn_vertical": (lambda u, v, a: abs(u - 0.5) * 2, 0.1),
    "barn_horizontal": (lambda u, v, a: abs(v - 0.5) * 2, 0.1),
    "close": (lambda u, v, a: 1 - abs(u - 0.5) * 2, 0.1),
    "clock": (_clock, 0.05),
    "circle": (_circle, 0.1),
    "diamond": (_diamond, 0.1),
    "thirds": (_thirds, 0.05),
}


def softness(kind: str) -> float:
    return PATTERNS[kind][1]


def luma_bytes(kind: str, width: int, height: int, aspect: float | None = None) -> bytes:
    """Niveaux de gris (un octet par point, ligne par ligne) du motif `kind` ; `aspect` :
    proportions de l'image affichée (par défaut celles du motif)."""
    pattern = PATTERNS[kind][0]
    a = aspect or width / height
    out = bytearray(width * height)
    for y in range(height):
        v = (y + 0.5) / height
        row = y * width
        for x in range(width):
            value = pattern((x + 0.5) / width, v, a)
            out[row + x] = max(0, min(255, round(value * 255)))
    return bytes(out)


def luma_size(canvas_w: int, canvas_h: int, longest: int = 320) -> tuple[int, int]:
    """Taille du motif, aux proportions de la toile (un cercle reste rond)."""
    if canvas_w >= canvas_h:
        return longest, max(2, round(longest * canvas_h / canvas_w))
    return max(2, round(longest * canvas_w / canvas_h)), longest
