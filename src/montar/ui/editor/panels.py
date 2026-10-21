# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneaux du rail de gauche : Texte (maquette 03), Transitions, Filtres, Effets."""
from __future__ import annotations

import copy

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout

from montar.core.project import Clip, Effects
from montar.core.timeline import VIDEO_TRANSITIONS
from montar.engine.looks import PRESETS
from montar.i18n import _
from montar.ui.editor.controller import EditorController
from montar.ui.editor.controls import SliderRow, section
from montar.ui.labels import PRESET_SWATCHES, TRANSITIONS
from montar.ui.text_render import PRESETS as TEXT_PRESETS
from montar.ui.text_render import render
from montar.ui.theme import theme
from montar.ui.theme.icons import pixmap as icon_pixmap
from montar.ui.widgets import button, label, rounded_pixmap

TILE = QSize(126, 72)


class _Panel(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("SidePanel")
        self.setFixedWidth(300)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 18, 16, 12)
        self.body.setSpacing(10)
        self.body.addWidget(label(title, "h3"))

    def hint(self, text: str) -> QLabel:
        lbl = label(text, "small")
        lbl.setWordWrap(True)
        return lbl


def _tile(pm: QPixmap, text: str = "") -> QPushButton:
    b = QPushButton()
    b.setProperty("variant", "tile")
    b.setCheckable(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedSize(TILE.width(), TILE.height() + (24 if text else 0))
    layout = QVBoxLayout(b)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(2)
    img = QLabel()
    img.setPixmap(rounded_pixmap(pm, QSize(TILE.width() - 10, TILE.height() - 10), 10))
    img.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout.addWidget(img, 0, Qt.AlignmentFlag.AlignHCenter)
    if text:
        t = label(text, "small")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(t)
    return b


class TextPanel(_Panel):
    addRequested = pyqtSignal(str)  # identifiant du style

    def __init__(self) -> None:
        super().__init__(_("Texte"))
        add = button(_("Ajouter une zone de texte"), "primary", "plus")
        add.setMinimumHeight(44)
        add.clicked.connect(lambda: self.addRequested.emit("title"))
        self.body.addWidget(add)
        for category, title in (("title", _("TITRES")), ("band", _("BANDEAUX & SOUS-TITRES"))):
            self.body.addWidget(section(title))
            grid = QGridLayout()
            grid.setSpacing(8)
            items = [(k, v) for k, v in TEXT_PRESETS.items() if v[1] == category]
            for i, (key, (_name, _cat, style)) in enumerate(items):
                tile = _tile(self._preview(style, category))
                tile.setCheckable(False)
                tile.setToolTip(_(TEXT_PRESETS[key][0]))
                tile.clicked.connect(lambda _=False, k=key: self.addRequested.emit(k))
                grid.addWidget(tile, i // 2, i % 2)
            self.body.addLayout(grid)
        self.body.addWidget(self.hint(_("Le texte est ajouté à la tête de lecture, sur la "
                                        "piste Texte. Réglez-le ensuite dans l'inspecteur.")))
        self.body.addStretch()

    @staticmethod
    def _preview(style, category: str) -> QPixmap:
        w, h = TILE.width() * 2, TILE.height() * 2
        pm = QPixmap(w, h)
        painter = QPainter(pm)
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor("#9CCBB0"))
        grad.setColorAt(1, QColor("#2F7A56"))
        painter.fillRect(0, 0, w, h, grad)
        preview = copy.deepcopy(style)
        preview.content = _(TEXT_PRESETS[style.preset][0])
        preview.x, preview.y = (0.5, 0.5)
        preview.align = "center"
        preview.size = style.size * (3.0 if category == "band" else 2.2)
        painter.drawImage(0, 0, render(preview, w, int(w * 9 / 16)))
        painter.end()
        return pm


class TransitionsPanel(_Panel):
    applyRequested = pyqtSignal(str)

    def __init__(self, controller: EditorController) -> None:
        super().__init__(_("Transitions"))
        self.controller = controller
        self.info = self.hint("")
        self.body.addWidget(self.info)
        grid = QGridLayout()
        grid.setSpacing(8)
        self._tiles = []
        for i, kind in enumerate(VIDEO_TRANSITIONS):
            name, icon = TRANSITIONS[kind]
            tile = _tile(self._icon_tile(icon), _(name))
            tile.setCheckable(False)
            tile.clicked.connect(lambda _=False, k=kind: self.applyRequested.emit(k))
            grid.addWidget(tile, i // 2, i % 2)
            self._tiles.append(tile)
        self.body.addLayout(grid)
        self.body.addStretch()
        controller.selectionChanged.connect(lambda _id: self.refresh())
        controller.changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _icon_tile(icon: str) -> QPixmap:
        p = theme().palette
        pm = QPixmap(TILE.width() * 2, TILE.height() * 2)
        pm.fill(QColor(p.mist))
        painter = QPainter(pm)
        ip = icon_pixmap(icon, p.forest, 64, 1.0)
        painter.drawPixmap((pm.width() - ip.width()) // 2, (pm.height() - ip.height()) // 2, ip)
        painter.end()
        return pm

    def target(self) -> tuple[Clip, Clip] | None:
        """Clips à relier : le clip sélectionné et son voisin collé (à droite de préférence)."""
        clip = self.controller.selected_clip()
        if clip is None:
            return None
        t = self.controller.timeline
        right = t.neighbour(clip.id, "right")
        if right is not None and t.transition_after(clip.id) is None:
            return clip, right
        left = t.neighbour(clip.id, "left")
        if left is not None and t.transition_before(clip.id) is None:
            return left, clip
        return None

    def refresh(self) -> None:
        pair = self.target()
        for tile in self._tiles:
            tile.setEnabled(pair is not None)
        if pair is None:
            self.info.setText(_("Sélectionnez dans la timeline un clip collé à un autre clip, "
                                "puis choisissez une transition."))
        else:
            self.info.setText(_("La transition sera placée entre le clip sélectionné et son "
                                "voisin. Cliquez dessus dans la timeline pour la régler."))


class FiltersPanel(_Panel):
    def __init__(self, controller: EditorController) -> None:
        super().__init__(_("Filtres"))
        self.controller = controller
        self.info = self.hint(_("Sélectionnez une vidéo ou une image dans la timeline."))
        self.body.addWidget(self.info)
        grid = QGridLayout()
        grid.setSpacing(8)
        self._group = QButtonGroup(self)
        self._tiles: dict[str, QPushButton] = {}
        for i, (key, name) in enumerate([("", "Aucun"), *PRESETS.items()]):
            tile = _tile(self._swatch(key), _(name))
            tile.clicked.connect(lambda _=False, k=key: self._apply(k))
            self._group.addButton(tile)
            self._tiles[key] = tile
            grid.addWidget(tile, i // 2, i % 2)
        self.body.addLayout(grid)
        self.amount = SliderRow(_("Intensité"), 0, 100, lambda v: f"{v:.0f} %")
        self.amount.moved.connect(self._set_amount)
        self.body.addWidget(self.amount)
        self.body.addStretch()
        controller.selectionChanged.connect(lambda _id: self.refresh())
        controller.changed.connect(self.refresh)
        self.refresh()

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
        clip = self.controller.selected_clip()
        if clip is None or clip.is_text:
            return None
        media = self.controller.project.find_media(clip.media_id)
        track = self.controller.timeline.track(clip.track_id)
        return clip if media and media.kind != "audio" and track.kind == "video" else None

    def refresh(self) -> None:
        clip = self._visual_clip()
        for tile in self._tiles.values():
            tile.setEnabled(clip is not None)
        self.amount.setEnabled(clip is not None and bool(clip.preset))
        self.info.setVisible(clip is None)
        if clip is not None:
            self._tiles.get(clip.preset, self._tiles[""]).setChecked(True)
            self.amount.set_value(clip.preset_amount * 100)

    def _apply(self, key: str) -> None:
        clip = self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(_("Filtre"), clip.id, lambda c: (
                setattr(c, "preset", key), setattr(c, "preset_amount", 1.0)))

    def _set_amount(self, value: float) -> None:
        clip = self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(_("Intensité du filtre"), clip.id,
                                      lambda c: setattr(c, "preset_amount", value / 100),
                                      merge=(clip.id, "preset_amount"))


class EffectsPanel(_Panel):
    def __init__(self, controller: EditorController) -> None:
        super().__init__(_("Effets"))
        self.controller = controller
        self.info = self.hint(_("Sélectionnez une vidéo ou une image dans la timeline."))
        self.body.addWidget(self.info)
        self._rows: dict[str, SliderRow] = {}
        for key, title in (("blur", _("Flou")), ("sharpen", _("Netteté")),
                           ("vignette", _("Vignettage"))):
            row = SliderRow(title, 0, 100, lambda v: f"{v:.0f} %")
            row.moved.connect(lambda v, k=key, t=title: self._set(k, t, v))
            self.body.addWidget(row)
            self._rows[key] = row
        reset = button(_("Retirer les effets"), "secondary", "rotate-ccw")
        reset.clicked.connect(self._reset)
        self.body.addWidget(reset)
        self._reset_button = reset
        self.body.addStretch()
        controller.selectionChanged.connect(lambda _id: self.refresh())
        controller.changed.connect(self.refresh)
        self.refresh()

    _visual_clip = FiltersPanel._visual_clip

    def refresh(self) -> None:
        clip = self._visual_clip()
        self.info.setVisible(clip is None)
        for key, row in self._rows.items():
            row.setEnabled(clip is not None)
            if clip is not None:
                row.set_value(getattr(clip.effects, key) * 100)
        self._reset_button.setEnabled(clip is not None)

    def _set(self, key: str, title: str, value: float) -> None:
        clip = self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(title, clip.id,
                                      lambda c: setattr(c.effects, key, value / 100),
                                      merge=(clip.id, f"effect:{key}"))

    def _reset(self) -> None:
        clip = self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(_("Retirer les effets"), clip.id,
                                      lambda c: setattr(c, "effects", Effects()))
