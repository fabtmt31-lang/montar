# SPDX-License-Identifier: GPL-3.0-or-later
"""Étalonnage avancé traduit en filtres FFmpeg : roues lift / gamma / gain (formule de type
ASC CDL, par canal), courbes, teinte, vibrance et LUT 3D (.cube)."""
from __future__ import annotations

import math

from montar.core.project import Grade

CURVE_KEYS = {"master": "av.m", "red": "av.r", "green": "av.g", "blue": "av.b"}
LIFT_RANGE = 0.25  # décalage maximal des noirs
POWER_RANGE = 1.0  # gamma et gain : facteur 2^±1 au plus


def wheel_rgb(x: float, y: float) -> tuple[float, float, float]:
    """Décalage de couleur (moyenne nulle) d'un point du disque : l'angle donne la teinte
    (0° = rouge, 120° = vert, 240° = bleu), la distance au centre l'intensité."""
    r = min(1.0, math.hypot(x, y))
    if r == 0:
        return 0.0, 0.0, 0.0
    angle = math.atan2(y, x)
    return tuple(r * math.cos(angle - k * 2 * math.pi / 3) * 2 / 3 for k in range(3))


def channel_values(grade: Grade) -> list[tuple[float, float, float]]:
    """(lift, gamma, gain) de chaque canal R, V, B."""
    lift = wheel_rgb(*grade.lift)
    gamma = wheel_rgb(*grade.gamma)
    gain = wheel_rgb(*grade.gain)
    values = []
    for c in range(3):
        values.append((LIFT_RANGE * (grade.lift_level + lift[c]),
                       2 ** (POWER_RANGE * (grade.gamma_level + gamma[c])),
                       2 ** (POWER_RANGE * (grade.gain_level + gain[c]))))
    return values


def _lgg_expr(lift: float, gamma: float, gain: float) -> str:
    x = "val/maxval"
    return (f"clip(pow(clip({x}*{gain:.4f}+{lift:.4f}*(1-{x}),0,1),{1 / gamma:.4f})"
            f"*maxval,0,maxval)")


def curve_string(points: list[list[float]]) -> str:
    pts = sorted((max(0.0, min(1.0, float(a))), max(0.0, min(1.0, float(b))))
                 for a, b in points)
    return " ".join(f"{a:.4f}/{b:.4f}" for a, b in pts)


def is_flat(points: list[list[float]]) -> bool:
    return all(abs(a - b) < 1e-4 for a, b in points)


def grade_filters(grade: Grade, lut_path: str = "") -> list[tuple[str, dict]]:
    if grade.is_identity():
        return []
    result: list[tuple[str, dict]] = []
    values = channel_values(grade)
    if any(v != (0.0, 1.0, 1.0) for v in values):
        result.append(("avfilter.lutrgb", {f"av.{ch}": _lgg_expr(*v)
                                           for ch, v in zip("rgb", values, strict=True)}))
    curves = {CURVE_KEYS[k]: curve_string(p) for k, p in grade.curves.items()
              if k in CURVE_KEYS and len(p) >= 2 and not is_flat(p)}
    if curves:
        result.append(("avfilter.curves", curves))
    if grade.hue:
        result.append(("avfilter.hue", {"av.h": round(grade.hue, 2)}))
    if grade.vibrance:
        result.append(("avfilter.vibrance", {"av.intensity": round(grade.vibrance, 3)}))
    if lut_path:
        result.append(("avfilter.lut3d", {"av.file": lut_path, "av.interp": "tetrahedral"}))
    return result
