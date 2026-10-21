# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences → Extensions : modules intégrés et installés (cahier des charges §3.11)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.plugins import ModuleError, ModuleManager
from montar.plugins.manager import ARCHIVE_SUFFIX
from montar.ui.widgets import button, label


class ExtensionsCard(QFrame):
    disabledChanged = pyqtSignal(list)  # identifiants des modules désactivés

    def __init__(self, manager: ModuleManager) -> None:
        super().__init__()
        self.setProperty("card", True)
        self.manager = manager
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label(_("Extensions"), "h3"))
        head.addStretch()
        folder = button(_("Ouvrir le dossier des modules"), "secondary", "folder-open")
        folder.clicked.connect(self._open_folder)
        install = button(_("Installer un module…"), "primary", "plus")
        install.clicked.connect(self.install)
        head.addWidget(folder)
        head.addWidget(install)
        layout.addLayout(head)
        hint = label(_("Les modules ajoutent des effets et des outils. Ils sont écrits en "
                       "Python et s'installent depuis un fichier local ({ext}).").format(
                           ext=ARCHIVE_SUFFIX), "small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._list = QVBoxLayout()
        self._list.setSpacing(0)
        layout.addLayout(self._list)
        manager.listeners.append(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        while self._list.count():
            w = self._list.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for info in sorted(self.manager.modules.values(), key=lambda m: (not m.builtin, m.name)):
            self._list.addWidget(self._row(info))

    def _row(self, info) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 12, 0, 12)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        origin = _("intégré") if info.builtin else _("installé")
        title = label(f"{info.name}  ·  {info.version}  ·  {origin}")
        title.setStyleSheet("font-weight: 700;")
        texts.addWidget(title)
        if info.description:
            d = label(info.description, "small")
            d.setWordWrap(True)
            texts.addWidget(d)
        if info.author:
            texts.addWidget(label(_("Auteur : {a}").format(a=info.author), "small"))
        if info.error:
            e = label(_("Erreur : {e}").format(e=info.error), "small")
            e.setStyleSheet("color: #B4452F;")
            e.setWordWrap(True)
            texts.addWidget(e)
        layout.addLayout(texts, 1)
        if not info.builtin:
            remove = button(_("Supprimer"), "secondary", "trash-2")
            remove.clicked.connect(lambda _=False, i=info.id: self._uninstall(i))
            layout.addWidget(remove)
        toggle = QCheckBox(_("Activé"))
        toggle.setChecked(info.enabled and not info.error)
        toggle.toggled.connect(lambda on, i=info.id: self._toggle(i, on))
        layout.addWidget(toggle)
        return row

    def _toggle(self, module_id: str, enabled: bool) -> None:
        self.manager.set_enabled(module_id, enabled)
        self.disabledChanged.emit(sorted(self.manager.disabled))

    def _uninstall(self, module_id: str) -> None:
        answer = QMessageBox.question(self, _("Supprimer le module"),
                                      _("Supprimer le module « {m} » ?").format(m=module_id))
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.manager.uninstall(module_id)
            except ModuleError as exc:
                QMessageBox.warning(self, _("Supprimer le module"), str(exc))

    def install(self, archive: str | None = None, confirm: bool = True) -> None:
        if archive is None:
            archive, _f = QFileDialog.getOpenFileName(
                self, _("Installer un module"), str(Path.home()),
                _("Modules montar") + f" (*{ARCHIVE_SUFFIX} *.zip)")
            if not archive:
                return
        try:
            data = self.manager.inspect_archive(Path(archive))
        except ModuleError as exc:
            QMessageBox.warning(self, _("Installer un module"), str(exc))
            return
        if confirm:
            permissions = ", ".join(data.get("permissions", [])) or _("aucune")
            answer = QMessageBox.question(
                self, _("Installer un module"),
                _("Installer « {name} » {version} de {author} ?\n\n"
                  "Permissions demandées : {perms}.\n\n"
                  "Un module s'exécute avec vos droits sur cet ordinateur : n'installez que "
                  "des modules de confiance.").format(
                      name=data["name"], version=data["version"],
                      author=data.get("author") or _("auteur inconnu"), perms=permissions))
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            info = self.manager.install(Path(archive))
        except ModuleError as exc:
            QMessageBox.warning(self, _("Installer un module"), str(exc))
            return
        self.disabledChanged.emit(sorted(self.manager.disabled))
        if info.error:
            QMessageBox.warning(self, _("Installer un module"),
                                _("Le module est installé mais n'a pas pu être chargé :\n{e}")
                                .format(e=info.error))

    def _open_folder(self) -> None:
        self.manager.user_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.user_dir)))
