# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Graphismes » : les éléments du panneau Graphiques (fichiers SVG du
dossier svg/, dessinés pour montar et publiés sous la même licence)."""
from __future__ import annotations

from montar.api import Graphic

# (fichier sans extension, nom, rubrique, plein cadre)
ITEMS = (
    ("fleche", "Flèche", "annotations", False),
    ("entoure", "Entourer", "annotations", False),
    ("souligne", "Souligner", "annotations", False),
    ("eclats", "Éclats", "annotations", False),
    ("couronne", "Couronne", "annotations", False),
    ("etoile", "Étoile", "figures", False),
    ("coeur", "Cœur", "figures", False),
    ("bulle", "Bulle", "figures", False),
    ("eclair", "Éclair", "figures", False),
    ("explosion", "Explosion", "figures", False),
    ("rectangle", "Rectangle", "formes", False),
    ("rectangle_arrondi", "Rectangle arrondi", "formes", False),
    ("cercle", "Cercle", "formes", False),
    ("anneau", "Anneau", "formes", False),
    ("triangle", "Triangle", "formes", False),
    ("fleche_pleine", "Flèche pleine", "formes", False),
    ("rayures", "Arc-en-ciel", "arriere-plans", True),
    ("coucher", "Coucher de soleil", "arriere-plans", True),
    ("ondes", "Collines", "arriere-plans", True),
    ("pois", "Pois", "arriere-plans", True),
    ("grille", "Grille", "arriere-plans", True),
    ("vignette", "Bords sombres", "superpositions", True),
    ("lumiere", "Lumière chaude", "superpositions", True),
    ("bokeh", "Bokeh", "superpositions", True),
    ("neige", "Neige", "superpositions", True),
    ("cadre_blanc", "Cadre blanc", "cadres", True),
    ("cadre_pointille", "Pointillés", "cadres", True),
    ("polaroid", "Photo instantanée", "cadres", True),
    ("pellicule", "Pellicule", "cadres", True),
    ("pouce", "Pouce", "stickers", False),
    ("wow", "WOW !", "stickers", False),
    ("nouveau", "Nouveau", "stickers", False),
    ("sourire", "Sourire", "stickers", False),
    ("coche", "Validé", "stickers", False),
    ("coeur_arc", "Cœur arc-en-ciel", "stickers", False),
)


def register(api):
    for file, name, category, fill in ITEMS:
        api.add_graphic(Graphic(f"graphismes.{file}", name, category, f"svg/{file}.svg", fill))
