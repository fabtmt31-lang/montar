# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran : réglages, puis petite fenêtre flottante pendant l'enregistrement."""
from __future__ import annotations

from PyQt6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import _
from montar.media.recorder import (
    ON_WINDOWS,
    RecordOptions,
    can_pick_window,
    can_record_system_audio,
    can_select_region,
    webcams,
    window_titles,
)
from montar.ui.widgets import Segmented, button, label

COUNTDOWN = 3


class RecorderDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Enregistrer l'écran"))
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.addWidget(label(_("Enregistrer l'écran"), "h2"))
        hint = label(_("L'enregistrement est ajouté aux médias du projet. montar se réduit "
                       "pendant l'enregistrement ; une petite fenêtre permet de l'arrêter."),
                     "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(6)

        layout.addWidget(label(_("Que filmer ?")))
        sources = [("screen", _("Écran"))]
        if can_select_region():
            sources.append(("region", _("Zone")))
        if can_pick_window():
            sources.append(("window", _("Fenêtre")))
        self.source = Segmented(sources, "screen")
        self.source.setVisible(len(sources) > 1)
        self.source.changed.connect(self._source_changed)
        layout.addWidget(self.source)
        self.screen = QComboBox()
        for i, screen in enumerate(QGuiApplication.screens()):
            g = screen.geometry()
            self.screen.addItem(f"{screen.name() or _('Écran')} {i + 1} · {g.width()} × "
                                f"{g.height()}", i)
        layout.addWidget(self.screen)
        self.window_choice = QComboBox()  # Windows : fenêtre à filmer, choisie dans la liste
        for title in window_titles():
            self.window_choice.addItem(title, title)
        layout.addWidget(self.window_choice)
        self.source_hint = label("", "small")
        self.source_hint.setWordWrap(True)
        layout.addWidget(self.source_hint)
        layout.addSpacing(6)

        layout.addWidget(label(_("Son")))
        self.microphone = QCheckBox(_("Micro"))
        self.microphone.setChecked(True)
        self.system_audio = QCheckBox(_("Son de l'ordinateur"))
        layout.addWidget(self.microphone)
        layout.addWidget(self.system_audio)
        self.system_audio.setVisible(can_record_system_audio())
        layout.addSpacing(6)
        layout.addWidget(label(_("Webcam (en incrustation, en bas à droite)")))
        self.webcam = QComboBox()
        self.webcam.addItem(_("Aucune"), "")
        for device in webcams():
            self.webcam.addItem(device, device)
        layout.addWidget(self.webcam)
        layout.addSpacing(12)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        start = button(_("Démarrer l'enregistrement"), "primary", "circle-dot")
        start.clicked.connect(self.accept)
        for b in (cancel, start):
            b.setMinimumHeight(42)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._source_changed("screen")

    def _source_changed(self, key: str) -> None:
        # Windows : la zone se dessine sur l'écran choisi, avant le compte à rebours
        self.screen.setVisible(key == "screen" or (ON_WINDOWS and key == "region"))
        self.window_choice.setVisible(ON_WINDOWS and key == "window")
        if ON_WINDOWS:
            hints = {"region": _("Après validation, dessinez la zone à filmer avec la souris "
                                 "(Échap pour annuler)."),
                     "window": _("La fenêtre est filmée même si elle passe derrière une autre ; "
                                 "elle ne doit pas être réduite.")
                     if self.window_choice.count() else _("Aucune fenêtre à filmer.")}
        else:
            hints = {"region": _("Après le compte à rebours, dessinez la zone à filmer avec la "
                                 "souris."),
                     "window": _("Après le compte à rebours, cliquez sur la fenêtre à filmer.")}
        self.source_hint.setText(hints.get(key, ""))

    def options(self) -> RecordOptions:
        screens = QGuiApplication.screens()
        screen = screens[self.screen.currentData() or 0] if screens else None
        geometry = (0, 0, 1920, 1080)
        if screen is not None:
            g = screen.geometry()
            ratio = screen.devicePixelRatio()
            geometry = (round(g.x() * ratio), round(g.y() * ratio),
                        round(g.width() * ratio), round(g.height() * ratio))
        return RecordOptions(self.source.current(), geometry,
                             microphone=self.microphone.isChecked(),
                             system_audio=self.system_audio.isChecked()
                             and self.system_audio.isVisible(),
                             webcam=self.webcam.currentData() or "",
                             screen_index=self.screen.currentData() or 0,
                             window_title=self.window_choice.currentData() or "")

    def chosen_screen(self):
        screens = QGuiApplication.screens()
        return screens[self.screen.currentData() or 0] if screens else None


class RegionSelector(QWidget):
    """Écran assombri ; la zone à filmer se dessine à la souris (Échap : annuler)."""

    def __init__(self, screen) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())
        self._start: QPoint | None = None
        self._rect = QRect()
        self.result: QRect | None = None
        self._loop = QEventLoop()

    def select(self) -> QRect | None:
        """Zone choisie, en coordonnées de l'écran (pixels logiques), ou None."""
        self.showFullScreen()
        self.activateWindow()
        self._loop.exec()
        return self.result

    def _finish(self, rect: QRect | None) -> None:
        self.result = rect
        self.close()
        self._loop.quit()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self._rect.isNull():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self._rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#2E7D5B"), 2))
            painter.drawRect(self._rect)
            painter.setPen(QColor("white"))
            painter.drawText(self._rect.bottomLeft() + QPoint(4, 18),
                             f"{self._rect.width()} × {self._rect.height()}")
        else:
            painter.setPen(QColor("white"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             _("Dessinez la zone à filmer — Échap pour annuler"))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._start = event.position().toPoint()
        self._rect = QRect(self._start, self._start)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start is not None:
            self._rect = QRect(self._start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._start is not None and self._rect.width() > 16 and self._rect.height() > 16:
            self._finish(self._rect)
        else:  # simple clic : on recommence
            self._start, self._rect = None, QRect()
            self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._loop.isRunning():
            self._loop.quit()
        super().closeEvent(event)


def physical_region(screen, rect: QRect) -> tuple[int, int, int, int]:
    """Zone en pixels réels de l'écran (mise à l'échelle de Windows prise en compte)."""
    ratio = screen.devicePixelRatio()
    return (round(rect.x() * ratio), round(rect.y() * ratio),
            round(rect.width() * ratio), round(rect.height() * ratio))


class RecordingBar(QFrame):
    """Fenêtre flottante, toujours au premier plan : compte à rebours, durée, Arrêter."""

    stopRequested = pyqtSignal()
    countdownFinished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("BusyCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 10, 10)
        layout.setSpacing(12)
        self.dot = label("●")
        self.dot.setStyleSheet("color: #D33A2C; font-size: 18px;")
        self.time = label("", "h3")
        self.stop_button = button(_("Arrêter"), "primary", "x")
        self.stop_button.clicked.connect(self.stopRequested)
        layout.addWidget(self.dot)
        layout.addWidget(self.time)
        layout.addWidget(self.stop_button)
        self._left = COUNTDOWN
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start_countdown(self, seconds: int = COUNTDOWN) -> None:
        self._left = seconds
        self.time.setText(_("Début dans {n} s").format(n=seconds))
        screen = QGuiApplication.primaryScreen()
        self.adjustSize()
        if screen is not None:
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.bottom() - self.height() - 40)
        self.show()
        exclude_from_capture(self)
        if seconds <= 0:
            self.countdownFinished.emit()
        else:
            self._timer.start()

    def _tick(self) -> None:
        self._left -= 1
        if self._left > 0:
            self.time.setText(_("Début dans {n} s").format(n=self._left))
        else:
            self._timer.stop()
            self.countdownFinished.emit()

    def set_elapsed(self, seconds: float) -> None:
        s = int(seconds)
        self.time.setText(f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}")


def exclude_from_capture(widget: QWidget) -> None:
    """Windows 10 (2004) et plus : la fenêtre n'apparaît pas dans l'enregistrement."""
    if not ON_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11)
    except (AttributeError, OSError):
        pass
