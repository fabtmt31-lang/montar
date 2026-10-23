# SPDX-License-Identifier: GPL-3.0-or-later
"""Images clés (F-EDT-10) : position, échelle, rotation et opacité d'un clip animées entre
des valeurs posées à certains instants. Positions en images depuis le début du clip ;
interpolation linéaire, valeur tenue avant la première et après la dernière clé."""
from __future__ import annotations

import copy
from bisect import bisect_right

from montar.core.project import Clip, Transform

ANIMATABLE = ("x", "y", "scale", "rotation", "opacity")


def value_at(points: list[list[float]], frame: float, default: float) -> float:
    if not points:
        return default
    frames = [p[0] for p in points]
    i = bisect_right(frames, frame)
    if i == 0:
        return float(points[0][1])
    if i == len(points):
        return float(points[-1][1])
    (f0, v0), (f1, v1) = points[i - 1], points[i]
    return float(v0 + (v1 - v0) * (frame - f0) / max(1e-9, f1 - f0))


def transform_at(clip: Clip, frame: float) -> Transform:
    """Transformation du clip à `frame` (relatif au clip)."""
    if not clip.keyframes:
        return clip.transform
    t = copy.copy(clip.transform)
    for prop in ANIMATABLE:
        points = clip.keyframes.get(prop)
        if points:
            setattr(t, prop, value_at(points, frame, getattr(t, prop)))
    return t


def key_frames(clip: Clip) -> list[int]:
    return sorted({int(p[0]) for points in clip.keyframes.values() for p in points})


def set_key(clip: Clip, frame: int, prop: str, value: float) -> None:
    points = clip.keyframes.setdefault(prop, [])
    for p in points:
        if p[0] == frame:
            p[1] = value
            break
    else:
        points.append([frame, value])
        points.sort(key=lambda p: p[0])


def add_keyframe(clip: Clip, frame: int) -> None:
    """Clé à `frame` pour toutes les propriétés, avec leurs valeurs actuelles à cet instant."""
    current = transform_at(clip, frame)
    for prop in ANIMATABLE:
        set_key(clip, frame, prop, getattr(current, prop))


def remove_keyframe(clip: Clip, frame: int) -> None:
    """Retire les clés de `frame` ; sans clé restante, la valeur de cet instant devient fixe."""
    current = transform_at(clip, frame)
    for prop in list(clip.keyframes):
        clip.keyframes[prop] = [p for p in clip.keyframes[prop] if p[0] != frame]
        if not clip.keyframes[prop]:
            del clip.keyframes[prop]
    if not clip.keyframes:
        clip.transform = current


def set_property(clip: Clip, prop: str, value: float, frame: int) -> None:
    """Réglage d'une propriété : clé à `frame` si le clip est animé, sinon valeur fixe."""
    if clip.keyframes and prop in ANIMATABLE:
        set_key(clip, frame, prop, value)
    else:
        setattr(clip.transform, prop, value)


def shift(clip: Clip, delta: int) -> None:
    """Décale les clés (coupe ou rognage du début du clip)."""
    for points in clip.keyframes.values():
        for p in points:
            p[0] = p[0] + delta
