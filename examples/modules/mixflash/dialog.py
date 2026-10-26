# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre du Mix Flash : clips de la piste, durées, transitions, son, aperçu du mélange."""
from __future__ import annotations

import random

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from montar.core.timecode import seconds_to_short
from montar.i18n import _
from montar.ui.theme import theme
from montar.ui.widgets import Segmented, label

from .core import BURST_MIN, COLORS, FADE_MIN, LIMITS, SOUND, TRANSITIONS, Settings, covers, plan

# une teinte par clip d'origine, dans l'aperçu
SWATCHES = ("#5FA882", "#6FA7C9", "#C79A5B", "#A784C2", "#D07A7A", "#7FB8A4", "#B5B35C")
LIGHT = "#FFF4C2"  # éclat lumineux, dans l'aperçu


class Strip(QWidget):
    """Bande proportionnelle : clips d'origine, ou extraits mélangés avec leurs transitions.

    Chaque bloc : (images, teinte, [(bord "in" / "out", couleur, images), …])."""

    def __init__(self, height: int = 30) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.blocks: list[tuple[int, str, list[tuple[str, str, int]]]] = []

    def set_blocks(self, blocks) -> None:
        self.blocks = list(blocks)
        self.update()

    def paintEvent(self, _event) -> None:
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(p.border)))
        painter.setBrush(QColor(p.field))
        painter.drawRoundedRect(rect, 6, 6)
        total = sum(b[0] for b in self.blocks)
        if not total:
            return
        x = rect.left()
        painter.setPen(Qt.PenStyle.NoPen)
        for frames, swatch, edges in self.blocks:
            w = rect.width() * frames / total
            box = QRectF(x, rect.top(), max(1.0, w - 1), rect.height())
            painter.setBrush(QColor(swatch))
            painter.drawRect(box)
            for edge, color, count in edges:
                if not count or not frames:
                    continue
                width = max(2.0, box.width() * min(0.5, count / frames))
                part = QRectF(box.left() if edge == "in" else box.right() - width,
                              box.top(), width, box.height())
                ramp = QLinearGradient(part.topLeft(), part.topRight())
                solid, clear = QColor(color), QColor(color)
                clear.setAlpha(0)
                ramp.setColorAt(0, solid if edge == "in" else clear)
                ramp.setColorAt(1, clear if edge == "in" else solid)
                painter.setBrush(ramp)
                painter.drawRect(part)
            x += w


def _decimal(seconds: float) -> str:
    return f"{seconds:.1f} s".replace(".", ",")


def _hex(color: str) -> str:
    return "#FFFFFF" if color == "white" else "#000000"


class MixFlashDialog(QDialog):
    def __init__(self, parent, clips, chosen: set[str], fps: int, settings: Settings,
                 remix: bool, names, skipped: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Mix Flash"))
        self.setMinimumWidth(620)
        self._clips, self._fps, self._seed = list(clips), fps, settings.seed
        self._swatch = {c.id: SWATCHES[i % len(SWATCHES)] for i, c in enumerate(self._clips)}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(label(_("Mix Flash"), "h2"))
        intro = label(_("Les vidéos cochées sont découpées en extraits mélangés au hasard. "
                        "Aucune image n'est perdue ; les extraits n'ont pas de son."), "muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        heading = QHBoxLayout()
        heading.addWidget(label(_("Vidéos de la piste") if not remix
                                else _("Vidéos du mélange")))
        heading.addStretch()
        self.whole = QCheckBox(_("Toute la piste"))  # coche ou décoche toutes les vidéos
        self.whole.setEnabled(not remix and len(self._clips) > 1)
        self.whole.clicked.connect(self._whole_clicked)
        heading.addWidget(self.whole)
        layout.addLayout(heading)
        if skipped:
            note = label(_("{n} autre(s) clip(s) de la piste (images, timelapses, extraits déjà "
                           "mélangés…) ne sont pas pris.").format(n=skipped), "small")
            note.setWordWrap(True)
            layout.addWidget(note)
        listing = QWidget()
        rows = QVBoxLayout(listing)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        self.boxes: dict[str, QCheckBox] = {}
        for c in self._clips:
            box = QCheckBox(f"{names(c)}  ·  {seconds_to_short(c.duration / fps)}")
            box.setChecked(c.id in chosen)
            box.setEnabled(not remix)
            box.toggled.connect(self._update)
            self.boxes[c.id] = box
            swatch = QFrame()  # teinte du clip dans l'aperçu
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background: {self._swatch[c.id]}; border-radius: 3px;")
            row = QHBoxLayout()
            row.addWidget(swatch)
            row.addWidget(box, 1)
            rows.addLayout(row)
        rows.addStretch()
        scroll = QScrollArea()  # une longue piste ne rallonge pas la fenêtre
        scroll.setWidget(listing)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(min(180, 30 * len(self._clips) + 6))
        layout.addWidget(scroll)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label(_("Extraits de")), 0, 0)
        self.min_s = self._seconds(settings.min_seconds, *LIMITS)
        grid.addWidget(self.min_s, 0, 1)
        grid.addWidget(label(_("à")), 0, 2)
        self.max_s = self._seconds(settings.max_seconds, *LIMITS)
        grid.addWidget(self.max_s, 0, 3)
        grid.setColumnStretch(4, 1)
        layout.addLayout(grid)

        layout.addWidget(label(_("Entre les extraits")))
        self.transition = Segmented([(k, _(v)) for k, v in TRANSITIONS.items()],
                                    settings.transition)
        self.transition.changed.connect(lambda _k: self._update())
        layout.addWidget(self.transition)
        hint = label(_("Posés par-dessus les images, sans changer la durée. Fondus après les "
                       "extraits d'au moins {f} s, éclats lumineux (l'image s'illumine "
                       "jusqu'au blanc à la coupe, puis retombe) dès {b} s.").format(
            f=f"{FADE_MIN:g}".replace(".", ","), b=f"{BURST_MIN:g}".replace(".", ",")),
            "small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label(_("Fréquence")), 0, 0)
        self.probability = QSlider(Qt.Orientation.Horizontal)
        self.probability.setRange(0, 100)
        self.probability.setSingleStep(5)
        self.probability.setValue(round(settings.probability * 100))
        self.probability.valueChanged.connect(self._update)
        grid.addWidget(self.probability, 0, 1, 1, 3)
        self.probability_text = QLabel()
        self.probability_text.setMinimumWidth(44)
        grid.addWidget(self.probability_text, 0, 4)
        self.fade_label = label(_("Fondu"))
        grid.addWidget(self.fade_label, 1, 0)
        self.color = Segmented([(k, _(v)) for k, v in COLORS.items()], settings.fade_color)
        self.color.changed.connect(lambda _k: self._update())
        grid.addWidget(self.color, 1, 1)
        self.fade = self._seconds(settings.fade_seconds, 0.1, 1.0)
        grid.addWidget(self.fade, 1, 2)
        self.burst_label = label(_("Éclat"))
        grid.addWidget(self.burst_label, 2, 0)
        self.burst = self._seconds(settings.burst_seconds, 0.1, 1.0)
        grid.addWidget(self.burst, 2, 2)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        layout.addWidget(label(_("Son des vidéos")))
        self.sound = Segmented([(k, _(v)) for k, v in SOUND.items()], settings.sound)
        layout.addWidget(self.sound)
        if remix:  # le son a déjà été détaché ou supprimé au premier mélange
            self.sound.setEnabled(False)
        self.no_adjacent = QCheckBox(_("Jamais deux extraits qui se suivaient dans la vidéo "
                                       "d'origine"))
        self.no_adjacent.setChecked(settings.no_adjacent)
        self.no_adjacent.toggled.connect(self._update)
        layout.addWidget(self.no_adjacent)

        layout.addWidget(label(_("Avant")))
        self.before = Strip(18)
        layout.addWidget(self.before)
        layout.addWidget(label(_("Résultat")))
        self.after = Strip(36)
        layout.addWidget(self.after)
        info = QFrame()
        info.setObjectName("InfoBox")
        il = QHBoxLayout(info)
        il.setContentsMargins(14, 10, 14, 10)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        il.addWidget(self.summary)
        layout.addWidget(info)

        footer = QHBoxLayout()
        shuffle = QPushButton(_("Remélanger"))
        shuffle.setProperty("variant", "tonal")
        shuffle.setMinimumHeight(40)
        shuffle.clicked.connect(self._reshuffle)
        footer.addWidget(shuffle)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok.setText(_("Appliquer"))
        self.ok.setProperty("variant", "primary")
        cancel.setText(_("Annuler"))
        for b in (self.ok, cancel):
            b.setIcon(QIcon())
            b.setMinimumHeight(40)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self._update()

    def _seconds(self, value: float, low: float, high: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(1)
        box.setSingleStep(0.1)
        box.setSuffix(" s")
        box.setValue(value)
        box.valueChanged.connect(self._update)
        return box

    def _whole_clicked(self, checked: bool) -> None:
        for box in self.boxes.values():
            box.blockSignals(True)
            box.setChecked(checked)
            box.blockSignals(False)
        self._update()

    def _reshuffle(self) -> None:
        self._seed = random.randint(1, 999_999)
        self._update()

    # --- résultat -------------------------------------------------------------------------

    def chosen_ids(self) -> list[str]:
        return [c.id for c in self._clips if self.boxes[c.id].isChecked()]

    def settings(self) -> Settings:
        low = self.min_s.value()
        return Settings.from_dict({
            "min_seconds": low, "max_seconds": max(low, self.max_s.value()),
            "transition": self.transition.current(), "fade_color": self.color.current(),
            "probability": self.probability.value() / 100, "fade_seconds": self.fade.value(),
            "burst_seconds": self.burst.value(),
            "sound": self.sound.current(), "no_adjacent": self.no_adjacent.isChecked(),
            "seed": self._seed})

    def _update(self, *_args) -> None:
        if self.max_s.value() < self.min_s.value():
            self.max_s.blockSignals(True)
            self.max_s.setValue(self.min_s.value())
            self.max_s.blockSignals(False)
        self.probability_text.setText(f"{self.probability.value()} %")
        kind = self.transition.current()
        for widget in (self.probability, self.probability_text):
            widget.setEnabled(kind != "none")
        for widget in (self.fade_label, self.color, self.fade):
            widget.setEnabled(kind in ("fade", "mix"))
        for widget in (self.burst_label, self.burst):
            widget.setEnabled(kind in ("burst", "mix"))
        chosen = [c for c in self._clips if self.boxes[c.id].isChecked()]
        self.whole.blockSignals(True)
        self.whole.setChecked(len(chosen) == len(self._clips))
        self.whole.blockSignals(False)
        self.ok.setEnabled(bool(chosen))
        if not chosen:
            self.before.set_blocks([])
            self.after.set_blocks([])
            self.summary.setText(_("Cochez au moins une vidéo."))
            return
        settings = self.settings()
        lengths = [c.duration for c in chosen]
        items = plan(lengths, self._fps, settings)
        self.before.set_blocks((c.duration, self._swatch[c.id], []) for c in chosen)
        self.after.set_blocks(
            (i.length, self._swatch[chosen[i.piece.source].id],
             [("in", _hex(i.fade_in_color), i.fade_in), ("out", _hex(i.color), i.fade_out),
              ("in", LIGHT, i.burst_in), ("out", LIGHT, i.burst_out)]) for i in items)
        fades = sum(1 for i in items if i.after == "fade")
        bursts = sum(1 for i in items if i.after == "burst")
        shortest = min(i.length for i in items) / self._fps
        longest = max(i.length for i in items) / self._fps
        total = sum(lengths)
        ok = covers(lengths, items)
        self.summary.setText(_(
            "{n} extraits de {a} à {b} · {f} fondus · {e} éclats · durée {d}\n{check}").format(
            n=len(items), a=_decimal(shortest), b=_decimal(longest), f=fades, e=bursts,
            d=seconds_to_short(total / self._fps),
            check=(_("✓ {t} images sur {t} replacées, sans trou ni doublon").format(t=total)
                   if ok else _("Découpage incomplet : impossible d'appliquer"))))
        self.ok.setEnabled(ok)
