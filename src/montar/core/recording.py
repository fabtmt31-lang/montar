# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistrement d'écran avec webcam, dans la timeline : deux clips liés (l'écran, la
webcam par-dessus) dont la disposition (coin, taille, rond, écran partagé) devient la
transformation de chaque clip. Sans dépendance au moteur ni à l'interface."""
from __future__ import annotations

from dataclasses import replace

from montar.core.project import Transform

CORNERS = ("bottom_right", "bottom_left", "top_right", "top_left")
MARGIN = 24 / 1920  # écart entre la webcam et le bord, en fraction de la largeur filmée
FADE_SECONDS = 0.3  # apparition / disparition de la webcam, passage en plein écran


def _fit(cw: int, ch: int, w: int, h: int) -> tuple[float, float, float, float]:
    """Rectangle (x, y, largeur, hauteur) d'une image `w` × `h` ajustée dans la toile."""
    k = min(cw / w, ch / h)
    return (cw - w * k) / 2, (ch - h * k) / 2, w * k, h * k


def _place(cw: int, ch: int, mw: int, mh: int, t: Transform,
           cx: float, cy: float, width: float) -> Transform:
    """`t` (recadrage compris) agrandi pour que sa partie visible mesure `width` pixels de
    large, centrée en (`cx`, `cy`)."""
    visible = mw * (1 - t.crop_left - t.crop_right)
    fit = min(cw / mw, ch / mh)
    scale = width / (visible * fit)
    # centre de la partie visible quand x = y = 0 (le recadrage le décale)
    x0 = cw / 2 + (t.crop_left - t.crop_right) / 2 * mw * fit * scale
    y0 = ch / 2 + (t.crop_top - t.crop_bottom) / 2 * mh * fit * scale
    return replace(t, scale=scale, x=(cx - x0) / cw, y=(cy - y0) / ch)


def _crop_to(mw: int, mh: int, aspect: float) -> dict[str, float]:
    """Recadrage centré de l'image `mw` × `mh` aux proportions `aspect` (largeur / hauteur)."""
    if mw / mh > aspect:
        side = (1 - aspect * mh / mw) / 2
        return {"crop_left": side, "crop_right": side}
    side = (1 - mw / mh / aspect) / 2
    return {"crop_top": side, "crop_bottom": side}


def layout_transforms(canvas: tuple[int, int], screen: tuple[int, int],
                      camera: tuple[int, int], layout: dict) -> tuple[Transform, Transform]:
    """Transformations (écran, webcam) d'une disposition d'enregistrement : `layout` porte
    `position` (coin ou split_left / split_right), `size` (part de la largeur filmée) et
    `shape` (rect ou round)."""
    cw, ch = canvas
    sw, sh = screen if screen[0] and screen[1] else canvas
    mw, mh = camera if camera[0] and camera[1] else (16, 9)
    position = layout.get("position", "bottom_right")
    share = max(0.1, min(0.6, float(layout.get("size", 0.25))))
    x, y, w, h = _fit(cw, ch, sw, sh)  # écran filmé, dans la toile
    if position.startswith("split"):
        cam_right = position == "split_right"
        screen_w = w * (1 - share)
        screen_t = _place(cw, ch, sw, sh, Transform(), (x + screen_w / 2) if cam_right
                          else (x + w - screen_w / 2), y + h / 2, screen_w)
        strip = w * share
        cam_t = Transform(**_crop_to(mw, mh, strip / h))
        cam_t = _place(cw, ch, mw, mh, cam_t, (x + w - strip / 2) if cam_right
                       else (x + strip / 2), y + h / 2, strip)
        return screen_t, cam_t
    round_ = layout.get("shape") == "round"
    cam_t = Transform(**_crop_to(mw, mh, 1.0), shape="round") if round_ else Transform()
    width = w * share
    height = width if round_ else width * mh / mw
    margin = MARGIN * w
    left = position.endswith("left")
    top = position.startswith("top")
    cx = x + margin + width / 2 if left else x + w - margin - width / 2
    cy = y + margin + height / 2 if top else y + h - margin - height / 2
    return Transform(), _place(cw, ch, mw, mh, cam_t, cx, cy, width)


def full_transform(canvas: tuple[int, int], camera: tuple[int, int]) -> Transform:
    """Webcam en plein écran : elle remplit toute la toile, sans forme ni recadrage."""
    cw, ch = canvas
    mw, mh = camera if camera[0] and camera[1] else canvas
    return Transform(scale=max(cw / mw, ch / mh) / min(cw / mw, ch / mh))


def small_transform(canvas: tuple[int, int], camera: tuple[int, int],
                    corner: Transform) -> Transform:
    """Point de départ du passage en plein écran : l'image entière de la webcam (sans
    recadrage), à la place et à la largeur de la webcam dans son coin."""
    from montar.engine.geometry import placement

    cw, ch = canvas
    mw, mh = camera if camera[0] and camera[1] else canvas
    p = placement(cw, ch, mw, mh, corner)
    return _place(cw, ch, mw, mh, Transform(), p.cx, p.cy, p.width)


def zoom_keys(start: Transform, end: Transform, duration: int, frames: int,
              enter: bool = True, leave: bool = True) -> dict[str, list[list[float]]]:
    """Images clés d'un clip montré comme `end`, qui arrive depuis `start` en `frames`
    images (`enter`) et y repart à la fin (`leave`) ; seuls x, y et l'échelle bougent."""
    last = max(0, duration - 1)
    frames = max(1, min(frames, last // 2))
    keys: dict[str, list[list[float]]] = {}
    for name in ("x", "y", "scale"):
        a, b = getattr(start, name), getattr(end, name)
        if abs(a - b) < 1e-9 or not (enter or leave) or last < 2:
            continue
        points = [[0, a], [frames, b]] if enter else [[0, b]]
        points += [[last - frames, b], [last, a]] if leave else [[last, b]]
        keys[name] = points
    return keys
