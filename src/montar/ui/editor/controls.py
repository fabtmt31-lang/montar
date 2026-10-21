# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôles de l'inspecteur : curseurs avec valeur, pastilles de couleur, onglets."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from montar.ui.widgets import Segmented, label

_STEPS = 1000


class SliderRow(QWidget):
    """Libellé, valeur affichée et curseur ; `moved` émet la valeur réelle (float)."""

    moved = pyqtSignal(float)

    def __init__(self, title: str, minimum: float, maximum: float,
                 fmt: Callable[[float], str] = lambda v: f"{v:.0f}",
                 to_slider: Callable[[float], float] | None = None,
                 from_slider: Callable[[float], float] | None = None) -> None:
        super().__init__()
        self._min, self._max, self._fmt = minimum, maximum, fmt
        # transformations facultatives (échelle logarithmique pour la vitesse, par exemple)
        self._to = to_slider or (lambda v: v)
        self._from = from_slider or (lambda v: v)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(label(title))
        head.addStretch()
        self.value_label = label("", "mono")
        self.value_label.setStyleSheet("font-size: 12px;")
        head.addWidget(self.value_label)
        layout.addLayout(head)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, _STEPS)
        self.slider.valueChanged.connect(self._changed)
        layout.addWidget(self.slider)
        self._value = minimum

    def _ratio(self, value: float) -> float:
        low, high = self._to(self._min), self._to(self._max)
        return (self._to(value) - low) / (high - low) if high != low else 0.0

    def _changed(self, position: int) -> None:
        low, high = self._to(self._min), self._to(self._max)
        value = self._from(low + (high - low) * position / _STEPS)
        self._value = max(self._min, min(self._max, value))
        self.value_label.setText(self._fmt(self._value))
        if not self.slider.signalsBlocked():
            self.moved.emit(self._value)

    def set_value(self, value: float) -> None:
        self._value = value
        self.slider.blockSignals(True)
        self.slider.setValue(round(max(0.0, min(1.0, self._ratio(value))) * _STEPS))
        self.slider.blockSignals(False)
        self.value_label.setText(self._fmt(value))

    def value(self) -> float:
        return self._value


class ColorSwatches(QWidget):
    """Pastilles de couleur de la charte + couleur personnalisée."""

    picked = pyqtSignal(str)

    def __init__(self, colors: Sequence[str], allow_none: bool = False) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}
        if allow_none:
            none = self._swatch("", "Aucun")
            layout.addWidget(none)
        for c in colors:
            layout.addWidget(self._swatch(c, c))
        custom = QPushButton("+")
        custom.setFixedSize(30, 30)
        custom.setToolTip("Couleur personnalisée")
        custom.setStyleSheet("QPushButton { border-radius: 15px; border: 1.5px dashed #9CCBB0;"
                             " padding: 0; font-weight: 700; }")
        custom.clicked.connect(self._custom)
        layout.addWidget(custom)
        layout.addStretch()
        self._current = ""

    def _swatch(self, color: str, tooltip: str) -> QPushButton:
        b = QPushButton()
        b.setFixedSize(30, 30)
        b.setCheckable(True)
        b.setToolTip(tooltip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        fill = color or "transparent"
        extra = "" if color else "background-image: none;"
        b.setStyleSheet(
            f"QPushButton {{ background: {fill}; border-radius: 15px; padding: 0;"
            f" border: 1px solid #9CCBB0; {extra} }}"
            "QPushButton:checked { border: 3px solid #2F7A56; }")
        if not color:
            b.setText("∅")
        b.clicked.connect(lambda _=False, c=color: self.picked.emit(c))
        self._buttons[color.upper()] = b
        return b

    def _custom(self) -> None:
        start = QColor(self._current) if self._current else QColor("#FFFFFF")
        color = QColorDialog.getColor(start, self, options=QColorDialog.ColorDialogOption
                                      .ShowAlphaChannel)
        if color.isValid():
            self.picked.emit(color.name(QColor.NameFormat.HexArgb if color.alpha() < 255
                                        else QColor.NameFormat.HexRgb).upper())

    def set_current(self, color: str) -> None:
        self._current = color
        for key, b in self._buttons.items():
            b.setChecked(key == color.upper())


class Tabs(QWidget):
    """Onglets segmentés (maquettes 02 et 03) au-dessus d'une pile de pages."""

    def __init__(self, pages: Sequence[tuple[str, str, QWidget]]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.bar = Segmented([(key, text) for key, text, _w in pages])
        self.bar.setProperty("compact", True)
        layout.addWidget(self.bar)
        self.stack = QStackedWidget()
        self._index = {}
        for key, _text, widget in pages:
            if widget.layout() is not None:
                widget.layout().addStretch(1)  # le contenu reste en haut de la page
            self._index[key] = self.stack.addWidget(widget)
        layout.addWidget(self.stack, 1)
        self.bar.changed.connect(self.show_tab)

    def show_tab(self, key: str) -> None:
        if key in self._index:
            self.bar.set_current(key)
            self.stack.setCurrentIndex(self._index[key])
            # la pile prend la hauteur de la page affichée, pas celle de la plus grande
            for i in range(self.stack.count()):
                policy = self.stack.widget(i).sizePolicy()
                policy.setVerticalPolicy(policy.Policy.Preferred if i == self.stack.currentIndex()
                                         else policy.Policy.Ignored)
                self.stack.widget(i).setSizePolicy(policy)
            self.stack.adjustSize()

    def set_visible_tabs(self, keys: Sequence[str]) -> None:
        for key in self._index:
            self.bar.button(key).setVisible(key in keys)
        if self.bar.current() not in keys and keys:
            self.show_tab(keys[0])

    def current(self) -> str:
        return self.bar.current()


def page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    return w, layout


def section(text: str) -> QWidget:
    lbl = label(text, "section")
    lbl.setContentsMargins(0, 10, 0, 2)
    return lbl


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFixedHeight(1)
    return line
