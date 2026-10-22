# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre « Appliquer un effet ou un module »."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.ui.editor.apply import CATEGORIES, ApplyAction
from montar.ui.theme import theme
from montar.ui.widgets import button, label

ROLE_ACTION = Qt.ItemDataRole.UserRole + 1


class ApplyEffectDialog(QDialog):
    def __init__(self, actions: list[ApplyAction], target: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Appliquer un effet ou un module"))
        self.setModal(True)
        self.resize(560, 620)
        self.actions = actions
        self.chosen: ApplyAction | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)
        layout.addWidget(label(_("Appliquer un effet ou un module"), "h2"))
        layout.addWidget(label(target, "muted"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher (nom, description, module)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("ApplyList")
        self.list.setIconSize(QSize(20, 20))
        self.list.setSpacing(2)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        self.list.currentItemChanged.connect(lambda *_a: self._update())
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        self.apply_button = button(_("Appliquer"), "primary", "sparkles")
        self.apply_button.clicked.connect(self._accept)
        for b in (cancel, self.apply_button):
            b.setMinimumHeight(42)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._fill()
        self.search.setFocus()

    def _fill(self) -> None:
        self.list.clear()
        p = theme().palette
        for kind, title in CATEGORIES.items():
            members = [a for a in self.actions if a.kind == kind]
            if not members:
                continue
            header = QListWidgetItem(_(title).upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.list.addItem(header)
            for action in members:
                text = action.title
                details = [d for d in (action.description, action.module_name and
                                       _("module {name}").format(name=action.module_name))
                           if d]
                if details:
                    text += "\n" + " · ".join(details)
                item = QListWidgetItem(theme().icon(action.icon, p.forest), text)
                item.setData(ROLE_ACTION, action)
                self.list.addItem(item)
        first = next((self.list.item(i) for i in range(self.list.count())
                      if self.list.item(i).data(ROLE_ACTION) is not None), None)
        if first is not None:
            self.list.setCurrentItem(first)
        self._update()

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        visible_kinds = set()
        for i in range(self.list.count()):
            item = self.list.item(i)
            action = item.data(ROLE_ACTION)
            if action is None:
                continue
            haystack = f"{action.title} {action.description} {action.module_name}".casefold()
            item.setHidden(bool(needle) and needle not in haystack)
            if not item.isHidden():
                visible_kinds.add(action.kind)
        for i in range(self.list.count()):  # titres des catégories vides masqués
            item = self.list.item(i)
            if item.data(ROLE_ACTION) is None:
                kind = next(k for k, t in CATEGORIES.items() if _(t).upper() == item.text())
                item.setHidden(kind not in visible_kinds)
        current = self.list.currentItem()
        if current is None or current.isHidden():
            visible = next((self.list.item(i) for i in range(self.list.count())
                            if not self.list.item(i).isHidden()
                            and self.list.item(i).data(ROLE_ACTION) is not None), None)
            self.list.setCurrentItem(visible)
        self._update()

    def _update(self) -> None:
        item = self.list.currentItem()
        self.apply_button.setEnabled(item is not None and not item.isHidden()
                                     and item.data(ROLE_ACTION) is not None)

    def select(self, kind: str, key: str) -> None:
        for i in range(self.list.count()):
            action = self.list.item(i).data(ROLE_ACTION)
            if action is not None and (action.kind, action.key) == (kind, key):
                self.list.setCurrentRow(i)

    def _accept(self) -> None:
        item = self.list.currentItem()
        if item is None or item.data(ROLE_ACTION) is None:
            return
        self.chosen = item.data(ROLE_ACTION)
        self.accept()
