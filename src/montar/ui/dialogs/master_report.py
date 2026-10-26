# SPDX-License-Identifier: GPL-3.0-or-later
"""Fin d'un export avec la finition pro : rapport de conformité (cible, résultat)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from montar.engine.export import human_size
from montar.i18n import _
from montar.ui.widgets import button, label


class MasterReportDialog(QDialog):
    def __init__(self, job, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.setWindowTitle(_("Export terminé"))
        self.setModal(True)
        self.setMinimumWidth(560)
        target = Path(job.settings.path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = label(_("Vidéo exportée") if not job.settings.audio_only else _("Son exporté"),
                      "h2")
        layout.addWidget(title)
        size = human_size(target.stat().st_size).lstrip("≈ ") if target.exists() else ""
        layout.addWidget(label(_("{name} · {size} · rapport de finition").format(
            name=target.name, size=size), "muted"))

        table = QFrame()
        table.setProperty("card", True)
        grid = QGridLayout(table)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for col, text in enumerate((_("Mesure"), _("Cible"), _("Résultat"), "")):
            grid.addWidget(label(text, "section"), 0, col)
        self.rows = []
        for row, item in enumerate(job.report, start=1):
            grid.addWidget(label(item.label), row, 0)
            grid.addWidget(label(item.target, "mono"), row, 1)
            result = label(item.result, "mono")
            result.setStyleSheet("font-weight: 600;")
            grid.addWidget(result, row, 2)
            mark = label("✓" if item.ok else "⚠")
            mark.setStyleSheet(f"color: {'#2F7A56' if item.ok else '#C2410C'}; "
                               "font-weight: 800; font-size: 16px;")
            mark.setToolTip(_("Conforme") if item.ok else _("Hors cible"))
            grid.addWidget(mark, row, 3, Qt.AlignmentFlag.AlignCenter)
            self.rows.append(item)
        grid.setColumnStretch(0, 1)
        if job.report:
            layout.addWidget(table)
        for note in job.notes:
            text = label(note, "small")
            text.setWordWrap(True)
            layout.addWidget(text)
        verdict = _("Tout est conforme.") if job.conform else \
            _("Certaines mesures sont hors cible : vérifiez le rapport.")
        layout.addWidget(label(verdict))
        if job.report_path:
            layout.addWidget(label(_("Rapport enregistré à côté de la vidéo ({name}).").format(
                name=Path(job.report_path).name), "small"))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        folder = button(_("Ouvrir le dossier"), "secondary", "folder-open")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(target.parent))))
        buttons.addWidget(folder)
        play = button(_("Lire"), "primary", "play")
        play.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))))
        buttons.addWidget(play)
        close = button(_("Fermer"), "secondary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
