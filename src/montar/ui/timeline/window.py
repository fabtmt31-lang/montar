# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre séparée de la timeline, pour la placer sur un autre écran."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from montar.i18n import _


class TimelineWindow(QWidget):
    """Fenêtre de premier niveau (enfant de l'écran de montage, fermée avec lui) ; la fermer
    remet la timeline dans l'écran de montage."""

    closed = pyqtSignal()

    def __init__(self, parent: QWidget, project_name: str) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("Page")
        self.setWindowTitle(_("Timeline — {name}").format(name=project_name))
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.resize(1400, 420)

    def hold(self, panel: QWidget) -> None:
        self.layout_.addWidget(panel)
        panel.show()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)
