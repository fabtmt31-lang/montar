# SPDX-License-Identifier: GPL-3.0-or-later
"""Jetons de la charte graphique « verts pastel, clair, épuré » (docs/maquettes)."""
from __future__ import annotations

from dataclasses import dataclass

FONT_UI = "Manrope"
FONT_MONO = "JetBrains Mono"

RADIUS_CLIP = 8
RADIUS_CONTROL = 10
RADIUS_CARD = 16
RADIUS_WINDOW = 24


@dataclass(frozen=True)
class Palette:
    dark: bool
    ink: str  # texte principal
    text_muted: str
    forest: str  # actions principales, accent
    on_forest: str  # texte sur fond Forêt
    sage: str
    mint: str  # clips vidéo
    water: str  # clips texte
    pistachio: str  # clips audio
    voiceover: str  # clips voix off
    mist: str  # sélection, survol, boutons tonals
    background: str  # fond des fenêtres
    sidebar: str
    surface: str  # cartes, champs
    field: str  # fond des champs de saisie
    border: str
    preview_bg: str  # fond autour de l'image dans l'aperçu
    shadow: str


LIGHT = Palette(
    dark=False,
    ink="#17261E",
    text_muted="#5E6E65",
    forest="#2F7A56",
    on_forest="#FFFFFF",
    sage="#9CCBB0",
    mint="#BFE3CF",
    water="#C9E7E3",
    pistachio="#D9EBB9",
    voiceover="#E6EBD3",
    mist="#DCEDE2",
    background="#EEF5F0",
    sidebar="#F7FAF8",
    surface="#FFFFFF",
    field="#F4F8F5",
    border="#D8E4DC",
    preview_bg="#E4EEE8",
    shadow="#1A17261E",
)

DARK = Palette(
    dark=True,
    ink="#E5EFE9",
    text_muted="#9DB1A6",
    forest="#4FA67A",
    on_forest="#0E1A14",
    sage="#5E8F74",
    mint="#2F5A45",
    water="#2D5652",
    pistachio="#4A5C30",
    voiceover="#4A5040",
    mist="#23382D",
    background="#111B16",
    sidebar="#15211B",
    surface="#1A2720",
    field="#14201A",
    border="#2A3B32",
    preview_bg="#0C1410",
    shadow="#66000000",
)

# Couleurs d'accent proposées dans les préférences (maquette 06), thème clair.
from montar.core.settings import ACCENTS  # noqa: E402,F401 - une seule définition
