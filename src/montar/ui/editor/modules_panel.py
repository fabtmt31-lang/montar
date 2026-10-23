# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau « Modules » du rail : tout ce qu'apportent les modules actifs, regroupé par
module (outils, effets vidéo et audio, transitions, générateurs, formats d'export)."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from montar.i18n import N_, _
from montar.ui.editor.panels import _Panel
from montar.ui.widgets import button, label

KIND_LABELS = {
    "tool": N_("Outil"), "module_effect": N_("Effet vidéo"), "audio_effect": N_("Effet audio"),
    "transition": N_("Transition"), "generator": N_("Générateur"),
    "export_format": N_("Format d'export"),
}


@dataclass(frozen=True)
class ModuleEntry:
    kind: str  # clé de KIND_LABELS
    module_id: str
    item: object  # objet de l'API (Tool, VideoEffect, Transition…)

    @property
    def name(self) -> str:
        return _(getattr(self.item, "name", ""))

    @property
    def description(self) -> str:
        return _(getattr(self.item, "description", ""))

    @property
    def icon(self) -> str:
        if self.kind == "export_format":
            return "download"
        return getattr(self.item, "icon", "") or "sparkles"


def entries(manager) -> dict[str, list[ModuleEntry]]:
    """Éléments des modules actifs, par module (dans l'ordre des modules)."""
    result: dict[str, list[ModuleEntry]] = {}
    for kind, items in (("tool", manager.tools()), ("module_effect", manager.effects()),
                        ("audio_effect", manager.audio_effects()),
                        ("transition", manager.transitions()),
                        ("generator", manager.generators()),
                        ("export_format", manager.export_formats())):
        for module_id, item in items:
            result.setdefault(module_id, []).append(ModuleEntry(kind, module_id, item))
    order = [m.id for m in manager.active()]
    return dict(sorted(result.items(), key=lambda kv: order.index(kv[0])
                       if kv[0] in order else len(order)))


class ModulesPanel(_Panel):
    activated = pyqtSignal(object)  # ModuleEntry choisie
    manageRequested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(_("Modules"), scroll=True)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher un effet, un outil…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._filter())
        self.body.addWidget(self.search)
        self.info = self.hint(_("Cliquez sur un effet ou un outil pour l'appliquer au clip "
                                "sélectionné ; une transition se place après lui."))
        self.body.addWidget(self.info)
        self._box = QVBoxLayout()
        self._box.setSpacing(2)
        self.body.addLayout(self._box)
        self.empty = self.hint(_("Aucun module actif."))
        self.body.addWidget(self.empty)
        self.body.addStretch()
        manage = button(_("Gérer les modules…"), "secondary", "puzzle")
        manage.clicked.connect(self.manageRequested)
        self.body.addWidget(manage)
        self._rows: list[tuple[QPushButton, ModuleEntry, QWidget]] = []
        self._headers: dict[str, QWidget] = {}

    def set_manager(self, manager) -> None:
        while self._box.count():
            item = self._box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._rows, self._headers = [], {}
        names = {m.id: m.name for m in manager.modules.values()}
        groups = entries(manager)
        for module_id, items in groups.items():
            head = label(_(names.get(module_id, module_id)).upper(), "section")
            head.setContentsMargins(0, 10, 0, 2)
            self._box.addWidget(head)
            self._headers[module_id] = head
            for entry in items:
                row = self._row(entry)
                self._box.addWidget(row)
        self.empty.setVisible(not groups)
        self._filter()

    def _row(self, entry: ModuleEntry) -> QWidget:
        b = button(entry.name, "ghost", entry.icon)
        b.setStyleSheet("text-align: left; padding: 7px 8px;")
        tip = _(KIND_LABELS[entry.kind])
        b.setToolTip(f"{tip} — {entry.description}" if entry.description else tip)
        b.clicked.connect(lambda _=False, e=entry: self.activated.emit(e))
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(b, 1)
        kind = label(_(KIND_LABELS[entry.kind]), "small")
        kind.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(kind)
        self._rows.append((b, entry, holder))
        return holder

    def _filter(self) -> None:
        text = self.search.text().strip().casefold()
        visible: set[str] = set()
        for _b, entry, holder in self._rows:
            show = not text or text in entry.name.casefold() \
                or text in entry.description.casefold()
            holder.setVisible(show)
            if show:
                visible.add(entry.module_id)
        for module_id, head in self._headers.items():
            head.setVisible(module_id in visible)

    def visible_entries(self) -> list[ModuleEntry]:
        return [e for _b, e, holder in self._rows if not holder.isHidden()]
