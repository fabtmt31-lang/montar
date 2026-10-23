# SPDX-License-Identifier: GPL-3.0-or-later
"""Cloche des notifications (accueil et écran de montage)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMenu, QPushButton

from montar.core.notifications import Notifications
from montar.i18n import _
from montar.ui.home.home_page import ago
from montar.ui.widgets import set_icon

_MARK = {"success": "✓ ", "error": "⚠ ", "info": ""}


class NotificationButton(QPushButton):
    """Cloche ; le nombre de notifications non lues s'affiche à côté."""

    def __init__(self, notifications: Notifications) -> None:
        super().__init__()
        self.notifications = notifications
        self.setProperty("variant", "ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Notifications"))
        set_icon(self, "bell")
        self.clicked.connect(self.show_menu)
        notifications.listeners.append(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        n = self.notifications.unread
        try:
            self.setText(str(n) if n else "")
            self.setStyleSheet("QPushButton { color: #B4452F; font-weight: 700; }" if n else "")
        except RuntimeError:  # bouton détruit avec sa page (projet fermé) : on se retire
            if self.refresh in self.notifications.listeners:
                self.notifications.listeners.remove(self.refresh)

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        items = self.notifications.items[:15]
        if not items:
            menu.addAction(_("Aucune notification")).setEnabled(False)
        for item in items:
            detail = item.text if len(item.text) <= 60 else item.text[:57] + "…"
            text = f"{_MARK.get(item.kind, '')}{item.title}" + (f" · {detail}" if detail else "")
            text += f" — {ago(item.time)}"
            action = menu.addAction(text)
            action.setToolTip(item.text)
            if item.path:
                action.triggered.connect(
                    lambda _=False, p=item.path: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(str(Path(p).parent))))
            elif not item.text:
                action.setEnabled(False)
            menu.setToolTipsVisible(True)
        if items:
            menu.addSeparator()
            menu.addAction(_("Tout effacer"), self.notifications.clear)
        return menu

    def show_menu(self) -> None:
        menu = self.build_menu()
        self.notifications.mark_all_read()
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))
