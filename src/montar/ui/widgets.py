# SPDX-License-Identifier: GPL-3.0-or-later
"""Composants d'interface réutilisables, conformes à la charte."""
from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QEvent, QObject, QRectF, QSize, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QWidget,
)

from montar.ui.theme import theme


def set_prop(widget: QWidget, name: str, value: object) -> None:
    """Change une propriété dynamique utilisée par la feuille de style et réapplique le style."""
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _IconBinder(QObject):
    """Met à jour l'icône d'un bouton quand le thème change (détruit avec le bouton)."""

    def __init__(self, button: QAbstractButton, name: str, role: str) -> None:
        super().__init__(button)
        self._button, self._name, self.role = button, name, role
        theme().changed.connect(self.refresh)
        self.refresh()

    @pyqtSlot()
    def refresh(self) -> None:
        color = getattr(theme().palette, self.role)
        self._button.setIcon(theme().icon(self._name, color))


def set_icon(button: QAbstractButton, name: str, role: str = "ink", size: int = 20) -> None:
    old = button.findChild(_IconBinder)
    if old is not None:
        old.deleteLater()
    button.setIconSize(QSize(size, size))
    _IconBinder(button, name, role)


def shrink(widget: QWidget) -> QWidget:
    """Le widget accepte d'être plus étroit que son contenu (panneaux de largeur fixe)."""
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)
    widget.setMinimumWidth(0)
    return widget


def label(text: str = "", role: str | None = None, parent: QWidget | None = None) -> QLabel:
    lbl = QLabel(text, parent)
    if role:
        lbl.setProperty("role", role)
    return lbl


def button(
    text: str = "",
    variant: str | None = None,
    icon: str | None = None,
    icon_role: str | None = None,
    tooltip: str | None = None,
) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        btn.setProperty("variant", variant)
    if icon:
        role = icon_role or {"primary": "on_forest", "round": "on_forest",
                             "tonal": "forest", "secondary": "forest",
                             "dashed": "forest"}.get(variant or "", "ink")
        set_icon(btn, icon, role, 18 if text else 20)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


class Segmented(QFrame):
    """Contrôle segmenté (ex. Montage | Couleur | Audio | Sous-titres)."""

    changed = pyqtSignal(str)

    def __init__(self, options: Sequence[tuple[str, str]], current: str | None = None,
                 parent: QWidget | None = None, compact: bool = False,
                 columns: int = 0) -> None:
        super().__init__(parent)
        self.setObjectName("Segmented")
        if compact:  # se partage la largeur disponible au lieu d'imposer la sienne
            self.setProperty("compact", True)
        # `columns` : choix sur plusieurs lignes (beaucoup d'options dans un volet étroit)
        layout = QGridLayout(self) if columns else QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            if compact:
                shrink(btn)
            self._group.addButton(btn)
            if columns:
                index = len(self._buttons)
                layout.addWidget(btn, index // columns, index % columns)
            else:
                layout.addWidget(btn)
            self._buttons[key] = btn
        self.set_current(current or options[0][0])

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def current(self) -> str:
        return next(k for k, b in self._buttons.items() if b.isChecked())

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]


class LogoMark(QFrame):
    """Carré Forêt arrondi avec le triangle « lecture » (logo montar)."""

    def __init__(self, size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogoMark")
        self.setFixedSize(size, size)
        icon_label = QLabel(self)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setGeometry(0, 0, size, size)
        self._icon_label, self._size = icon_label, size
        theme().changed.connect(self._refresh)
        self._refresh()

    @pyqtSlot()
    def _refresh(self) -> None:
        from montar.ui.theme.icons import pixmap

        self._icon_label.setPixmap(pixmap("play", theme().palette.on_forest, self._size // 2))


def logo(size: int = 36, with_text: bool = True) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(LogoMark(size))
    if with_text:
        layout.addWidget(label("montar", "logo"))
    layout.addStretch()
    return box


def rounded_pixmap(source: QPixmap, size: QSize, radius: float,
                   fill: QColor | None = None) -> QPixmap:
    """Image recadrée pour remplir `size`, coins arrondis."""
    dpr = 2.0
    out = QPixmap(int(size.width() * dpr), int(size.height() * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    painter.setClipPath(path)
    if fill is not None:
        painter.fillRect(QRectF(0, 0, size.width(), size.height()), fill)
    if not source.isNull():
        scaled = source.scaled(out.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        x = (size.width() - scaled.width() / dpr) / 2
        y = (size.height() - scaled.height() / dpr) / 2
        painter.drawPixmap(int(x), int(y), scaled)
    painter.end()
    return out


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFixedHeight(1)
    return line


class Switch(QAbstractButton):
    """Interrupteur (maquette 06)."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        theme().changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        on = self.isChecked()
        track = QColor(p.forest if on else p.mist)
        if not self.isEnabled():
            track.setAlphaF(0.5)
        painter.setBrush(track)
        painter.drawRoundedRect(self.rect(), 13, 13)
        painter.setBrush(QColor("#FFFFFF"))
        x = self.width() - 23 if on else 3
        painter.drawEllipse(x, 3, 20, 20)
        painter.end()


class WheelGuard(QObject):
    """Dans un panneau qui défile (inspecteur, panneaux latéraux, préférences), la molette
    ou le défilement à deux doigts fait défiler le panneau, même si le pointeur passe sur un
    curseur ou une liste déroulante : ceux-ci ne réagissent à la molette qu'après un clic.
    Ailleurs (zoom de la timeline, volume de l'aperçu), la molette garde son effet."""

    GUARDED = (QAbstractSlider, QComboBox, QAbstractSpinBox)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel or not isinstance(obj, self.GUARDED) \
                or isinstance(obj, QScrollBar) or obj.hasFocus():
            return False  # la barre de défilement reçoit la molette du panneau : on la laisse
        area = obj.parentWidget()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is None:
            return False
        QApplication.sendEvent(area.viewport(), event)  # le panneau défile
        return True


_wheel_guard: WheelGuard | None = None


def install_wheel_guard(app: QApplication) -> None:
    """Une seule fois par application ; les curseurs ne prennent le focus qu'au clic."""
    global _wheel_guard
    if _wheel_guard is None:
        _wheel_guard = WheelGuard(app)
        app.installEventFilter(_wheel_guard)
