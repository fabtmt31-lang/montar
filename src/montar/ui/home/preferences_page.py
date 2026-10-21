# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences (maquette 06)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from montar.core.settings import Settings
from montar.i18n import _
from montar.ui.widgets import Segmented, button, label

_THEME_PREVIEW = {
    "light": ("#F4F8F5", "#FFFFFF", "#D8E4DC"),
    "dark": ("#17261E", "#24362C", "#9CCBB0"),
    "system": ("#F4F8F5", "#17261E", "#17261E"),
}


class _ThemeCard(QPushButton):
    def __init__(self, key: str, text: str) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setProperty("variant", "tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        bg, bar, border = _THEME_PREVIEW[key]
        preview = QFrame()
        preview.setFixedHeight(68)
        preview.setStyleSheet(f"background: {bg}; border: 1px solid #D8E4DC; border-radius: 8px;")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.addStretch()
        b = QFrame()
        b.setFixedSize(144, 14)
        b.setStyleSheet(f"background: {bar}; border: 1px solid {border}; border-radius: 4px;")
        pl.addWidget(b)
        layout.addWidget(preview)
        t = label(text)
        t.setStyleSheet("font-weight: 700;")
        layout.addWidget(t)
        for w in (preview, b, t):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def _row(title: str, subtitle: str, control: QWidget) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 14, 0, 14)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    t = label(title)
    t.setStyleSheet("font-weight: 700;")
    texts.addWidget(t)
    sub = label(subtitle, "small")
    texts.addWidget(sub)
    layout.addLayout(texts, 1)
    layout.addWidget(control)
    row.subtitle_label = sub  # type: ignore[attr-defined]
    return row


class PreferencesPage(QWidget):
    themeChanged = pyqtSignal(str)
    settingsChanged = pyqtSignal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.settings = settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(20)
        layout.addWidget(label(_("Préférences"), "h1"))

        appearance = QFrame()
        appearance.setProperty("card", True)
        al = QVBoxLayout(appearance)
        al.setContentsMargins(24, 22, 24, 24)
        al.addWidget(label(_("Apparence"), "h3"))
        al.addSpacing(10)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self._theme_group = QButtonGroup(self)
        self._theme_cards: dict[str, _ThemeCard] = {}
        for key, text in (("light", _("Clair")), ("dark", _("Sombre")),
                          ("system", _("Système"))):
            c = _ThemeCard(key, text)
            c.setChecked(settings.theme == key)
            c.clicked.connect(lambda _=False, k=key: self._set_theme(k))
            self._theme_group.addButton(c)
            self._theme_cards[key] = c
            cards.addWidget(c, 1)
        al.addLayout(cards)
        layout.addWidget(appearance)

        general = QFrame()
        general.setProperty("card", True)
        gl = QVBoxLayout(general)
        gl.setContentsMargins(24, 8, 24, 8)
        change = button(_("Modifier…"), "secondary")
        change.clicked.connect(self._choose_folder)
        self._folder_row = _row(_("Dossier des projets"), str(settings.projects_path), change)
        self._folder_row.subtitle_label.setProperty("role", "mono")  # type: ignore[attr-defined]
        gl.addWidget(self._folder_row)
        self.quality = Segmented([("low", _("Basse")), ("medium", _("Moyenne")),
                                  ("full", _("Pleine"))], settings.preview_quality)
        self.quality.changed.connect(self._set_quality)
        gl.addWidget(_row(_("Qualité de l'aperçu"),
                          _("Réduisez-la sur une machine moins puissante"), self.quality))
        layout.addWidget(general)
        layout.addStretch()

    def _set_theme(self, key: str) -> None:
        self.settings.theme = key
        self.themeChanged.emit(key)
        self.settingsChanged.emit()

    def _set_quality(self, key: str) -> None:
        self.settings.preview_quality = key
        self.settingsChanged.emit()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, _("Dossier des projets"), str(self.settings.projects_path))
        if folder:
            self.settings.projects_dir = folder
            self._folder_row.subtitle_label.setText(folder)  # type: ignore[attr-defined]
            self.settingsChanged.emit()
