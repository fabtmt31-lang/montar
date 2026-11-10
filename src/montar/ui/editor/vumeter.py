# SPDX-License-Identifier: GPL-3.0-or-later
"""Vu-mètre de l'aperçu : deux barres (gauche, droite) du son mixé pendant la lecture.

Échelle IEC 60268-18 (0 à 1) : vert jusqu'à −10 dB, or jusqu'à −4 dB, orange au-delà.
Un clic replie le vu-mètre en un mince trait ; un autre clic le rouvre."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from montar.i18n import _
from montar.ui.theme import theme

GREEN, GOLD, ORANGE = "#3FA66B", "#D4A23A", "#E07A2E"
GOLD_FROM, ORANGE_FROM = 0.75, 0.90  # −10 dB, −4 dB sur l'échelle IEC
WIDE, FOLDED = 22, 6
DECAY = 0.82  # retombée des barres à chaque rafraîchissement sans nouveau niveau
HOLD_FRAMES = 30  # crête maintenue ~1 s avant de redescendre


class VuMeter(QWidget):
    toggled = pyqtSignal(bool)  # True : déplié

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.levels = [0.0, 0.0]  # affichés (lissés)
        self.peaks = [0.0, 0.0]
        self._hold = [0, 0]
        self._target = [0.0, 0.0]  # derniers niveaux reçus
        self.expanded = True
        self.setFixedWidth(WIDE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_tooltip()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)

    def set_levels(self, left: float, right: float) -> None:
        self._target = [max(0.0, min(1.0, left)), max(0.0, min(1.0, right))]
        if not self._timer.isActive():
            self._timer.start()

    def set_expanded(self, on: bool) -> None:
        self.expanded = on
        self.setFixedWidth(WIDE if on else FOLDED)
        self._update_tooltip()
        self.update()
        self.toggled.emit(on)

    def _update_tooltip(self) -> None:
        self.setToolTip(_("Vu-mètre (gauche, droite) — cliquer pour le replier") if self.expanded
                        else _("Afficher le vu-mètre"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_expanded(not self.expanded)

    def _step(self) -> None:
        moving = False
        for i in range(2):
            target = self._target[i]
            # montée immédiate, descente progressive
            self.levels[i] = target if target >= self.levels[i] else max(
                target, self.levels[i] * DECAY)
            if self.levels[i] >= self.peaks[i]:
                self.peaks[i], self._hold[i] = self.levels[i], HOLD_FRAMES
            elif self._hold[i] > 0:
                self._hold[i] -= 1
            else:
                self.peaks[i] = max(self.levels[i], self.peaks[i] - 0.02)
            moving = moving or self.levels[i] > 0.005 or self.peaks[i] > 0.005
        self._target = [t * DECAY for t in self._target]  # sans nouvelle mesure : silence
        if not moving:
            self.levels, self.peaks = [0.0, 0.0], [0.0, 0.0]
            self._timer.stop()
        if self.expanded:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        if not self.expanded:
            back = QColor(p.text_muted)
            back.setAlpha(70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(back)
            painter.drawRoundedRect(QRectF(2, 0, 2, h), 1, 1)
            return
        bar_w, gap = 7.0, 4.0
        x0 = (self.width() - 2 * bar_w - gap) / 2
        back = QColor(p.text_muted)
        back.setAlpha(40)
        for i in range(2):
            x = x0 + i * (bar_w + gap)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(back)
            painter.drawRoundedRect(QRectF(x, 0, bar_w, h), 2, 2)
            level = self.levels[i]
            for low, high, color in ((0.0, GOLD_FROM, GREEN), (GOLD_FROM, ORANGE_FROM, GOLD),
                                     (ORANGE_FROM, 1.0, ORANGE)):
                top = min(level, high)
                if top <= low:
                    break
                painter.setBrush(QColor(color))
                painter.drawRect(QRectF(x, h * (1 - top), bar_w, h * (top - low)))
            peak = self.peaks[i]
            if peak > 0.01:
                color = ORANGE if peak >= ORANGE_FROM else GOLD if peak >= GOLD_FROM else GREEN
                painter.setBrush(QColor(color))
                painter.drawRect(QRectF(x, h * (1 - peak), bar_w, 2))
