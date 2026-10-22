# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistrement d'une voix off pendant la lecture de la timeline (F-TL-03)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from montar.core.timecode import frames_to_timecode
from montar.i18n import _
from montar.media.voiceover import VoiceRecorder, microphones
from montar.ui.dialogs.recorder import COUNTDOWN
from montar.ui.widgets import button, label

POLL_MS = 20


class VoiceOverDialog(QDialog):
    """Réglages, compte à rebours, puis enregistrement : la lecture de la timeline démarre
    dès que le micro fournit du son, pour que la voix tombe au bon endroit.

    `recorded(chemin, secondes à retirer au début)` est émis quand l'enregistrement réussit."""

    recorded = pyqtSignal(str, float)
    failed = pyqtSignal(str)

    def __init__(self, player, start: int, fps: float, target: Path,
                 parent: QWidget | None = None, countdown: int = COUNTDOWN) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Voix off"))
        self.setModal(True)
        self.setMinimumWidth(480)
        self.player, self.start, self.fps, self.target = player, start, fps, target
        self._countdown = countdown
        self._recorder: VoiceRecorder | None = None
        self._lead: float | None = None  # son capté avant le début de la lecture
        self._volume = player.volume
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.addWidget(label(_("Enregistrer une voix off"), "h2"))
        hint = label(_("La timeline est lue pendant que vous parlez ; l'enregistrement est "
                       "placé sur une piste « Voix off » à partir de {tc}.").format(
                           tc=frames_to_timecode(start, fps)), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(6)
        layout.addWidget(label(_("Micro")))
        self.microphone = QComboBox()
        for device, text in microphones():
            self.microphone.addItem(_(text), device)
        layout.addWidget(self.microphone)
        self.listen = QCheckBox(_("Écouter le montage pendant l'enregistrement (casque conseillé)"))
        self.listen.setChecked(True)
        layout.addWidget(self.listen)
        layout.addSpacing(8)
        self.status = label("", "h3")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = button(_("Annuler"), "secondary")
        self.cancel_button.clicked.connect(self.reject)
        self.record_button = button(_("Enregistrer"), "primary", "mic")
        self.record_button.clicked.connect(self._record_clicked)
        for b in (self.cancel_button, self.record_button):
            b.setMinimumHeight(42)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._left = 0

    @property
    def recording(self) -> bool:
        return self._recorder is not None

    def _record_clicked(self) -> None:
        if self._recorder is not None:
            self.stop()
        elif not self._timer.isActive():
            self.microphone.setEnabled(False)
            self.listen.setEnabled(False)
            self.player.pause()
            self.player.seek(self.start)
            self._left = self._countdown
            self.record_button.setEnabled(False)
            self._timer.start(1000)
            self._tick()

    def _tick(self) -> None:
        if self._recorder is None:  # compte à rebours
            if self._left > 0:
                self.status.setText(_("Début dans {n} s…").format(n=self._left))
                self._left -= 1
                return
            self._begin()
            return
        if self._lead is None:
            if self._recorder.captured() > 0:
                self._lead = self._recorder.captured()
                if not self.listen.isChecked():
                    self.player.set_volume(0.0)
                self.player.play()
            elif not self._recorder.running:
                self.stop()
            return
        if not self._recorder.running:
            self.stop()
            return
        s = int(self._recorder.elapsed)
        self.status.setText("● " + f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}")

    def _begin(self) -> None:
        self._recorder = VoiceRecorder(self.microphone.currentData() or "default", self.target)
        try:
            self._recorder.start()
        except OSError as exc:
            self._recorder = None
            self._timer.stop()
            self.failed.emit(str(exc))
            self.reject()
            return
        self.status.setText("● 00:00:00")
        self.record_button.setText(_("Arrêter"))
        self.record_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._timer.start(POLL_MS)

    def stop(self) -> None:
        recorder, self._recorder = self._recorder, None
        self._timer.stop()
        self.player.pause()
        self.player.set_volume(self._volume)
        if recorder is None:
            return
        if recorder.stop() and self._lead is not None:
            self.recorded.emit(str(recorder.target), self._lead)
            self.accept()
        else:
            recorder.target.unlink(missing_ok=True)
            self.failed.emit(recorder.error or _("aucun son reçu du micro"))
            self.reject()

    def reject(self) -> None:
        if self._recorder is not None:  # fermeture pendant l'enregistrement : on garde
            self.stop()
            return
        self._timer.stop()
        super().reject()
