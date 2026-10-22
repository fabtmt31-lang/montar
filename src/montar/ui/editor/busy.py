# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre d'avancement des calculs longs (module, export) : posée sur l'écran de montage,
elle empêche de modifier le projet pendant le calcul et permet de l'annuler."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from montar.i18n import _
from montar.ui.widgets import button, label


def remaining_text(elapsed: float, ratio: float) -> str:
    """« moins d'une minute », « 3 min restantes »… ; vide tant que l'estimation est floue."""
    if ratio < 0.03 or elapsed < 2:
        return ""
    left = elapsed / ratio * (1 - ratio)
    if left < 60:
        return _("moins d'une minute")
    return _("{n} min restantes").format(n=round(left / 60))


class BusyOverlay(QWidget):
    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("BusyOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card = QFrame()
        card.setObjectName("BusyCard")
        card.setFixedWidth(520)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 28)
        cl.setSpacing(12)
        self.title = label("", "h2")
        self.title.setWordWrap(True)
        self.detail = label(_("Le projet ne peut pas être modifié pendant ce calcul."), "muted")
        self.detail.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setObjectName("BusyBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(12)
        row = QHBoxLayout()
        self.percent = label("0 %", "h3")
        self.remaining = label("", "muted")
        row.addWidget(self.percent)
        row.addStretch()
        row.addWidget(self.remaining)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = button(_("Annuler"), "secondary", "x")
        self.cancel_button.setMinimumHeight(42)
        self.cancel_button.clicked.connect(self.cancelRequested)
        buttons.addWidget(self.cancel_button)
        for w in (self.title, self.detail, self.bar):
            cl.addWidget(w)
        cl.addLayout(row)
        cl.addSpacing(6)
        cl.addLayout(buttons)
        outer.addWidget(card)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def show_progress(self, title: str, ratio: float, remaining: str = "") -> None:
        self.title.setText(title)
        self.bar.setValue(round(max(0.0, min(1.0, ratio)) * 1000))
        self.percent.setText(f"{round(ratio * 100)} %")
        self.remaining.setText(remaining)
        if not self.isVisible():
            self.setGeometry(self.parent().rect())
            self.show()
            self.raise_()
            self.setFocus()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(11, 18, 14, 150))
        painter.end()

    # le calcul en cours ne doit pas être perturbé par la souris ou le clavier
    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelRequested.emit()
        event.accept()
