# SPDX-License-Identifier: GPL-3.0-or-later
"""Raccourcis clavier personnalisables (F-UX-07) : actions, touches par défaut, conflits.

Les touches sont écrites au format portable de QKeySequence (« Ctrl+Shift+Z »). Une touche
personnalisée remplace celle par défaut et ses variantes ; une chaîne vide désactive
l'action."""
from __future__ import annotations

from montar.i18n import N_

# (identifiant, libellé), dans l'ordre des préférences
ACTIONS: tuple[tuple[str, str], ...] = (
    ("play", N_("Lecture / pause")),
    ("start", N_("Aller au début")),
    ("end", N_("Aller à la fin")),
    ("previous_frame", N_("Image précédente")),
    ("next_frame", N_("Image suivante")),
    ("shuttle_back", N_("Lecture arrière (J)")),
    ("pause", N_("Pause (K)")),
    ("shuttle_forward", N_("Lecture avant accélérée (L)")),
    ("fullscreen", N_("Plein écran")),
    ("split", N_("Couper à la tête de lecture")),
    ("delete", N_("Supprimer")),
    ("ripple_delete", N_("Supprimer et refermer le vide")),
    ("duplicate", N_("Dupliquer")),
    ("undo", N_("Annuler")),
    ("redo", N_("Rétablir")),
    ("save", N_("Enregistrer")),
    ("export", N_("Exporter")),
    ("zoom_in", N_("Zoom avant sur la timeline")),
    ("zoom_out", N_("Zoom arrière sur la timeline")),
    ("zoom_fit", N_("Toute la timeline")),
    ("mark_in", N_("Début de la sélection (I)")),
    ("mark_out", N_("Fin de la sélection (O)")),
    ("clear_range", N_("Effacer la sélection")),
    ("marker", N_("Marqueur")),
    ("previous_marker", N_("Marqueur précédent")),
    ("next_marker", N_("Marqueur suivant")),
)
# touches par défaut (appel à dict : ces noms de touches ne sont pas à traduire)
DEFAULT_KEYS: dict[str, str] = dict(
    play="Space",
    start="Home",
    end="End",
    previous_frame="Left",
    next_frame="Right",
    shuttle_back="J",
    pause="K",
    shuttle_forward="L",
    fullscreen="F",
    split="S",
    delete="Del",
    ripple_delete="Shift+Del",
    duplicate="Ctrl+D",
    undo="Ctrl+Z",
    redo="Ctrl+Shift+Z",
    save="Ctrl+S",
    export="Ctrl+E",
    zoom_in="Ctrl++",
    zoom_out="Ctrl+-",
    zoom_fit="Ctrl+0",
    mark_in="I",
    mark_out="O",
    clear_range="Esc",
    marker="M",
    previous_marker="Ctrl+Left",
    next_marker="Ctrl+Right",
)
# variantes gardées tant que l'action n'est pas personnalisée
ALIASES: dict[str, tuple[str, ...]] = dict(
    fullscreen=("F11",),
    delete=("Backspace",),
    redo=("Ctrl+Y",),
    zoom_in=("Ctrl+=",),
)
IDS = tuple(a[0] for a in ACTIONS)


def default(action: str) -> str:
    return DEFAULT_KEYS[action]


def keys_for(overrides: dict[str, str], action: str) -> list[str]:
    """Touches actives d'une action."""
    if action in overrides:
        return [overrides[action]] if overrides[action] else []
    return [DEFAULT_KEYS[action], *ALIASES.get(action, ())]


def current(overrides: dict[str, str], action: str) -> str:
    """Touche principale affichée dans les préférences."""
    keys = keys_for(overrides, action)
    return keys[0] if keys else ""


def conflicts(overrides: dict[str, str]) -> dict[str, list[str]]:
    """Touches attribuées à plusieurs actions : touche → actions."""
    used: dict[str, list[str]] = {}
    for action in IDS:
        for key in keys_for(overrides, action):
            used.setdefault(key.lower(), []).append(action)
    return {k: v for k, v in used.items() if len(v) > 1}


def cleaned(raw: object) -> dict[str, str]:
    """Personnalisations valides lues depuis les préférences."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items()
            if k in DEFAULT_KEYS and isinstance(v, str) and v != default(k)}
