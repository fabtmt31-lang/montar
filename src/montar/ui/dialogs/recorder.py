# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran : réglages, puis petite fenêtre flottante pendant l'enregistrement."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.media.recorder import RecordOptions, can_pick_window, webcams
from montar.ui.widgets import Segmented, button, label

COUNTDOWN = 3


class RecorderDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Enregistrer l'écran"))
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.addWidget(label(_("Enregistrer l'écran"), "h2"))
        hint = label(_("L'enregistrement est ajouté aux médias du projet. montar se réduit "
                       "pendant l'enregistrement ; une petite fenêtre permet de l'arrêter."),
                     "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(6)

        layout.addWidget(label(_("Que filmer ?")))
        sources = [("screen", _("Écran")), ("region", _("Zone"))]
        if can_pick_window():
            sources.append(("window", _("Fenêtre")))
        self.source = Segmented(sources, "screen")
        self.source.changed.connect(self._source_changed)
        layout.addWidget(self.source)
        self.screen = QComboBox()
        for i, screen in enumerate(QGuiApplication.screens()):
            g = screen.geometry()
            self.screen.addItem(f"{screen.name() or _('Écran')} {i + 1} · {g.width()} × "
                                f"{g.height()}", i)
        layout.addWidget(self.screen)
        self.source_hint = label("", "small")
        self.source_hint.setWordWrap(True)
        layout.addWidget(self.source_hint)
        layout.addSpacing(6)

        layout.addWidget(label(_("Son")))
        self.microphone = QCheckBox(_("Micro"))
        self.microphone.setChecked(True)
        self.system_audio = QCheckBox(_("Son de l'ordinateur"))
        layout.addWidget(self.microphone)
        layout.addWidget(self.system_audio)
        layout.addSpacing(6)
        layout.addWidget(label(_("Webcam (en incrustation, en bas à droite)")))
        self.webcam = QComboBox()
        self.webcam.addItem(_("Aucune"), "")
        for device in webcams():
            self.webcam.addItem(device, device)
        layout.addWidget(self.webcam)
        layout.addSpacing(12)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        start = button(_("Démarrer l'enregistrement"), "primary", "circle-dot")
        start.clicked.connect(self.accept)
        for b in (cancel, start):
            b.setMinimumHeight(42)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._source_changed("screen")

    def _source_changed(self, key: str) -> None:
        self.screen.setVisible(key == "screen")
        self.source_hint.setText({
            "screen": "",
            "region": _("Après le compte à rebours, dessinez la zone à filmer avec la souris."),
            "window": _("Après le compte à rebours, cliquez sur la fenêtre à filmer."),
        }[key])

    def options(self) -> RecordOptions:
        screens = QGuiApplication.screens()
        screen = screens[self.screen.currentData() or 0] if screens else None
        geometry = (0, 0, 1920, 1080)
        if screen is not None:
            g = screen.geometry()
            ratio = screen.devicePixelRatio()
            geometry = (round(g.x() * ratio), round(g.y() * ratio),
                        round(g.width() * ratio), round(g.height() * ratio))
        return RecordOptions(self.source.current(), geometry,
                             microphone=self.microphone.isChecked(),
                             system_audio=self.system_audio.isChecked(),
                             webcam=self.webcam.currentData() or "")


class RecordingBar(QFrame):
    """Fenêtre flottante, toujours au premier plan : compte à rebours, durée, Arrêter."""

    stopRequested = pyqtSignal()
    countdownFinished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("BusyCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 10, 10)
        layout.setSpacing(12)
        self.dot = label("●")
        self.dot.setStyleSheet("color: #D33A2C; font-size: 18px;")
        self.time = label("", "h3")
        self.stop_button = button(_("Arrêter"), "primary", "x")
        self.stop_button.clicked.connect(self.stopRequested)
        layout.addWidget(self.dot)
        layout.addWidget(self.time)
        layout.addWidget(self.stop_button)
        self._left = COUNTDOWN
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start_countdown(self, seconds: int = COUNTDOWN) -> None:
        self._left = seconds
        self.time.setText(_("Début dans {n} s").format(n=seconds))
        screen = QGuiApplication.primaryScreen()
        self.adjustSize()
        if screen is not None:
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.bottom() - self.height() - 40)
        self.show()
        if seconds <= 0:
            self.countdownFinished.emit()
        else:
            self._timer.start()

    def _tick(self) -> None:
        self._left -= 1
        if self._left > 0:
            self.time.setText(_("Début dans {n} s").format(n=self._left))
        else:
            self._timer.stop()
            self.countdownFinished.emit()

    def set_elapsed(self, seconds: float) -> None:
        s = int(seconds)
        self.time.setText(f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}")
