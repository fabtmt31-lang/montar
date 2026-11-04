# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre « montar s'est fermé de façon inattendue », au démarrage suivant un plantage :
le rapport se copie d'un clic pour le transmettre."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from montar.i18n import _
from montar.ui.widgets import button, label


class CrashReportDialog(QDialog):
    def __init__(self, text: str, folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Rapport de plantage"))
        self.resize(760, 520)
        self.text = text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(label(_("montar s'est fermé de façon inattendue"), "h2"))
        hint = label(_("Le rapport ci-dessous indique où le problème s'est produit. Copiez-le "
                       "et transmettez-le pour qu'il soit corrigé. Il ne contient que des "
                       "informations techniques (versions, fichiers de montar)."), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        self.copy_button = button(_("Copier le rapport"), "primary", "copy")
        self.copy_button.clicked.connect(self.copy)
        folder_button = button(_("Ouvrir le dossier des journaux"), "secondary", "folder")
        folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
        close = button(_("Fermer"), "secondary")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(folder_button)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.copy_button.setText(_("Rapport copié"))
