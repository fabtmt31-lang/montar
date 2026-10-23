# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau « Médias du projet » (maquette 02)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMimeData, QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from montar.core.project import MediaItem
from montar.core.timecode import seconds_to_short
from montar.i18n import _
from montar.media.thumbnails import FILMSTRIP_FRAMES, make_filmstrip
from montar.ui.thumbgrid import (
    ROLE_BADGE,
    ROLE_ICON,
    ROLE_PAYLOAD,
    ROLE_PLACEHOLDER,
    ROLE_USED,
    ROLE_WARNING,
    ThumbGrid,
)
from montar.ui.widgets import Segmented, button, label

MEDIA_MIME = "application/x-montar-media"  # identifiant du média glissé vers la timeline

_FILTERS = (("all", "Tout"), ("video", "Vidéos"), ("image", "Images"), ("audio", "Sons"))
_USAGE = (("all", "Tous"), ("used", "Utilisés"), ("unused", "Non utilisés"))
_PLACEHOLDER = {"video": "mint", "image": "voiceover", "audio": "pistachio"}
_ICON = {"video": "film", "image": "image", "audio": "music"}


ROLE_ORIGINAL = Qt.ItemDataRole.UserRole + 20  # vignette d'origine pendant le survol


class _FilmstripSignals(QObject):
    ready = pyqtSignal(str, str)  # chemin du média, bande (vide si impossible)


class _FilmstripTask(QRunnable):
    def __init__(self, cache: Path, media: MediaItem, signals: _FilmstripSignals) -> None:
        super().__init__()
        self.cache, self.media, self.signals = cache, media, signals

    def run(self) -> None:
        path = make_filmstrip(self.cache, self.media)
        self.signals.ready.emit(self.media.path, str(path) if path else "")


class _MediaGrid(ThumbGrid):
    """Grille dont les vignettes se glissent vers la timeline ; au survol d'une vidéo, la
    vignette défile dans la vidéo selon la position du pointeur (F-MED-03)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cache: Path | None = None
        self._strips: dict[str, QPixmap | None] = {}  # média → bande (None : en cours)
        self._hovered: QListWidgetItem | None = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _FilmstripSignals(self)
        self._signals.ready.connect(self._strip_ready)

    def _strip_ready(self, media_path: str, strip: str) -> None:
        self._strips[media_path] = QPixmap(strip) if strip else QPixmap()

    def _strip(self, media: MediaItem) -> QPixmap | None:
        if self.cache is None or media.kind != "video":
            return None
        if media.path not in self._strips:
            self._strips[media.path] = None
            self._pool.start(_FilmstripTask(self.cache, media, self._signals))
        strip = self._strips[media.path]
        return strip if strip is not None and not strip.isNull() else None

    def _restore_hovered(self) -> None:
        item, self._hovered = self._hovered, None
        if item is not None and item.data(ROLE_ORIGINAL) is not None:
            item.setData(Qt.ItemDataRole.DecorationRole, item.data(ROLE_ORIGINAL))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().mouseMoveEvent(event)
        if event.buttons() != Qt.MouseButton.NoButton:
            return
        item = self.itemAt(event.position().toPoint())
        if item is not self._hovered:
            self._restore_hovered()
        media = item.data(ROLE_PAYLOAD) if item is not None else None
        strip = self._strip(media) if media is not None and media.exists else None
        if strip is None:
            return
        if self._hovered is not item:
            self._hovered = item
            item.setData(ROLE_ORIGINAL, item.data(Qt.ItemDataRole.DecorationRole))
        rect = self.visualItemRect(item)
        ratio = (event.position().x() - rect.left()) / max(1, rect.width())
        index = max(0, min(FILMSTRIP_FRAMES - 1, int(ratio * FILMSTRIP_FRAMES)))
        cell = strip.width() // FILMSTRIP_FRAMES
        item.setData(Qt.ItemDataRole.DecorationRole,
                     strip.copy(index * cell, 0, cell, strip.height()))

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._restore_hovered()
        super().leaveEvent(event)

    def startDrag(self, actions) -> None:  # noqa: N802 - API Qt
        item = self.currentItem()
        if item is None:
            return
        media = item.data(ROLE_PAYLOAD)
        mime = QMimeData()
        mime.setData(MEDIA_MIME, media.id.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pm = item.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(pm, QPixmap) and not pm.isNull():
            drag.setPixmap(pm.scaledToWidth(96, Qt.TransformationMode.SmoothTransformation))
        self._restore_hovered()
        drag.exec(Qt.DropAction.CopyAction)


class MediaPanel(QFrame):
    importRequested = pyqtSignal()
    mediaSelected = pyqtSignal(object)  # MediaItem ou None
    removeRequested = pyqtSignal(object)  # MediaItem
    addToTimelineRequested = pyqtSignal(object)  # MediaItem
    editRequested = pyqtSignal(object)  # MediaItem
    relinkRequested = pyqtSignal(object)  # MediaItem introuvable
    relinkAllRequested = pyqtSignal()
    libraryRequested = pyqtSignal()
    generateRequested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SidePanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 12)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label(_("Médias du projet"), "h3"))
        head.addStretch()
        self.count_label = label("", "small")
        head.addWidget(self.count_label)
        layout.addLayout(head)

        self.missing_box = QFrame()
        self.missing_box.setObjectName("WarningBox")
        ml = QHBoxLayout(self.missing_box)
        ml.setContentsMargins(12, 8, 8, 8)
        self.missing_label = label("", "small")
        self.missing_label.setWordWrap(True)
        relink = button(_("Relier…"), "secondary", "link")
        relink.clicked.connect(self.relinkAllRequested)
        ml.addWidget(self.missing_label, 1)
        ml.addWidget(relink)
        self.missing_box.setVisible(False)
        layout.addWidget(self.missing_box)

        imp = button(_("Importer des fichiers"), "dashed", "plus")
        imp.clicked.connect(self.importRequested)
        layout.addWidget(imp)
        lib = button(_("Médiathèque…"), "ghost", "library",
                     tooltip=_("Réutiliser un média d'un autre projet"))
        lib.clicked.connect(self.libraryRequested)
        self.generate_button = button(_("Créer…"), "ghost", "sparkles",
                                      tooltip=_("Créer un fond ou un motif (modules)"))
        self.generate_button.clicked.connect(self.generateRequested)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(lib, 1)
        row.addWidget(self.generate_button, 1)
        layout.addLayout(row)

        chips = QHBoxLayout()
        chips.setSpacing(4)
        self._filter_group = QButtonGroup(self)
        for key, text in _FILTERS:
            chip = QPushButton(_(text))
            chip.setProperty("variant", "chip")
            chip.setProperty("compact", True)
            chip.setCheckable(True)
            chip.setChecked(key == "all")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self._filter_group.addButton(chip)
            chips.addWidget(chip)
        chips.addStretch()
        layout.addLayout(chips)

        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher par nom"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._apply_filters())
        layout.addWidget(self.search)
        self.usage = Segmented([(k, _(t)) for k, t in _USAGE], "all", compact=True)
        self.usage.setToolTip(_("Utilisés : médias déjà dans le montage (pastille ✓)"))
        self.usage.changed.connect(lambda _k: self._apply_filters())
        layout.addWidget(self.usage)

        self.grid = _MediaGrid(min_width=110, aspect=16 / 11, title_px=13, radius=10,
                               with_subtitle=False)
        self.grid.setDragEnabled(True)
        self.grid.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.grid.setToolTip("")
        self.grid.itemDoubleClicked.connect(
            lambda item: self.addToTimelineRequested.emit(item.data(ROLE_PAYLOAD)))
        self.grid.currentItemChanged.connect(self._current_changed)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.grid, 1)

        self.empty_hint = label(_("Glissez des vidéos, images ou sons ici, ou utilisez "
                                  "« Importer des fichiers ». Glissez ensuite un média vers "
                                  "la timeline, ou double-cliquez dessus."), "small")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_hint)
        self._filter = "all"
        self._items: dict[str, QListWidgetItem] = {}
        self._used: set[str] = set()

    def set_media(self, media: list[MediaItem], thumbnails: dict[str, str]) -> None:
        self.grid.clear()
        self._items.clear()
        for m in media:
            self.add_media(m, thumbnails.get(m.path))
        self._update_count()

    def add_media(self, media: MediaItem, thumbnail: str | None) -> None:
        item = QListWidgetItem(media.name)
        item.setData(ROLE_PAYLOAD, media)
        item.setData(ROLE_PLACEHOLDER, _PLACEHOLDER.get(media.kind, "mint"))
        item.setData(ROLE_ICON, _ICON.get(media.kind, "film"))
        if media.kind != "image":
            item.setData(ROLE_BADGE, seconds_to_short(media.duration))
        if not media.exists:
            item.setData(ROLE_WARNING, True)
            item.setToolTip(_("Fichier introuvable : {path}").format(path=media.path))
        else:
            item.setToolTip(media.path)
        if thumbnail:
            item.setData(Qt.ItemDataRole.DecorationRole, QPixmap(thumbnail))
        item.setData(ROLE_USED, media.id in self._used)
        self.grid.addItem(item)
        self._items[media.id] = item
        item.setHidden(not self._matches(media))
        self._update_count()

    def set_missing(self, count: int) -> None:
        """Bandeau des médias introuvables (fichiers déplacés ou supprimés)."""
        self.missing_box.setVisible(count > 0)
        self.missing_label.setText(_("1 média introuvable") if count == 1 else
                                   _("{n} médias introuvables").format(n=count))

    def set_used(self, media_ids: set[str]) -> None:
        """Médias présents dans la timeline : pastille ✓ et filtre « Dans le montage »."""
        self._used = set(media_ids)
        for media_id, item in self._items.items():
            item.setData(ROLE_USED, media_id in self._used)
        self._apply_filters()

    def _matches(self, media: MediaItem) -> bool:
        if self._filter not in ("all", media.kind):
            return False
        usage = self.usage.current()
        if usage == "used" and media.id not in self._used:
            return False
        if usage == "unused" and media.id in self._used:
            return False
        text = self.search.text().strip().casefold()
        return not text or text in media.name.casefold()

    def _apply_filters(self) -> None:
        for item in self._items.values():
            item.setHidden(not self._matches(item.data(ROLE_PAYLOAD)))

    def set_thumbnail(self, media_id: str, thumbnail: str) -> None:
        item = self._items.get(media_id)
        if item is not None:
            item.setData(Qt.ItemDataRole.DecorationRole, QPixmap(thumbnail))

    def remove_media(self, media_id: str) -> None:
        item = self._items.pop(media_id, None)
        if item is not None:
            self.grid.takeItem(self.grid.row(item))
        self._update_count()

    def select(self, media_id: str) -> None:
        item = self._items.get(media_id)
        if item is not None:
            self.grid.setCurrentItem(item)

    def _update_count(self) -> None:
        n = len(self._items)
        self.count_label.setText(_("{n} élément").format(n=n) if n == 1
                                 else _("{n} éléments").format(n=n))
        self.empty_hint.setVisible(n == 0)

    def set_filter(self, key: str) -> None:
        for chip, (k, _t) in zip(self._filter_group.buttons(), _FILTERS, strict=True):
            chip.setChecked(k == key)
        self._set_filter(key)

    def _set_filter(self, key: str) -> None:
        self._filter = key
        self._apply_filters()

    def _current_changed(self, current: QListWidgetItem | None, _prev) -> None:
        self.mediaSelected.emit(current.data(ROLE_PAYLOAD) if current else None)

    def _context_menu(self, pos) -> None:
        item = self.grid.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction(_("Ajouter à la timeline"),
                       lambda: self.addToTimelineRequested.emit(item.data(ROLE_PAYLOAD)))
        media = item.data(ROLE_PAYLOAD)
        if media.exists:
            menu.addAction(_("Modifier le média…"), lambda: self.editRequested.emit(media))
        else:
            menu.addAction(_("Relier à un fichier…"), lambda: self.relinkRequested.emit(media))
        menu.addAction(_("Retirer du projet"),
                       lambda: self.removeRequested.emit(item.data(ROLE_PAYLOAD)))
        menu.exec(self.grid.viewport().mapToGlobal(pos))
