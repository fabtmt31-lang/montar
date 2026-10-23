# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences → « Catalogue de modules » (F-MOD-08) : liste des modules proposés en ligne,
installation et mise à jour. Désactivé par défaut : aucune connexion sans l'accord de
l'utilisateur."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from montar.api import API_VERSION
from montar.core import catalog
from montar.core.settings import Settings
from montar.i18n import _
from montar.ui.widgets import Switch, button, label

STATUS_LABELS = {"available": "Installer", "update": "Mettre à jour",
                 "installed": "Installé", "incompatible": "Version de montar trop ancienne"}


class _Signals(QObject):
    listed = pyqtSignal(object, str)  # entrées, erreur
    downloaded = pyqtSignal(object, object, str)  # entrée, archive, erreur


class _Fetch(QRunnable):
    def __init__(self, url: str, signals: _Signals) -> None:
        super().__init__()
        self.url, self.signals = url, signals

    def run(self) -> None:
        try:
            self.signals.listed.emit(catalog.fetch(self.url), "")
        except catalog.CatalogError as exc:
            self.signals.listed.emit([], str(exc))


class _Download(QRunnable):
    def __init__(self, entry: catalog.Entry, folder: Path, signals: _Signals) -> None:
        super().__init__()
        self.entry, self.folder, self.signals = entry, folder, signals

    def run(self) -> None:
        try:
            path = catalog.download(self.entry, self.folder)
            self.signals.downloaded.emit(self.entry, path, "")
        except catalog.CatalogError as exc:
            self.signals.downloaded.emit(self.entry, None, str(exc))


class CatalogCard(QFrame):
    changed = pyqtSignal()  # réglages du catalogue modifiés (à enregistrer)

    def __init__(self, settings: Settings, extensions) -> None:
        super().__init__()
        self.settings = settings
        self.extensions = extensions  # ExtensionsCard : installation et confirmation
        self.entries: list[catalog.Entry] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.listed.connect(self._on_listed)
        self._signals.downloaded.connect(self._on_downloaded)
        self._downloads: Path | None = None  # dossier temporaire, créé au premier besoin
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label(_("Catalogue de modules"), "h3"))
        head.addStretch()
        self.enabled = Switch(settings.catalog_enabled)
        self.enabled.toggled.connect(self._set_enabled)
        head.addWidget(self.enabled)
        layout.addLayout(head)
        hint = label(_("Facultatif : montar ne se connecte à internet que si vous l'activez, "
                       "et seulement pour lire la liste des modules ou en télécharger un. Chaque "
                       "archive est vérifiée (empreinte SHA-256) avant l'installation."), "small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.url = QLineEdit(settings.catalog_url or catalog.DEFAULT_URL)
        self.url.setPlaceholderText(catalog.DEFAULT_URL)
        self.url.editingFinished.connect(self._set_url)
        row.addWidget(self.url, 1)
        self.refresh_button = button(_("Actualiser"), "secondary", "rotate-ccw")
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.status = label("", "small")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._list = QVBoxLayout()
        self._list.setSpacing(0)
        layout.addLayout(self._list)
        self._update_enabled()

    # --- réglages ----------------------------------------------------------------------

    def _set_enabled(self, on: bool) -> None:
        self.settings.catalog_enabled = on
        self.changed.emit()
        self._update_enabled()
        if on:
            self.refresh()

    def _set_url(self) -> None:
        url = self.url.text().strip() or catalog.DEFAULT_URL
        if url != self.settings.catalog_url:
            self.settings.catalog_url = url
            self.changed.emit()

    def _update_enabled(self) -> None:
        on = self.settings.catalog_enabled
        for w in (self.url, self.refresh_button):
            w.setEnabled(on)
        if not on:
            self.entries = []
            self._show_entries()
            self.status.setText(_("Catalogue désactivé."))

    # --- liste ---------------------------------------------------------------------------

    def refresh(self) -> None:
        if not self.settings.catalog_enabled:
            return
        self._set_url()
        self.status.setText(_("Lecture du catalogue…"))
        self.refresh_button.setEnabled(False)
        self._pool.start(_Fetch(self.settings.catalog_url or catalog.DEFAULT_URL,
                                self._signals))

    def _on_listed(self, entries, error: str) -> None:
        self.refresh_button.setEnabled(self.settings.catalog_enabled)
        if not self.settings.catalog_enabled:
            return
        self.entries = list(entries)
        self.status.setText(_("Catalogue indisponible : {error}").format(error=error) if error
                            else _("{n} module(s) proposé(s).").format(n=len(self.entries)))
        self._show_entries()

    def installed_versions(self) -> dict[str, str]:
        return {m.id: m.version for m in self.extensions.manager.modules.values()
                if not m.builtin}

    def _show_entries(self) -> None:
        while self._list.count():
            w = self._list.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        installed = self.installed_versions()
        builtin = {m.id for m in self.extensions.manager.modules.values() if m.builtin}
        for entry in self.entries:
            if entry.id in builtin:
                continue  # déjà fourni avec montar
            self._list.addWidget(self._row(entry, catalog.status(entry, installed,
                                                                 API_VERSION)))

    def _row(self, entry: catalog.Entry, state: str) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 10, 0, 10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = label(f"{entry.name} · {entry.version}")
        title.setStyleSheet("font-weight: 700;")
        texts.addWidget(title)
        details = label(" · ".join(x for x in (entry.description, entry.author, entry.license)
                                   if x), "small")
        details.setWordWrap(True)
        texts.addWidget(details)
        layout.addLayout(texts, 1)
        action = button(_(STATUS_LABELS[state]),
                        "primary" if state in ("available", "update") else "secondary")
        action.setEnabled(state in ("available", "update"))
        action.clicked.connect(lambda _=False, e=entry: self.install(e))
        layout.addWidget(action)
        row.action = action  # type: ignore[attr-defined]
        row.entry = entry  # type: ignore[attr-defined]
        return row

    def rows(self) -> list[QWidget]:
        return [self._list.itemAt(i).widget() for i in range(self._list.count())]

    # --- installation ----------------------------------------------------------------------

    def install(self, entry: catalog.Entry) -> None:
        self.status.setText(_("Téléchargement de {name}…").format(name=entry.name))
        if self._downloads is None:
            self._downloads = Path(tempfile.mkdtemp(prefix="montar-catalogue-"))
        self._pool.start(_Download(entry, self._downloads, self._signals))

    def _on_downloaded(self, entry, archive, error: str) -> None:
        if error:
            self.status.setText(_("Installation impossible : {error}").format(error=error))
            return
        self.status.setText("")
        self.extensions.install(str(archive))  # confirmation, puis installation
        self._show_entries()
