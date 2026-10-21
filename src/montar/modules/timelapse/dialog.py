# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogue de réglage du timelapse (cahier des charges §3.9.2)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from montar.core.timecode import seconds_to_short
from montar.i18n import _
from montar.ui.widgets import Segmented, label

from .core import (
    AUDIO,
    MAX_FACTOR,
    METHODS,
    MIN_FACTOR,
    PRESETS,
    RAMPS,
    Settings,
    factor_for_duration,
    output_frames,
)


class TimelapseDialog(QDialog):
    def __init__(self, parent, source_frames: int, fps: int, settings: Settings,
                 whole_clip: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Timelapse"))
        self.setMinimumWidth(520)
        self._source_frames, self._fps = source_frames, fps
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(label(_("Timelapse"), "h2"))
        scope = (_("Tout le clip") if whole_clip
                 else _("Plage marquée dans la timeline (touches I et O)"))
        layout.addWidget(label(_("Partie accélérée : {scope} · {d}").format(
            scope=scope, d=seconds_to_short(source_frames / fps)), "muted"))
        layout.addSpacing(6)

        self.mode = Segmented([("factor", _("Facteur")), ("duration", _("Durée cible"))])
        self.mode.changed.connect(self._mode_changed)
        layout.addWidget(self.mode)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label(_("Facteur")), 0, 0)
        self.factor = QDoubleSpinBox()
        self.factor.setRange(MIN_FACTOR, MAX_FACTOR)
        self.factor.setDecimals(1)
        self.factor.setPrefix("×")
        self.factor.setValue(settings.factor)
        self.factor.valueChanged.connect(self._update)
        grid.addWidget(self.factor, 0, 1)
        presets = QHBoxLayout()
        group = QButtonGroup(self)
        for value in PRESETS:
            b = QPushButton(f"×{value}")
            b.setProperty("variant", "chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self.factor.setValue(v))
            group.addButton(b)
            presets.addWidget(b)
        grid.addLayout(presets, 1, 1)
        grid.addWidget(label(_("Durée cible")), 2, 0)
        self.target = QDoubleSpinBox()
        self.target.setRange(0.1, max(0.2, source_frames / fps / MIN_FACTOR))
        self.target.setSuffix(" s")
        self.target.setDecimals(1)
        self.target.setValue(source_frames / fps / settings.factor)
        self.target.valueChanged.connect(self._target_changed)
        grid.addWidget(self.target, 2, 1)
        layout.addLayout(grid)

        layout.addWidget(label(_("Méthode")))
        self.method = Segmented([(k, _(v)) for k, v in METHODS.items()], settings.method)
        self.method.changed.connect(lambda _k: self._update())
        layout.addWidget(self.method)
        hint = label(_("Échantillonnage : une image sur N, rendu net et saccadé. Fusion : "
                       "moyenne d'images réparties sur chaque intervalle, rendu fluide avec "
                       "traînées de mouvement."), "small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(label(_("Rampe de vitesse")))
        self.ramp = Segmented([(k, _(v)) for k, v in RAMPS.items()], settings.ramp)
        self.ramp.changed.connect(lambda _k: self._update())
        layout.addWidget(self.ramp)
        row = QHBoxLayout()
        row.addWidget(label(_("Durée de la rampe")))
        self.ramp_seconds = QDoubleSpinBox()
        self.ramp_seconds.setRange(0.0, 3.0)
        self.ramp_seconds.setSingleStep(0.5)
        self.ramp_seconds.setSuffix(" s")
        self.ramp_seconds.setValue(settings.ramp_seconds)
        self.ramp_seconds.valueChanged.connect(self._update)
        row.addWidget(self.ramp_seconds)
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(label(_("Son du segment")))
        self.audio = Segmented([(k, _(v)) for k, v in AUDIO.items()], settings.audio)
        layout.addWidget(self.audio)
        self.deflicker = QCheckBox(_("Stabiliser l'exposition (réduit le scintillement)"))
        self.deflicker.setChecked(settings.deflicker)
        layout.addWidget(self.deflicker)

        info = QFrame()
        info.setObjectName("InfoBox")
        il = QHBoxLayout(info)
        il.setContentsMargins(14, 10, 14, 10)
        self.summary = QLabel()
        il.addWidget(self.summary)
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok.setText(_("Appliquer"))
        ok.setProperty("variant", "primary")
        cancel.setText(_("Annuler"))
        for b in (ok, cancel):
            b.setIcon(QIcon())
            b.setMinimumHeight(40)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._mode_changed("factor")

    def _mode_changed(self, mode: str) -> None:
        self.factor.setEnabled(mode == "factor")
        self.target.setEnabled(mode == "duration")
        self._update()

    def _target_changed(self, seconds: float) -> None:
        if self.mode.current() == "duration":
            self.factor.blockSignals(True)
            self.factor.setValue(factor_for_duration(self._source_frames,
                                                     round(seconds * self._fps)))
            self.factor.blockSignals(False)
            self._update()

    def settings(self) -> Settings:
        return Settings.from_dict({
            "factor": self.factor.value(), "method": self.method.current(),
            "ramp": self.ramp.current(), "ramp_seconds": self.ramp_seconds.value(),
            "audio": self.audio.current(), "deflicker": self.deflicker.isChecked()})

    def _update(self) -> None:
        blend = self.method.current() == "blend"
        for w in (self.ramp, self.ramp_seconds):
            w.setEnabled(not blend)
            w.setToolTip(_("Les rampes ne sont possibles qu'en échantillonnage") if blend
                         else "")
        produced = output_frames(self._source_frames, self.settings(), self._fps)
        if self.mode.current() == "factor":
            self.target.blockSignals(True)
            self.target.setValue(produced / self._fps)
            self.target.blockSignals(False)
        self.summary.setText(_("{src} → {dst} ({n} images)").format(
            src=seconds_to_short(self._source_frames / self._fps),
            dst=f"{produced / self._fps:.1f} s", n=produced))
