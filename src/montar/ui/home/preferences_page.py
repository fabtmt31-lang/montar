# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences (maquette 06)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
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
from montar.ui.widgets import Segmented, Switch, button, label

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

    def __init__(self, settings: Settings, modules=None) -> None:
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
        language = QComboBox()
        language.addItem(_("Français"))
        language.setEnabled(False)
        language.setToolTip(_("Seule langue disponible pour le moment"))
        gl.addWidget(_row(_("Langue de l'interface"), _("Menus, info-bulles et raccourcis"),
                          language))
        self.switches: dict[str, Switch] = {}
        for key, title, subtitle in (
            ("hardware_export", _("Accélération matérielle"),
             _("Encodage de l'export par la carte graphique, si elle le permet")),
            ("video_waveforms", _("Ondes audio sur les clips vidéo"),
             _("Affiche la forme d'onde sous les vignettes")),
            ("snap", _("Magnétisme par défaut"),
             _("Les clips s'aimantent à la tête de lecture et aux bords")),
        ):
            switch = Switch(getattr(settings, key))
            switch.toggled.connect(lambda on, k=key: self._set_flag(k, on))
            self.switches[key] = switch
            gl.addWidget(_row(title, subtitle, switch))
        layout.addWidget(general)
        if modules is not None:
            from montar.ui.home.extensions import ExtensionsCard

            self.extensions = ExtensionsCard(modules)
            self.extensions.disabledChanged.connect(self._set_disabled)
            layout.addWidget(self.extensions)
        layout.addStretch()

    def _set_theme(self, key: str) -> None:
        self.settings.theme = key
        self.themeChanged.emit(key)
        self.settingsChanged.emit()

    def _set_disabled(self, disabled: list) -> None:
        self.settings.disabled_modules = list(disabled)
        self.settingsChanged.emit()

    def _set_flag(self, key: str, on: bool) -> None:
        setattr(self.settings, key, on)
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
