# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre du suivi : rectangle tracé autour de l'objet, puis action choisie."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _


class RectSelector(QWidget):
    """Image de départ ; on y trace le rectangle de l'objet à suivre."""

    def __init__(self, image: QImage) -> None:
        super().__init__()
        self.image = image
        self.rect: QRectF | None = None  # en fractions de l'image
        self._start: QPointF | None = None
        self.setMinimumSize(560, 315)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _frame(self) -> QRectF:
        w, h = self.image.width() or 16, self.image.height() or 9
        scale = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * scale) / 2, (self.height() - h * scale) / 2,
                      w * scale, h * scale)

    def _norm(self, pos: QPointF) -> QPointF:
        f = self._frame()
        return QPointF(min(1.0, max(0.0, (pos.x() - f.left()) / f.width())),
                       min(1.0, max(0.0, (pos.y() - f.top()) / f.height())))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._start = self._norm(event.position())
        self.rect = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start is not None:
            self.rect = QRectF(self._start, self._norm(event.position())).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._start = None
        if self.rect is not None and (self.rect.width() < 0.01 or self.rect.height() < 0.01):
            self.rect = None
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect_widget(), QColor("#0B120E"))
        f = self._frame()
        painter.drawImage(f, self.image)
        if self.rect is not None:
            r = QRectF(f.left() + self.rect.left() * f.width(),
                       f.top() + self.rect.top() * f.height(),
                       self.rect.width() * f.width(), self.rect.height() * f.height())
            painter.setPen(QPen(QColor(0, 0, 0, 140), 3))
            painter.drawRect(r)
            painter.setPen(QPen(QColor("#FFFFFF"), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(r)
        painter.end()

    def rect_widget(self):
        return super().rect()


class TrackDialog(QDialog):
    def __init__(self, parent, image: QImage, followers: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Suivre un objet"))
        layout = QVBoxLayout(self)
        hint = QLabel(_("Tracez un rectangle autour de l'objet à suivre (assez contrasté, "
                        "visible dès cette image). Le suivi part de la tête de lecture."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.selector = RectSelector(image)
        layout.addWidget(self.selector, 1)
        self.mode = QButtonGroup(self)
        self.follow = QRadioButton(_("Faire suivre un élément :"))
        self.pixelate = QRadioButton(_("Pixeliser l'objet (visage, plaque…)"))
        self.mode.addButton(self.follow)
        self.mode.addButton(self.pixelate)
        row = QHBoxLayout()
        row.addWidget(self.follow)
        self.targets = QComboBox()
        for clip_id, name in followers:
            self.targets.addItem(name, clip_id)
        row.addWidget(self.targets, 1)
        layout.addLayout(row)
        if followers:
            self.follow.setChecked(True)
        else:
            self.follow.setEnabled(False)
            self.targets.setEnabled(False)
            self.targets.addItem(_("aucun graphisme ni image au-dessus de ce clip"))
            self.pixelate.setChecked(True)
        prow = QHBoxLayout()
        prow.addWidget(self.pixelate)
        prow.addWidget(QLabel(_("Pavés")))
        self.block = QSlider(Qt.Orientation.Horizontal)
        self.block.setRange(4, 48)
        self.block.setValue(16)
        prow.addWidget(self.block, 1)
        layout.addLayout(prow)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(_("Suivre"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Annuler"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(720, 560)

    def _accept(self) -> None:
        if self.selector.rect is not None:
            self.accept()

    def choice(self) -> dict:
        r = self.selector.rect
        return {"rect": (r.left(), r.top(), r.width(), r.height()),
                "mode": "follow" if self.follow.isChecked() else "pixelate",
                "target": self.targets.currentData(), "block": self.block.value()}
