# SPDX-License-Identifier: GPL-3.0-or-later
"""Édition d'un média avant le montage (F-MED-07) : lecteur (image et son, réglages
appliqués, original d'un clic ou en maintenant C), partie gardée en boucle, puis
remplacement du média d'origine ou création d'une copie."""
from __future__ import annotations

import copy
import math
from collections.abc import Callable

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap, QShortcut, QTransform
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
from montar.ui.widgets import Segmented, button, label, set_icon

PANE = QSize(816, 459)  # grand lecteur
_COLORS = (("brightness", "Luminosité"), ("contrast", "Contraste"),
           ("saturation", "Saturation"), ("temperature", "Température"),
           ("exposure", "Exposition"))
_TIMELAPSE_METHODS = (("sample", "Échantillonnage"), ("blend", "Fusion d'images"))


def _signed(v: float) -> str:
    return f"{v:+.0f}" if round(v) else "0"


class TrimBar(QWidget):
    """Barre de la partie gardée : zone verte bornée d'or, tête de lecture ; un clic y
    place la lecture."""

    seekRequested = pyqtSignal(float)  # fraction de la durée

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(14)
        self.kept = (0.0, 1.0)
        self.head = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, kept: tuple[float, float], head: float) -> None:
        self.kept, self.head = kept, head
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API Qt
        self.seekRequested.emit(max(0.0, min(1.0, event.position().x() / max(1, self.width()))))

    def paintEvent(self, _event) -> None:  # noqa: N802 - API Qt
        w, h = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(127, 140, 132, 60))
        painter.drawRoundedRect(QRectF(0, 3, w, h - 6), 4, 4)
        a, b = self.kept
        painter.setBrush(QColor("#9CCBB0"))
        painter.drawRect(QRectF(a * w, 3, max(1.0, (b - a) * w), h - 6))
        painter.setBrush(QColor("#C99A2E"))
        for x in (a * w, b * w):
            painter.drawRect(QRectF(min(w - 3.0, max(0.0, x - 1.5)), 0, 3, h))
        painter.setBrush(QColor("#D33A2C"))
        painter.drawRect(QRectF(min(w - 2.0, self.head * w), 0, 2, h))
        painter.end()


def preview_size(media: MediaItem) -> tuple[int, int]:
    """Taille des images d'aperçu (au plus 960 × 540, proportions du média)."""
    mw, mh = media.width or 640, media.height or 360
    scale = min(1.0, 960 / mw, 540 / mh)
    return max(2, int(mw * scale) // 2 * 2), max(2, int(mh * scale) // 2 * 2)


def preview_spec(media: MediaItem, edit: MediaEdit, fps: int, length: int) -> TimelineSpec:
    """Le média seul, avec la couleur, le filtre, la vitesse et le volume de `edit` (le
    recadrage et la rotation sont appliqués à l'image affichée)."""
    w, h = preview_size(media)
    speed = max(0.1, edit.speed) if media.kind != "image" else 1.0
    duration = max(1, round(length / speed))
    clip = ClipSpec(media.path, media.kind, 0, duration, speed=speed,
                    volume=0.0 if edit.mute else edit.volume,
                    media_size=(media.width, media.height),
                    color=copy.deepcopy(edit.color), preset=edit.preset,
                    preset_amount=edit.preset_amount, media_length=length)
    kind = "audio" if media.kind == "audio" else "video"
    return TimelineSpec(Canvas(w, h, fps), (TrackSpec(kind, False, False, (clip,)),))


class _Renderer:
    """Images fixes (photos) : source et version avec couleur et filtres, par le moteur."""

    def __init__(self, engine: Engine, media: MediaItem) -> None:
        self.media = media
        self.fps = max(1, round(media.fps or 25))
        self.size = preview_size(media)
        self.length = 1
        self._engine = engine
        self.original = engine.build(self._spec(MediaEdit()))
        self.edited = engine.build(self._spec(MediaEdit()))

    def _spec(self, edit: MediaEdit) -> TimelineSpec:
        return preview_spec(self.media, edit, self.fps, self.length)

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
        timed = media.kind != "image"
        self._renderer = _Renderer(engine_factory(), media) if not timed else None
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
        self.view = Segmented([("edited", _("Modifié")), ("original", _("Original"))],
                              "edited", compact=True)
        self.view.setToolTip(_("Maintenez C pour voir l'original"))
        self.view.changed.connect(lambda _k: self._view_changed())
        top = QHBoxLayout()
        top.addStretch()
        top.addWidget(self.view)
        ll.addLayout(top)
        self.screen = QLabel()
        self.screen.setFixedSize(PANE)
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setStyleSheet("background: #0B120E; border-radius: 10px; color: #FFFFFF;")
        if not visual:
            self.screen.setText(_("Son : pas d'image, la lecture fait entendre le résultat"))
        ll.addWidget(self.screen, 0, Qt.AlignmentFlag.AlignHCenter)
        self._frame_image: QImage | None = None  # dernière image du lecteur

        self.position = QSlider(Qt.Orientation.Horizontal)
        self._fps = max(1, round(media.fps or 25))
        length = max(1, round(media.duration * self._fps)) if timed else 1
        self._length = length
        self.position.setRange(0, max(0, length - 1))
        self.position.valueChanged.connect(self._position_changed)
        self.position.sliderMoved.connect(self._scrubbed)
        self.timecode = label("", "mono")
        self.trim_bar = TrimBar()
        self.trim_bar.seekRequested.connect(
            lambda f: self.position.setValue(round(f * self.position.maximum())))
        transport = QHBoxLayout()
        self.play_button = button("", "primary", "play", tooltip=_("Lecture / pause (Espace)"))
        self.play_button.clicked.connect(self.toggle_play)
        self.loop_button = button(_("Boucle"), "secondary", "repeat",
                                  tooltip=_("Relire la partie gardée en continu"))
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(True)
        bars = QVBoxLayout()
        bars.setSpacing(2)
        bars.addWidget(self.trim_bar)
        bars.addWidget(self.position)
        transport.addWidget(self.play_button)
        transport.addLayout(bars, 1)
        transport.addWidget(self.loop_button)
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
        for w in (self.position, self.set_in, self.set_out, self.trim_label, self.timecode,
                  self.trim_bar, self.play_button, self.loop_button):
            w.setVisible(timed)
        ll.addLayout(transport)
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
        self.player = None
        if timed:  # vidéo ou son : vrai lecteur, avec le son
            from montar.ui.editor.player import Player

            self.player = Player(engine_factory, self)
            self.player.frameReady.connect(self._on_frame)
            self.player.playingChanged.connect(self._on_playing)
            self.player.set_render_size(*preview_size(media))
        for key, action in (("Space", self.toggle_play), ("K", self._pause),
                            ("J", lambda: self._shuttle(-1)), ("L", lambda: self._shuttle(1))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(action)
        self._showing_original = False
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

    # --- lecture ------------------------------------------------------------------

    def _speed(self) -> float:
        return 1.0 if self._showing_original else max(0.1, self.edit.speed)

    def _player_spec(self) -> TimelineSpec:
        edit = MediaEdit() if self._showing_original else self.edit
        return preview_spec(self.media, edit, self._fps, self._length)

    def _position_changed(self, _value: int) -> None:
        self.timecode.setText(frames_to_timecode(self.position.value(), self._fps))
        self._update_trim_bar()
        if self.player is not None and not self.player.playing:
            self._seek_player()
        self._timer.start()

    def _scrubbed(self, value: int) -> None:
        if self.player is not None and self.player.playing:
            self.player.pause()
        self.position.setValue(value)

    def _seek_player(self) -> None:
        if self.player is not None:
            self.player.seek(round(self.position.value() / self._speed()))

    def toggle_play(self) -> None:
        if self.player is None:
            return
        if self.player.playing:
            self.player.pause()
            return
        start, end = self.edit.segment(self.media)
        here = self.position.value() / self._fps
        if self.loop_button.isChecked() and not start <= here < end - 1 / self._fps:
            self.position.setValue(round(start * self._fps))  # repart du début gardé
        self._seek_player()
        self.player.play()

    def _pause(self) -> None:
        if self.player is not None:
            self.player.pause()

    def _shuttle(self, direction: int) -> None:
        if self.player is not None:
            self.player.shuttle(direction)

    def _on_playing(self, playing: bool) -> None:
        set_icon(self.play_button, "pause" if playing else "play")

    def _on_frame(self, image: QImage, frame: int) -> None:
        self._frame_image = image
        media_frame = min(self._length - 1, round(frame * self._speed()))
        if self.player is not None and self.player.playing:
            start, end = self.edit.segment(self.media)
            if self.loop_button.isChecked() and media_frame >= round(end * self._fps) - 1:
                self.position.setValue(round(start * self._fps))  # boucle sur la partie gardée
                self.player.seek(round(self.position.value() / self._speed()))
                return
            self.position.blockSignals(True)
            self.position.setValue(media_frame)
            self.position.blockSignals(False)
            self.timecode.setText(frames_to_timecode(media_frame, self._fps))
            self._update_trim_bar()
        self._show()

    def _update_trim_bar(self) -> None:
        total = max(1e-6, self.media.duration)
        start, end = self.edit.segment(self.media)
        self.trim_bar.set_state((start / total, end / total),
                                self.position.value() / max(1, self._length - 1))

    def _view_changed(self) -> None:
        original = self.view.current() == "original"
        if original == self._showing_original:
            return
        self._showing_original = original
        if self.player is not None:
            playing = self.player.playing
            self.player.load(self._player_spec())
            self._seek_player()
            if playing:
                self.player.play()
        self._timer.start()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.key() == Qt.Key.Key_C and not event.isAutoRepeat():
            self.view.set_current("original")  # maintenir C : l'original
            self._view_changed()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.key() == Qt.Key.Key_C and not event.isAutoRepeat():
            self.view.set_current("edited")
            self._view_changed()
            return
        super().keyReleaseEvent(event)

    def done(self, result: int) -> None:
        if self.player is not None:
            self.player.shutdown()
            self.player = None
        super().done(result)

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
        self._update_trim_bar()
        if self._renderer is not None:
            self._renderer.set_edit(self.edit)
        if self.player is not None and not self._showing_original:
            playing = self.player.playing
            self.player.load(self._player_spec())  # vitesse, son, couleur à jour
            if not playing:
                self._seek_player()
        self._timer.start()

    def _render(self) -> None:
        """Photo : images du moteur ; vidéo : dernière image du lecteur, redessinée."""
        if self._renderer is not None:
            source = self._renderer.original if self._showing_original \
                else self._renderer.edited
            self._frame_image = self._renderer.image(source, 0)
        self._show()

    def _show(self) -> None:
        image = self._frame_image
        if image is None or self.media.kind == "audio":
            return
        if not self._showing_original:
            image = geometry(image, self.edit)
        self.screen.setPixmap(QPixmap.fromImage(image).scaled(
            PANE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _finish(self, mode: str) -> None:
        self.result_mode = mode
        self.accept()

