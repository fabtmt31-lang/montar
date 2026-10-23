# SPDX-License-Identifier: GPL-3.0-or-later
"""Widgets de l'étalonnage avancé : roues de couleur (ombres, tons moyens, hautes lumières)
et éditeur de courbes."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from montar.ui.theme import theme


def import_lut(source: Path, media_dir: Path) -> str:
    """Copie une LUT dans les médias du projet ; renvoie son chemin relatif au projet."""
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / source.name
    if target.resolve() != source.resolve():
        shutil.copy2(source, target)
    return str(Path(media_dir.name) / target.name)


CURVE_COLORS = {"master": "#E8EDEA", "red": "#E5484D", "green": "#46A758", "blue": "#3E7BFA"}
IDENTITY = [[0.0, 0.0], [1.0, 1.0]]


class ColorWheel(QWidget):
    """Disque des teintes : le point indique la couleur ajoutée (distance = intensité).
    Double-clic : retour au centre. Maj pendant le glisser : réglage fin."""

    moved = pyqtSignal(float, float)  # x, y dans le disque unité (y vers le haut)
    released = pyqtSignal()

    def __init__(self, size: int = 88) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.value = (0.0, 0.0)
        self._drag: QPointF | None = None

    def set_value(self, x: float, y: float) -> None:
        self.value = (x, y)
        self.update()

    def _radius(self) -> float:
        return self.width() / 2 - 4

    def _to_value(self, pos: QPointF) -> tuple[float, float]:
        c = QPointF(self.width() / 2, self.height() / 2)
        x, y = (pos.x() - c.x()) / self._radius(), -(pos.y() - c.y()) / self._radius()
        d = math.hypot(x, y)
        if d > 1:
            x, y = x / d, y / d
        return round(x, 4), round(y, 4)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position()
            self._start = self.value
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._emit(self._to_value(event.position()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:  # réglage fin : ×0,2
            delta = (event.position() - self._drag) / self._radius() * 0.2
            x, y = self._start[0] + delta.x(), self._start[1] - delta.y()
            d = math.hypot(x, y)
            self._emit((round(x / max(1, d), 4), round(y / max(1, d), 4)))
        else:
            self._emit(self._to_value(event.position()))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self.released.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._emit((0.0, 0.0))
        self.released.emit()

    def _emit(self, value: tuple[float, float]) -> None:
        if value != self.value:
            self.set_value(*value)
            self.moved.emit(*value)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = self._radius()
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        hues = QConicalGradient(c, 0)  # 0° à droite = rouge, sens trigonométrique
        for i in range(7):
            hues.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 0.75, 0.95))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hues))
        painter.drawEllipse(rect)
        fade = QRadialGradient(c, r)
        fade.setColorAt(0, QColor(128, 128, 128, 255))
        fade.setColorAt(1, QColor(128, 128, 128, 0))
        painter.setBrush(QBrush(fade))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        x, y = self.value
        dot = QPointF(c.x() + x * r, c.y() - y * r)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawEllipse(dot, 5, 5)
        painter.end()


def spline(points: list[list[float]], samples: int = 64) -> list[tuple[float, float]]:
    """Courbe lissée (spline cubique naturelle, comme le filtre « curves » de FFmpeg)."""
    pts = sorted((float(a), float(b)) for a, b in points)
    if len(pts) < 2:
        return [(0.0, 0.0), (1.0, 1.0)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    n = len(pts)
    h = [max(1e-6, xs[i + 1] - xs[i]) for i in range(n - 1)]
    # dérivées secondes (système tridiagonal, extrémités naturelles)
    m = [0.0] * n
    if n > 2:
        a = [0.0] * n
        b = [1.0] * n
        c = [0.0] * n
        d = [0.0] * n
        for i in range(1, n - 1):
            a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
            d[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
        for i in range(1, n):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            d[i] -= w * d[i - 1]
        m[n - 1] = d[n - 1] / b[n - 1]
        for i in range(n - 2, -1, -1):
            m[i] = (d[i] - c[i] * m[i + 1]) / b[i]
        m[0] = m[n - 1] = 0.0
    out = []
    for k in range(samples + 1):
        x = k / samples
        if x <= xs[0]:
            out.append((x, ys[0]))
            continue
        if x >= xs[-1]:
            out.append((x, ys[-1]))
            continue
        i = max(j for j in range(n - 1) if xs[j] <= x)
        t = x - xs[i]
        u = xs[i + 1] - x
        y = (m[i] * u ** 3 + m[i + 1] * t ** 3) / (6 * h[i]) + \
            (ys[i] / h[i] - m[i] * h[i] / 6) * u + (ys[i + 1] / h[i] - m[i + 1] * h[i] / 6) * t
        out.append((x, max(0.0, min(1.0, y))))
    return out


class CurvesEditor(QWidget):
    """Courbe d'un canal : clic = nouveau point, glisser = déplacer, double-clic sur un
    point = le retirer (les extrémités restent)."""

    changed = pyqtSignal(str, list)  # canal, points
    released = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.channel = "master"
        self.curves: dict[str, list[list[float]]] = {}
        self._drag: int | None = None

    def set_curves(self, curves: dict[str, list[list[float]]]) -> None:
        self.curves = {k: [list(p) for p in v] for k, v in curves.items()}
        self.update()

    def set_channel(self, channel: str) -> None:
        self.channel = channel
        self.update()

    def points(self) -> list[list[float]]:
        return sorted(self.curves.get(self.channel) or [list(p) for p in IDENTITY])

    def _box(self) -> QRectF:
        return QRectF(8, 8, self.width() - 16, self.height() - 16)

    def _to_point(self, pos: QPointF) -> list[float]:
        b = self._box()
        return [round(max(0.0, min(1.0, (pos.x() - b.left()) / b.width())), 4),
                round(max(0.0, min(1.0, 1 - (pos.y() - b.top()) / b.height())), 4)]

    def _to_screen(self, p) -> QPointF:
        b = self._box()
        return QPointF(b.left() + p[0] * b.width(), b.top() + (1 - p[1]) * b.height())

    def _hit(self, pos: QPointF) -> int | None:
        for i, p in enumerate(self.points()):
            if (self._to_screen(p) - pos).manhattanLength() < 10:
                return i
        return None

    def _set(self, points: list[list[float]]) -> None:
        points = sorted(points)
        self.curves[self.channel] = points
        self.update()
        self.changed.emit(self.channel, points)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(event.position())
        points = self.points()
        if hit is None:
            new = self._to_point(event.position())
            if any(abs(p[0] - new[0]) < 0.02 for p in points):
                return
            points.append(new)
            self._set(points)
            hit = sorted(points).index(new)
        self._drag = hit

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        points = self.points()
        i = self._drag
        x, y = self._to_point(event.position())
        low = points[i - 1][0] + 0.01 if i > 0 else 0.0
        high = points[i + 1][0] - 0.01 if i < len(points) - 1 else 1.0
        if i in (0, len(points) - 1):  # extrémités : seule la hauteur change
            x = points[i][0]
        points[i] = [max(low, min(high, x)), y]
        self._set(points)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self.released.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        hit = self._hit(event.position())
        points = self.points()
        if hit is not None and 0 < hit < len(points) - 1:
            del points[hit]
            self._set(points)
            self.released.emit()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        b = self._box()
        painter.fillRect(b, QColor("#17261E"))
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        for k in range(1, 4):
            x = b.left() + b.width() * k / 4
            y = b.top() + b.height() * k / 4
            painter.drawLine(QPointF(x, b.top()), QPointF(x, b.bottom()))
            painter.drawLine(QPointF(b.left(), y), QPointF(b.right(), y))
        painter.drawLine(b.bottomLeft(), b.topRight())
        for channel, points in self.curves.items():  # autres canaux, en léger
            if channel != self.channel and points:
                self._draw_curve(painter, points, QColor(CURVE_COLORS[channel]), 70, 1)
        color = QColor(CURVE_COLORS[self.channel])
        self._draw_curve(painter, self.points(), color, 255, 2)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        painter.setBrush(color)
        for point in self.points():
            painter.drawEllipse(self._to_screen(point), 4.5, 4.5)
        painter.setPen(QPen(QColor(p.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(b)
        painter.end()

    def _draw_curve(self, painter, points, color: QColor, alpha: int, width: float) -> None:
        color = QColor(color)
        color.setAlpha(alpha)
        path = QPainterPath()
        for i, pt in enumerate(spline(points)):
            screen = self._to_screen(pt)
            if i == 0:
                path.moveTo(screen)
            else:
                path.lineTo(screen)
        painter.setPen(QPen(color, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
