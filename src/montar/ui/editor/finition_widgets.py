# SPDX-License-Identifier: GPL-3.0-or-later
"""Éléments dessinés de la fenêtre Finition : comparaison avant / après, bande des plans,
courbe de loudness et égaliseur de mastering."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from montar.core.mastering import EQ_BANDS
from montar.i18n import _
from montar.ui.theme import theme

DARK = "#0B120E"
AFTER = "#4FA67A"
BEFORE = "#E0A33A"
TARGET = "#E5484D"
EQ_RANGE = 12.0  # dB affichés de part et d'autre de 0
FREQ_RANGE = (20.0, 20000.0)


def _fit(image_size: tuple[int, int], box: QRectF) -> QRectF:
    w, h = image_size
    if w <= 0 or h <= 0:
        return QRectF(box)
    k = min(box.width() / w, box.height() / h)
    return QRectF(box.center().x() - w * k / 2, box.center().y() - h * k / 2, w * k, h * k)


def zebra_overlay(image: QImage) -> QImage | None:
    """Rayures sur les pixels écrêtés (blancs brûlés ou noirs bouchés)."""
    import numpy as np

    rgb = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = rgb.width(), rgb.height()
    data = np.frombuffer(rgb.constBits().asstring(rgb.sizeInBytes()), dtype=np.uint8)
    pixels = data.reshape(h, rgb.bytesPerLine())[:, :w * 4].reshape(h, w, 4)[..., :3]
    mask = (pixels >= 250).all(axis=2) | (pixels <= 3).all(axis=2)
    if not mask.any():
        return None
    ys, xs = np.mgrid[0:h, 0:w]
    stripes = ((xs + ys) // 4) % 2 == 0
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[mask & stripes] = (229, 72, 77, 220)
    return QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class CompareView(QWidget):
    """Image avant et après la finition : rideau à glisser ou côte à côte."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(360, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.before: QImage | None = None
        self.after: QImage | None = None
        self.mode = "curtain"  # curtain | side
        self.zebras = False
        self.split = 0.5
        self.message = ""
        self._zebra: QImage | None = None

    def set_images(self, before: QImage | None, after: QImage | None) -> None:
        self.before, self.after = before, after
        self._zebra = None
        if self.zebras and after is not None:
            self._zebra = zebra_overlay(after)
        self.message = ""
        self.update()

    def set_message(self, text: str) -> None:
        self.message = text
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.setCursor(Qt.CursorShape.SplitHCursor if mode == "curtain"
                       else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_zebras(self, on: bool) -> None:
        self.zebras = on
        self._zebra = zebra_overlay(self.after) if on and self.after is not None else None
        self.update()

    def _move(self, x: float) -> None:
        if self.mode == "curtain" and self.width() > 0:
            self.split = max(0.0, min(1.0, x / self.width()))
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._move(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._move(event.position().x())

    def _tag(self, painter: QPainter, text: str, pos: QPointF, accent: bool) -> None:
        font = painter.font()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 16
        rect = QRectF(pos.x(), pos.y(), width, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(AFTER) if accent else QColor(12, 20, 16, 210))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor("#0E1A14") if accent else QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(DARK))
        if self.after is None or self.before is None:
            painter.setPen(QColor("#C8D6CE"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self.message or _("Aperçu en préparation…"))
            painter.end()
            return
        box = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        size = (self.after.width(), self.after.height())
        if self.mode == "side":
            half = box.width() / 2 - 4
            left = _fit(size, QRectF(box.left(), box.top(), half, box.height()))
            right = _fit(size, QRectF(box.left() + half + 8, box.top(), half, box.height()))
            painter.drawImage(left, self.before)
            painter.drawImage(right, self.after)
            if self._zebra is not None:
                painter.drawImage(right, self._zebra)
            self._tag(painter, _("AVANT"), left.topLeft() + QPointF(8, 8), False)
            self._tag(painter, _("APRÈS"), right.topLeft() + QPointF(8, 8), True)
        else:
            target = _fit(size, box)
            painter.drawImage(target, self.after)
            if self._zebra is not None:
                painter.drawImage(target, self._zebra)
            x = target.left() + target.width() * self.split
            painter.save()
            painter.setClipRect(QRectF(target.left(), target.top(), x - target.left(),
                                       target.height()))
            painter.drawImage(target, self.before)
            painter.restore()
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(QPointF(x, target.top()), QPointF(x, target.bottom()))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QPointF(x, target.center().y()), 9, 9)
            self._tag(painter, _("AVANT"), target.topLeft() + QPointF(10, 10), False)
            tag = _("APRÈS")
            width = painter.fontMetrics().horizontalAdvance(tag) + 16
            self._tag(painter, tag, QPointF(target.right() - width - 10, target.top() + 10),
                      True)
        painter.end()


def deviation_color(value: float) -> str:
    if value < 0.05:
        return "#46A758"
    if value < 0.12:
        return "#E0A33A"
    return "#E5484D"


class ShotStrip(QWidget):
    """Vignettes des plans ; la pastille indique l'écart avec la référence (étoile).
    Un clic choisit le plan comme référence."""

    picked = pyqtSignal(str)

    THUMB = (96, 54)

    def __init__(self) -> None:
        super().__init__()
        self.shots: list = []
        self.reference = ""
        self.setFixedHeight(self.THUMB[1] + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._images: list[QImage] = []

    def set_shots(self, shots: list, reference: str) -> None:
        self.shots, self.reference = shots, reference
        w, h = self.THUMB
        self._images = [QImage(s.thumb, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
                        if len(s.thumb) == w * h * 4 else QImage() for s in shots]
        self.setMinimumWidth(len(shots) * (w + 6))
        self.update()

    def set_reference(self, key: str) -> None:
        self.reference = key
        self.update()

    def _rect(self, index: int) -> QRectF:
        w, h = self.THUMB
        return QRectF(index * (w + 6) + 2, 4, w, h)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        for i, shot in enumerate(self.shots):
            if self._rect(i).contains(event.position()):
                self.picked.emit(shot.key)
                return

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.shots:
            painter.setPen(QColor(p.text_muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter,
                             _("Analysez le projet pour voir ses plans."))
            painter.end()
            return
        for i, (shot, image) in enumerate(zip(self.shots, self._images, strict=True)):
            rect = self._rect(i)
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(rect, QColor(DARK))
            if not image.isNull():
                painter.drawImage(rect, image)
            painter.restore()
            if shot.key == self.reference:
                painter.setPen(QPen(QColor(p.forest), 2.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, 6, 6)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawPolygon(_star(QPointF(rect.right() - 10, rect.top() + 10), 7))
            else:
                painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
                painter.setBrush(QColor(deviation_color(shot.deviation)))
                painter.drawEllipse(QPointF(rect.left() + 9, rect.bottom() - 9), 5, 5)
        painter.end()


def _star(center: QPointF, radius: float):
    from PyQt6.QtGui import QPolygonF

    points = []
    for k in range(10):
        r = radius if k % 2 == 0 else radius * 0.45
        angle = -math.pi / 2 + k * math.pi / 5
        points.append(QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle)))
    return QPolygonF(points)


class LoudnessGraph(QWidget):
    """Loudness à court terme sur tout le projet : avant, après (gain appliqué, limité) et
    cible."""

    LOW, HIGH = -50.0, 0.0

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.curve: list[float] = []
        self.gain = 0.0
        self.target = -14.0
        self.ceiling = -1.0

    def set_data(self, curve: list[float], gain: float, target: float, ceiling: float) -> None:
        self.curve, self.gain, self.target, self.ceiling = curve, gain, target, ceiling
        self.update()

    def _y(self, box: QRectF, value: float) -> float:
        v = max(self.LOW, min(self.HIGH, value))
        return box.top() + (self.HIGH - v) / (self.HIGH - self.LOW) * box.height()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(DARK))
        box = QRectF(self.rect()).adjusted(40, 10, -10, -10)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        for level in range(int(self.HIGH), int(self.LOW) - 1, -10):
            y = self._y(box, level)
            painter.setPen(QPen(QColor(255, 255, 255, 25), 1))
            painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
            painter.setPen(QColor("#9DB1A6"))
            painter.drawText(QRectF(0, y - 7, 34, 14), Qt.AlignmentFlag.AlignRight,
                             str(level).replace("-", "−"))
        y = self._y(box, self.target)
        painter.setPen(QPen(QColor(TARGET), 1.2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        if len(self.curve) < 2:
            painter.setPen(QColor("#C8D6CE"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter,
                             _("Analysez le projet pour mesurer son volume."))
            painter.end()
            return
        n = len(self.curve) - 1
        for values, color in ((self.curve, BEFORE),
                              ([min(v + self.gain, self.ceiling) if v > -69 else v
                                for v in self.curve], AFTER)):
            path = QPainterPath()
            for i, v in enumerate(values):
                point = QPointF(box.left() + box.width() * i / n, self._y(box, v))
                if i == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            painter.setPen(QPen(QColor(color), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.end()


def _freq_x(box: QRectF, freq: float) -> float:
    lo, hi = (math.log10(f) for f in FREQ_RANGE)
    return box.left() + (math.log10(freq) - lo) / (hi - lo) * box.width()


class EqEditor(QWidget):
    """Égaliseur cinq bandes : glisser un point vers le haut ou le bas ; double-clic : 0 dB.
    Le spectre moyen du projet est dessiné en fond."""

    changed = pyqtSignal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.gains = [0.0] * len(EQ_BANDS)
        self.spectrum: list[float] = []
        self._drag: int | None = None

    def set_gains(self, gains: list[float]) -> None:
        self.gains = [float(g) for g in gains]
        self.update()

    def set_spectrum(self, values: list[float]) -> None:
        self.spectrum = values
        self.update()

    def _box(self) -> QRectF:
        return QRectF(self.rect()).adjusted(10, 10, -10, -18)

    def _point(self, i: int) -> QPointF:
        box = self._box()
        y = box.center().y() - self.gains[i] / EQ_RANGE * box.height() / 2
        return QPointF(_freq_x(box, EQ_BANDS[i]), y)

    def _gain_at(self, y: float) -> float:
        box = self._box()
        value = (box.center().y() - y) / (box.height() / 2) * EQ_RANGE
        return round(max(-EQ_RANGE, min(EQ_RANGE, value)) * 2) / 2

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        nearest = min(range(len(EQ_BANDS)), key=lambda i: abs(self._point(i).x() - pos.x()))
        if abs(self._point(nearest).x() - pos.x()) < 24:
            self._drag = nearest

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        self.gains[self._drag] = self._gain_at(event.position().y())
        self.update()
        self.changed.emit(list(self.gains))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.mousePressEvent(event)
        if self._drag is not None:
            self.gains[self._drag] = 0.0
            self._drag = None
            self.update()
            self.changed.emit(list(self.gains))

    def _response(self, freq: float) -> float:
        """Courbe approchée : somme de cloches (log-fréquence) centrées sur les bandes."""
        total = 0.0
        for i, (f0, g) in enumerate(zip(EQ_BANDS, self.gains, strict=True)):
            d = math.log2(freq / f0)
            if (i == 0 and d < 0) or (i == len(EQ_BANDS) - 1 and d > 0):
                total += g  # plateaux des graves et des aigus
            else:
                total += g * math.exp(-(d * d) / 0.9)
        return max(-EQ_RANGE, min(EQ_RANGE, total))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(DARK))
        box = self._box()
        if self.spectrum:  # spectre moyen, de -60 dB (bas) à 0 dB (haut)
            n = len(self.spectrum)
            lo, hi = 30.0, 16000.0
            path = QPainterPath(QPointF(_freq_x(box, lo), box.bottom()))
            for i, v in enumerate(self.spectrum):
                f = lo * (hi / lo) ** ((i + 0.5) / n)
                path.lineTo(QPointF(_freq_x(box, f), box.bottom() - (v + 60) / 60 * box.height()))
            path.lineTo(QPointF(_freq_x(box, hi), box.bottom()))
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(47, 90, 69, 170))
            painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawLine(QPointF(box.left(), box.center().y()),
                         QPointF(box.right(), box.center().y()))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor("#9DB1A6"))
        for f, text in ((50, "50"), (200, "200"), (1000, "1 k"), (5000, "5 k"),
                        (15000, "15 kHz")):
            x = _freq_x(box, f)
            painter.drawText(QRectF(x - 30, box.bottom() + 2, 60, 14),
                             Qt.AlignmentFlag.AlignCenter, text)
        path = QPainterPath()
        steps = 120
        for k in range(steps + 1):
            f = FREQ_RANGE[0] * (FREQ_RANGE[1] / FREQ_RANGE[0]) ** (k / steps)
            point = QPointF(_freq_x(box, f),
                            box.center().y() - self._response(f) / EQ_RANGE * box.height() / 2)
            if k == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QPen(QColor(AFTER), 2.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(QPen(QColor(DARK), 1.5))
        painter.setBrush(QColor("#E5EFE9"))
        for i in range(len(EQ_BANDS)):
            painter.drawEllipse(self._point(i), 6, 6)
        painter.end()
