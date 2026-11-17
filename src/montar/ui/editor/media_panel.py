# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau « Médias du projet » (maquette 02)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QMimeData,
    QModelIndex,
    QObject,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDrag, QFont, QKeySequence, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyleOptionViewItem,
    QVBoxLayout,
)

from montar.core.project import MediaItem
from montar.core.timecode import seconds_to_short
from montar.i18n import _
from montar.media.thumbnails import FILMSTRIP_FRAMES, make_filmstrip
from montar.ui.editor.panels import SIDE_MIN_WIDTH
from montar.ui.theme import theme
from montar.ui.theme.icons import pixmap as icon_pixmap
from montar.ui.theme.manager import ui_font
from montar.ui.thumbgrid import (
    ROLE_BADGE,
    ROLE_ICON,
    ROLE_PAYLOAD,
    ROLE_PLACEHOLDER,
    ROLE_USED,
    ROLE_WARNING,
    ThumbDelegate,
    ThumbGrid,
)
from montar.ui.widgets import Segmented, button, label

MEDIA_MIME = "application/x-montar-media"  # identifiant du média glissé vers la timeline

# (« Audio » : sons et musique ; la grille les sépare par intertitres)
_FILTERS = (("all", "Tout"), ("video", "Vidéos"), ("image", "Images"), ("audio", "Audio"))
_USAGE = (("all", "Tous"), ("used", "Utilisés"), ("unused", "Non utilisés"))
_PLACEHOLDER = {"video": "mint", "image": "voiceover", "audio": "pistachio"}
_ICON = {"video": "film", "image": "image", "audio": "music"}


ROLE_ORIGINAL = Qt.ItemDataRole.UserRole + 20  # vignette d'origine pendant le survol
ROLE_HEADER = Qt.ItemDataRole.UserRole + 21  # intertitre de rubrique (identifiant)

# rubriques de la grille, dans l'ordre : (identifiant, intitulé, jeton de couleur)
GROUPS = (("video", "Vidéos", "mint"), ("recording", "Enregistrements", "sage"),
          ("image", "Images", "water"), ("sound", "Sons", "pistachio"),
          ("music", "Musique", "voiceover"))
_GROUP_NAMES = dict((k, t) for k, t, _c in GROUPS)


class _FilmstripSignals(QObject):
    ready = pyqtSignal(str, str)  # chemin du média, bande (vide si impossible)


class _FilmstripTask(QRunnable):
    def __init__(self, cache: Path, media: MediaItem, signals: _FilmstripSignals) -> None:
        super().__init__()
        self.cache, self.media, self.signals = cache, media, signals

    def run(self) -> None:
        path = make_filmstrip(self.cache, self.media)
        self.signals.ready.emit(self.media.path, str(path) if path else "")


class _MediaDelegate(ThumbDelegate):
    """Vignettes du panneau Médias : intertitres de rubrique et cases à cocher."""

    def sizeHint(self, option, index: QModelIndex) -> QSize:  # noqa: N802 - API Qt
        if index.data(ROLE_HEADER):
            return QSize(self._view._usable_width(), 30)
        return super().sizeHint(option, index)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        header = index.data(ROLE_HEADER)
        p = theme().palette
        if header:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(option.rect).adjusted(4, 8, -4, -2)
            color = dict((k, c) for k, _t, c in GROUPS).get(header, "mint")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(getattr(p, color)))
            painter.drawRoundedRect(QRectF(r.x(), r.center().y() - 5, 10, 10), 3, 3)
            f = ui_font()
            f.setPixelSize(12)
            f.setWeight(QFont.Weight.Bold)
            painter.setFont(f)
            painter.setPen(QColor(p.ink))
            painter.drawText(r.adjusted(18, 0, 0, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             index.data(Qt.ItemDataRole.DisplayRole) or "")
            painter.restore()
            return
        super().paint(painter, option, index)
        if self._view.checking:  # sélection partielle : une case sur chaque vignette
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(option.rect.x() + 11, option.rect.y() + 11, 20, 20)
            on = self._view.selectionModel().isSelected(index)
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.setBrush(QColor(p.forest) if on else QColor(10, 20, 15, 110))
            painter.drawRoundedRect(box, 6, 6)
            if on:
                ip = icon_pixmap("check", "#FFFFFF", 14)
                painter.drawPixmap(int(box.center().x() - 7), int(box.center().y() - 7), ip)
            painter.restore()


class _MediaGrid(ThumbGrid):
    """Grille dont les vignettes se glissent vers la timeline ; au survol d'une vidéo, la
    vignette défile dans la vidéo selon la position du pointeur (F-MED-03). Plusieurs
    médias se sélectionnent (Ctrl / Maj + clic, Ctrl+A) et se glissent ensemble."""

    deleteRequested = pyqtSignal()  # touche Suppr sur la sélection
    checkingEnded = pyqtSignal()  # Échap en sélection partielle

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.checking = False  # sélection partielle : un clic coche ou décoche
        self.setItemDelegate(_MediaDelegate(self))
        self.setUniformItemSizes(False)  # intertitres sur toute la largeur
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

    def _update_grid(self) -> None:
        # pas de grille fixe : les intertitres prennent toute la largeur, les vignettes
        # gardent la taille calculée par le délégué
        self.setGridSize(QSize())
        self.doItemsLayout()

    def set_checking(self, on: bool) -> None:
        self.checking = on
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection if on
                              else QAbstractItemView.SelectionMode.ExtendedSelection)
        self.viewport().update()

    def media_items(self) -> list[QListWidgetItem]:
        """Vignettes de médias visibles (sans les intertitres), dans l'ordre du panneau."""
        return [it for it in (self.item(i) for i in range(self.count()))
                if not it.isHidden() and it.data(ROLE_PAYLOAD) is not None]

    def selected_medias(self) -> list[MediaItem]:
        """Médias sélectionnés (Ctrl / Maj + clic, Ctrl+A), dans l'ordre du panneau."""
        items = sorted(self.selectedItems(), key=self.row)
        if not items and self.currentItem() is not None and not self.checking:
            items = [self.currentItem()]
        return [i.data(ROLE_PAYLOAD) for i in items
                if not i.isHidden() and i.data(ROLE_PAYLOAD) is not None]

    def event(self, event) -> bool:  # noqa: A003 - API Qt
        # le panneau a la main : Suppr et Ctrl+A agissent sur les médias, pas sur la timeline
        if event.type() == QEvent.Type.ShortcutOverride and (
                event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                or event.matches(QKeySequence.StandardKey.SelectAll)
                or (self.checking and event.key() == Qt.Key.Key_Escape)):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.key() == Qt.Key.Key_Escape and self.checking:
            self.checkingEnded.emit()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_medias():
            # après l'événement : les vignettes retirées ne doivent pas disparaître pendant
            # que la grille traite encore la touche
            QTimer.singleShot(0, self.deleteRequested.emit)
            return
        super().keyPressEvent(event)

    def startDrag(self, actions) -> None:  # noqa: N802 - API Qt
        item = self.currentItem()
        if item is None or item.data(ROLE_PAYLOAD) is None:
            return
        medias = self.selected_medias()
        if item.data(ROLE_PAYLOAD) not in medias:
            medias = [item.data(ROLE_PAYLOAD)]
        mime = QMimeData()
        mime.setData(MEDIA_MIME, "\n".join(m.id for m in medias).encode())
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
    removeManyRequested = pyqtSignal(object)  # list[MediaItem]
    addToTimelineRequested = pyqtSignal(object)  # MediaItem
    addManyRequested = pyqtSignal(object)  # list[MediaItem], posés à la suite
    categoryRequested = pyqtSignal(object, str)  # MediaItem, "music" | "sound"
    editRequested = pyqtSignal(object)  # MediaItem
    fitCanvasRequested = pyqtSignal(object)  # MediaItem : toile du projet à sa taille
    relinkRequested = pyqtSignal(object)  # MediaItem introuvable
    relinkAllRequested = pyqtSignal()
    libraryRequested = pyqtSignal()
    generateRequested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SidePanel")
        self.setMinimumWidth(SIDE_MIN_WIDTH)
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

        self.import_button = imp = button(_("Importer des fichiers"), "dashed", "plus")
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
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.deleteRequested.connect(
            lambda: self.removeManyRequested.emit(self.grid.selected_medias()))
        self.grid.setToolTip("")
        self.grid.itemDoubleClicked.connect(
            lambda item: self.addToTimelineRequested.emit(item.data(ROLE_PAYLOAD)))
        self.grid.currentItemChanged.connect(self._current_changed)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.grid, 1)
        self.grid.itemSelectionChanged.connect(self._update_action_bar)
        self.grid.checkingEnded.connect(lambda: self.set_checking(False))
        self.grid.viewport().installEventFilter(self)

        # sélection de plusieurs médias : ce qu'on peut en faire d'un coup
        self.action_bar = QFrame()
        self.action_bar.setObjectName("SelectionBar")
        ab = QHBoxLayout(self.action_bar)
        ab.setContentsMargins(10, 6, 6, 6)
        ab.setSpacing(4)
        self.selection_label = label("", "small")
        self.selection_label.setStyleSheet("font-weight: 700;")
        ab.addWidget(self.selection_label, 1)
        add = button("", "ghost", "list-plus", tooltip=_("Ajouter à la timeline, à la suite"))
        add.clicked.connect(lambda: self._act(self.addManyRequested))
        remove = button("", "ghost", "trash-2", tooltip=_("Retirer du projet"))
        remove.clicked.connect(lambda: self._act(self.removeManyRequested))
        self.done_button = button(_("Terminer"), "secondary")
        self.done_button.clicked.connect(self.end_selection)
        for b in (add, remove, self.done_button):
            ab.addWidget(b)
        self.action_bar.setVisible(False)
        layout.addWidget(self.action_bar)

        self.empty_hint = label(_("Glissez des vidéos, images ou sons ici, ou utilisez "
                                  "« Importer des fichiers ». Glissez ensuite un média vers "
                                  "la timeline, ou double-cliquez dessus."), "small")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_hint)
        self._filter = "all"
        self._items: dict[str, QListWidgetItem] = {}
        self._headers: dict[str, QListWidgetItem] = {}  # intertitres des rubriques
        self._order: list[str] = []  # ordre affiché (rubriques puis médias)
        self._used: set[str] = set()

    # --- sélection ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - API Qt
        # clic dans le vide de la grille en sélection partielle : rien ne se décoche
        if (obj is self.grid.viewport() and self.grid.checking
                and event.type() == QEvent.Type.MouseButtonPress
                and self.grid.itemAt(event.position().toPoint()) is None):
            return True
        return super().eventFilter(obj, event)

    def set_checking(self, on: bool) -> None:
        """Sélection partielle : une case sur chaque vignette, un clic coche ou décoche."""
        if not on:
            self.grid.clearSelection()
        self.grid.set_checking(on)
        self._update_action_bar()

    def end_selection(self) -> None:
        self.set_checking(False)
        self.grid.clearSelection()

    def select_all(self) -> None:
        self.grid.clearSelection()
        for it in self.grid.media_items():
            it.setSelected(True)

    def invert_selection(self) -> None:
        for it in self.grid.media_items():
            it.setSelected(not it.isSelected())

    def select_unused(self) -> None:
        self.grid.clearSelection()
        for it in self.grid.media_items():
            it.setSelected(it.data(ROLE_PAYLOAD).id not in self._used)

    def _act(self, signal) -> None:
        medias = self.grid.selected_medias()
        if medias:
            signal.emit(medias)

    def _update_action_bar(self) -> None:
        n = len([i for i in self.grid.selectedItems() if i.data(ROLE_PAYLOAD) is not None])
        self.action_bar.setVisible(self.grid.checking or n > 1)
        self.selection_label.setText(_("{n} sélectionné").format(n=n) if n <= 1
                                     else _("{n} sélectionnés").format(n=n))
        self.grid.viewport().update()

    def _selection_actions(self, menu: QMenu) -> None:
        menu.addAction(_("Tout sélectionner (Ctrl+A)"),
                       lambda: (self.set_checking(True), self.select_all()))
        menu.addAction(_("Sélection partielle…"), lambda: self.set_checking(True))
        menu.addAction(_("Inverser la sélection"),
                       lambda: (self.set_checking(True), self.invert_selection()))
        menu.addAction(_("Sélectionner les non utilisés"),
                       lambda: (self.set_checking(True), self.select_unused()))
        if self.grid.checking:
            menu.addAction(_("Terminer la sélection (Échap)"), self.end_selection)

    def set_media(self, media: list[MediaItem], thumbnails: dict[str, str]) -> None:
        """Liste des médias ; un média ajouté ou retiré ne fait plus reconstruire toute la
        liste (des centaines de vignettes relues à chaque import)."""
        ids = [m.id for m in media]
        current = list(self._items)
        if current == ids[:len(current)] and all(
                self._items[m.id].data(ROLE_PAYLOAD) is m for m in media[:len(current)]):
            for m in media[len(current):]:  # médias ajoutés à la fin
                self.add_media(m, thumbnails.get(m.path), arrange=False)
            self._arrange()
            self._update_count()
            return
        kept = [i for i in current if i in set(ids)]
        if kept == ids and all(self._items[m.id].data(ROLE_PAYLOAD) is m for m in media):
            for media_id in set(current) - set(ids):  # médias retirés
                item = self._items.pop(media_id)
                if self.grid._hovered is item:
                    self.grid._hovered = None
                self.grid.takeItem(self.grid.row(item))
            self._arrange()  # classement changé (Musique / Sons) ou rubrique vidée
            self._update_count()
            return
        self.grid._hovered = None
        self.grid.clear()
        self._items.clear()
        self._headers.clear()
        self._order = []
        for m in media:
            self.add_media(m, thumbnails.get(m.path), arrange=False)
        self._arrange()
        self._update_count()

    def add_media(self, media: MediaItem, thumbnail: str | None, arrange: bool = True) -> None:
        item = QListWidgetItem(media.name)
        item.setData(ROLE_PAYLOAD, media)
        item.setData(ROLE_PLACEHOLDER, _PLACEHOLDER.get(media.kind, "mint"))
        item.setData(ROLE_ICON, _ICON.get(media.kind, "film"))
        if media.kind != "image":
            item.setData(ROLE_BADGE, seconds_to_short(media.duration))
        if not media.exists:
            item.setData(ROLE_WARNING, True)
            item.setToolTip(_("Fichier introuvable : {path}").format(path=media.path))
        elif media.webcam:  # enregistrement : écran et webcam, posés ensemble
            item.setToolTip(_("{path}\nÉcran + webcam : deux clips liés dans la timeline "
                              "(la webcam peut être retirée sur une partie)").format(
                                  path=media.path))
        else:
            item.setToolTip(media.path)
        if thumbnail:
            item.setData(Qt.ItemDataRole.DecorationRole, _pixmap(thumbnail))
        item.setData(ROLE_USED, media.id in self._used)
        self.grid.addItem(item)
        self._items[media.id] = item
        item.setHidden(not self._matches(media))
        if arrange:
            self._arrange()
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
        group = media.group
        wanted = {"all": None, "video": ("video", "recording"), "image": ("image",),
                  "audio": ("sound", "music"), "music": ("music",)}.get(self._filter)
        if wanted is not None and group not in wanted:
            return False
        usage = self.usage.current()
        if usage == "used" and media.id not in self._used:
            return False
        if usage == "unused" and media.id in self._used:
            return False
        text = self.search.text().strip().casefold()
        return not text or text in media.name.casefold()

    def _apply_filters(self) -> None:
        shown: dict[str, int] = {}
        for item in self._items.values():
            media = item.data(ROLE_PAYLOAD)
            visible = self._matches(media)
            item.setHidden(not visible)
            if visible:
                shown[media.group] = shown.get(media.group, 0) + 1
        totals: dict[str, int] = {}
        for item in self._items.values():
            g = item.data(ROLE_PAYLOAD).group
            totals[g] = totals.get(g, 0) + 1
        filtered = shown != totals
        for key, header in self._headers.items():
            n = shown.get(key, 0)
            header.setHidden(n == 0)  # rubrique sans média affiché : pas d'intertitre
            count = f"{n} / {totals.get(key, 0)}" if filtered else str(n)
            header.setText(f"{_(_GROUP_NAMES[key])}  ·  {count}")
        self._update_action_bar()

    def _arrange(self) -> None:
        """Grille unique rangée par rubrique (Vidéos, Enregistrements, Images, Sons,
        Musique), chacune sous un intertitre ; ordre d'import dans chaque rubrique."""
        by_group: dict[str, list[str]] = {}
        for media_id, item in self._items.items():
            by_group.setdefault(item.data(ROLE_PAYLOAD).group, []).append(media_id)
        order = []
        for key, _t, _c in GROUPS:
            if by_group.get(key):
                order.append("#" + key)
                order += by_group[key]
        if order != self._order:
            chosen = {m.id for m in self.grid.selected_medias()} if self.grid.selectedItems() \
                else set()
            self.grid._hovered = None
            while self.grid.count():
                self.grid.takeItem(0)  # (les objets restent gardés dans les dictionnaires)
            for key in order:
                if key.startswith("#"):
                    header = self._headers.get(key[1:])
                    if header is None:
                        header = QListWidgetItem()
                        header.setData(ROLE_HEADER, key[1:])
                        header.setFlags(Qt.ItemFlag.NoItemFlags)
                        self._headers[key[1:]] = header
                    self.grid.addItem(header)
                else:
                    self.grid.addItem(self._items[key])
                    if key in chosen:
                        self._items[key].setSelected(True)
            for key in [k for k in self._headers if "#" + k not in order]:
                del self._headers[key]
            self._order = order
        self._apply_filters()

    def set_thumbnail(self, media_id: str, thumbnail: str) -> None:
        item = self._items.get(media_id)
        if item is not None:
            item.setData(Qt.ItemDataRole.DecorationRole, QPixmap(thumbnail))

    def remove_media(self, media_id: str) -> None:
        item = self._items.pop(media_id, None)
        if item is not None:
            if self.grid._hovered is item:
                self.grid._hovered = None
            self.grid.takeItem(self.grid.row(item))
            self._arrange()
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
        media = item.data(ROLE_PAYLOAD) if item is not None else None
        menu = QMenu(self)
        if media is None:  # clic droit dans le vide ou sur un intertitre
            if self._items:
                self._selection_actions(menu)
                menu.addSeparator()
            menu.addAction(_("Importer des fichiers…"), self.importRequested)
            menu.exec(self.grid.viewport().mapToGlobal(pos))
            return
        chosen = self.grid.selected_medias()
        if len(chosen) > 1 and media in chosen:  # clic droit dans une sélection multiple
            n = len(chosen)
            menu.addAction(_("Ajouter les {n} médias à la timeline").format(n=n),
                           lambda: self.addManyRequested.emit(chosen))
            menu.addAction(_("Retirer les {n} médias du projet").format(n=n),
                           lambda: self.removeManyRequested.emit(chosen))
            menu.addSeparator()
            self._selection_actions(menu)
            menu.exec(self.grid.viewport().mapToGlobal(pos))
            return
        menu.addAction(_("Ajouter à la timeline"),
                       lambda: self.addToTimelineRequested.emit(media))
        if media.exists:
            menu.addAction(_("Modifier le média…"), lambda: self.editRequested.emit(media))
            if media.kind in ("video", "image") and media.width and media.height:
                menu.addAction(_("Ajuster le cadre à ce média"),
                               lambda: self.fitCanvasRequested.emit(media))
        else:
            menu.addAction(_("Relier à un fichier…"), lambda: self.relinkRequested.emit(media))
        if media.kind == "audio":
            if media.group == "music":
                menu.addAction(_("Classer dans Sons"),
                               lambda: self.categoryRequested.emit(media, "sound"))
            else:
                menu.addAction(_("Classer dans Musique"),
                               lambda: self.categoryRequested.emit(media, "music"))
        menu.addAction(_("Retirer du projet"), lambda: self.removeRequested.emit(media))
        menu.addSeparator()
        self._selection_actions(menu)
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def refresh_groups(self) -> None:
        """Après un changement de rubrique (Musique / Sons)."""
        self._arrange()


_PIXMAPS: dict[str, QPixmap] = {}


def _pixmap(path: str) -> QPixmap:
    """Vignette lue une fois (la liste des médias se reconstruit sans relire le disque)."""
    pm = _PIXMAPS.get(path)
    if pm is None:
        if len(_PIXMAPS) > 2000:
            _PIXMAPS.clear()
        pm = _PIXMAPS[path] = QPixmap(path)
    return pm
