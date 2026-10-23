# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences → « Raccourcis clavier » (F-UX-07) : une touche par action, modifiable,
avec signalement des touches attribuées deux fois."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFrame, QGridLayout, QKeySequenceEdit, QVBoxLayout

from montar.core import shortcuts
from montar.core.settings import Settings
from montar.i18n import _
from montar.ui.widgets import button, label, set_icon

PORTABLE = QKeySequence.SequenceFormat.PortableText
NATIVE = QKeySequence.SequenceFormat.NativeText


class ShortcutsCard(QFrame):
    changed = pyqtSignal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setProperty("card", True)
        cl = QVBoxLayout(self)
        cl.setContentsMargins(24, 18, 24, 18)
        cl.setSpacing(8)
        cl.addWidget(label(_("Raccourcis clavier"), "h3"))
        hint = label(_("Cliquez sur une touche puis appuyez sur la nouvelle combinaison. "
                       "Effacer le champ désactive le raccourci."), "small")
        hint.setWordWrap(True)
        cl.addWidget(hint)
        self.conflict = label("", "small")
        self.conflict.setWordWrap(True)
        self.conflict.setStyleSheet("color: #B4452F;")
        cl.addWidget(self.conflict)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        half = -(-len(shortcuts.ACTIONS) // 2)  # deux colonnes d'actions
        for block in (0, 4):
            grid.setColumnStretch(block, 1)
            grid.setColumnMinimumWidth(block + 2, 32)
        grid.setColumnMinimumWidth(3, 24)
        self.edits: dict[str, QKeySequenceEdit] = {}
        self.resets = {}
        for i, (action, title) in enumerate(shortcuts.ACTIONS):
            row, col = i % half, (i // half) * 4
            grid.addWidget(label(_(title)), row, col)
            edit = QKeySequenceEdit()
            edit.setFixedWidth(150)
            edit.setClearButtonEnabled(True)
            edit.editingFinished.connect(lambda a=action: self._edited(a))
            edit.keySequenceChanged.connect(lambda seq, a=action: self._cleared(a, seq))
            grid.addWidget(edit, row, col + 1)
            reset = button("", "ghost", tooltip=_("Touche par défaut : {key}").format(
                key=QKeySequence(shortcuts.default(action)).toString(NATIVE)))
            set_icon(reset, "rotate-ccw", "ink", 16)
            reset.clicked.connect(lambda _=False, a=action: self.set_key(a, None))
            reset.setFixedSize(32, 28)
            grid.addWidget(reset, row, col + 2)
            self.edits[action] = edit
            self.resets[action] = reset
        cl.addLayout(grid)
        self.reset_all = button(_("Rétablir tous les raccourcis"), "secondary", "rotate-ccw")
        self.reset_all.clicked.connect(self._reset_all)
        cl.addWidget(self.reset_all, 0, Qt.AlignmentFlag.AlignLeft)
        self.refresh()

    def refresh(self, keep: str | None = None) -> None:
        """`keep` : champ en cours de saisie, laissé tel quel."""
        overrides = self.settings.shortcuts
        for action, edit in self.edits.items():
            if action == keep:
                self.resets[action].setVisible(action in overrides)
                continue
            edit.blockSignals(True)
            edit.setKeySequence(QKeySequence(shortcuts.current(overrides, action)))
            edit.blockSignals(False)
            self.resets[action].setVisible(action in overrides)
        labels = dict(shortcuts.ACTIONS)
        found = shortcuts.conflicts(overrides)
        self.conflict.setVisible(bool(found))
        self.conflict.setText("\n".join(
            _("« {key} » sert à plusieurs actions : {actions}").format(
                key=QKeySequence(key).toString(NATIVE),
                actions=", ".join(_(labels[a]) for a in actions))
            for key, actions in sorted(found.items())))
        self.reset_all.setEnabled(bool(overrides))

    def set_key(self, action: str, key: str | None, keep: bool = False) -> None:
        """Nouvelle touche (None : celle par défaut, "" : aucune)."""
        overrides = dict(self.settings.shortcuts)
        overrides.pop(action, None)
        if key is not None and key != shortcuts.default(action):
            overrides[action] = key
        if overrides != self.settings.shortcuts:
            self.settings.shortcuts = overrides
            self.changed.emit()
        self.refresh(action if keep else None)

    def _edited(self, action: str) -> None:
        seq = self.edits[action].keySequence()
        # une seule combinaison : les suivantes d'une séquence sont ignorées
        key = QKeySequence(seq[0]).toString(PORTABLE) if seq.count() else ""
        if key != shortcuts.current(self.settings.shortcuts, action):
            self.set_key(action, key)

    def _cleared(self, action: str, seq: QKeySequence) -> None:
        if seq.isEmpty():  # bouton d'effacement (ou début d'une saisie, finie par _edited)
            self.set_key(action, "", keep=True)

    def _reset_all(self) -> None:
        if self.settings.shortcuts:
            self.settings.shortcuts = {}
            self.changed.emit()
        self.refresh()
