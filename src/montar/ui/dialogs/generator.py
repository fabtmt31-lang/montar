# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre « Créer un média » : générateurs des modules (fond uni, dégradé…)."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.ui.editor.params import ParamControl
from montar.ui.theme import theme
from montar.ui.widgets import button, label


class GeneratorDialog(QDialog):
    """`generators` : liste de (module, montar.api.Generator). Après validation, `chosen`
    vaut (module, générateur) et `values` ses réglages."""

    def __init__(self, generators: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Créer un média"))
        self.setModal(True)
        self.resize(680, 460)
        self.generators = generators
        self.chosen = None
        self.values: dict = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(label(_("Créer un média"), "h2"))
        layout.addWidget(label(_("Le média est créé à la taille du projet et ajouté au "
                                 "panneau Médias."), "muted"))
        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = QListWidget()
        self.list.setObjectName("ApplyList")
        self.list.setIconSize(QSize(20, 20))
        self.list.setFixedWidth(230)
        for module_id, generator in generators:
            item = QListWidgetItem(theme().icon(generator.icon, theme().palette.forest),
                                   _(generator.name))
            item.setData(Qt.ItemDataRole.UserRole, (module_id, generator))
            self.list.addItem(item)
        self.list.currentItemChanged.connect(lambda *_a: self._show())
        body.addWidget(self.list)
        self.form_holder = QWidget()
        self.form = QVBoxLayout(self.form_holder)
        self.form.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.form_holder, 1)
        layout.addLayout(body, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        self.create_button = button(_("Créer"), "primary", "plus")
        self.create_button.clicked.connect(self._accept)
        for b in (cancel, self.create_button):
            b.setMinimumHeight(42)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.controls: list[ParamControl] = []
        if generators:
            self.list.setCurrentRow(0)
        self.create_button.setEnabled(bool(generators))

    def select(self, generator_id: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole)[1].id == generator_id:
                self.list.setCurrentRow(row)

    def _show(self) -> None:
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.controls = []
        current = self.list.currentItem()
        if current is None:
            return
        _module_id, generator = current.data(Qt.ItemDataRole.UserRole)
        self.values = generator.defaults()
        description = label(_(generator.description), "muted")
        description.setWordWrap(True)
        self.form.addWidget(description)
        for param in generator.params:
            control = ParamControl(param, lambda v, _m, k=param.key: self.values.__setitem__(k, v))
            control.set_value(self.values.get(param.key, param.default))
            self.form.addWidget(control.widget)
            self.controls.append(control)
        self.form.addStretch()

    def _accept(self) -> None:
        current = self.list.currentItem()
        if current is not None:
            self.chosen = current.data(Qt.ItemDataRole.UserRole)
            self.accept()
