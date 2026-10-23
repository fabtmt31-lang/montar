# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences (maquette 06)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from montar.core import storage
from montar.core.settings import ACCENTS, BACKUP_INTERVALS, TRASH_DAYS, Settings
from montar.engine.export import human_size
from montar.i18n import LANGUAGES, _
from montar.ui.widgets import Segmented, Switch, button, label, shrink

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
    sub.setWordWrap(True)
    shrink(sub)  # un long chemin ne doit pas élargir la page
    texts.addWidget(sub)
    layout.addLayout(texts, 1)
    layout.addWidget(control)
    row.subtitle_label = sub  # type: ignore[attr-defined]
    return row


class PreferencesPage(QWidget):
    themeChanged = pyqtSignal(str)
    accentChanged = pyqtSignal(str)
    settingsChanged = pyqtSignal()
    cacheCleared = pyqtSignal()

    def __init__(self, settings: Settings, modules=None, cache: Path | None = None,
                 project_paths: Callable[[], list[Path]] | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.settings = settings
        self.cache = cache
        self._project_paths = project_paths or (lambda: [])
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
        al.addSpacing(12)
        accents = QHBoxLayout()
        accents.setSpacing(10)
        accents.addWidget(label(_("Couleur d'accent")))
        accents.addSpacing(8)
        self._accent_group = QButtonGroup(self)
        self.accent_buttons: dict[str, QPushButton] = {}
        for color in ACCENTS:
            b = QPushButton()
            b.setCheckable(True)
            b.setFixedSize(30, 30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(color)
            b.setStyleSheet(f"QPushButton {{ background: {color}; border-radius: 15px; "
                            "border: 2px solid transparent; padding: 0; }"
                            "QPushButton:checked { border: 3px solid #17261E; }")
            b.setChecked(color.upper() == settings.accent.upper())
            b.clicked.connect(lambda _=False, c=color: self._set_accent(c))
            self._accent_group.addButton(b)
            self.accent_buttons[color] = b
            accents.addWidget(b)
        accents.addStretch()
        al.addLayout(accents)
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
        self.language = QComboBox()
        self.language.addItem(_("Système (langue de l'ordinateur)"), "system")
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.language.currentIndexChanged.connect(self._set_language)
        gl.addWidget(_row(_("Langue de l'interface"), _("Menus, info-bulles et raccourcis"),
                          self.language))
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
        layout.addWidget(self._saving_card(settings))
        if cache is not None:
            layout.addWidget(self._storage_card(cache))
        if modules is not None:
            from montar.ui.home.extensions import ExtensionsCard

            self.extensions = ExtensionsCard(modules)
            self.extensions.disabledChanged.connect(self._set_disabled)
            layout.addWidget(self.extensions)
        layout.addStretch()

    def _saving_card(self, settings: Settings) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 18, 24, 8)
        cl.addWidget(label(_("Projets & sauvegarde"), "h3"))
        self.autosave = Switch(settings.autosave)
        self.autosave.toggled.connect(lambda on: self._set_flag("autosave", on))
        cl.addWidget(_row(_("Sauvegarde automatique"),
                          _("Le projet est enregistré à chaque modification ; sinon avec "
                            "Ctrl+S, et montar le propose à la fermeture"), self.autosave))
        self.backup_interval = Segmented(
            [(str(m), _("{n} min").format(n=m)) for m in BACKUP_INTERVALS],
            str(settings.backup_minutes))
        self.backup_interval.changed.connect(self._set_backup_interval)
        cl.addWidget(_row(_("Copies de sauvegarde"),
                          _("Intervalle entre deux copies datées du projet, gardées dans "
                            "son dossier « sauvegardes » (les 10 dernières)"),
                          self.backup_interval))
        self.trash_days = Segmented(
            [(str(d), _("{n} jours").format(n=d)) for d in TRASH_DAYS], str(settings.trash_days))
        self.trash_days.changed.connect(self._set_trash_days)
        cl.addWidget(_row(_("Corbeille"), _("Durée avant l'effacement définitif d'un projet "
                                             "supprimé"), self.trash_days))
        return card

    def _storage_card(self, cache: Path) -> QFrame:
        card = QFrame()
        card.setProperty("card", True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 18, 24, 8)
        cl.addWidget(label(_("Stockage & cache"), "h3"))
        buttons = QWidget()
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        open_button = button(_("Ouvrir"), "secondary", "folder-open", tooltip=str(cache))
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(cache))))
        self.clear_cache_button = button(_("Vider le cache"), "secondary", "trash-2")
        self.clear_cache_button.clicked.connect(self._clear_cache)
        bl.addWidget(open_button)
        bl.addWidget(self.clear_cache_button)
        self._cache_row = _row(_("Cache"), "", buttons)
        cl.addWidget(self._cache_row)
        self._backups_row = _row(_("Sauvegardes des projets"), "", QWidget())
        cl.addWidget(self._backups_row)
        self._disk_row = _row(_("Espace libre"), "", QWidget())
        cl.addWidget(self._disk_row)
        self.refresh_storage()
        return card

    def refresh_storage(self) -> None:
        """Tailles recalculées à chaque affichage de la page."""
        if self.cache is None:
            return
        size = storage.cache_size(self.cache)
        self._cache_row.subtitle_label.setText(  # type: ignore[attr-defined]
            _("{size} — vignettes, formes d'onde, textes, calculs des modules").format(
                size=_size(size)))
        self._cache_row.subtitle_label.setToolTip(str(self.cache))  # type: ignore[attr-defined]
        self.clear_cache_button.setEnabled(size > 0)
        count, used = storage.backups_usage(self._project_paths())
        self._backups_row.subtitle_label.setText(  # type: ignore[attr-defined]
            _("{n} copies · {size}, dans le dossier « sauvegardes » de chaque projet").format(
                n=count, size=_size(used)) if count else _("Aucune copie pour l'instant"))
        free = storage.free_space(self.settings.projects_path)
        self._disk_row.subtitle_label.setText(  # type: ignore[attr-defined]
            _("{size} sur le disque du dossier des projets").format(size=_size(free))
            if free is not None else _("inconnu"))

    def _clear_cache(self) -> None:
        answer = QMessageBox.question(
            self, _("Vider le cache"),
            _("Supprimer le cache ? Vignettes, formes d'onde et calculs des modules (Timelapse…) "
              "seront refaits quand ils seront nécessaires. Les projets et leurs médias ne sont "
              "pas touchés."))
        if answer == QMessageBox.StandardButton.Yes:
            storage.clear_cache(self.cache)
            self.refresh_storage()
            self.cacheCleared.emit()

    def _set_language(self, _index: int) -> None:
        code = self.language.currentData()
        if code == self.settings.language:
            return
        self.settings.language = code
        self.settingsChanged.emit()
        QMessageBox.information(self, _("Langue"), _(
            "Le changement de langue prendra effet au prochain démarrage de montar."))

    def _set_backup_interval(self, key: str) -> None:
        self.settings.backup_minutes = int(key)
        self.settingsChanged.emit()

    def _set_accent(self, color: str) -> None:
        self.settings.accent = color
        self.accentChanged.emit(color)
        self.settingsChanged.emit()

    def _set_trash_days(self, key: str) -> None:
        self.settings.trash_days = int(key)
        self.settingsChanged.emit()

    def _set_theme(self, key: str) -> None:
        self.settings.theme = key
        self.themeChanged.emit(key)
        self.settingsChanged.emit()

    def set_disabled_modules(self, disabled: list) -> None:
        self._set_disabled(disabled)
        if hasattr(self, "extensions"):
            self.extensions.refresh()

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


def _size(size: int) -> str:
    return human_size(size).lstrip("≈ ") if size else _("vide")
