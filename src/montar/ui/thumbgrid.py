# SPDX-License-Identifier: GPL-3.0-or-later
"""Grille / liste de vignettes (projets récents, médias du projet)."""
from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QListView,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from montar.ui.theme import theme
from montar.ui.theme.icons import pixmap as icon_pixmap
from montar.ui.theme.tokens import FONT_MONO, FONT_UI

ROLE_SUBTITLE = Qt.ItemDataRole.UserRole + 1
ROLE_BADGE = Qt.ItemDataRole.UserRole + 2
ROLE_PLACEHOLDER = Qt.ItemDataRole.UserRole + 3  # nom de jeton de couleur (mint, pistachio…)
ROLE_ICON = Qt.ItemDataRole.UserRole + 4  # icône affichée sans vignette
ROLE_WARNING = Qt.ItemDataRole.UserRole + 5  # média manquant
ROLE_USED = Qt.ItemDataRole.UserRole + 6  # média présent dans la timeline (pastille ✓)
ROLE_PAYLOAD = Qt.ItemDataRole.UserRole + 10


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, view: ThumbGrid) -> None:
        super().__init__(view)
        self._view = view

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return self._view.item_size()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        p = theme().palette
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        grid = self._view.viewMode() == QListView.ViewMode.IconMode
        subtitle = index.data(ROLE_SUBTITLE)
        title_h = 22 + (18 if subtitle else 0)
        if grid:
            thumb = QRectF(rect.x(), rect.y(), rect.width(), rect.height() - title_h - 6)
            text_rect = QRect(rect.x() + 2, int(thumb.bottom()) + 6, rect.width() - 4, title_h)
        else:
            th = rect.height()
            thumb = QRectF(rect.x(), rect.y(), th * 16 / 9, th)
            text_rect = QRect(int(thumb.right()) + 14, rect.y(), rect.width(), rect.height())
            if selected or hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(p.mist))
                painter.drawRoundedRect(QRectF(option.rect.adjusted(0, 0, 0, 0)), 10, 10)

        radius = self._view.radius
        path = QPainterPath()
        path.addRoundedRect(thumb, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(getattr(p, index.data(ROLE_PLACEHOLDER) or "mint")))
        painter.drawPath(path)
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(pm, QPixmap) and not pm.isNull():
            painter.save()
            painter.setClipPath(path)
            scaled = pm.scaled(thumb.size().toSize() * 2,
                               Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
            sw, sh = scaled.width() / 2, scaled.height() / 2
            target = QRectF(thumb.center().x() - sw / 2, thumb.center().y() - sh / 2, sw, sh)
            painter.drawPixmap(target, scaled, QRectF(scaled.rect()))
            painter.restore()
        else:
            icon_name = index.data(ROLE_ICON)
            if icon_name:
                size = 26
                ip = icon_pixmap(icon_name, p.forest, size)
                painter.drawPixmap(int(thumb.center().x() - size / 2),
                                   int(thumb.center().y() - size / 2), ip)
        if index.data(ROLE_WARNING):
            ip = icon_pixmap("triangle-alert", "#B4452F", 18)
            painter.drawPixmap(int(thumb.x()) + 8, int(thumb.y()) + 8, ip)

        if index.data(ROLE_USED):
            d = 22
            circle = QRectF(thumb.right() - d - 7, thumb.y() + 7, d, d)
            painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
            painter.setBrush(QColor(p.forest))
            painter.drawEllipse(circle)
            ip = icon_pixmap("check", "#FFFFFF", 14)
            painter.drawPixmap(int(circle.center().x() - 7), int(circle.center().y() - 7), ip)
            painter.setPen(Qt.PenStyle.NoPen)

        badge = index.data(ROLE_BADGE)
        if badge:
            f = QFont(FONT_MONO)
            f.setPixelSize(11)
            painter.setFont(f)
            fm = QFontMetrics(f)
            bw, bh = fm.horizontalAdvance(badge) + 12, 18
            br = QRectF(thumb.right() - bw - 8, thumb.bottom() - bh - 8, bw, bh)
            painter.setBrush(QColor("#17261E"))
            painter.drawRoundedRect(br, 4, 4)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)

        if selected and grid:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = painter.pen()
            pen.setColor(QColor(p.forest))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.drawRoundedRect(thumb.adjusted(1, 1, -1, -1), radius, radius)

        f = QFont(FONT_UI)
        f.setPixelSize(self._view.title_px)
        f.setWeight(QFont.Weight.DemiBold if self._view.title_px > 13 else QFont.Weight.Medium)
        painter.setFont(f)
        painter.setPen(QColor(p.ink))
        fm = QFontMetrics(f)
        title = fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                              Qt.TextElideMode.ElideMiddle, text_rect.width() - 4)
        if grid:
            painter.drawText(text_rect.adjusted(0, 0, 0, -(18 if subtitle else 0)),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title)
        else:
            painter.drawText(text_rect.adjusted(0, 0, 0, -(rect.height() // 2 - 2)
                                                if subtitle else 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
                             if subtitle else Qt.AlignmentFlag.AlignVCenter, title)
        if subtitle:
            f2 = QFont(FONT_UI)
            f2.setPixelSize(12)
            painter.setFont(f2)
            painter.setPen(QColor(p.text_muted))
            if grid:
                sub_rect = text_rect.adjusted(0, 22, 0, 0)
                painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                 subtitle)
            else:
                sub_rect = text_rect.adjusted(0, rect.height() // 2 + 2, 0, 0)
                painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                 subtitle)
        painter.restore()


class ThumbGrid(QListWidget):
    """QListWidget en mode vignettes dont la largeur des cases s'adapte à la place disponible."""

    def __init__(self, min_width: int = 220, aspect: float = 16 / 10.5, title_px: int = 15,
                 radius: float = 16, with_subtitle: bool = True) -> None:
        super().__init__()
        self.min_width, self.aspect, self.title_px = min_width, aspect, title_px
        self.radius, self.with_subtitle = radius, with_subtitle
        self.setItemDelegate(ThumbDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme().changed.connect(self.viewport().update)

    def set_list_mode(self, as_list: bool) -> None:
        self.setViewMode(QListView.ViewMode.ListMode if as_list
                         else QListView.ViewMode.IconMode)
        self._update_grid()
        self.doItemsLayout()

    def _usable_width(self) -> int:
        # La place de la barre de défilement est toujours réservée : sinon son apparition
        # ferait passer la dernière colonne à la ligne.
        width = self.width() - 2 * self.frameWidth() - 4
        if self.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            width -= self.verticalScrollBar().sizeHint().width()
        return max(100, width)

    def _columns(self) -> int:
        if self.viewMode() == QListView.ViewMode.ListMode:
            return 1
        return max(1, self._usable_width() // self.min_width)

    def item_size(self) -> QSize:
        width = self._usable_width()
        if self.viewMode() == QListView.ViewMode.ListMode:
            return QSize(width, 72)
        w = width // self._columns() - 2  # marge : Qt passe à la ligne dès l'égalité
        text_h = 30 + (18 if self.with_subtitle else 0)
        return QSize(w, int((w - 8) / self.aspect) + text_h + 8)

    def _update_grid(self) -> None:
        self.setGridSize(self.item_size())

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        self._update_grid()

    def content_height(self) -> int:
        """Hauteur nécessaire pour afficher toutes les cases sans défilement."""
        if self.count() == 0:
            return 0
        visible = sum(1 for i in range(self.count()) if not self.item(i).isHidden())
        rows = (visible + self._columns() - 1) // self._columns()
        return rows * self.item_size().height() + 4
