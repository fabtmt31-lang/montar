# SPDX-License-Identifier: GPL-3.0-or-later
"""Icônes Lucide (ISC) recolorées à la volée, trait 1,8 px comme dans la charte."""
from __future__ import annotations

from functools import cache, lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from montar.platform.paths import assets_dir

_SIZES = (16, 20, 24, 32, 48)


@cache
def _svg_source(name: str) -> str:
    return (assets_dir() / "icons" / f"{name}.svg").read_text(encoding="utf-8")


def pixmap(name: str, color: str, size: int, dpr: float = 2.0) -> QPixmap:
    svg = _svg_source(name).replace("currentColor", color)
    svg = svg.replace('stroke-width="2"', 'stroke-width="1.8"')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


@lru_cache(maxsize=512)
def icon(name: str, color: str, disabled_color: str | None = None) -> QIcon:
    result = QIcon()
    for s in _SIZES:
        result.addPixmap(pixmap(name, color, s), QIcon.Mode.Normal)
        if disabled_color:
            result.addPixmap(pixmap(name, disabled_color, s), QIcon.Mode.Disabled)
    return result
