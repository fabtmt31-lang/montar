# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneaux du rail de gauche : Texte (maquette 03), Transitions, Effets."""
from __future__ import annotations

import copy
from functools import cache

from PyQt6.QtCore import QMimeData, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QImage, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from montar.core.project import Clip, Effects
from montar.core.timeline import VIDEO_TRANSITIONS
from montar.i18n import _
from montar.ui.editor.controller import EditorController
from montar.ui.editor.controls import SliderRow, section
from montar.ui.editor.params import ParamControl
from montar.ui.labels import TRANSITIONS
from montar.ui.text_render import PRESETS as TEXT_PRESETS
from montar.ui.text_render import render, text_bounds
from montar.ui.theme import theme
from montar.ui.theme.icons import pixmap as icon_pixmap
from montar.ui.widgets import button, label, rounded_pixmap

SIDE_WIDTH = 320  # largeur de départ des volets de gauche (réglable par l'utilisateur)
SIDE_MIN_WIDTH = 280
TILE = QSize(126, 72)
ICON_TILE = QSize(126, 50)  # tuiles à pictogramme (transitions) : plus basses
TRANSITION_MIME = "application/x-montar-transition"  # type de transition glissée


class _DragTile(QPushButton):
    """Tuile qui se glisse vers la timeline (données `mime` → `payload`)."""

    def __init__(self, mime: str, payload: str) -> None:
        super().__init__()
        self._mime, self._payload = mime, payload
        self._press = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            mime = QMimeData()
            mime.setData(self._mime, self._payload.encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab().scaledToWidth(
                90, Qt.TransformationMode.SmoothTransformation))
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)


class _Panel(QFrame):
    def __init__(self, title: str, scroll: bool = False) -> None:
        super().__init__()
        self.setObjectName("SidePanel")
        self.setMinimumWidth(SIDE_MIN_WIDTH)
        if not scroll:
            self.body = QVBoxLayout(self)
            self.body.setContentsMargins(16, 18, 16, 12)
            self.body.setSpacing(10)
            self.body.addWidget(label(title, "h3"))
            return
        # contenu plus haut que la fenêtre : titre fixe, le reste défile
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 18, 0, 0)
        outer.setSpacing(10)
        head = label(title, "h3")
        head.setContentsMargins(16, 0, 16, 0)
        outer.addWidget(head)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(area, 1)
        inner = QWidget()
        area.setWidget(inner)
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(16, 0, 16, 12)
        self.body.setSpacing(10)

    def hint(self, text: str) -> QLabel:
        lbl = label(text, "small")
        lbl.setWordWrap(True)
        return lbl


def _tile(pm: QPixmap, text: str = "", button: QPushButton | None = None,
          size: QSize = TILE) -> QPushButton:
    b = button or QPushButton()
    b.setProperty("variant", "tile")
    b.setCheckable(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    # place du libellé d'après la police réelle (elle varie d'un système à l'autre)
    text_height = b.fontMetrics().height() + 8 if text else 0
    b.setFixedSize(size.width(), size.height() + text_height)
    layout = QVBoxLayout(b)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(2)
    img = QLabel()
    img.setPixmap(rounded_pixmap(pm, QSize(size.width() - 10, size.height() - 10), 10))
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
        super().__init__(_("Texte"), scroll=True)
        add = button(_("Ajouter une zone de texte"), "primary", "plus")
        add.setMinimumHeight(44)
        add.clicked.connect(lambda: self.addRequested.emit("title"))
        self.body.addWidget(add)
        for category, title in (("title", _("TITRES")), ("band", _("BANDEAUX & SOUS-TITRES")),
                                ("other", _("CITATIONS, MÈMES & GÉNÉRIQUES"))):
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
        # nom du modèle ; texte d'exemple s'il a plusieurs lignes (nom et fonction…)
        preview.content = _(style.content) if "\n" in style.content \
            else _(TEXT_PRESETS[style.preset][0])
        preview.x, preview.y = (0.5, 0.5)
        preview.align = "center" if not style.accent else "left"
        preview.size = style.size * (3.0 if category == "band" else 2.2)
        fit = w * 0.86 / max(1.0, text_bounds(preview, w, int(w * 9 / 16)).width())
        preview.size *= min(1.0, fit)  # le texte tient dans la vignette
        painter.drawImage(0, 0, render(preview, w, int(w * 9 / 16)))
        painter.end()
        return pm


@cache
def _pattern_image(kind: str, width: int, height: int) -> QImage:
    """Vignette d'une transition à motif, à mi-parcours : la première scène (sombre) et la
    seconde (claire) séparées par le motif, bord adouci comme dans le rendu."""
    from montar.engine.lumas import luma_bytes, softness

    levels = luma_bytes(kind, width, height, 16 / 9)  # comme dans une vidéo 16:9
    soft = max(0.04, softness(kind)) / 2
    first = (QColor("#17261E"), QColor("#2F7A56"))
    second = (QColor("#BFE3CF"), QColor("#F4F1E6"))
    image = QImage(width, height, QImage.Format.Format_RGB32)
    for y in range(height):
        k = y / max(1, height - 1)
        a = [round(c0 + (c1 - c0) * k) for c0, c1 in
             zip(first[0].getRgb()[:3], first[1].getRgb()[:3], strict=True)]
        b = [round(c0 + (c1 - c0) * k) for c0, c1 in
             zip(second[0].getRgb()[:3], second[1].getRgb()[:3], strict=True)]
        for x in range(width):
            level = levels[y * width + x] / 255
            mix = max(0.0, min(1.0, (0.5 - level) / (2 * soft) + 0.5))  # 1 : seconde scène
            r, g, bl = (round(ca + (cb - ca) * mix) for ca, cb in zip(a, b, strict=True))
            image.setPixel(x, y, 0xFF000000 | (r << 16) | (g << 8) | bl)
    return image


def pattern_tile(kind: str) -> QPixmap:
    w, h = ICON_TILE.width(), ICON_TILE.height()
    pm = QPixmap.fromImage(_pattern_image(kind, w, h).scaled(
        w * 2, h * 2, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    return pm


class TransitionsPanel(_Panel):
    applyRequested = pyqtSignal(str)

    def __init__(self, controller: EditorController) -> None:
        super().__init__(_("Transitions"), scroll=True)
        self.controller = controller
        self.info = self.hint("")
        self.body.addWidget(self.info)
        grid = QGridLayout()
        grid.setSpacing(8)
        self._tiles = []
        for i, kind in enumerate(VIDEO_TRANSITIONS):
            name, icon = TRANSITIONS[kind]
            picture = self._icon_tile(icon) if icon else pattern_tile(kind)
            tile = _tile(picture, _(name), _DragTile(TRANSITION_MIME, kind), ICON_TILE)
            tile.setCheckable(False)
            tile.setToolTip(_("Glissez la transition entre deux clips de la timeline, ou "
                              "cliquez pour la placer après le clip sélectionné"))
            tile.clicked.connect(lambda _=False, k=kind: self.applyRequested.emit(k))
            grid.addWidget(tile, i // 2, i % 2)
            self._tiles.append(tile)
        self.body.addLayout(grid)
        # transitions apportées par les modules
        self._module_grid = QGridLayout()
        self._module_grid.setSpacing(8)
        self.body.addLayout(self._module_grid)
        self.body.addStretch()
        controller.selectionChanged.connect(lambda _id: self.refresh())
        controller.changed.connect(self.refresh)
        self.refresh()

    def set_module_transitions(self, transitions) -> None:
        """`transitions` : liste de (module, montar.api.Transition)."""
        while self._module_grid.count():
            item = self._module_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, (_module_id, t) in enumerate(transitions):
            tile = _tile(self._icon_tile(t.icon), _(t.name), _DragTile(TRANSITION_MIME, t.id),
                         ICON_TILE)
            tile.setCheckable(False)
            tile.setToolTip(_(t.description) or _(t.name))
            tile.clicked.connect(lambda _=False, k=t.id: self.applyRequested.emit(k))
            self._module_grid.addWidget(tile, i // 2, i % 2)

    @staticmethod
    def _icon_tile(icon: str) -> QPixmap:
        p = theme().palette
        pm = QPixmap(ICON_TILE.width() * 2, ICON_TILE.height() * 2)
        pm.fill(QColor(p.mist))
        painter = QPainter(pm)
        ip = icon_pixmap(icon, p.forest, 44, 1.0)
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
        if pair is None:
            self.info.setText(_("Glissez une transition entre deux clips qui se suivent dans "
                                "la timeline. Un clic la place après le clip sélectionné."))
        else:
            self.info.setText(_("Glissez une transition entre deux clips, ou cliquez pour la "
                                "placer entre le clip sélectionné et son voisin. Cliquez "
                                "ensuite sur sa pastille dans la timeline pour la régler."))


class EffectsPanel(_Panel):
    """Effets intégrés du clip, puis effets des modules appliqués au clip (avec leurs
    réglages) ; « Ajouter un effet… » ouvre la fenêtre de choix."""

    addRequested = pyqtSignal(str)  # clip

    def __init__(self, controller: EditorController) -> None:
        super().__init__(_("Effets"), scroll=True)
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
        # effets des modules appliqués au clip sélectionné
        self._modules_box = QVBoxLayout()
        self._modules_box.setSpacing(6)
        self.body.addLayout(self._modules_box)
        self.add_button = button(_("Ajouter un effet ou un module…"), "tonal", "plus")
        self.add_button.clicked.connect(self._add_clicked)
        self.body.addWidget(self.add_button)
        reset = button(_("Retirer les effets"), "secondary", "rotate-ccw")
        reset.clicked.connect(self._reset)
        self.body.addWidget(reset)
        self._reset_button = reset
        self._module_controls: list = []  # (effet, ParamControl, effet audio ?)
        self._shown: tuple | None = None  # (clip, effets affichés)
        self.modules = None
        self.body.addStretch()
        controller.selectionChanged.connect(lambda _id: self.refresh())
        controller.changed.connect(self.refresh)
        self.refresh()

    def _visual_clip(self) -> Clip | None:
        clip = self.controller.selected_clip()
        if clip is None or clip.is_text:
            return None
        media = self.controller.project.find_media(clip.media_id)
        track = self.controller.timeline.track(clip.track_id)
        return clip if media and media.kind != "audio" and track.kind == "video" else None

    def set_modules(self, modules) -> None:
        self.modules = modules
        self.rebuild_modules()

    def rebuild_modules(self) -> None:
        self._shown = None  # liste des effets des modules changée : tout est refait
        self.refresh()

    def _applied(self) -> list:
        """(effet, audio ?) des modules appliqués au clip sélectionné."""
        manager = self.modules.manager if self.modules else None
        if manager is None:
            return []
        result = []
        for audio, effects, clip in ((False, manager.effects(), self._visual_clip()),
                                     (True, manager.audio_effects(), self._audio_clip())):
            if clip is not None:
                result += [(e, audio) for _m, e in effects if e.id in clip.modules]
        return result

    def _build_applied(self, applied: list) -> None:
        while self._modules_box.count():
            item = self._modules_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._module_controls = []
        for effect, audio in applied:
            head = QWidget()
            hl = QHBoxLayout(head)
            hl.setContentsMargins(0, 8, 0, 0)
            title = label(_(effect.name).upper(), "section")
            title.setToolTip(_(effect.description))
            hl.addWidget(title, 1)
            remove = button("", "ghost", "x", tooltip=_("Retirer {name}").format(
                name=_(effect.name)))
            remove.clicked.connect(lambda _=False, e=effect, a=audio: self._remove(e, a))
            hl.addWidget(remove)
            self._modules_box.addWidget(head)
            for param in effect.params:
                control = ParamControl(
                    param, lambda v, merge, e=effect, k=param.key, a=audio:
                    self._store(e, k, v, merge, a))
                self._modules_box.addWidget(control.widget)
                self._module_controls.append((effect, control, audio))

    def _audio_clip(self) -> Clip | None:
        clip = self.controller.selected_clip()
        if clip is None or clip.is_text:
            return None
        media = self.controller.project.find_media(clip.media_id)
        return clip if media is not None and media.kind in ("video", "audio") \
            and media.has_audio else None

    def _store(self, effect, key: str, value, merge: bool, audio: bool) -> None:
        clip = self._audio_clip() if audio else self._visual_clip()
        if clip is None:
            return

        def change(c):
            values = dict(c.modules.get(effect.id) or effect.defaults())
            values[key] = value
            c.modules[effect.id] = values

        self.controller.edit_clip(_(effect.name), clip.id, change,
                                  merge=(clip.id, effect.id, key) if merge else None)

    def _remove(self, effect, audio: bool) -> None:
        clip = self._audio_clip() if audio else self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(_("Retirer {name}").format(name=_(effect.name)),
                                      clip.id, lambda c: c.modules.pop(effect.id, None))

    def _add_clicked(self) -> None:
        clip = self.controller.selected_clip()
        if clip is not None:
            self.addRequested.emit(clip.id)

    def refresh(self) -> None:
        clip = self._visual_clip()
        self.info.setVisible(clip is None)
        for key, row in self._rows.items():
            row.setEnabled(clip is not None)
            if clip is not None:
                row.set_value(getattr(clip.effects, key) * 100)
        selected = self.controller.selected_clip()
        applied = self._applied()
        shown = (selected.id if selected else None, tuple((e.id, a) for e, a in applied))
        if shown != self._shown:
            self._shown = shown
            self._build_applied(applied)
        for effect, control, audio in self._module_controls:
            target = self._audio_clip() if audio else clip
            if target is not None:
                values = {**effect.defaults(), **(target.modules.get(effect.id) or {})}
                control.set_value(values.get(control.param.key, control.param.default))
        self.add_button.setEnabled(selected is not None and not selected.is_text)
        self._reset_button.setEnabled(clip is not None or bool(applied))

    def _set(self, key: str, title: str, value: float) -> None:
        clip = self._visual_clip()
        if clip is not None:
            self.controller.edit_clip(title, clip.id,
                                      lambda c: setattr(c.effects, key, value / 100),
                                      merge=(clip.id, f"effect:{key}"))

    def _reset(self) -> None:
        clip = self._visual_clip() or self._audio_clip()
        if clip is not None:
            manager = self.modules.manager if self.modules else None
            effect_ids = {e.id for _m, e in manager.effects() + manager.audio_effects()} \
                if manager else set()

            def change(c):
                c.effects = Effects()
                for key in effect_ids:
                    c.modules.pop(key, None)

            self.controller.edit_clip(_("Retirer les effets"), clip.id, change)
