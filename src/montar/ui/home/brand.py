# SPDX-License-Identifier: GPL-3.0-or-later
"""Accueil → Kit de marque (F-PRJ-13) : logos, couleurs et polices réutilisables dans tous
les projets (panneau Graphiques, couleurs et polices des textes)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from montar.core.brand import FONT_EXTENSIONS, LOGO_EXTENSIONS, BrandError, BrandKit
from montar.i18n import _
from montar.ui.widgets import button, label

_FONT_IDS: dict[str, int] = {}  # police déjà chargée → identifiant Qt


def brand_families(kit: BrandKit) -> list[str]:
    """Charge les polices du kit dans l'application ; renvoie leurs familles."""
    families: list[str] = []
    for path in kit.fonts():
        key = str(path)
        if key not in _FONT_IDS:
            _FONT_IDS[key] = QFontDatabase.addApplicationFont(key)
        if _FONT_IDS[key] >= 0:
            for family in QFontDatabase.applicationFontFamilies(_FONT_IDS[key]):
                if family not in families:
                    families.append(family)
    return families


def logo_pixmap(path: Path, size: QSize) -> QPixmap:
    image = QImage(str(path))
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))


def _card(title: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setProperty("card", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(24, 18, 24, 18)
    layout.setSpacing(10)
    layout.addWidget(label(title, "h3"))
    text = label(hint, "small")
    text.setWordWrap(True)
    layout.addWidget(text)
    return card, layout


class BrandPage(QWidget):
    changed = pyqtSignal()  # logos, couleurs ou polices modifiés

    LOGO_SIZE = QSize(120, 80)

    def __init__(self, kit: BrandKit) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.kit = kit
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(16)
        layout.addWidget(label(_("Kit de marque"), "h1"))
        hint = label(_("Vos logos, couleurs et polices, disponibles dans tous les projets : "
                       "logos dans le panneau Graphiques, couleurs et polices dans les "
                       "réglages des textes."), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        card, cl = _card(_("Logos"), _("PNG (de préférence transparent), JPEG, WebP ou SVG. "
                                       "Clic droit pour retirer."))
        self.logos = QListWidget()
        self.logos.setViewMode(QListWidget.ViewMode.IconMode)
        self.logos.setIconSize(self.LOGO_SIZE)
        self.logos.setGridSize(QSize(150, 120))
        self.logos.setFixedHeight(150)
        self.logos.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.logos.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.logos.customContextMenuRequested.connect(
            lambda pos: self._remove_menu(self.logos, pos))
        cl.addWidget(self.logos)
        add_logo = button(_("Ajouter un logo…"), "secondary", "plus")
        add_logo.clicked.connect(self._choose_logo)
        cl.addWidget(add_logo, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)

        card, cl = _card(_("Couleurs"), _("Elles s'ajoutent aux pastilles de couleur des "
                                          "textes. Cliquez sur une couleur pour la retirer."))
        self.colors_row = QHBoxLayout()
        self.colors_row.setSpacing(8)
        cl.addLayout(self.colors_row)
        layout.addWidget(card)

        card, cl = _card(_("Polices"), _("Fichiers TTF ou OTF ; elles apparaissent dans la "
                                         "liste des polices des textes. Clic droit pour "
                                         "retirer."))
        self.fonts = QListWidget()
        self.fonts.setFixedHeight(130)
        self.fonts.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fonts.customContextMenuRequested.connect(
            lambda pos: self._remove_menu(self.fonts, pos))
        cl.addWidget(self.fonts)
        add_font = button(_("Ajouter une police…"), "secondary", "plus")
        add_font.clicked.connect(self._choose_font)
        cl.addWidget(add_font, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        self.logos.clear()
        for path in self.kit.logos():
            item = QListWidgetItem(QIcon(logo_pixmap(path, self.LOGO_SIZE)), path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.logos.addItem(item)
        while self.colors_row.count():
            w = self.colors_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for color in self.kit.colors:
            swatch = QPushButton(self)
            swatch.setFixedSize(34, 34)
            swatch.setToolTip(_("{color} — cliquer pour retirer").format(color=color))
            swatch.setStyleSheet(f"QPushButton {{ background: {color}; border-radius: 17px;"
                                 " border: 1px solid #9CCBB0; padding: 0; }")
            swatch.clicked.connect(lambda _=False, c=color: self.remove_color(c))
            self.colors_row.addWidget(swatch)
        add = QPushButton("+", self)
        add.setFixedSize(34, 34)
        add.setToolTip(_("Ajouter une couleur"))
        add.setStyleSheet("QPushButton { border-radius: 17px; border: 1.5px dashed #9CCBB0;"
                          " padding: 0; font-weight: 700; }")
        add.clicked.connect(self._choose_color)
        self.colors_row.addWidget(add)
        self.colors_row.addStretch()
        self.fonts.clear()
        brand_families(self.kit)  # charge les polices avant de les montrer
        for path in self.kit.fonts():
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            font_id = _FONT_IDS.get(str(path), -1)
            names = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            if names:
                item.setText(f"{names[0]} — {_('Portez ce vieux whisky au juge blond')}")
                item.setFont(QFont(names[0], 13))
            self.fonts.addItem(item)

    # --- ajouts et retraits ------------------------------------------------------------

    def add_logo(self, path: Path) -> bool:
        return self._add(lambda: self.kit.add_logo(path))

    def add_font(self, path: Path) -> bool:
        return self._add(lambda: self.kit.add_font(path))

    def add_color(self, color: str) -> bool:
        return self._add(lambda: self.kit.add_color(color))

    def _add(self, action) -> bool:
        try:
            action()
        except (OSError, BrandError) as exc:
            QMessageBox.warning(self, _("Kit de marque"), str(exc))
            return False
        self.refresh()
        self.changed.emit()
        return True

    def remove_color(self, color: str) -> None:
        self.kit.remove_color(color)
        self.refresh()
        self.changed.emit()

    def remove_file(self, path: Path) -> None:
        self.kit.remove(path)
        self.refresh()
        self.changed.emit()

    def _remove_menu(self, widget: QListWidget, pos) -> None:
        item = widget.itemAt(pos)
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        menu.addAction(_("Retirer du kit"), lambda: self.remove_file(path))
        menu.exec(widget.viewport().mapToGlobal(pos))

    def _choose_logo(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(LOGO_EXTENSIONS))
        names, _f = QFileDialog.getOpenFileNames(self, _("Ajouter un logo"), str(Path.home()),
                                                 _("Images") + f" ({patterns})")
        for name in names:
            self.add_logo(Path(name))

    def _choose_font(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(FONT_EXTENSIONS))
        names, _f = QFileDialog.getOpenFileNames(self, _("Ajouter une police"),
                                                 str(Path.home()),
                                                 _("Polices") + f" ({patterns})")
        for name in names:
            self.add_font(Path(name))

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor("#2F7A56"), self, _("Ajouter une couleur"))
        if color.isValid():
            self.add_color(color.name().upper())
