# SPDX-License-Identifier: GPL-3.0-or-later
"""Libellés et icônes des transitions et des filtres affichés dans l'interface."""
from __future__ import annotations

TRANSITIONS: dict[str, tuple[str, str]] = {  # identifiant → (libellé, icône)
    "dissolve": ("Fondu enchaîné", "blend"),
    "dip_black": ("Fondu au noir", "moon"),
    "dip_white": ("Fondu au blanc", "sun"),
    "slide_left": ("Glissement ←", "arrow-left-right"),
    "slide_right": ("Glissement →", "arrow-left-right"),
    "zoom": ("Zoom", "zoom-in"),
    # transitions à motif (engine/lumas.py) : la vignette montre le motif, pas d'icône
    "wipe_right": ("Balayage →", ""),
    "wipe_left": ("Balayage ←", ""),
    "wipe_down": ("Balayage ↓", ""),
    "wipe_up": ("Balayage ↑", ""),
    "wipe_diagonal": ("Balayage ↘", ""),
    "soft_wipe_right": ("Balayage doux →", ""),
    "soft_wipe_left": ("Balayage doux ←", ""),
    "soft_wipe_down": ("Balayage doux ↓", ""),
    "soft_wipe_up": ("Balayage doux ↑", ""),
    "blinds": ("Stores", ""),
    "barn_vertical": ("Ouverture verticale", ""),
    "barn_horizontal": ("Ouverture horizontale", ""),
    "close": ("Fermeture", ""),
    "clock": ("Balayage circulaire", ""),
    "circle": ("Cercle", ""),
    "diamond": ("Losange", ""),
    "thirds": ("Tiers", ""),
}

# Couleurs d'aperçu des filtres prédéfinis (dégradé de la tuile)
PRESET_SWATCHES: dict[str, tuple[str, str]] = {
    "": ("#BFE3CF", "#9CCBB0"),
    "bw": ("#E8E8E8", "#4A4A4A"),
    "noir": ("#9A9A9A", "#111111"),
    "sepia": ("#E8D3A9", "#8A6A3C"),
    "vintage": ("#E6D8B8", "#7C8A6A"),
    "warm": ("#FFD9A8", "#E07B39"),
    "cold": ("#CDE7F7", "#3C7BB0"),
    "vivid": ("#FF5FA2", "#2FB36B"),
    "fade": ("#E6EFE9", "#B9C9BF"),
}
