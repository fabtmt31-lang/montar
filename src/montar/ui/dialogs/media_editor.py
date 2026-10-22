# SPDX-License-Identifier: GPL-3.0-or-later
"""Édition d'un média avant le montage (F-MED-07) : aperçu partagé avant / après, puis
remplacement du média d'origine ou création d'une copie."""
from __future__ import annotations

import copy
import math
from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from montar.core.project import MediaItem
from montar.core.timecode import frames_to_timecode
from montar.engine.base import Canvas, ClipSpec, Engine, TimelineSpec, TrackSpec
from montar.engine.looks import PRESETS
from montar.i18n import _
from montar.media.edit import MediaEdit
from montar.ui.editor.controls import SliderRow, Tabs, page, section
from montar.ui.widgets import Segmented, button, label

PANE = QSize(400, 225)
_COLORS = (("brightness", "Luminosité"), ("contrast", "Contraste"),
           ("saturation", "Saturation"), ("temperature", "Température"),
           ("exposure", "Exposition"))
_TIMELAPSE_METHODS = (("sample", "Échantillonnage"), ("blend", "Fusion d'images"))


def _signed(v: float) -> str:
    return f"{v:+.0f}" if round(v) else "0"


class _Renderer:
    """Image source (gauche) et image avec couleur et filtres (droite), par le moteur."""

    def __init__(self, engine: Engine, media: MediaItem) -> None:
        self.media = media
        self.fps = max(1, round(media.fps or 25))
        mw, mh = media.width or 640, media.height or 360
        scale = min(1.0, 640 / mw, 360 / mh)
        w, h = max(2, int(mw * scale) // 2 * 2), max(2, int(mh * scale) // 2 * 2)
        self.size = (w, h)
        self.length = 1 if media.kind == "image" else max(1, round(media.duration * self.fps))
        self._canvas = Canvas(w, h, self.fps)
        self._engine = engine
        self.original = engine.build(self._spec(MediaEdit()))
        self.edited = engine.build(self._spec(MediaEdit()))

    def _spec(self, edit: MediaEdit) -> TimelineSpec:
        clip = ClipSpec(self.media.path, self.media.kind, 0, self.length,
                        media_size=(self.media.width, self.media.height),
                        color=copy.deepcopy(edit.color), preset=edit.preset,
                        preset_amount=edit.preset_amount)
        return TimelineSpec(self._canvas, (TrackSpec("video", False, False, (clip,)),))

    def set_edit(self, edit: MediaEdit) -> None:
        if not self.edited.update(self._spec(edit)):
            self.edited = self._engine.build(self._spec(edit))

    def image(self, source, frame: int) -> QImage:
        w, h = self.size
        data = source.render(max(0, min(frame, self.length - 1)), w, h)
        return QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


def geometry(image: QImage, edit: MediaEdit) -> QImage:
    """Recadrage, rotation et retournement appliqués à l'image d'aperçu."""
    left, right, top, bottom = edit.crops()
    w, h = image.width(), image.height()
    image = image.copy(round(w * left), round(h * top),
                       max(1, round(w * (1 - left - right))),
                       max(1, round(h * (1 - top - bottom))))
    if edit.rotation % 360:
        image = image.transformed(QTransform().rotate(edit.rotation),
                                  Qt.TransformationMode.SmoothTransformation)
    if edit.flip_h or edit.flip_v:
        image = image.mirrored(edit.flip_h, edit.flip_v)
    return image


class MediaEditorDialog(QDialog):
    """`result_mode` vaut « replace » ou « copy » après validation."""

    def __init__(self, media: MediaItem, engine_factory: Callable[[], Engine],
                 timelapse_available: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Modifier le média"))
        self.setModal(True)
        self.setMinimumSize(1300, 700)
        self.media = media
        self.edit = MediaEdit()
        self.result_mode = ""
        self._refreshing = False
        visual = media.kind in ("video", "image")
        self._renderer = _Renderer(engine_factory(), media) if visual else None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._render)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        left = QFrame()
        left.setObjectName("ExportSide")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(28, 24, 28, 24)
        ll.setSpacing(12)
        ll.addWidget(label(_("Modifier « {name} »").format(name=media.name), "h2"))
        intro = label(_("Les modifications donnent un nouveau fichier : vous choisirez de "
                        "remplacer le média d'origine dans le projet ou d'en créer une "
                        "copie."), "muted")
        intro.setWordWrap(True)
        ll.addWidget(intro)
        panes = QHBoxLayout()
        panes.setSpacing(16)
        self.before, self.after = QLabel(), QLabel()
        for title, pane in ((_("Original"), self.before), (_("Modifié"), self.after)):
            col = QVBoxLayout()
            col.addWidget(label(title, "h3"))
            pane.setFixedSize(PANE)
            pane.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pane.setStyleSheet("background: #0B120E; border-radius: 10px;")
            col.addWidget(pane)
            panes.addLayout(col)
        if not visual:
            for pane in (self.before, self.after):
                pane.setText(_("Son : aperçu non disponible"))
                pane.setStyleSheet(pane.styleSheet() + "color: #FFFFFF;")
        ll.addLayout(panes)

        self.position = QSlider(Qt.Orientation.Horizontal)
        length = self._renderer.length if self._renderer else max(1, round(media.duration
                                                                            * 25))
        self._fps = self._renderer.fps if self._renderer else 25
        self.position.setRange(0, max(0, length - 1))
        self.position.valueChanged.connect(self._position_changed)
        self.timecode = label("", "mono")
        trim_row = QHBoxLayout()
        self.set_in = button(_("Début ici"), "secondary")
        self.set_out = button(_("Fin ici"), "secondary")
        self.set_in.clicked.connect(lambda: self._mark("in"))
        self.set_out.clicked.connect(lambda: self._mark("out"))
        self.trim_label = label("", "small")
        trim_row.addWidget(self.timecode)
        trim_row.addStretch()
        trim_row.addWidget(self.trim_label)
        trim_row.addWidget(self.set_in)
        trim_row.addWidget(self.set_out)
        timed = media.kind != "image"
        for w in (self.position, self.set_in, self.set_out, self.trim_label, self.timecode):
            w.setVisible(timed)
        ll.addWidget(self.position)
        ll.addLayout(trim_row)
        self.summary = label("", "small")
        ll.addWidget(self.summary)
        ll.addStretch()
        outer.addWidget(left, 1)

        side = QWidget()
        side.setFixedWidth(380)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(24, 24, 24, 24)
        pages = []
        if visual:
            pages.append(("image", _("Image"), self._image_page()))
            pages.append(("color", _("Couleur"), self._color_page()))
        if timed:
            pages.append(("speed", _("Vitesse et son"), self._speed_page(timelapse_available)))
        self.tabs = Tabs(pages)
        sl.addWidget(self.tabs, 1)
        buttons = QHBoxLayout()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        self.copy_button = button(_("Créer une copie"), "secondary", "copy")
        self.copy_button.clicked.connect(lambda: self._finish("copy"))
        self.replace_button = button(_("Remplacer l'original"), "primary")
        self.replace_button.clicked.connect(lambda: self._finish("replace"))
        for b in (cancel, self.copy_button, self.replace_button):
            b.setMinimumHeight(42)
        buttons.addWidget(cancel)
        buttons.addStretch()
        sl.addLayout(buttons)
        final = QHBoxLayout()
        final.addWidget(self.copy_button, 1)
        final.addWidget(self.replace_button, 1)
        sl.addLayout(final)
        outer.addWidget(side)
        self._position_changed(0)
        self._changed()

    # --- pages -------------------------------------------------------------------

    def _image_page(self) -> QWidget:
        w, layout = page()
        layout.addWidget(section(_("Recadrage")))
        self.crop_rows = {}
        for name, title in (("crop_left", _("Gauche")), ("crop_right", _("Droite")),
                            ("crop_top", _("Haut")), ("crop_bottom", _("Bas"))):
            row = SliderRow(title, 0, 45, lambda v: f"{v:.0f} %")
            row.moved.connect(lambda v, n=name: self._set(n, v / 100))
            self.crop_rows[name] = row
            layout.addWidget(row)
        layout.addWidget(section(_("Orientation")))
        tools = QHBoxLayout()
        for icon, tip, action in (
            ("rotate-ccw", _("Pivoter à gauche"), lambda: self._rotate(-90)),
            ("rotate-cw", _("Pivoter à droite"), lambda: self._rotate(90)),
            ("flip-horizontal-2", _("Miroir horizontal"),
             lambda: self._set("flip_h", not self.edit.flip_h)),
            ("flip-vertical-2", _("Miroir vertical"),
             lambda: self._set("flip_v", not self.edit.flip_v)),
        ):
            b = button("", "secondary", icon, tooltip=tip)
            b.clicked.connect(action)
            tools.addWidget(b)
        tools.addStretch()
        layout.addLayout(tools)
        return w

    def _color_page(self) -> QWidget:
        w, layout = page()
        layout.addWidget(section(_("Réglages")))
        self.color_rows = {}
        for name, title in _COLORS:
            row = SliderRow(_(title), -100, 100, _signed)
            row.set_value(0)
            row.moved.connect(lambda v, n=name: self._set_color(n, v / 100))
            self.color_rows[name] = row
            layout.addWidget(row)
        layout.addWidget(section(_("Filtre")))
        self.preset = QComboBox()
        self.preset.addItem(_("Aucun"), "")
        for key, text in PRESETS.items():
            self.preset.addItem(_(text), key)
        self.preset.currentIndexChanged.connect(
            lambda _i: self._set("preset", self.preset.currentData()))
        layout.addWidget(self.preset)
        self.preset_amount = SliderRow(_("Intensité"), 0, 100, lambda v: f"{v:.0f} %")
        self.preset_amount.set_value(100)
        self.preset_amount.moved.connect(lambda v: self._set("preset_amount", v / 100))
        layout.addWidget(self.preset_amount)
        return w

    def _speed_page(self, timelapse: bool) -> QWidget:
        w, layout = page()
        layout.addWidget(section(_("Vitesse")))
        self.speed = SliderRow(_("Vitesse"), 0.1, 16, lambda v: f"×{v:.2g}",
                               to_slider=math.log, from_slider=math.exp)
        self.speed.set_value(1.0)
        self.speed.moved.connect(lambda v: self._set("speed", round(v, 3)))
        layout.addWidget(self.speed)
        layout.addWidget(section(_("Son")))
        self.volume = SliderRow(_("Volume"), 0, 200, lambda v: f"{v:.0f} %")
        self.volume.set_value(100)
        self.volume.moved.connect(lambda v: self._set("volume", v / 100))
        layout.addWidget(self.volume)
        self.mute = QCheckBox(_("Supprimer le son"))
        self.mute.toggled.connect(lambda on: self._set("mute", on))
        self.mute.setVisible(self.media.kind == "video" and self.media.has_audio)
        layout.addWidget(self.mute)
        self.timelapse = QCheckBox(_("Timelapse sur tout le média"))
        self.timelapse_factor = QDoubleSpinBox()
        self.timelapse_factor.setRange(2, 1000)
        self.timelapse_factor.setValue(16)
        self.timelapse_factor.setPrefix("×")
        self.timelapse_method = Segmented([(k, _(t)) for k, t in _TIMELAPSE_METHODS],
                                          "sample", compact=True)
        if timelapse and self.media.kind == "video":
            layout.addWidget(section(_("Timelapse")))
            layout.addWidget(self.timelapse)
            row = QHBoxLayout()
            row.addWidget(label(_("Facteur")))
            row.addWidget(self.timelapse_factor)
            row.addStretch()
            layout.addLayout(row)
            layout.addWidget(self.timelapse_method)
        for widget in (self.timelapse, self.timelapse_factor):
            signal = widget.toggled if widget is self.timelapse else widget.valueChanged
            signal.connect(lambda *_a: self._timelapse_changed())
        self.timelapse_method.changed.connect(lambda _k: self._timelapse_changed())
        return w

    # --- état ---------------------------------------------------------------------

    def _set(self, name: str, value) -> None:
        setattr(self.edit, name, value)
        self._changed()

    def _set_color(self, name: str, value: float) -> None:
        setattr(self.edit.color, name, value)
        self._changed()

    def _rotate(self, delta: int) -> None:
        self._set("rotation", (self.edit.rotation + delta) % 360)

    def _timelapse_changed(self) -> None:
        on = self.timelapse.isChecked()
        self.edit.timelapse = ({"factor": self.timelapse_factor.value(),
                                "method": self.timelapse_method.current()} if on else None)
        self._changed()

    def _mark(self, which: str) -> None:
        t = self.position.value() / self._fps
        if which == "in":
            self.edit.trim_in = min(t, self.edit.segment(self.media)[1] - 1 / self._fps)
        else:
            self.edit.trim_out = max(t, self.edit.trim_in + 1 / self._fps)
        self._changed()

    def _position_changed(self, _value: int) -> None:
        self.timecode.setText(frames_to_timecode(self.position.value(), self._fps))
        self._timer.start()

    def _changed(self) -> None:
        start, end = self.edit.segment(self.media)
        self.trim_label.setText(_("Gardé : {a} → {b}").format(
            a=frames_to_timecode(round(start * self._fps), self._fps),
            b=frames_to_timecode(round(end * self._fps), self._fps)))
        parts = []
        if self.media.kind != "audio":
            w, h = self.edit.output_size(self.media)
            parts.append(f"{w} × {h}")
        if self.media.kind != "image":
            seconds = self.edit.duration(self.media)
            if self.edit.timelapse:
                seconds /= self.edit.timelapse["factor"]
            parts.append(_("{s:.1f} s").format(s=seconds))
        self.summary.setText(_("Résultat : {info}").format(info=" · ".join(parts)))
        modified = not self.edit.is_identity()
        self.copy_button.setEnabled(modified)
        self.replace_button.setEnabled(modified)
        if self._renderer is not None:
            self._renderer.set_edit(self.edit)
        self._timer.start()

    def _render(self) -> None:
        if self._renderer is None:
            return
        frame = self.position.value()
        before = self._renderer.image(self._renderer.original, frame)
        after = geometry(self._renderer.image(self._renderer.edited, frame), self.edit)
        for pane, image in ((self.before, before), (self.after, after)):
            pane.setPixmap(QPixmap.fromImage(image).scaled(
                PANE, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _finish(self, mode: str) -> None:
        self.result_mode = mode
        self.accept()

