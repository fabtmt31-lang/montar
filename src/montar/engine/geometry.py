# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement d'un clip dans la toile (sans dépendance au moteur).

MLT commence par recadrer l'image source, puis l'ajuste à la toile en conservant ses
proportions (bandes transparentes). Le filtre « affine » redimensionne ensuite cette
image pleine toile : `affine_rect` calcule le rectangle qui donne le placement voulu.
"""
from __future__ import annotations

from dataclasses import dataclass

from montar.core.project import Transform

MAX_CROP = 0.45


@dataclass(frozen=True)
class Placement:
    """Rectangle occupé par le contenu visible, centre et taille en pixels de la toile."""

    cx: float
    cy: float
    width: float
    height: float
    rotation: float

    @property
    def left(self) -> float:
        return self.cx - self.width / 2

    @property
    def top(self) -> float:
        return self.cy - self.height / 2


def _crops(t: Transform) -> tuple[float, float, float, float]:
    left, right = (max(0.0, min(MAX_CROP, v)) for v in (t.crop_left, t.crop_right))
    top, bottom = (max(0.0, min(MAX_CROP, v)) for v in (t.crop_top, t.crop_bottom))
    return left, right, top, bottom


def _fit_factors(cw: float, ch: float, mw: float, mh: float, fit: str) -> tuple[float, float]:
    if fit == "stretch":
        return cw / mw, ch / mh
    f = max(cw / mw, ch / mh) if fit == "fill" else min(cw / mw, ch / mh)
    return f, f


def placement(cw: int, ch: int, mw: int, mh: int, t: Transform) -> Placement:
    mw, mh = (mw or cw), (mh or ch)
    left, right, top, bottom = _crops(t)
    fx, fy = _fit_factors(cw, ch, mw, mh, t.fit)
    fx, fy = fx * t.scale, fy * t.scale
    width = mw * (1 - left - right) * fx
    height = mh * (1 - top - bottom) * fy
    cx = cw / 2 + t.x * cw + (left - right) / 2 * mw * fx
    cy = ch / 2 + t.y * ch + (top - bottom) / 2 * mh * fy
    return Placement(cx, cy, width, height, t.rotation)


def affine_rect(cw: int, ch: int, mw: int, mh: int,
                t: Transform) -> tuple[tuple[float, float, float, float], bool]:
    """Rectangle (x, y, largeur, hauteur) du filtre affine et besoin de déformation."""
    mw, mh = (mw or cw), (mh or ch)
    left, right, top, bottom = _crops(t)
    visible_w, visible_h = mw * (1 - left - right), mh * (1 - top - bottom)
    normalised = min(cw / visible_w, ch / visible_h)  # ajustement fait par MLT
    p = placement(cw, ch, mw, mh, t)
    kx = p.width / (visible_w * normalised)
    ky = p.height / (visible_h * normalised)
    w, h = cw * kx, ch * ky
    return (p.cx - w / 2, p.cy - h / 2, w, h), abs(kx - ky) > 1e-6


def crop_pixels(mw: int, mh: int, t: Transform) -> tuple[int, int, int, int]:
    left, right, top, bottom = _crops(t)
    return round(left * mw), round(right * mw), round(top * mh), round(bottom * mh)
