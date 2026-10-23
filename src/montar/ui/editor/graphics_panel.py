# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau « Graphiques » : éléments apportés par les modules (annotations, formes,
arrière-plans, cadres, stickers…), rangés par rubrique. Un clic place l'élément à la tête
de lecture."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLineEdit, QPushButton, QWidget

from montar.api import GRAPHIC_CATEGORIES
from montar.i18n import N_, _
from montar.ui.editor.controls import section
from montar.ui.editor.panels import TILE, _Panel, _tile
from montar.ui.graphics import thumbnail

CATEGORY_LABELS = {
    "annotations": N_("Annotations"), "figures": N_("Figures"), "formes": N_("Formes"),
    "arriere-plans": N_("Arrière-plans"), "superpositions": N_("Superpositions"),
    "cadres": N_("Cadres"), "stickers": N_("Stickers"),
}


class GraphicsPanel(_Panel):
    graphicRequested = pyqtSignal(str, object)  # module, montar.api.Graphic

    def __init__(self) -> None:
        super().__init__(_("Graphiques"), scroll=True)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._filter())
        self.body.addWidget(self.search)
        self.body.addWidget(self.hint(_("Un clic place l'élément à la tête de lecture, sur une "
                                        "piste au-dessus de la vidéo (les arrière-plans en "
                                        "dessous).")))
        self._content = QWidget()
        self._layout = QGridLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.body.addWidget(self._content)
        self.empty = self.hint(_("Aucun graphisme : activez le module « Graphismes » ou "
                                 "installez un module qui en fournit."))
        self.body.addWidget(self.empty)
        self.body.addStretch()
        self._tiles: list[tuple[QPushButton, str, object]] = []
        self._sections: dict[str, QWidget] = {}

    def set_graphics(self, graphics: list) -> None:
        """`graphics` : liste de (module, Graphic)."""
        while self._layout.count():
            self._layout.takeAt(0)
        for widget in [t for t, _c, _g in self._tiles] + list(self._sections.values()):
            widget.deleteLater()
        self._tiles, self._sections = [], {}
        order = list(GRAPHIC_CATEGORIES)
        by_category: dict[str, list] = {}
        for module_id, g in graphics:
            by_category.setdefault(g.category, []).append((module_id, g))
        for category in sorted(by_category, key=lambda c: (order.index(c) if c in order
                                                            else len(order), c)):
            head = section(_(CATEGORY_LABELS.get(category, category)).upper())
            head.setParent(self._content)  # hors de la grille, il ne doit pas devenir fenêtre
            self._sections[category] = head
            for module_id, g in by_category[category]:
                tile = _tile(thumbnail(g, TILE), _(g.name))
                tile.setParent(self._content)
                tile.setCheckable(False)
                tile.setToolTip(_(g.description) or _(g.name))
                tile.clicked.connect(
                    lambda _=False, m=module_id, gr=g: self.graphicRequested.emit(m, gr))
                self._tiles.append((tile, category, g))
        self.empty.setVisible(not graphics)
        self._filter()

    def _filter(self) -> None:
        """Rubriques et vignettes qui correspondent à la recherche, sans trou dans la grille."""
        text = self.search.text().strip().casefold()
        while self._layout.count():
            self._layout.takeAt(0)  # les widgets restent, seule leur place est refaite
        row = 0
        for category, head in self._sections.items():
            label_ = _(CATEGORY_LABELS.get(category, category)).casefold()
            tiles = [t for t, c, g in self._tiles if c == category
                     and (not text or text in _(g.name).casefold() or text in label_)]
            for t, c, _g in self._tiles:
                if c == category:
                    t.setVisible(t in tiles)
            head.setVisible(bool(tiles))
            if not tiles:
                continue
            self._layout.addWidget(head, row, 0, 1, 2)
            row += 1
            for i, tile in enumerate(tiles):
                self._layout.addWidget(tile, row + i // 2, i % 2)
            row += (len(tiles) + 1) // 2

    def tiles(self) -> list[tuple[QPushButton, object]]:
        return [(t, g) for t, _c, g in self._tiles if not t.isHidden()]
