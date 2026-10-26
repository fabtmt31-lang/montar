# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôles de l'inspecteur : curseurs avec valeur, pastilles de couleur, onglets."""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.ui.widgets import Segmented, label

_STEPS = 1000
_NUMBER = re.compile(r"[-+−]?\d+(?:[.,]\d+)?")


def number_in(text: str) -> float | None:
    """Premier nombre d'un texte (« 100 % », « −12 », « ×1,5 »…), virgule acceptée."""
    found = _NUMBER.search(text)
    if found is None:
        return None
    return float(found.group().replace(",", ".").replace("−", "-"))


class ValueField(QLineEdit):
    """Valeur d'un curseur, affichée comme un texte ; un clic permet de la taper."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ValueField")
        self.setProperty("role", "mono")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedWidth(84)
        self.setToolTip(_("Cliquez pour saisir une valeur précise, puis Entrée"))

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.selectAll()


class SliderRow(QWidget):
    """Libellé, valeur affichée et curseur ; `moved` émet la valeur réelle (float)."""

    moved = pyqtSignal(float)
    pressed = pyqtSignal()  # début et fin d'un glisser du curseur
    released = pyqtSignal()

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
        self.value_label = ValueField()
        self.value_label.editingFinished.connect(self._typed)
        head.addWidget(self.value_label)
        layout.addLayout(head)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, _STEPS)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderPressed.connect(self.pressed)
        self.slider.sliderReleased.connect(self.released)
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

    def _typed(self) -> None:
        """Valeur saisie : dans l'unité affichée (« 50 » pour 50 %), bornée au curseur."""
        typed = number_in(self.value_label.text())
        if typed is None:
            self.value_label.setText(self._fmt(self._value))
            return
        # l'affichage peut être une conversion linéaire de la valeur (0,5 → « 50 % »)
        low, high = number_in(self._fmt(self._min)), number_in(self._fmt(self._max))
        value = typed
        if low is not None and high is not None and high != low:
            value = self._min + (typed - low) * (self._max - self._min) / (high - low)
        value = max(self._min, min(self._max, value))
        self.value_label.clearFocus()
        if abs(value - self._value) < 1e-9:
            self.value_label.setText(self._fmt(self._value))
            return
        self.set_value(value)
        self.moved.emit(self._value)

    def set_value(self, value: float) -> None:
        self._value = value
        self.slider.blockSignals(True)
        self.slider.setValue(round(max(0.0, min(1.0, self._ratio(value))) * _STEPS))
        self.slider.blockSignals(False)
        if not self.value_label.hasFocus():  # pas pendant la saisie
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
            none = self._swatch("", _("Aucun"))
            layout.addWidget(none)
        for c in colors:
            layout.addWidget(self._swatch(c, c))
        self._layout = layout
        self._extra: list[QPushButton] = []
        custom = QPushButton("+")
        self._custom_button = custom
        custom.setFixedSize(30, 30)
        custom.setToolTip(_("Couleur personnalisée"))
        custom.setStyleSheet("QPushButton { border-radius: 15px; border: 1.5px dashed #9CCBB0;"
                             " padding: 0; font-weight: 700; }")
        custom.clicked.connect(self._custom)
        layout.addWidget(custom)
        layout.addStretch()
        self._current = ""

    def set_extra(self, colors: Sequence[str]) -> None:
        """Couleurs supplémentaires (kit de marque), avant le bouton « + »."""
        for b in self._extra:
            self._buttons.pop(str(b.property("color")).upper(), None)
            b.deleteLater()
        self._extra = []
        index = self._layout.indexOf(self._custom_button)
        for c in colors:
            if c.upper() in self._buttons:
                continue
            b = self._swatch(c, _("{color} (kit de marque)").format(color=c))
            b.setProperty("color", c)
            self._layout.insertWidget(index, b)
            index += 1
            self._extra.append(b)
        self.set_current(self._current)

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
        self.bar = Segmented([(key, text) for key, text, _w in pages], compact=True)
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
