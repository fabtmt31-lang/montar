# SPDX-License-Identifier: GPL-3.0-or-later
"""Application du thème (clair, sombre, système) et chargement des polices."""
from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication

from montar.platform.paths import assets_dir
from montar.ui.theme import icons
from montar.ui.theme.qss import build_stylesheet
from montar.ui.theme.tokens import DARK, FONT_UI, LIGHT, Palette


def load_fonts() -> None:
    for ttf in sorted((assets_dir() / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))


def app_icon() -> QIcon:
    """Icône de l'application, rendue depuis le SVG sans greffon d'images Qt."""
    from PyQt6.QtCore import QByteArray, QRectF
    from PyQt6.QtGui import QPainter, QPixmap
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray((assets_dir() / "montar.svg").read_bytes()))
    result = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pm)
    return result


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)  # Qt ≥ 6.5
    if scheme is not None:
        return scheme() == Qt.ColorScheme.Dark
    window = QGuiApplication.palette().window().color()
    return window.lightness() < 128


class ThemeManager(QObject):
    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.mode = "light"
        self.palette: Palette = LIGHT

    def apply(self, mode: str) -> None:
        self.mode = mode
        dark = mode == "dark" or (mode == "system" and system_prefers_dark())
        self.palette = DARK if dark else LIGHT
        app = QApplication.instance()
        if app is not None:
            font = QFont(FONT_UI)
            font.setPixelSize(14)
            app.setFont(font)
            app.setStyleSheet(build_stylesheet(self.palette))
        self.changed.emit()

    def icon(self, name: str, color: str | None = None) -> QIcon:
        p = self.palette
        return icons.icon(name, color or p.ink, p.text_muted)


_theme: ThemeManager | None = None


def theme() -> ThemeManager:
    global _theme
    if _theme is None:
        _theme = ThemeManager()
    return _theme
