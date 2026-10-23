# SPDX-License-Identifier: GPL-3.0-or-later
"""Écran d'accueil (maquette 01) : création rapide et projets récents."""
from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from montar.core.recent import RecentEntry
from montar.i18n import _
from montar.platform.paths import user_first_name
from montar.ui.theme import theme
from montar.ui.thumbgrid import ROLE_ICON, ROLE_PAYLOAD, ROLE_PLACEHOLDER, ROLE_SUBTITLE, ThumbGrid
from montar.ui.widgets import Segmented, button, label, logo, set_icon

# Couleur et rapport largeur/hauteur de l'aperçu de format sur les tuiles.
_FORMAT_SWATCH = {"16:9": ("mist", 66, 37), "9:16": ("pistachio", 24, 40),
                  "1:1": ("water", 38, 38)}
_PLACEHOLDER_BY_ASPECT = {"16:9": "mint", "9:16": "pistachio", "1:1": "water",
                          "4:5": "voiceover", "21:9": "mist"}


def ago(timestamp: float, now: float | None = None) -> str:
    """« à l'instant », « il y a 3 min », « hier », « le 12/10/2026 »…"""
    delta = max(0, (now or time.time()) - timestamp)
    if delta < 60:
        return _("à l'instant")
    if delta < 3600:
        return _("il y a {n} min").format(n=int(delta // 60))
    if delta < 86400:
        return _("il y a {n} h").format(n=int(delta // 3600))
    days = int(delta // 86400)
    if days == 1:
        return _("hier")
    if days < 7:
        return _("il y a {n} jours").format(n=days)
    if days < 14:
        return _("la semaine dernière")
    return _("le {date}").format(date=time.strftime("%d/%m/%Y", time.localtime(timestamp)))


def relative_time(timestamp: float, now: float | None = None) -> str:
    return _("Modifié {when}").format(when=ago(timestamp, now))


class _Swatch(QFrame):
    def __init__(self, role: str, w: int, h: int) -> None:
        super().__init__()
        self.setFixedSize(w, h)
        self._role = role
        theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        p = theme().palette
        self.setStyleSheet(f"background: {getattr(p, self._role)}; border-radius: 6px;"
                           f"border: 1px solid {p.sage};")


def _tile(title: str, subtitle: str, primary: bool = False,
          swatch: tuple[str, int, int] | None = None) -> QPushButton:
    tile = QPushButton()
    tile.setProperty("variant", "tile-primary" if primary else "tile")
    tile.setCursor(Qt.CursorShape.PointingHandCursor)
    tile.setMinimumSize(180, 148)
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(20, 20, 20, 18)
    layout.setSpacing(2)
    if primary:
        plus = QPushButton()
        plus.setFixedSize(40, 40)
        plus.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        plus.setStyleSheet("background: rgba(255,255,255,0.18); border: none; border-radius: 10px;")
        set_icon(plus, "plus", "on_forest", 20)
        layout.addWidget(plus, 0, Qt.AlignmentFlag.AlignLeft)
    elif swatch:
        role, w, h = swatch
        holder = QWidget()
        holder.setFixedHeight(40)
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(_Swatch(role, w, h), 0,
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(holder)
    layout.addStretch()
    t = label(title, "h3")
    s = label(subtitle, "small")
    if primary:
        s.setStyleSheet("color: rgba(255,255,255,0.85);")
    for w in (t, s):
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(w)
    return tile


class ProjectList(QWidget):
    """Projets récents en grille ou en liste."""

    openRequested = pyqtSignal(object)  # Path
    duplicateRequested = pyqtSignal(object)  # Path
    deleteRequested = pyqtSignal(object)  # Path

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.grid = ThumbGrid(min_width=230, aspect=16 / 10, title_px=15, radius=16)
        self.grid.itemActivated.connect(self._activate)
        self.grid.itemClicked.connect(self._activate)
        self.grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.empty = QFrame()
        self.empty.setObjectName("EmptyState")
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(24, 32, 24, 32)
        msg = label(_("Aucun projet pour l'instant. Créez-en un ou importez des médias "
                      "pour commencer."), "muted")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        el.addWidget(msg)
        layout.addWidget(self.grid)
        layout.addWidget(self.empty)
        self._entries: list[RecentEntry] = []
        self._filter = ""
        self._thumb_for = None

    def set_thumbnail_provider(self, provider) -> None:
        """provider(media_path) -> chemin de vignette ou None."""
        self._thumb_for = provider

    def set_entries(self, entries: list[RecentEntry]) -> None:
        self._entries = entries
        self._rebuild()

    def set_filter(self, text: str) -> None:
        self._filter = text.strip().lower()
        self._rebuild()

    def set_list_mode(self, as_list: bool) -> None:
        self.grid.set_list_mode(as_list)
        self._fit()

    def _rebuild(self) -> None:
        self.grid.clear()
        shown = [e for e in self._entries if self._filter in e.name.lower()]
        for e in shown:
            item = QListWidgetItem(e.name)
            item.setData(ROLE_SUBTITLE, f"{relative_time(e.modified)} · {e.aspect}")
            item.setData(ROLE_PLACEHOLDER, _PLACEHOLDER_BY_ASPECT.get(e.aspect, "mint"))
            item.setData(ROLE_ICON, "film")
            item.setData(ROLE_PAYLOAD, str(e.path))
            item.setToolTip(str(e.path))
            if e.thumbnail_media and self._thumb_for:
                thumb = self._thumb_for(e.thumbnail_media)
                if thumb:
                    item.setData(Qt.ItemDataRole.DecorationRole, QPixmap(str(thumb)))
            self.grid.addItem(item)
        self.empty.setVisible(not shown)
        self.grid.setVisible(bool(shown))
        self._fit()

    def _fit(self) -> None:
        self.grid.setFixedHeight(max(0, self.grid.content_height()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _activate(self, item: QListWidgetItem) -> None:
        self.openRequested.emit(Path(item.data(ROLE_PAYLOAD)))

    def _context_menu(self, pos) -> None:
        item = self.grid.itemAt(pos)
        if item is None:
            return
        path = Path(item.data(ROLE_PAYLOAD))
        menu = QMenu(self)
        menu.addAction(_("Ouvrir"), lambda: self.openRequested.emit(path))
        menu.addAction(_("Dupliquer"), lambda: self.duplicateRequested.emit(path))
        menu.addAction(_("Ouvrir le dossier"), lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(path.parent))))
        menu.addSeparator()
        menu.addAction(_("Mettre à la corbeille"), lambda: self.deleteRequested.emit(path))
        menu.exec(self.grid.viewport().mapToGlobal(pos))


class HomePage(QWidget):
    newProjectRequested = pyqtSignal(object)  # format ("16:9"…) ou None pour le dialogue
    importRequested = pyqtSignal()
    openRequested = pyqtSignal(object)
    showAllRequested = pyqtSignal()

    def __init__(self, compact: bool = False) -> None:
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(40, 28, 40, 32)
        layout.setSpacing(0)

        # barre supérieure : recherche, importer, avatar
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setProperty("variant", "search")
        self.search.setPlaceholderText(_("Rechercher un projet…"))
        self.search.setMaximumWidth(560)
        self.search.setMinimumHeight(44)
        self._search_icon = QLabel(self.search)
        self._search_icon.move(13, 13)
        theme().changed.connect(self._refresh_search_icon)
        self._refresh_search_icon()
        top.addWidget(self.search, 1)
        top.addStretch()
        imp = button(_("Importer"), "secondary", "upload")
        imp.setMinimumHeight(44)
        imp.clicked.connect(self.importRequested)
        top.addWidget(imp)
        self._top = top
        name = user_first_name()
        avatar = QLabel((name[:1] or "?").upper())
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(44, 44)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addSpacing(8)
        top.addWidget(avatar)
        layout.addLayout(top)
        layout.addSpacing(36)

        if not compact:
            greet = _("Bonjour {name}").format(name=name) if name else _("Bonjour")
            layout.addWidget(label(greet, "h1"))
            layout.addSpacing(6)
            layout.addWidget(label(_("Que voulez-vous monter aujourd'hui ?"), "muted"))
            layout.addSpacing(20)
            tiles = QHBoxLayout()
            tiles.setSpacing(16)
            new = _tile(_("Nouveau projet"), _("Partir de zéro"), primary=True)
            new.clicked.connect(lambda: self.newProjectRequested.emit(None))
            tiles.addWidget(new, 1)
            for aspect, title, sub in (
                ("16:9", _("Paysage 16:9"), _("YouTube, présentation")),
                ("9:16", _("Vertical 9:16"), _("Reels, Shorts, TikTok")),
                ("1:1", _("Carré 1:1"), _("Publications sociales")),
            ):
                t = _tile(title, sub, swatch=_FORMAT_SWATCH[aspect])
                t.clicked.connect(lambda _=False, a=aspect: self.newProjectRequested.emit(a))
                tiles.addWidget(t, 1)
            layout.addLayout(tiles)
            layout.addSpacing(36)

        head = QHBoxLayout()
        head.addWidget(label(_("Mes projets") if compact else _("Projets récents"), "h2"))
        head.addStretch()
        self.view_mode = Segmented([("grid", _("Grille")), ("list", _("Liste"))])
        head.addWidget(self.view_mode)
        if not compact:
            see_all = button(_("Tout voir"), "link")
            see_all.clicked.connect(self.showAllRequested)
            head.addSpacing(8)
            head.addWidget(see_all)
        layout.addLayout(head)
        layout.addSpacing(14)
        self.projects = ProjectList()
        self.projects.openRequested.connect(self.openRequested)
        self.view_mode.changed.connect(lambda k: self.projects.set_list_mode(k == "list"))
        self.search.textChanged.connect(self.projects.set_filter)
        layout.addWidget(self.projects)
        layout.addStretch()
        self._compact = compact

    def _refresh_search_icon(self) -> None:
        from montar.ui.theme.icons import pixmap

        self._search_icon.setPixmap(pixmap("search", theme().palette.text_muted, 18))

    def set_notifications(self, notifications) -> None:
        from montar.ui.notifications import NotificationButton

        self.bell = NotificationButton(notifications)
        self.bell.setMinimumHeight(44)
        index = next(i for i in range(self._top.count())
                     if self._top.itemAt(i).widget() is not None
                     and self._top.itemAt(i).widget().objectName() == "Avatar")
        self._top.insertWidget(index - 1, self.bell)

    def set_entries(self, entries: list[RecentEntry]) -> None:
        self.projects.set_entries(entries if self._compact else entries[:8])


class HomeShell(QWidget):
    """Navigation latérale + pages (Accueil, Mes projets, Préférences)."""

    def __init__(self, home: HomePage, projects: HomePage, preferences: QWidget,
                 extra: list[tuple[str, str, str, QWidget]] = ()) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(240)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 24, 16, 16)
        sl.setSpacing(4)
        sl.addWidget(logo(34))
        sl.addSpacing(26)

        self.pages = QStackedWidget()
        self._group = QButtonGroup(self)
        self._nav: dict[str, QPushButton] = {}
        for key, text, icon, page in (
            ("home", _("Accueil"), "house", home),
            ("projects", _("Mes projets"), "folder-open", projects),
            *extra,
        ):
            sl.addWidget(self._nav_button(key, text, icon, page))
        sl.addStretch()
        sl.addWidget(self._nav_button("preferences", _("Préférences"), "settings", preferences))

        layout.addWidget(side)
        layout.addWidget(self.pages, 1)
        self.show_page("home")

    def _nav_button(self, key: str, text: str, icon: str, page: QWidget) -> QPushButton:
        btn = button(text, "nav", icon)
        btn.setIconSize(QSize(18, 18))
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self.show_page(key))
        self._group.addButton(btn)
        self._nav[key] = btn
        self.pages.addWidget(page)
        btn.setProperty("page_index", self.pages.count() - 1)
        return btn

    pageShown = pyqtSignal(str)

    def show_page(self, key: str) -> None:
        btn = self._nav[key]
        btn.setChecked(True)
        self.pages.setCurrentIndex(btn.property("page_index"))
        self.pageShown.emit(key)
