# SPDX-License-Identifier: GPL-3.0-or-later
"""Pages « Médiathèque » et « Corbeille » de l'accueil, et choix dans la médiathèque depuis
l'écran de montage."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from montar.core.library import LibraryItem
from montar.core.timecode import seconds_to_short
from montar.core.trash import RETENTION_DAYS, Trash, TrashEntry
from montar.engine.export import human_size
from montar.i18n import _
from montar.ui.home.home_page import ago
from montar.ui.thumbgrid import (
    ROLE_BADGE,
    ROLE_ICON,
    ROLE_PAYLOAD,
    ROLE_PLACEHOLDER,
    ROLE_SUBTITLE,
    ThumbGrid,
)
from montar.ui.widgets import Segmented, button, label

_KINDS = (("all", "Tout"), ("video", "Vidéos"), ("image", "Images"), ("audio", "Sons"))
_PLACEHOLDER = {"video": "mint", "image": "voiceover", "audio": "pistachio"}
_ICON = {"video": "film", "image": "image", "audio": "music"}


class LibraryGrid(QWidget):
    """Médias de la médiathèque, filtrables par type et par nom."""

    def __init__(self, thumbnail_for: Callable[[str], str | None] | None = None,
                 multi: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher un média"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._apply())
        self.kind = Segmented([(k, _(t)) for k, t in _KINDS], "all")
        self.kind.changed.connect(lambda _k: self._apply())
        row.addWidget(self.search, 1)
        row.addWidget(self.kind)
        layout.addLayout(row)
        self.grid = ThumbGrid(min_width=170, aspect=16 / 11, title_px=13, radius=10)
        if multi:
            self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.grid, 1)
        self.empty = label(_("La médiathèque rassemble les médias de vos projets. Elle est "
                             "vide pour l'instant."), "muted")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self._thumb_for = thumbnail_for
        self._items: list[tuple[QListWidgetItem, LibraryItem]] = []

    def set_items(self, items: list[LibraryItem]) -> None:
        self.grid.clear()
        self._items = []
        for entry in items:
            media = entry.media
            item = QListWidgetItem(media.name)
            item.setData(ROLE_SUBTITLE, ", ".join(entry.projects))
            item.setData(ROLE_PLACEHOLDER, _PLACEHOLDER.get(media.kind, "mint"))
            item.setData(ROLE_ICON, _ICON.get(media.kind, "film"))
            item.setData(ROLE_PAYLOAD, entry)
            if media.kind != "image":
                item.setData(ROLE_BADGE, seconds_to_short(media.duration))
            item.setToolTip(media.path)
            thumb = self._thumb_for(media.path) if self._thumb_for else None
            if thumb:
                item.setData(Qt.ItemDataRole.DecorationRole, QPixmap(thumb))
            self.grid.addItem(item)
            self._items.append((item, entry))
        self._apply()

    def _apply(self) -> None:
        kind, text = self.kind.current(), self.search.text().strip().casefold()
        shown = 0
        for item, entry in self._items:
            visible = (kind in ("all", entry.media.kind)
                       and (not text or text in entry.media.name.casefold()
                            or any(text in p.casefold() for p in entry.projects)))
            item.setHidden(not visible)
            shown += visible
        self.empty.setVisible(not self._items)

    def selected(self) -> list[LibraryItem]:
        return [item.data(ROLE_PAYLOAD) for item in self.grid.selectedItems()]


class LibraryPage(QWidget):
    def __init__(self, thumbnail_for: Callable[[str], str | None]) -> None:
        super().__init__()
        self.setObjectName("Page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(14)
        layout.addWidget(label(_("Médiathèque"), "h1"))
        hint = label(_("Tous les médias de vos projets. Pour en réutiliser un, ouvrez un "
                       "projet puis « Médiathèque… » dans le panneau Médias."), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.library = LibraryGrid(thumbnail_for)
        self.library.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library.grid.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.library, 1)

    def set_items(self, items: list[LibraryItem]) -> None:
        self.library.set_items(items)

    def _context_menu(self, pos) -> None:
        item = self.library.grid.itemAt(pos)
        if item is None:
            return
        entry = item.data(ROLE_PAYLOAD)
        menu = QMenu(self)
        menu.addAction(_("Ouvrir le dossier"), lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(entry.path).parent))))
        menu.exec(self.library.grid.viewport().mapToGlobal(pos))


class LibraryDialog(QDialog):
    """Choix de médias de la médiathèque à ajouter au projet ouvert."""

    def __init__(self, items: list[LibraryItem], thumbnail_for, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Médiathèque"))
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(label(_("Ajouter depuis la médiathèque"), "h2"))
        layout.addWidget(label(_("Sélectionnez un ou plusieurs médias (Ctrl ou Maj + clic). Ils "
                                 "sont copiés dans ce projet."), "muted"))
        self.library = LibraryGrid(thumbnail_for, multi=True)
        self.library.set_items(items)
        self.library.grid.itemSelectionChanged.connect(self._update)
        self.library.grid.itemDoubleClicked.connect(lambda _i: self.accept())
        layout.addWidget(self.library, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        self.add_button = button(_("Ajouter au projet"), "primary", "plus")
        self.add_button.clicked.connect(self.accept)
        for b in (cancel, self.add_button):
            b.setMinimumHeight(42)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._update()

    def _update(self) -> None:
        self.add_button.setEnabled(bool(self.library.selected()))

    def paths(self) -> list[str]:
        return [entry.path for entry in self.library.selected()]


class TrashPage(QWidget):
    """Projets supprimés : restaurer, supprimer définitivement, vider."""

    restored = pyqtSignal(object)  # Path du projet restauré

    def __init__(self, trash: Trash) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.trash = trash
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label(_("Corbeille"), "h1"))
        head.addStretch()
        self.empty_button = button(_("Vider la corbeille"), "secondary", "trash-2")
        self.empty_button.clicked.connect(self._empty)
        head.addWidget(self.empty_button)
        layout.addLayout(head)
        layout.addWidget(label(_("Les projets supprimés restent ici {n} jours avant d'être "
                                 "effacés.").format(n=RETENTION_DAYS), "muted"))
        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        layout.addLayout(self.rows)
        self.empty_label = label(_("La corbeille est vide."), "muted")
        layout.addWidget(self.empty_label)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        entries = self.trash.entries()
        for entry in entries:
            self.rows.addWidget(self._row(entry))
        self.empty_label.setVisible(not entries)
        self.empty_button.setEnabled(bool(entries))

    def _row(self, entry: TrashEntry) -> QWidget:
        row = QFrame()
        row.setProperty("card", True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 12, 12, 12)
        texts = QVBoxLayout()
        title = label(entry.name)
        title.setStyleSheet("font-weight: 700;")
        texts.addWidget(title)
        left = max(0, RETENTION_DAYS - int((time.time() - entry.deleted) / 86400))
        texts.addWidget(label(_("Supprimé {when} · {size} · effacé dans {n} jours").format(
            when=ago(entry.deleted), size=human_size(entry.size).lstrip("≈ "),
            n=left), "small"))
        layout.addLayout(texts, 1)
        restore = button(_("Restaurer"), "secondary", "archive-restore")
        restore.clicked.connect(lambda _=False, e=entry: self._restore(e))
        delete = button(_("Supprimer définitivement"), "secondary", "trash-2")
        delete.clicked.connect(lambda _=False, e=entry: self._delete(e))
        layout.addWidget(restore)
        layout.addWidget(delete)
        return row

    def _restore(self, entry: TrashEntry) -> None:
        path = self.trash.restore(entry)
        self.refresh()
        self.restored.emit(path)

    def _delete(self, entry: TrashEntry) -> None:
        answer = QMessageBox.question(
            self, _("Supprimer définitivement"),
            _("Supprimer « {name} » et tous ses médias ? Cette action est définitive.").format(
                name=entry.name))
        if answer == QMessageBox.StandardButton.Yes:
            self.trash.delete(entry)
            self.refresh()

    def _empty(self) -> None:
        answer = QMessageBox.question(self, _("Vider la corbeille"),
                                      _("Supprimer définitivement tous les projets de la "
                                        "corbeille ?"))
        if answer == QMessageBox.StandardButton.Yes:
            self.trash.empty()
            self.refresh()
