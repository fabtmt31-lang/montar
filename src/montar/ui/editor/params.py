# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôles générés à partir des paramètres des modules (`montar.api.Param`)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.ui.editor.controls import SliderRow
from montar.ui.widgets import label


class ColorButton(QWidget):
    """Libellé et pastille de couleur ; un clic ouvre le choix de couleur."""

    def __init__(self, title: str, changed: Callable[[str], None]) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(label(title))
        layout.addStretch()
        self.swatch = QPushButton()
        self.swatch.setFixedSize(44, 28)
        self.swatch.clicked.connect(self._pick)
        layout.addWidget(self.swatch)
        self._changed = changed
        self.value = "#FFFFFF"

    def set_value(self, color: str) -> None:
        self.value = color
        self.swatch.setStyleSheet(f"QPushButton {{ background: {color}; border-radius: 8px;"
                                  " border: 1px solid #9CCBB0; padding: 0; }")

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(self.value), self)
        if color.isValid():
            self.set_value(color.name().upper())
            self._changed(self.value)


class ParamControl:
    """Un contrôle par paramètre ; `on_change(valeur, fusion)` reçoit chaque modification
    (fusion : réglage continu, regroupé dans l'historique)."""

    def __init__(self, param, on_change: Callable[[Any, bool], None]) -> None:
        self.param = param
        kind = param.kind
        if kind == "bool":
            w = QCheckBox(_(param.label))
            w.toggled.connect(lambda on: on_change(bool(on), False))
        elif kind == "choice":
            combo = QComboBox()
            for value, text in param.choices:
                combo.addItem(_(text), value)
            combo.currentIndexChanged.connect(lambda _i: on_change(combo.currentData(), False))
            w = QWidget()
            layout = QVBoxLayout(w)
            layout.setContentsMargins(0, 4, 0, 4)
            layout.setSpacing(4)
            layout.addWidget(label(_(param.label)))
            layout.addWidget(combo)
            self.combo = combo
        elif kind == "color":
            w = ColorButton(_(param.label), lambda c: on_change(c, False))
        else:
            unit = f" {param.unit}" if param.unit else ""
            decimals = 0 if kind == "int" or abs(param.maximum) >= 20 else 2
            w = SliderRow(_(param.label), param.minimum, param.maximum,
                          lambda v, d=decimals, u=unit: f"{v:.{d}f}{u}")
            w.moved.connect(lambda v: on_change(round(v) if kind == "int" else round(v, 4),
                                                True))
        self.widget = w

    def set_value(self, value: Any) -> None:
        w, kind = self.widget, self.param.kind
        w.blockSignals(True)
        if kind == "bool":
            w.setChecked(bool(value))
        elif kind == "choice":
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(max(0, self.combo.findData(value)))
            self.combo.blockSignals(False)
        elif kind == "color":
            w.set_value(str(value))
        else:
            w.set_value(float(value))
        w.blockSignals(False)
