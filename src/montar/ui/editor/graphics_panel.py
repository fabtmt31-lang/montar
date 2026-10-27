# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau « Éléments » : logos du kit de marque, effets animés, filtres et graphismes des
modules (annotations, formes, arrière-plans, cadres, stickers…), rangés par catégorie.

Chaque catégorie est un accordéon : deux exemples sont visibles, « Tout voir » déplie la
catégorie (une seule à la fois) ; une recherche montre tout ce qui correspond. Un clic
place l'élément à la tête de lecture (les filtres s'appliquent au clip sélectionné)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from montar.api import GRAPHIC_CATEGORIES
from montar.core.project import Clip
from montar.engine.looks import PRESETS
from montar.i18n import N_, _
from montar.ui.animated import EFFECTS
from montar.ui.animated import thumbnail as animated_thumbnail
from montar.ui.editor.controller import EditorController
from montar.ui.editor.controls import SliderRow, section
from montar.ui.editor.panels import TILE, _Panel, _tile
from montar.ui.graphics import thumbnail
from montar.ui.labels import PRESET_SWATCHES
from montar.ui.widgets import button

CATEGORY_LABELS = {
    "annotations": N_("Annotations"), "figures": N_("Figures"), "formes": N_("Formes"),
    "arriere-plans": N_("Arrière-plans"), "superpositions": N_("Superpositions"),
    "cadres": N_("Cadres"), "stickers": N_("Stickers"),
}
PREVIEW_TILES = 2  # exemples visibles d'une catégorie repliée


class _Section(QWidget):
    """Catégorie repliable : titre, « Tout voir (n) », vignettes et réglages éventuels."""

    toggled = pyqtSignal(str)

    def __init__(self, key: str, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.key, self.title = key, title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.head = section(title.upper())
        head.addWidget(self.head)
        head.addStretch()
        self.more = button("", "ghost")
        self.more.setStyleSheet("padding: 2px 6px; font-weight: 600;")
        self.more.clicked.connect(lambda: self.toggled.emit(self.key))
        head.addWidget(self.more)
        layout.addLayout(head)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        layout.addLayout(self.grid)
        self.extra = QVBoxLayout()  # réglages montrés quand la catégorie est dépliée
        self.extra.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.extra)
        self.tiles: list[tuple[QPushButton, str]] = []  # (vignette, texte cherché)
        self.extras: list[QWidget] = []

    def add_tile(self, tile: QPushButton, words: str) -> None:
        tile.setParent(self)
        self.tiles.append((tile, words.casefold()))

    def add_extra(self, widget: QWidget) -> None:
        self.extra.addWidget(widget)
        self.extras.append(widget)

    def arrange(self, query: str, expanded: bool) -> int:
        """Place les vignettes visibles ; renvoie leur nombre (0 : catégorie cachée)."""
        while self.grid.count():
            self.grid.takeAt(0)
        title = self.title.casefold()
        matching = [t for t, words in self.tiles
                    if not query or query in words or query in title]
        shown = matching if expanded or query else matching[:PREVIEW_TILES]
        for t, _w in self.tiles:
            t.setVisible(t in shown)
        for i, t in enumerate(shown):
            self.grid.addWidget(t, i // 2, i % 2)
        self.more.setVisible(not query and len(matching) > PREVIEW_TILES)
        self.more.setText(_("Réduire") if expanded else
                          _("Tout voir ({n})").format(n=len(matching)))
        for w in self.extras:
            w.setVisible(expanded or bool(query))
        self.setVisible(bool(matching))
        return len(shown)


class ElementsPanel(_Panel):
    graphicRequested = pyqtSignal(str, object)  # module, montar.api.Graphic
    logoRequested = pyqtSignal(object)  # Path d'un logo du kit de marque
    animatedRequested = pyqtSignal(str)  # identifiant d'un effet animé

    def __init__(self, controller: EditorController | None = None) -> None:
        super().__init__(_("Éléments"), scroll=True)
        self.controller = controller
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher un élément"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._arrange())
        self.body.addWidget(self.search)
        self.body.addWidget(self.hint(_("Un clic place l'élément à la tête de lecture, sur une "
                                        "piste au-dessus de la vidéo (les arrière-plans en "
                                        "dessous) ; un filtre s'applique au clip "
                                        "sélectionné.")))
        self.expanded: str | None = None
        self._sections: dict[str, _Section] = {}
        self._order: list[str] = []
        self._holder = QWidget()
        self._holder_layout = QVBoxLayout(self._holder)
        self._holder_layout.setContentsMargins(0, 0, 0, 0)
        self._holder_layout.setSpacing(6)
        self.body.addWidget(self._holder)
        self.empty = self.hint(_("Aucun graphisme : activez le module « Graphismes » ou "
                                 "installez un module qui en fournit."))
        self.body.addWidget(self.empty)
        self.body.addStretch()

        # kit de marque (logos), effets animés, filtres, puis les graphismes des modules
        self._brand = self._section("brand", _("Kit de marque"))
        self._brand.setVisible(False)
        self._logo_tiles: list[tuple[QPushButton, Path]] = []
        animated = self._section("animated", _("Effets animés"))
        for effect in EFFECTS.values():
            tile = _tile(animated_thumbnail(effect, TILE), _(effect.name))
            tile.setCheckable(False)
            tile.setToolTip(_("{name} : effet animé de {s} s, placé au-dessus de la vidéo")
                            .format(name=_(effect.name), s=f"{effect.seconds:g}"))
            tile.clicked.connect(lambda _=False, k=effect.id: self.animatedRequested.emit(k))
            animated.add_tile(tile, _(effect.name))
        self._build_filters()
        self._graphic_keys: list[str] = []
        self._tiles: list[tuple[QPushButton, str, object]] = []
        if controller is not None:
            controller.selectionChanged.connect(lambda _id: self.refresh())
            controller.changed.connect(self.refresh)
        self.refresh()
        self._arrange()

    def _section(self, key: str, title: str) -> _Section:
        s = _Section(key, title, self._holder)
        s.toggled.connect(self.toggle)
        self._sections[key] = s
        self._order.append(key)
        self._holder_layout.addWidget(s)
        return s

    def toggle(self, key: str) -> None:
        self.expanded = None if self.expanded == key else key
        self._arrange()

    def expand(self, key: str) -> None:
        """Déplie une catégorie (ex. « filters » depuis le menu Appliquer un effet)."""
        self.expanded = key
        self._arrange()

    def _arrange(self) -> None:
        query = self.search.text().strip().casefold()
        for key in self._order:
            self._sections[key].arrange(query, self.expanded == key)

    # --- filtres -----------------------------------------------------------------------

    def _build_filters(self) -> None:
        filters = self._section("filters", _("Filtres"))
        self._group = QButtonGroup(self)
        self._filter_tiles: dict[str, QPushButton] = {}
        for key, name in [*PRESETS.items(), ("", "Aucun")]:  # exemples parlants d'abord
            tile = _tile(self._swatch(key), _(name))
            tile.clicked.connect(lambda _=False, k=key: self._apply(k))
            self._group.addButton(tile)
            self._filter_tiles[key] = tile
            filters.add_tile(tile, _(name))
        self.filter_info = self.hint(_("Sélectionnez une vidéo ou une image dans la timeline "
                                       "pour lui appliquer un filtre."))
        filters.add_extra(self.filter_info)
        self.amount = SliderRow(_("Intensité"), 0, 100, lambda v: f"{v:.0f} %")
        self.amount.moved.connect(self._set_amount)
        filters.add_extra(self.amount)

    @staticmethod
    def _swatch(key: str) -> QPixmap:
        a, b = PRESET_SWATCHES.get(key, PRESET_SWATCHES[""])
        pm = QPixmap(TILE.width() * 2, TILE.height() * 2)
        painter = QPainter(pm)
        grad = QLinearGradient(0, 0, pm.width(), pm.height())
        grad.setColorAt(0, QColor(a))
        grad.setColorAt(1, QColor(b))
        painter.fillRect(pm.rect(), grad)
        painter.end()
        return pm

    def _visual_clip(self) -> Clip | None:
        if self.controller is None:
            return None
        clip = self.controller.selected_clip()
        if clip is None or clip.is_text:
            return None
        media = self.controller.project.find_media(clip.media_id)
        track = self.controller.timeline.track(clip.track_id)
        return clip if media and media.kind != "audio" and track.kind == "video" else None

    def refresh(self) -> None:
        clip = self._visual_clip()
        for tile in self._filter_tiles.values():
            tile.setEnabled(clip is not None)
        self.amount.setEnabled(clip is not None and bool(clip.preset))
        self.filter_info.setText(_("Filtre du clip sélectionné.") if clip is not None else
                                 _("Sélectionnez une vidéo ou une image dans la timeline "
                                   "pour lui appliquer un filtre."))
        if clip is not None:
            self._filter_tiles.get(clip.preset, self._filter_tiles[""]).setChecked(True)
            self.amount.set_value(clip.preset_amount * 100)

    def _apply(self, key: str) -> None:
        clip = self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(_("Filtre"), clip.id, lambda c: (
                setattr(c, "preset", key), setattr(c, "preset_amount", 1.0)))

    def _set_amount(self, value: float) -> None:
        clip = self._visual_clip()
        if clip is not None and clip.preset:
            self.controller.edit_clip(_("Intensité du filtre"), clip.id,
                                      lambda c: setattr(c, "preset_amount", value / 100),
                                      merge=(clip.id, "preset_amount"))

    # --- kit de marque et graphismes ------------------------------------------------------

    def set_brand_logos(self, logos: list[Path]) -> None:
        from montar.ui.home.brand import logo_pixmap

        for tile, _p in self._logo_tiles:
            tile.deleteLater()
        self._brand.tiles = []
        self._logo_tiles = []
        for logo in logos:
            tile = _tile(logo_pixmap(logo, TILE), logo.stem)
            tile.setCheckable(False)
            tile.setToolTip(_("Logo « {name} » : placé en haut à droite").format(
                name=logo.stem))
            tile.clicked.connect(lambda _=False, p=logo: self.logoRequested.emit(p))
            self._brand.add_tile(tile, logo.stem)
            self._logo_tiles.append((tile, logo))
        self._arrange()
        self.empty.setVisible(not self._tiles and not logos)

    def set_graphics(self, graphics: list) -> None:
        """`graphics` : liste de (module, Graphic)."""
        for key in self._graphic_keys:
            s = self._sections.pop(key)
            self._order.remove(key)
            s.deleteLater()
        self._graphic_keys, self._tiles = [], []
        order = list(GRAPHIC_CATEGORIES)
        by_category: dict[str, list] = {}
        for module_id, g in graphics:
            by_category.setdefault(g.category, []).append((module_id, g))
        for category in sorted(by_category, key=lambda c: (order.index(c) if c in order
                                                            else len(order), c)):
            s = self._section(f"graphics:{category}",
                              _(CATEGORY_LABELS.get(category, category)))
            self._graphic_keys.append(s.key)
            for module_id, g in by_category[category]:
                tile = _tile(thumbnail(g, TILE), _(g.name))
                tile.setCheckable(False)
                tile.setToolTip(_(g.description) or _(g.name))
                tile.clicked.connect(
                    lambda _=False, m=module_id, gr=g: self.graphicRequested.emit(m, gr))
                s.add_tile(tile, _(g.name))
                self._tiles.append((tile, category, g))
        self.empty.setVisible(not graphics and not self._logo_tiles)
        self._arrange()

    def tiles(self) -> list[tuple[QPushButton, object]]:
        """Graphismes des modules visibles (dépliés ou trouvés par la recherche)."""
        return [(t, g) for t, _c, g in self._tiles if not t.isHidden()]

    def graphics(self) -> list:
        return [g for _t, _c, g in self._tiles]


GraphicsPanel = ElementsPanel  # ancien nom
