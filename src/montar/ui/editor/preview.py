# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau d'aperçu : image, curseur de position, commandes de lecture."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QKeySequence, QPainter, QPainterPath, QShortcut
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QSlider, QVBoxLayout, QWidget

from montar.core.settings import PREVIEW_QUALITIES
from montar.core.timecode import frames_to_timecode
from montar.i18n import _
from montar.ui.editor.player import Player
from montar.ui.theme import theme
from montar.ui.widgets import button, label, set_icon

QUALITY_LABELS = {"low": "Basse", "medium": "Moyenne", "full": "Pleine"}


class PreviewCanvas(QWidget):
    """Affiche l'image courante centrée, au format de la toile du projet."""

    resized = pyqtSignal(QSize)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 180)
        self._image: QImage | None = None
        self.canvas_size = (1920, 1080)  # taille de la toile du projet
        self._message = ""
        theme().changed.connect(self.update)

    def set_canvas(self, width: int, height: int) -> None:
        self.canvas_size = (width, height)
        self.update()

    def set_image(self, image: QImage | None) -> None:
        self._image = image
        self._message = ""
        self.update()

    def set_message(self, text: str) -> None:
        self._image = None
        self._message = text
        self.update()

    def frame_rect(self) -> QRectF:
        cw, ch = self.canvas_size
        scale = min(self.width() / cw, self.height() / ch)
        w, h = cw * scale, ch * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.frame_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor("#0B120E") if self._image is not None else QColor(p.mint))
        if self._image is not None:
            painter.drawImage(rect, self._image)
        elif self._message:
            painter.setPen(QColor(p.forest))
            painter.drawText(rect.adjusted(20, 20, -20, -20),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self._message)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit(self.size())


class PreviewPanel(QFrame):
    def __init__(self, player: Player, quality: str = "medium") -> None:
        super().__init__()
        self.setObjectName("PreviewArea")
        self.player = player
        self.quality = quality
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label(_("Aperçu"), "muted"))
        head.addStretch()
        self.quality_button = button("", "secondary")
        self.quality_button.setStyleSheet("padding: 5px 10px; font-weight: 500;")
        menu = QMenu(self.quality_button)
        for key, text in QUALITY_LABELS.items():
            menu.addAction(_(text), lambda k=key: self.set_quality(k))
        self.quality_button.setMenu(menu)
        head.addWidget(self.quality_button)
        layout.addLayout(head)

        frame = QFrame()
        frame.setObjectName("PreviewFrame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(16, 16, 16, 16)
        self.canvas = PreviewCanvas()
        self.canvas.set_message(_("Sélectionnez un média pour l'afficher ici"))
        fl.addWidget(self.canvas)
        layout.addWidget(frame, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._slider_moved)
        layout.addWidget(self.slider)

        transport = QHBoxLayout()
        self.timecode = label("00:00:00:00", "mono")
        self.timecode.setStyleSheet("font-size: 15px; font-weight: 500;")
        self.duration = label("/  00:00:00:00", "mono")
        self.duration.setProperty("role", "mono")
        self.duration.setStyleSheet("font-size: 14px;")
        transport.addWidget(self.timecode)
        transport.addSpacing(8)
        transport.addWidget(self.duration)
        transport.addStretch()
        self.to_start = button("", "ghost", "skip-back", tooltip=_("Aller au début (Origine)"))
        self.play_button = button("", "round", "play", tooltip=_("Lecture / pause (Espace)"))
        self.to_end = button("", "ghost", "skip-forward", tooltip=_("Aller à la fin (Fin)"))
        self.to_start.clicked.connect(lambda: self.player.seek(0))
        self.to_end.clicked.connect(lambda: self.player.seek(self.player.length - 1))
        self.play_button.clicked.connect(self.player.toggle)
        for b in (self.to_start, self.play_button, self.to_end):
            transport.addWidget(b)
        transport.addStretch()
        transport.addSpacing(self.timecode.sizeHint().width() + self.duration.sizeHint().width())
        layout.addLayout(transport)
        self._set_controls_enabled(False)

        self._fps = 25.0
        self._updating_slider = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._push_render_size)
        self.canvas.resized.connect(lambda _s: self._resize_timer.start())

        player.frameReady.connect(self._on_frame)
        player.opened.connect(self._on_opened)
        player.failed.connect(self._on_failed)
        player.playingChanged.connect(self._on_playing)
        self.set_quality(quality)

        for key, slot in (
            (Qt.Key.Key_Space, self.player.toggle),
            (Qt.Key.Key_Home, lambda: self.player.seek(0)),
            (Qt.Key.Key_End, lambda: self.player.seek(self.player.length - 1)),
            (Qt.Key.Key_Left, lambda: self.step(-1)),
            (Qt.Key.Key_Right, lambda: self.step(1)),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

    def set_canvas(self, width: int, height: int) -> None:
        self.canvas.set_canvas(width, height)
        self._push_render_size()

    def set_quality(self, key: str) -> None:
        self.quality = key
        self.quality_button.setText(_("Qualité : {q}").format(q=_(QUALITY_LABELS[key]).lower()))
        self._push_render_size()

    def step(self, delta: int) -> None:
        if self.player.length:
            self.player.pause()
            self.player.seek(max(0, min(self.player.length - 1, self.player.position + delta)))

    def clear(self, message: str) -> None:
        self.player.close()
        self.canvas.set_message(message)
        self._set_controls_enabled(False)
        self.timecode.setText(frames_to_timecode(0, self._fps))
        self.duration.setText("/  " + frames_to_timecode(0, self._fps))

    def _push_render_size(self) -> None:
        # Qualité = fraction de la résolution de la toile, sans dépasser la taille affichée.
        rect = self.canvas.frame_rect()
        cw, ch = self.canvas.canvas_size
        factor = PREVIEW_QUALITIES[self.quality]
        dpr = self.devicePixelRatioF()
        scale = min(factor, rect.width() * dpr / cw, rect.height() * dpr / ch)
        self.player.set_render_size(int(cw * scale), int(ch * scale))

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self.slider, self.to_start, self.play_button, self.to_end):
            w.setEnabled(enabled)

    def _slider_moved(self, value: int) -> None:
        if not self._updating_slider:
            self.player.seek(value)

    def _on_opened(self, length: int, fps: float) -> None:
        self._fps = fps
        self._updating_slider = True
        self.slider.setRange(0, max(0, length - 1))
        self.slider.setValue(0)
        self._updating_slider = False
        self.duration.setText("/  " + frames_to_timecode(length, fps))
        self._set_controls_enabled(True)
        self._push_render_size()

    def _on_frame(self, image: QImage, frame: int) -> None:
        self.canvas.set_image(image)
        self.timecode.setText(frames_to_timecode(frame, self._fps))
        self._updating_slider = True
        self.slider.setValue(frame)
        self._updating_slider = False

    def _on_failed(self, message: str) -> None:
        self.canvas.set_message(_("Aperçu impossible : {error}").format(error=message))
        self._set_controls_enabled(False)

    def _on_playing(self, playing: bool) -> None:
        set_icon(self.play_button, "pause" if playing else "play", "on_forest", 20)
