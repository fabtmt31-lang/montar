# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendu des clips de texte en images PNG transparentes (taille de la toile), avec Qt.

Le moteur affiche ensuite ces images comme des images fixes : l'aperçu et l'export
utilisent ainsi exactement les polices embarquées."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass
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
    # --- titres ---
    "title_sub": ("Titre et sous-titre", "title", TextStyle(
        "Grand titre\nSous-titre", "title_sub", "Fraunces", 120, 700, color="#FFFFFF",
        shadow=True, sub_scale=0.42, sub_color="#D9EBB9", animation_in="slide",
        animation_out="fade")),
    "creator": ("Créateur", "title", TextStyle(
        "Créateur", "creator", "Manrope", 112, 800, uppercase=True, color="#FFFFFF",
        outline_color="#17261E", outline_width=6, shadow=True, animation_in="pop")),
    "retro": ("Rétro", "title", TextStyle(
        "Rétro", "retro", "Fraunces", 140, 800, uppercase=True, color="#F7C948",
        outline_color="#E4572E", outline_width=5, shadow=True, shadow_color="#CC2B1B5A",
        animation_in="zoom")),
    "groovy": ("Groovy", "title", TextStyle(
        "Groovy", "groovy", "Caveat", 170, 700, color="#FF7AB6", outline_color="#2B1B5A",
        outline_width=5, shadow=True, animation_in="pop")),
    "bubble": ("Bulle", "title", TextStyle(
        "Bulle", "bubble", "Manrope", 124, 800, color="#C8F560", outline_color="#17261E",
        outline_width=8, animation_in="pop", animation_out="pop")),
    "outline": ("Contour", "title", TextStyle(
        "Contour", "outline", "Manrope", 130, 800, uppercase=True, color="#00FFFFFF",
        outline_color="#FFFFFF", outline_width=3, letter_spacing=6, animation_in="fade")),
    "cinema": ("Cinéma", "title", TextStyle(
        "Cinéma", "cinema", "Fraunces", 88, 400, uppercase=True, letter_spacing=26,
        color="#FFFFFF", animation_in="fade", animation_out="fade",
        animation_in_duration=1.2, animation_out_duration=1.2)),
    "typing": ("Machine à écrire", "title", TextStyle(
        "Il était une fois…", "typing", "JetBrains Mono", 72, 500, color="#FFFFFF",
        shadow=True, animation_in="typewriter")),
    "rise": ("Titre montant", "title", TextStyle(
        "Titre montant", "rise", "Manrope", 104, 800, color="#FFFFFF", shadow=True,
        animation_in="slide", animation_out="slide_top", animation_in_duration=0.8)),
    # --- bandeaux et tiers inférieurs ---
    "lower_third_2": ("Tiers inférieur 2 niveaux", "band", TextStyle(
        "Prénom Nom\nFonction", "lower_third_2", "Manrope", 52, 800, align="left",
        color="#17261E", background="#FFFFFF", x=0.24, y=0.82, sub_scale=0.62,
        sub_color="#2F7A56", animation_in="slide_left", animation_out="slide_left")),
    "lower_third_min": ("Tiers inférieur minimaliste", "band", TextStyle(
        "Prénom Nom\nFonction", "lower_third_min", "Manrope", 50, 700, align="left",
        color="#FFFFFF", shadow=True, x=0.2, y=0.82, sub_scale=0.6, sub_color="#D9EBB9",
        accent="#9CCBB0", animation_in="slide_left", animation_out="fade")),
    "lower_third_color": ("Tiers inférieur coloré", "band", TextStyle(
        "Prénom Nom · Rôle", "lower_third_color", "Manrope", 44, 700, align="left",
        color="#FFFFFF", background="#2F7A56", x=0.25, y=0.84, animation_in="slide_left",
        animation_out="slide_left")),
    "breaking": ("Info spéciale", "band", TextStyle(
        "Info spéciale", "breaking", "Manrope", 46, 800, uppercase=True, align="left",
        color="#FFFFFF", background="#C0392B", x=0.2, y=0.86, letter_spacing=3,
        animation_in="slide_left")),
    "text_box": ("Zone de texte", "band", TextStyle(
        "Votre texte ici", "text_box", "Manrope", 56, 700, color="#FFFFFF",
        background="#17261E", animation_in="fade", animation_out="fade")),
    "button": ("Bouton", "band", TextStyle(
        "En savoir plus", "button", "Manrope", 48, 700, color="#FFFFFF",
        background="#2F7A56", pill=True, y=0.8, animation_in="pop", animation_out="fade")),
    "hashtag": ("#hashtag", "band", TextStyle(
        "#montar", "hashtag", "Manrope", 56, 800, color="#17261E", background="#D9EBB9",
        pill=True, x=0.5, y=0.14, animation_in="slide_top")),
    # --- divers ---
    "quote": ("Citation", "other", TextStyle(
        "« Une belle citation »\n— Auteur", "quote", "Fraunces", 68, 400, italic=True,
        color="#FFFFFF", shadow=True, sub_scale=0.55, sub_color="#D9EBB9", line_height=1.25,
        animation_in="fade", animation_out="fade", animation_in_duration=1.0)),
    "meme": ("Texte mème", "other", TextStyle(
        "Texte en haut", "meme", "Manrope", 100, 800, uppercase=True, color="#FFFFFF",
        outline_color="#000000", outline_width=8, y=0.12)),
    "credits": ("Générique", "other", TextStyle(
        "Réalisation\nPrénom Nom", "credits", "Manrope", 44, 500, color="#D9EBB9",
        sub_scale=1.5, sub_color="#FFFFFF", line_height=1.3, animation_in="slide",
        animation_out="slide_top", animation_in_duration=1.0, animation_out_duration=1.0)),
    "intro": ("Intro", "other", TextStyle(
        "Intro", "intro", "Fraunces", 180, 800, color="#FFFFFF", shadow=True,
        animation_in="zoom", animation_out="fade", animation_in_duration=1.0)),
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


@dataclass
class _Line:
    text: str
    font: QFont
    metrics: QFontMetricsF
    width: float
    top: float = 0.0
    sub: bool = False  # ligne secondaire (taille et couleur propres)


def _layout(style: TextStyle, width: int, height: int):
    """Lignes placées, rectangle du bloc de texte et du bandeau (pixels de la toile). Les
    lignes après la première peuvent être plus petites (`sub_scale`) : nom puis fonction,
    titre puis sous-titre, citation puis auteur."""
    scale = height / REFERENCE_HEIGHT
    main = _font(style, scale)
    sub_font = _font(style, scale * max(0.2, min(2.0, style.sub_scale)))
    lines = []
    for i, text in enumerate(_lines(style)):
        font = main if i == 0 else sub_font
        fm = QFontMetricsF(font)
        lines.append(_Line(text, font, fm, fm.horizontalAdvance(text), sub=i > 0))
    y = 0.0
    for i, line in enumerate(lines):
        line.top = y
        if i + 1 < len(lines):  # hauteur de la ligne × interligne
            y += _line_step(style, line.metrics)
    block_w = max((line.width for line in lines), default=0.0)
    block_h = y + lines[-1].metrics.height()
    line_h = lines[0].metrics.height()
    accent = 0.0
    if style.accent:  # barre verticale à gauche du texte
        accent = 0.12 * line_h + 0.3 * line_h
    cx, cy = style.x * width, style.y * height
    block = QRectF(cx - (block_w + accent) / 2 + accent, cy - block_h / 2, block_w, block_h)
    for line in lines:
        line.top += block.top()
    pad_x, pad_y = (0.55 if style.pill else 0.4) * line_h, 0.18 * line_h
    outer = block.adjusted(-accent, 0, 0, 0)
    box = outer.adjusted(-pad_x, -pad_y, pad_x, pad_y) if style.background else outer
    return lines, block, box, line_h


def _line_step(style: TextStyle, fm: QFontMetricsF) -> float:
    """Distance entre deux lignes (interligne)."""
    return fm.height() * max(0.5, min(3.0, style.line_height))


def text_bounds(style: TextStyle, width: int, height: int) -> QRectF:
    """Rectangle occupé par le texte (et son bandeau) dans la toile."""
    return _layout(style, width, height)[2]


def render(style: TextStyle, width: int, height: int, visible: int | None = None) -> QImage:
    """Image du texte ; `visible` : nombre de caractères déjà tapés (machine à écrire), les
    autres restent à leur place mais invisibles."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    lines, block, box, line_h = _layout(style, width, height)
    scale = height / REFERENCE_HEIGHT
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if style.background:
        radius = box.height() / 2 if style.pill else 12 * scale
        painter.setPen(Qt.PenStyle.NoPen)
        fill = QColor(style.background)
        fill.setAlphaF(fill.alphaF() * max(0.0, min(1.0, style.background_opacity)))
        painter.setBrush(fill)
        painter.drawRoundedRect(box, radius, radius)
    if style.accent:
        bar = 0.12 * line_h
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.accent))
        painter.drawRoundedRect(QRectF(block.left() - 0.3 * line_h - bar, block.top(), bar,
                                       block.height()), bar / 2, bar / 2)
    main, sub = QPainterPath(), QPainterPath()
    left = len("".join(line.text for line in lines)) if visible is None else visible
    for line in lines:
        if style.align == "left":
            x = block.left()
        elif style.align == "right":
            x = block.right() - line.width
        else:
            x = block.left() + (block.width() - line.width) / 2
        shown, left = line.text[:max(0, left)], max(0, left - len(line.text))
        target = sub if line.sub and style.sub_color else main
        target.addText(QPointF(x, line.top + line.metrics.ascent()), line.font, shown)
    path = QPainterPath(main)
    path.addPath(sub)
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
    painter.drawPath(main)
    if not sub.isEmpty():
        painter.setBrush(QColor(style.sub_color))
        painter.drawPath(sub)
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


def typing_steps(chars: int, duration: int, fps: int,
                 cps: float = TYPING_CPS) -> list[tuple[int, int]]:
    """(caractères visibles, images) de chaque étape ; la dernière tient jusqu'à la fin.
    `cps` : vitesse de frappe en caractères par seconde."""
    if chars <= 0 or duration <= 1:
        return [(chars, max(1, duration))]
    per_char = max(1, round(fps / max(1.0, cps)))
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
    for shown, frames in typing_steps(chars, clip.duration, fps, clip.text.typing_speed):
        out = folder / f"{shown:05d}.png"
        if not out.exists():
            folder.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp.png")
            render(clip.text, width, height, shown).save(str(tmp), "PNG")
            tmp.replace(out)
        result.append((str(out), frames))
    return result
