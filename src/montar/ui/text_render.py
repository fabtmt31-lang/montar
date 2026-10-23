# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendu des clips de texte en images PNG transparentes (taille de la toile), avec Qt.

Le moteur affiche ensuite ces images comme des images fixes : l'aperçu et l'export
utilisent ainsi exactement les polices embarquées."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from montar.core.project import Clip, TextStyle
from montar.i18n import _

REFERENCE_HEIGHT = 1080  # les tailles des styles sont données pour une toile de 1080 px

WEIGHTS = {400: QFont.Weight.Normal, 500: QFont.Weight.Medium, 600: QFont.Weight.DemiBold,
           700: QFont.Weight.Bold, 800: QFont.Weight.ExtraBold}

# Styles proposés dans le panneau Texte (maquette 03) : identifiant → (libellé, catégorie, style)
PRESETS: dict[str, tuple[str, str, TextStyle]] = {
    "title": ("Titre", "title", TextStyle(
        "Titre", "title", "Fraunces", 120, 700, color="#FFFFFF", shadow=True)),
    "bold": ("GRAS", "title", TextStyle(
        "Gras", "bold", "Manrope", 96, 800, uppercase=True, letter_spacing=10,
        color="#FFFFFF", shadow=True)),
    "script": ("Manuscrit", "title", TextStyle(
        "Manuscrit", "script", "Caveat", 128, 700, color="#FFFFFF", shadow=True)),
    "neon": ("Néon doux", "title", TextStyle(
        "Néon doux", "neon", "Manrope", 92, 600, color="#D9EBB9", shadow=True,
        shadow_color="#CC9CCBB0")),
    "lower_third": ("Nom · Rôle", "band", TextStyle(
        "Prénom Nom · Rôle", "lower_third", "Manrope", 44, 700, align="left",
        color="#17261E", background="#FFFFFF", x=0.25, y=0.82)),
    "subtitle": ("Sous-titre", "band", TextStyle(
        "Sous-titre", "subtitle", "Manrope", 44, 600, color="#FFFFFF",
        background="#D917261E", y=0.88)),
    "ticker": ("Info défilante", "band", TextStyle(
        "Information", "ticker", "Manrope", 40, 700, align="left", color="#FFFFFF",
        background="#2F7A56", x=0.3, y=0.92)),
    "subscribe": ("S'abonner", "band", TextStyle(
        "S'abonner", "subscribe", "Manrope", 44, 700, color="#17261E",
        background="#FFFFFF", pill=True, x=0.84, y=0.86)),
}

FAMILIES = ("Manrope", "Fraunces", "Caveat", "JetBrains Mono")


def preset_style(preset: str) -> TextStyle:
    style = copy.deepcopy(PRESETS.get(preset, PRESETS["title"])[2])
    style.content = _(style.content)  # texte d'exemple dans la langue de l'interface
    return style


def _font(style: TextStyle, scale: float) -> QFont:
    font = QFont(style.family)
    font.setPixelSize(max(4, round(style.size * scale)))
    font.setWeight(WEIGHTS.get(style.weight, QFont.Weight.Bold))
    font.setItalic(style.italic)
    font.setUnderline(style.underline)
    if style.letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, style.letter_spacing * scale)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def _lines(style: TextStyle) -> list[str]:
    text = style.content.upper() if style.uppercase else style.content
    return text.split("\n") or [""]


def _layout(style: TextStyle, width: int, height: int):
    """Police, lignes, rectangle du bloc de texte et du bandeau (pixels de la toile)."""
    scale = height / REFERENCE_HEIGHT
    font = _font(style, scale)
    fm = QFontMetricsF(font)
    lines = _lines(style)
    line_h = fm.height()
    widths = [fm.horizontalAdvance(line) for line in lines]
    block_w, block_h = max(widths, default=0.0), line_h * len(lines)
    cx, cy = style.x * width, style.y * height
    block = QRectF(cx - block_w / 2, cy - block_h / 2, block_w, block_h)
    pad_x, pad_y = (0.55 if style.pill else 0.4) * line_h, 0.18 * line_h
    box = block.adjusted(-pad_x, -pad_y, pad_x, pad_y) if style.background else block
    return font, fm, lines, widths, block, box


def text_bounds(style: TextStyle, width: int, height: int) -> QRectF:
    """Rectangle occupé par le texte (et son bandeau) dans la toile."""
    return _layout(style, width, height)[5]


def render(style: TextStyle, width: int, height: int, visible: int | None = None) -> QImage:
    """Image du texte ; `visible` : nombre de caractères déjà tapés (machine à écrire), les
    autres restent à leur place mais invisibles."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    font, fm, lines, widths, block, box = _layout(style, width, height)
    scale = height / REFERENCE_HEIGHT
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if style.background:
        radius = box.height() / 2 if style.pill else 12 * scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.background))
        painter.drawRoundedRect(box, radius, radius)
    path = QPainterPath()
    left = len("".join(lines)) if visible is None else visible
    for i, (line, w) in enumerate(zip(lines, widths, strict=True)):
        if style.align == "left":
            x = block.left()
        elif style.align == "right":
            x = block.right() - w
        else:
            x = block.left() + (block.width() - w) / 2
        shown, left = line[:max(0, left)], max(0, left - len(line))
        path.addText(QPointF(x, block.top() + i * fm.height() + fm.ascent()), font, shown)
    if style.shadow:
        offset = max(1.0, style.size * scale * 0.035)
        shadow = QColor(style.shadow_color)
        for spread in (2.2, 1.4, 0.7):  # ombre douce : plusieurs passes transparentes
            color = QColor(shadow)
            color.setAlphaF(shadow.alphaF() * 0.35)
            painter.setPen(QPen(color, offset * spread, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QBrush(color))
            painter.drawPath(path.translated(offset * 0.6, offset))
    if style.outline_width > 0:
        painter.setPen(QPen(QColor(style.outline_color), style.outline_width * scale * 2,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(style.color))
    painter.drawPath(path)
    painter.end()
    return image


def image_path(cache: Path, clip: Clip, width: int, height: int) -> str:
    """Image PNG du texte d'un clip, rendue une seule fois par style et taille de toile."""
    assert clip.text is not None
    key = hashlib.sha1(json.dumps([asdict(clip.text), width, height],
                                  sort_keys=True).encode()).hexdigest()
    out = cache / "texts" / f"{key}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.png")
        render(clip.text, width, height).save(str(tmp), "PNG")
        tmp.replace(out)
    return str(out)


TYPING_CPS = 18  # caractères par seconde de la machine à écrire
TYPING_SHARE = 0.7  # au plus 70 % de la durée du clip pour taper le texte


def typing_steps(chars: int, duration: int, fps: int) -> list[tuple[int, int]]:
    """(caractères visibles, images) de chaque étape ; la dernière tient jusqu'à la fin."""
    if chars <= 0 or duration <= 1:
        return [(chars, max(1, duration))]
    per_char = max(1, round(fps / TYPING_CPS))
    budget = max(1, int(duration * TYPING_SHARE))
    step = max(1, -(-chars * per_char // budget))  # caractères ajoutés par étape
    steps, shown, used = [], 0, 0
    while shown < chars:
        shown = min(chars, shown + step)
        frames = per_char if shown < chars else max(1, duration - used)
        steps.append((shown, frames))
        used += frames
    return steps


def typing_sequence(cache: Path, clip: Clip, width: int, height: int,
                    fps: int) -> list[tuple[str, int]]:
    """Images (PNG, frames) de l'animation « machine à écrire » d'un clip de texte."""
    assert clip.text is not None
    chars = len("".join(_lines(clip.text)))
    key = hashlib.sha1(json.dumps([asdict(clip.text), width, height],
                                  sort_keys=True).encode()).hexdigest()
    folder = cache / "texts" / key
    result = []
    for shown, frames in typing_steps(chars, clip.duration, fps):
        out = folder / f"{shown:05d}.png"
        if not out.exists():
            folder.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp.png")
            render(clip.text, width, height, shown).save(str(tmp), "PNG")
            tmp.replace(out)
        result.append((str(out), frames))
    return result
