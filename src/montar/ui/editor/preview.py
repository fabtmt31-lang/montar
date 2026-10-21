# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau d'aperçu : image, curseur de position, commandes de lecture."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QShortcut,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from montar.core.settings import PREVIEW_QUALITIES
from montar.core.timecode import frames_to_timecode
from montar.i18n import _
from montar.ui.editor.player import Player
from montar.ui.theme import theme
from montar.ui.widgets import button, label, set_icon

QUALITY_LABELS = {"low": "Basse", "medium": "Moyenne", "full": "Pleine"}
EMPTY_MESSAGE = "Glissez des médias dans la timeline pour les voir ici"


HANDLE = 10  # côté des poignées de redimensionnement (pixels écran)
SNAP = 8  # distance d'aimantation (pixels écran)


def _rotate(point: QPointF, center: QPointF, degrees: float) -> QPointF:
    """Rotation dans le sens horaire à l'écran (comme MLT et QPainter)."""
    a = math.radians(degrees)
    dx, dy = point.x() - center.x(), point.y() - center.y()
    return QPointF(center.x() + dx * math.cos(a) - dy * math.sin(a),
                   center.y() + dx * math.sin(a) + dy * math.cos(a))


def box_corners(rect: QRectF, rotation: float) -> list[QPointF]:
    """Coins (haut-gauche, haut-droit, bas-droit, bas-gauche) du cadre tourné."""
    c = rect.center()
    return [_rotate(pt, c, rotation) for pt in
            (rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft())]


def _bounds(points: list[QPointF]) -> QRectF:
    xs, ys = [p.x() for p in points], [p.y() for p in points]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


@dataclass
class _Drag:
    mode: str  # « move » ou « scale »
    corner: int  # coin tiré (redimensionnement)
    start: QPointF  # point de départ (pixels de la toile)
    rect: QRectF  # cadre au départ
    ghost: QImage | None  # contenu du cadre au départ, déplacé sans attendre le rendu
    current: QRectF  # cadre voulu


class PreviewCanvas(QWidget):
    """Affiche l'image courante centrée, au format de la toile du projet.

    Le cadre de l'élément sélectionné (`selection`, en pixels de la toile, tourné de
    `rotation` degrés) se déplace en le faisant glisser et se redimensionne par ses coins,
    le coin opposé restant fixe. Le cadre s'aimante au centre et aux bords de la toile
    (Ctrl désactive l'aimantation)."""

    resized = pyqtSignal(QSize)
    # (mode « move » ou « scale », cadre voulu non tourné, en pixels de la toile)
    boxChanged = pyqtSignal(str, QRectF)
    dragFinished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self._image: QImage | None = None
        self.canvas_size = (1920, 1080)  # taille de la toile du projet
        self._message = ""
        self.selection: QRectF | None = None
        self.rotation = 0.0
        self._drag: _Drag | None = None
        self._guides: list[tuple[str, float]] = []  # (« v » ou « h », position dans la toile)
        theme().changed.connect(self.update)

    def set_selection(self, rect: QRectF | None, rotation: float = 0.0) -> None:
        self.selection, self.rotation = rect, rotation
        if rect is None:
            self._drag = None
        self.update()

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    def _k(self) -> float:
        """Pixels écran par pixel de la toile."""
        return self.frame_rect().width() / self.canvas_size[0]

    def _to_widget_point(self, point: QPointF) -> QPointF:
        frame, k = self.frame_rect(), self._k()
        return QPointF(frame.left() + point.x() * k, frame.top() + point.y() * k)

    def _to_widget(self, rect: QRectF) -> QRectF:
        frame, k = self.frame_rect(), self._k()
        return QRectF(frame.left() + rect.left() * k, frame.top() + rect.top() * k,
                      rect.width() * k, rect.height() * k)

    def _to_canvas(self, point: QPointF) -> QPointF:
        frame = self.frame_rect()
        k = self.canvas_size[0] / frame.width()
        return QPointF((point.x() - frame.left()) * k, (point.y() - frame.top()) * k)

    def _box(self) -> QRectF | None:
        return self._drag.current if self._drag is not None else self.selection

    def _handles(self) -> list[QRectF]:
        box = self._box()
        if box is None:
            return []
        h = HANDLE
        return [QRectF(pt.x() - h / 2, pt.y() - h / 2, h, h)
                for pt in map(self._to_widget_point, box_corners(box, self.rotation))]

    def _hit(self, pos: QPointF) -> tuple[str, int] | None:
        if self.selection is None or self._image is None:
            return None
        for i, h in enumerate(self._handles()):
            if h.adjusted(-4, -4, 4, 4).contains(pos):
                return "scale", i
        local = _rotate(self._to_canvas(pos), self.selection.center(), -self.rotation)
        return ("move", -1) if self.selection.contains(local) else None

    def _cursor_for(self, hit: tuple[str, int] | None) -> Qt.CursorShape:
        if hit is None:
            return Qt.CursorShape.ArrowCursor
        if hit[0] == "move":
            return Qt.CursorShape.SizeAllCursor
        # diagonale du coin après rotation (repère écran, y vers le bas)
        angle = (self.rotation + (225, 315, 45, 135)[hit[1]]) % 180
        return Qt.CursorShape.SizeFDiagCursor if 0 <= angle < 90 else \
            Qt.CursorShape.SizeBDiagCursor

    def _grab_ghost(self, rect: QRectF) -> QImage | None:
        if self._image is None:
            return None
        k = self._image.width() / self.canvas_size[0]
        b = _bounds(box_corners(rect, self.rotation))
        return self._image.copy(round(b.left() * k), round(b.top() * k),
                                max(1, round(b.width() * k)), max(1, round(b.height() * k)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        hit = self._hit(event.position())
        if hit and event.button() == Qt.MouseButton.LeftButton:
            rect = QRectF(self.selection)
            self._drag = _Drag(hit[0], hit[1], self._to_canvas(event.position()), rect,
                               self._grab_ghost(rect), QRectF(rect))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        drag = self._drag
        if drag is None:
            self.setCursor(self._cursor_for(self._hit(event.position())))
            return
        point = self._to_canvas(event.position())
        snap = not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if drag.mode == "move":
            rect = self._moved(drag, point, snap)
        else:
            rect = self._scaled(drag, point, snap)
        if rect != drag.current:
            drag.current = rect
            self.update()
            self.boxChanged.emit(drag.mode, QRectF(rect))

    def _snap_tolerance(self) -> float:
        return SNAP / max(1e-6, self._k())

    def _moved(self, drag: _Drag, point: QPointF, snap: bool) -> QRectF:
        rect = drag.rect.translated(point - drag.start)
        self._guides = []
        if not snap:
            return rect
        cw, ch = self.canvas_size
        tol = self._snap_tolerance()
        b = _bounds(box_corners(rect, self.rotation))
        dx = dy = 0.0
        best_x = best_y = tol
        for value, target in ((b.center().x(), cw / 2), (b.left(), 0.0), (b.right(), cw)):
            if abs(target - value) <= best_x:
                best_x, dx, gx = abs(target - value), target - value, target
        for value, target in ((b.center().y(), ch / 2), (b.top(), 0.0), (b.bottom(), ch)):
            if abs(target - value) <= best_y:
                best_y, dy, gy = abs(target - value), target - value, target
        if best_x < tol:
            self._guides.append(("v", gx))
        if best_y < tol:
            self._guides.append(("h", gy))
        return rect.translated(dx, dy)

    def _scaled(self, drag: _Drag, point: QPointF, snap: bool) -> QRectF:
        corners = box_corners(drag.rect, self.rotation)
        anchor, corner = corners[(drag.corner + 2) % 4], corners[drag.corner]
        dx, dy = corner.x() - anchor.x(), corner.y() - anchor.y()
        length = dx * dx + dy * dy
        if length < 1e-6:
            return drag.rect
        # projection du curseur sur la diagonale : les proportions sont conservées
        ratio = ((point.x() - anchor.x()) * dx + (point.y() - anchor.y()) * dy) / length
        self._guides = []
        if snap and abs(self.rotation) < 0.01:
            ratio = self._snap_ratio(anchor, dx, dy, ratio)
        minimum = 8.0 / max(1.0, min(drag.rect.width(), drag.rect.height()))
        ratio = max(minimum, ratio)
        center = drag.rect.center()
        new_center = QPointF(anchor.x() + (center.x() - anchor.x()) * ratio,
                             anchor.y() + (center.y() - anchor.y()) * ratio)
        w, h = drag.rect.width() * ratio, drag.rect.height() * ratio
        return QRectF(new_center.x() - w / 2, new_center.y() - h / 2, w, h)

    def _snap_ratio(self, anchor: QPointF, dx: float, dy: float, ratio: float) -> float:
        """Aimante le coin tiré aux bords et aux axes de la toile."""
        cw, ch = self.canvas_size
        tol = self._snap_tolerance()
        best, snapped, guide = tol, ratio, None
        for axis, origin, delta, targets in (("v", anchor.x(), dx, (0.0, cw / 2, cw)),
                                             ("h", anchor.y(), dy, (0.0, ch / 2, ch))):
            if abs(delta) < 1e-6:
                continue
            for target in targets:
                distance = abs(origin + delta * ratio - target)
                candidate = (target - origin) / delta
                if distance <= best and candidate > 0:
                    best, snapped, guide = distance, candidate, (axis, target)
        if guide is not None and best < tol:
            self._guides.append(guide)
        return snapped

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._guides = []
            self.update()
            self.dragFinished.emit()

    def set_canvas(self, width: int, height: int) -> None:
        self.canvas_size = (width, height)
        self.update()

    def set_image(self, image: QImage | None) -> None:
        self._image = image
        self._message = ""
        self.update()

    def set_message(self, text: str) -> None:
        self._image = None
        self._message = text
        self.update()

    def frame_rect(self) -> QRectF:
        cw, ch = self.canvas_size
        scale = min(self.width() / cw, self.height() / ch)
        w, h = cw * scale, ch * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.frame_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor("#0B120E") if self._image is not None else QColor(p.mint))
        if self._image is not None:
            painter.drawImage(rect, self._image)
        elif self._message:
            painter.setPen(QColor(p.forest))
            painter.drawText(rect.adjusted(20, 20, -20, -20),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self._message)
        box = self._box()
        if box is not None and self._image is not None:
            polygon = QPolygonF([self._to_widget_point(pt)
                                 for pt in box_corners(box, self.rotation)])
            drag = self._drag
            if drag is not None and drag.ghost is not None and drag.current != drag.rect:
                # aperçu immédiat : le contenu suit la souris pendant le calcul du rendu
                ratio = drag.current.width() / max(1e-6, drag.rect.width())
                b = _bounds(box_corners(drag.rect, self.rotation))
                target = QRectF(0, 0, b.width() * ratio, b.height() * ratio)
                target.moveCenter(drag.current.center())
                painter.save()
                clip = QPainterPath()
                clip.addPolygon(polygon)
                painter.setClipPath(clip.intersected(path))
                painter.drawImage(self._to_widget(target), drag.ghost)
                painter.restore()
            painter.setClipPath(path)
            guide_pen = QPen(QColor("#FF4FA3"), 1, Qt.PenStyle.SolidLine)
            painter.setPen(guide_pen)
            for axis, value in self._guides:
                if axis == "v":
                    x = rect.left() + value * self._k()
                    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                else:
                    y = rect.top() + value * self._k()
                    painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setClipping(False)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 110), 3))
            painter.drawPolygon(polygon)
            painter.setPen(QPen(QColor("#FFFFFF"), 1.5, Qt.PenStyle.DashLine))
            painter.drawPolygon(polygon)
            painter.setPen(QPen(QColor(p.forest), 1.5))
            painter.setBrush(QColor("#FFFFFF"))
            for h in self._handles():
                painter.drawRect(h)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit(self.size())


class PreviewPanel(QFrame):
    def __init__(self, player: Player, quality: str = "medium") -> None:
        super().__init__()
        self.setObjectName("PreviewArea")
        self.player = player
        self.quality = quality
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label(_("Aperçu"), "muted"))
        head.addStretch()
        self.quality_button = button("", "secondary")
        self.quality_button.setStyleSheet("padding: 5px 10px; font-weight: 500;")
        menu = QMenu(self.quality_button)
        for key, text in QUALITY_LABELS.items():
            menu.addAction(_(text), lambda k=key: self.set_quality(k))
        self.quality_button.setMenu(menu)
        head.addWidget(self.quality_button)
        layout.addLayout(head)

        frame = QFrame()
        frame.setObjectName("PreviewFrame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(16, 16, 16, 16)
        self.canvas = PreviewCanvas()
        self.canvas.set_message(_(EMPTY_MESSAGE))
        fl.addWidget(self.canvas)
        layout.addWidget(frame, 1)

        transport = QHBoxLayout()
        self.timecode = label("00:00:00:00", "mono")
        self.timecode.setStyleSheet("font-size: 15px; font-weight: 500;")
        self.duration = label("/  00:00:00:00", "mono")
        self.duration.setProperty("role", "mono")
        self.duration.setStyleSheet("font-size: 14px;")
        transport.addWidget(self.timecode)
        transport.addSpacing(8)
        transport.addWidget(self.duration)
        transport.addStretch()
        self.to_start = button("", "ghost", "skip-back", tooltip=_("Aller au début (Origine)"))
        self.play_button = button("", "round", "play", tooltip=_("Lecture / pause (Espace)"))
        self.to_end = button("", "ghost", "skip-forward", tooltip=_("Aller à la fin (Fin)"))
        self.to_start.clicked.connect(lambda: self.player.seek(0))
        self.to_end.clicked.connect(lambda: self.player.seek(self.player.length - 1))
        self.play_button.clicked.connect(self.player.toggle)
        for b in (self.to_start, self.play_button, self.to_end):
            transport.addWidget(b)
        transport.addStretch()
        transport.addSpacing(self.timecode.sizeHint().width() + self.duration.sizeHint().width())
        layout.addLayout(transport)
        self._set_controls_enabled(False)

        self._fps = 25.0
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._push_render_size)
        self.canvas.resized.connect(lambda _s: self._resize_timer.start())

        player.frameReady.connect(self._on_frame)
        player.loaded.connect(self._on_loaded)
        player.failed.connect(self._on_failed)
        player.playingChanged.connect(self._on_playing)
        self.set_quality(quality)

        for key, slot in (
            (Qt.Key.Key_Space, self.player.toggle),
            (Qt.Key.Key_Home, lambda: self.player.seek(0)),
            (Qt.Key.Key_End, lambda: self.player.seek(self.player.length - 1)),
            (Qt.Key.Key_Left, lambda: self.step(-1)),
            (Qt.Key.Key_Right, lambda: self.step(1)),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

    def set_canvas(self, width: int, height: int) -> None:
        self.canvas.set_canvas(width, height)
        self._push_render_size()

    def set_quality(self, key: str) -> None:
        self.quality = key
        self.quality_button.setText(_("Qualité : {q}").format(q=_(QUALITY_LABELS[key]).lower()))
        self._push_render_size()

    def step(self, delta: int) -> None:
        if self.player.length:
            self.player.pause()
            self.player.seek(max(0, min(self.player.length - 1, self.player.position + delta)))

    def _push_render_size(self) -> None:
        # Qualité = fraction de la résolution de la toile, sans dépasser la taille affichée.
        rect = self.canvas.frame_rect()
        cw, ch = self.canvas.canvas_size
        factor = PREVIEW_QUALITIES[self.quality]
        dpr = self.devicePixelRatioF()
        scale = min(factor, rect.width() * dpr / cw, rect.height() * dpr / ch)
        self.player.set_render_size(int(cw * scale), int(ch * scale))

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self.to_start, self.play_button, self.to_end):
            w.setEnabled(enabled)

    def _on_loaded(self, length: int, fps: float) -> None:
        self._fps = fps
        self.duration.setText("/  " + frames_to_timecode(length, fps))
        self._set_controls_enabled(length > 0)
        if length == 0:
            self.canvas.set_message(_(EMPTY_MESSAGE))
        self._push_render_size()

    def _on_frame(self, image: QImage, frame: int) -> None:
        if self.player.length == 0:
            return
        self.canvas.set_image(image)
        self.timecode.setText(frames_to_timecode(frame, self._fps))

    def _on_failed(self, message: str) -> None:
        self.canvas.set_message(_("Aperçu impossible : {error}").format(error=message))
        self._set_controls_enabled(False)

    def _on_playing(self, playing: bool) -> None:
        set_icon(self.play_button, "pause" if playing else "play", "on_forest", 20)
