# SPDX-License-Identifier: GPL-3.0-or-later
"""Réglages de couleur, filtres prédéfinis et effets, traduits en filtres FFmpeg (via MLT).

Chaque fonction renvoie une liste de (service MLT, propriétés)."""
from __future__ import annotations

from montar.core.project import ColorAdjust, Effects

Filters = list[tuple[str, dict[str, object]]]

# Filtres prédéfinis proposés dans le panneau « Filtres » : identifiant → libellé.
PRESETS = {
    "bw": "Noir et blanc",
    "noir": "Noir intense",
    "sepia": "Sépia",
    "vintage": "Vintage",
    "warm": "Chaud",
    "cold": "Froid",
    "vivid": "Éclatant",
    "fade": "Délavé",
}

_SEPIA = ((0.393, 0.769, 0.189), (0.349, 0.686, 0.168), (0.272, 0.534, 0.131))


def _eq(brightness: float = 0.0, contrast: float = 1.0, saturation: float = 1.0) -> Filters:
    return [("avfilter.eq", {"av.brightness": round(brightness, 4),
                             "av.contrast": round(contrast, 4),
                             "av.saturation": round(saturation, 4)})]


def _temperature(kelvin: float) -> Filters:
    return [("avfilter.colortemperature", {"av.temperature": round(kelvin)})]


def _sepia(amount: float) -> Filters:
    names = "rgb"
    props: dict[str, object] = {}
    for i, row in enumerate(_SEPIA):
        for j, value in enumerate(row):
            identity = 1.0 if i == j else 0.0
            props[f"av.{names[i]}{names[j]}"] = round(identity + (value - identity) * amount, 4)
    return [("avfilter.colorchannelmixer", props)]


def color_filters(c: ColorAdjust) -> Filters:
    if c.is_identity():
        return []
    filters: Filters = []
    if c.brightness or c.contrast or c.saturation:
        filters += _eq(c.brightness * 0.3, 1 + c.contrast * 0.6, 1 + c.saturation)
    if c.temperature:
        # > 0 : plus chaud (température de couleur plus basse)
        filters += _temperature(6500 - c.temperature * 3000 if c.temperature > 0
                                else 6500 - c.temperature * 6000)
    if c.exposure:
        filters.append(("avfilter.exposure", {"av.exposure": round(c.exposure * 1.5, 4)}))
    return filters


def preset_filters(preset: str, amount: float) -> Filters:
    a = max(0.0, min(1.0, amount))
    if not preset or a == 0:
        return []
    if preset == "bw":
        return _eq(saturation=1 - a)
    if preset == "noir":
        return _eq(contrast=1 + 0.5 * a, saturation=1 - a, brightness=-0.05 * a)
    if preset == "sepia":
        return _sepia(a)
    if preset == "vintage":
        return _sepia(0.5 * a) + _eq(contrast=1 - 0.15 * a, brightness=0.03 * a) + [
            ("avfilter.vignette", {"av.angle": round(0.2 + 0.4 * a, 4)})]
    if preset == "warm":
        return _temperature(6500 - 2500 * a)
    if preset == "cold":
        return _temperature(6500 + 5000 * a)
    if preset == "vivid":
        return _eq(contrast=1 + 0.15 * a, saturation=1 + 0.7 * a)
    if preset == "fade":
        return _eq(contrast=1 - 0.35 * a, brightness=0.08 * a, saturation=1 - 0.3 * a)
    return []


def effect_filters(e: Effects) -> Filters:
    if e.is_identity():
        return []
    filters: Filters = []
    if e.blur > 0:
        filters.append(("avfilter.gblur", {"av.sigma": round(e.blur * 20, 3)}))
    if e.sharpen > 0:
        filters.append(("avfilter.unsharp", {"av.la": round(e.sharpen * 2.5, 3)}))
    if e.vignette > 0:
        filters.append(("avfilter.vignette", {"av.angle": round(0.15 + e.vignette * 0.75, 4)}))
    return filters
