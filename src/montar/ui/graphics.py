# SPDX-License-Identifier: GPL-3.0-or-later
"""Graphismes des modules (`montar.api.Graphic`) : rendu en image PNG transparente à la
taille du projet, et vignettes du panneau Graphiques."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

ELEMENT_SHARE = 0.45  # largeur d'un élément, en fraction du petit côté de la toile


def _source_size(path: Path) -> QSize:
    if path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(path))
        box = renderer.viewBoxF()
        return QSize(round(box.width()), round(box.height())) if not box.isEmpty() \
            else renderer.defaultSize()
    return QImage(str(path)).size()


def graphic_size(graphic, canvas: tuple[int, int]) -> tuple[int, int]:
    cw, ch = canvas
    if graphic.fill:
        return cw, ch
    source = _source_size(Path(graphic.path))
    width = max(2, round(min(cw, ch) * ELEMENT_SHARE))
    if source.isEmpty():
        return width, width
    return width, max(2, round(width * source.height() / source.width()))


def _paint(path: Path, painter: QPainter, rect: QRectF) -> None:
    if path.suffix.lower() == ".svg":
        QSvgRenderer(str(path)).render(painter, rect)
    else:
        painter.drawImage(rect, QImage(str(path)))


def render_graphic(graphic, size: tuple[int, int], target: Path) -> Path:
    """Image PNG transparente de l'élément, à `size` pixels."""
    image = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    _paint(Path(graphic.path), painter, QRectF(0, 0, size[0], size[1]))
    painter.end()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part.png")
    if not image.save(str(tmp), "PNG"):
        raise OSError(f"écriture impossible : {target}")
    tmp.replace(target)
    return target


def thumbnail(graphic, size: QSize, dpr: float = 2.0) -> QPixmap:
    """Vignette sur damier (la transparence reste visible)."""
    pm = QPixmap(round(size.width() * dpr), round(size.height() * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor("#3A4A41"))
    painter = QPainter(pm)
    cell = 8
    for y in range(0, size.height(), cell):
        for x in range(0, size.width(), cell):
            if (x // cell + y // cell) % 2:
                painter.fillRect(x, y, cell, cell, QColor("#4A5A51"))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    w, h = size.width(), size.height()
    if graphic.fill:
        rect = QRectF(0, 0, w, h)
    else:
        source = _source_size(Path(graphic.path))
        k = min((w - 14) / max(1, source.width()), (h - 14) / max(1, source.height()))
        sw, sh = source.width() * k, source.height() * k
        rect = QRectF((w - sw) / 2, (h - sh) / 2, sw, sh)
    _paint(Path(graphic.path), painter, rect)
    painter.end()
    return pm
