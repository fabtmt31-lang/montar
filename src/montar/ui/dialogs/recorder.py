# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran : réglages, puis petite fenêtre flottante pendant l'enregistrement."""
from __future__ import annotations

from PyQt6.QtCore import QEventLoop, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from montar.i18n import N_, _
from montar.media.recorder import (
    ON_WINDOWS,
    CameraPreview,
    LevelMeter,
    RecordOptions,
    can_pick_window,
    can_record_system_audio,
    can_select_region,
    microphones,
    webcams,
    window_titles,
)
from montar.ui.widgets import Segmented, button, label

COUNTDOWN = 3
WEBCAM_PLACES = (("bottom_right", N_("En bas à droite")), ("bottom_left", N_("En bas à gauche")),
                 ("top_right", N_("En haut à droite")), ("top_left", N_("En haut à gauche")),
                 ("split_right", N_("Écran partagé, webcam à droite")),
                 ("split_left", N_("Écran partagé, webcam à gauche")))


class LayoutPreview(QWidget):
    """Schéma de l'image enregistrée : l'écran et la place de la webcam."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(120)
        self.options = RecordOptions()

    def show_options(self, options: RecordOptions) -> None:
        self.options = options
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        o = self.options
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height() - 4
        w = h * 16 / 9
        frame = QRectF((self.width() - w) / 2, 2, w, h)
        p.fillRect(frame, QColor("#17261E"))
        share = max(0.1, min(0.6, o.webcam_size))
        screen = QRectF(frame)
        if o.split:
            sw = w * (1 - share)
            sh = sw * 9 / 16
            x = frame.left() if o.webcam_position == "split_right" else frame.right() - sw
            screen = QRectF(x, frame.top() + (h - sh) / 2, sw, sh)
            cam_w = w * share
            cam = QRectF(frame.right() - cam_w if o.webcam_position == "split_right"
                         else frame.left(), frame.top(), cam_w, h)
        else:
            cam_w = w * share
            cam_h = cam_w if o.webcam_shape == "round" else cam_w * 3 / 4
            m = 6
            left = o.webcam_position.endswith("left")
            top = o.webcam_position.startswith("top")
            cam = QRectF(frame.left() + m if left else frame.right() - m - cam_w,
                         frame.top() + m if top else frame.bottom() - m - cam_h, cam_w, cam_h)
        p.fillRect(screen, QColor("#9CCBB0"))
        p.setPen(QColor("#17261E"))
        p.drawText(screen, Qt.AlignmentFlag.AlignCenter, _("Écran"))
        if not o.webcam:
            p.end()
            return
        path = QPainterPath()
        if o.webcam_shape == "round" and not o.split:
            path.addEllipse(cam)
        else:
            path.addRoundedRect(cam, 3, 3)
        p.fillPath(path, QColor("#F4F1E6") if o.webcam_background != "remove"
                   else QColor(0, 0, 0, 0))
        # silhouette de la personne
        person = QPainterPath()
        cx, size = cam.center().x(), min(cam.width(), cam.height())
        person.addEllipse(QRectF(cx - size * 0.16, cam.top() + cam.height() * 0.2,
                                 size * 0.32, size * 0.36))
        person.addRoundedRect(QRectF(cx - size * 0.32, cam.top() + cam.height() * 0.6,
                                     size * 0.64, cam.height() * 0.4), size * 0.2, size * 0.2)
        p.save()
        p.setClipPath(path)
        p.fillPath(person, QColor("#2F7A56"))
        p.restore()
        p.setPen(QPen(QColor("#F4F1E6"), 1.5))
        p.drawPath(path)
        p.end()


class RecorderDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Enregistrer l'écran"))
        self.setModal(True)
        self.setMinimumWidth(860)
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

        # deux colonnes : que filmer et le son à gauche, la webcam à droite
        columns = QHBoxLayout()
        columns.setSpacing(28)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(10)
        right.setSpacing(10)
        left.addWidget(label(_("Que filmer ?")))
        sources = [("screen", _("Écran"))]
        if can_select_region():
            sources.append(("region", _("Zone")))
        if can_pick_window():
            sources.append(("window", _("Fenêtre")))
        self.source = Segmented(sources, "screen")
        self.source.setVisible(len(sources) > 1)
        self.source.changed.connect(self._source_changed)
        left.addWidget(self.source)
        self.screen = QComboBox()
        for i, screen in enumerate(QGuiApplication.screens()):
            g = screen.geometry()
            self.screen.addItem(f"{screen.name() or _('Écran')} {i + 1} · {g.width()} × "
                                f"{g.height()}", i)
        left.addWidget(self.screen)
        self.window_choice = QComboBox()  # Windows : fenêtre à filmer, choisie dans la liste
        for title in window_titles():
            self.window_choice.addItem(title, title)
        left.addWidget(self.window_choice)
        self.source_hint = label("", "small")
        self.source_hint.setWordWrap(True)
        left.addWidget(self.source_hint)
        left.addSpacing(6)

        left.addWidget(label(_("Son")))
        self.microphone = QCheckBox(_("Micro"))
        self.microphone.setChecked(True)
        left.addWidget(self.microphone)
        mic_row = QHBoxLayout()
        self.mic_device = QComboBox()
        self.mic_device.addItem(_("Micro par défaut"), "")
        for device, name in microphones():
            self.mic_device.addItem(name, device)
        self.mic_device.currentIndexChanged.connect(lambda _i: self._stop_test())
        self.test_button = button(_("Tester"), "secondary", "mic")
        self.test_button.setCheckable(True)
        self.test_button.toggled.connect(self._toggle_test)
        self.replay_button = button(_("Réécouter"), "secondary", "play")
        self.replay_button.setToolTip(_("Réécouter les dernières secondes du test du micro"))
        self.replay_button.setEnabled(False)
        self.replay_button.clicked.connect(self._replay)
        mic_row.addWidget(self.mic_device, 1)
        mic_row.addWidget(self.test_button)
        mic_row.addWidget(self.replay_button)
        left.addLayout(mic_row)
        self.level = QProgressBar()
        self.level.setObjectName("BusyBar")
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(8)
        self.level.setVisible(False)
        left.addWidget(self.level)
        self.level_hint = label("", "small")
        self.level_hint.setVisible(False)
        left.addWidget(self.level_hint)
        self.microphone.toggled.connect(self._mic_toggled)
        self._meter: LevelMeter | None = None
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(80)
        self._meter_timer.timeout.connect(self._show_level)
        self.system_audio = QCheckBox(_("Son de l'ordinateur"))
        left.addWidget(self.system_audio)
        self.system_audio.setVisible(can_record_system_audio())
        left.addSpacing(6)

        right.addWidget(label(_("Webcam")))
        self.webcam = QComboBox()
        self.webcam.addItem(_("Aucune"), "")
        for device in webcams():
            self.webcam.addItem(device, device)
        self.webcam.currentIndexChanged.connect(lambda _i: self._webcam_changed())
        cam_row = QHBoxLayout()
        cam_row.addWidget(self.webcam, 1)
        self.cam_test = button(_("Tester"), "secondary", "eye")
        self.cam_test.setCheckable(True)
        self.cam_test.toggled.connect(self._toggle_camera)
        cam_row.addWidget(self.cam_test)
        right.addLayout(cam_row)
        self.cam_view = QLabel()
        self.cam_view.setFixedSize(320, 180)
        self.cam_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cam_view.setStyleSheet("background: #17261E; color: #E8F0EC; border-radius: 8px;")
        self.cam_view.setVisible(False)
        right.addWidget(self.cam_view, 0, Qt.AlignmentFlag.AlignHCenter)
        self._camera: CameraPreview | None = None
        self._camera_timer = QTimer(self)
        self._camera_timer.setInterval(66)
        self._camera_timer.timeout.connect(self._show_camera)
        self.webcam_box = QWidget()
        wl = QVBoxLayout(self.webcam_box)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(8)
        self.place = QComboBox()
        for key, text in WEBCAM_PLACES:
            self.place.addItem(_(text), key)
        self.place.currentIndexChanged.connect(lambda _i: self._webcam_changed())
        wl.addWidget(self.place)
        size_row = QHBoxLayout()
        self.size_label = label("", "small")
        self.cam_size = QSlider(Qt.Orientation.Horizontal)
        self.cam_size.setRange(10, 50)
        self.cam_size.setValue(25)
        self.cam_size.valueChanged.connect(lambda _v: self._webcam_changed())
        size_row.addWidget(label(_("Taille")))
        size_row.addWidget(self.cam_size, 1)
        size_row.addWidget(self.size_label)
        wl.addLayout(size_row)
        self.shape = Segmented([("rect", _("Rectangle")), ("round", _("Rond"))], "rect",
                               compact=True)
        self.shape.changed.connect(lambda _k: self._webcam_changed())
        wl.addWidget(self.shape)
        wl.addWidget(label(_("Fond de la webcam")))
        self.background = Segmented([("none", _("Tel quel")), ("blur", _("Flouté")),
                                     ("remove", _("Effacé"))], "none", compact=True)
        self.background.changed.connect(lambda _k: self._webcam_changed())
        wl.addWidget(self.background)
        self.background_hint = label(_(
            "La personne est détourée sur l'ordinateur, une fois l'enregistrement fini "
            "(compter environ la moitié de la durée de l'enregistrement)."), "small")
        self.background_hint.setWordWrap(True)
        wl.addWidget(self.background_hint)
        self.preview = LayoutPreview()
        wl.addWidget(self.preview)
        right.addWidget(self.webcam_box)
        right.addSpacing(12)

        left.addStretch()
        right.addStretch()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)
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
        self._restore(RecorderDialog.last)
        self._webcam_changed()

    # réglages gardés d'un enregistrement à l'autre (pendant la session)
    last: RecordOptions | None = None

    def _restore(self, o: RecordOptions | None) -> None:
        if o is None:
            return
        for combo, value in ((self.mic_device, o.microphone_device), (self.webcam, o.webcam),
                             (self.place, o.webcam_position)):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.microphone.setChecked(o.microphone)
        self.cam_size.setValue(round(o.webcam_size * 100))
        self.shape.set_current(o.webcam_shape)
        self.background.set_current(o.webcam_background)

    def _webcam_changed(self) -> None:
        on = bool(self.webcam.currentData())
        self.webcam_box.setVisible(on)
        self.cam_test.setVisible(on)
        if self._camera is not None and self._camera_device != self.webcam.currentData():
            self._stop_camera()
        split = str(self.place.currentData()).startswith("split")
        self.shape.setVisible(not split)
        self.size_label.setText(f"{self.cam_size.value()} %")
        self.background_hint.setVisible(self.background.current() != "none")
        self.preview.show_options(self.options())
        if self.isVisible():
            self._fit()

    # --- test du micro ----------------------------------------------------------------

    def _mic_toggled(self, on: bool) -> None:
        self.mic_device.setEnabled(on)
        self.test_button.setEnabled(on)
        if not on:
            self._stop_test()

    def _toggle_test(self, on: bool) -> None:
        if not on:
            self._stop_test()
            return
        self._meter = LevelMeter(self.mic_device.currentData() or "")
        self.level.setVisible(True)
        self.level_hint.setVisible(True)
        self.level_hint.setText(self._meter.error or _("Parlez : la barre doit bouger."))
        self.test_button.setText(_("Arrêter le test"))
        self._meter_timer.start()

    def _show_level(self) -> None:
        meter = self._meter
        if meter is None:
            return
        self.level.setValue(round(min(1.0, meter.level * 1.6) * 100))
        if meter.error:
            self.level_hint.setText(meter.error)

    def _stop_test(self) -> None:
        self._meter_timer.stop()
        if self._meter is not None:
            self._meter.stop()
            self._keep_sample(self._meter)
            self._meter = None
        self.level.setValue(0)
        self.level.setVisible(False)
        self.level_hint.setVisible(False)
        if self.test_button.isChecked():
            self.test_button.blockSignals(True)
            self.test_button.setChecked(False)
            self.test_button.blockSignals(False)
        self.test_button.setText(_("Tester"))

    def _keep_sample(self, meter: LevelMeter) -> None:
        """Ce que le micro a entendu pendant le test, pour le réécouter."""
        import tempfile
        from pathlib import Path

        path = Path(tempfile.gettempdir()) / "montar-test-micro.wav"
        self._sample = (path, meter.seconds) if meter.save_wav(path) else None
        self.replay_button.setEnabled(self._sample is not None)

    def _replay(self) -> None:
        sample = getattr(self, "_sample", None)
        if sample is None:
            return
        path, seconds = sample
        try:
            from montar.engine import get_engine
            from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec

            frames = max(1, round(seconds * 25))
            spec = TimelineSpec(Canvas(320, 180, 25), (TrackSpec(
                "audio", False, False, (ClipSpec(str(path), "audio", 0, frames),)),))
            self._stop_replay()
            self._replay_output = get_engine().audio_output(spec)
        except Exception as exc:  # moteur ou sortie son absents
            self.level_hint.setText(str(exc))
            self.level_hint.setVisible(True)
            return
        if self._replay_output is None:
            self.level_hint.setText(_("Aucune sortie son pour réécouter."))
            self.level_hint.setVisible(True)
            return
        self._replay_output.start(0)
        QTimer.singleShot(round(seconds * 1000) + 300, self._stop_replay)

    def _stop_replay(self) -> None:
        output = getattr(self, "_replay_output", None)
        self._replay_output = None
        if output is not None:
            output.stop()
            output.close()

    # --- test de la webcam -------------------------------------------------------------

    def _toggle_camera(self, on: bool) -> None:
        if not on:
            self._stop_camera()
            return
        self._camera_device = self.webcam.currentData() or ""
        self._camera = CameraPreview(self._camera_device)
        self.cam_view.setText(self._camera.error or _("Ouverture de la webcam…"))
        self.cam_view.setVisible(True)
        self.cam_test.setText(_("Arrêter"))
        self._camera_timer.start()
        if self.isVisible():
            self._fit()

    def _show_camera(self) -> None:
        camera = self._camera
        if camera is None:
            return
        if camera.frame is not None:
            w, h = camera.size
            image = QImage(camera.frame, w, h, w * 3, QImage.Format.Format_RGB888)
            self.cam_view.setPixmap(QPixmap.fromImage(image))
        elif camera.error:
            self.cam_view.setText(camera.error)

    def _stop_camera(self) -> None:
        self._camera_timer.stop()
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
        self.cam_view.clear()
        self.cam_view.setVisible(False)
        if self.cam_test.isChecked():
            self.cam_test.blockSignals(True)
            self.cam_test.setChecked(False)
            self.cam_test.blockSignals(False)
        self.cam_test.setText(_("Tester"))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Hauteur ajustée au contenu (textes sur plusieurs lignes compris)."""
        self.adjustSize()
        wanted = self.layout().heightForWidth(self.width())
        if wanted > self.height():
            self.resize(self.width(), wanted)

    def done(self, result: int) -> None:  # noqa: D102
        # le micro et la webcam doivent être libres pour l'enregistrement
        self._stop_test()
        self._stop_camera()
        self._stop_replay()
        if result == QDialog.DialogCode.Accepted:
            RecorderDialog.last = self.options()
        super().done(result)

    def _source_changed(self, key: str) -> None:
        # Windows : la zone se dessine sur l'écran choisi, avant le compte à rebours
        self.screen.setVisible(key in ("screen", "region"))
        self.window_choice.setVisible(ON_WINDOWS and key == "window")
        if ON_WINDOWS:
            hints = {"region": _("Après validation, dessinez la zone à filmer avec la souris "
                                 "(Échap pour annuler)."),
                     "window": _("La fenêtre passe au premier plan au début de "
                                 "l'enregistrement et la place qu'elle occupe à l'écran est "
                                 "filmée : gardez-la devant les autres, sans la déplacer.")
                     if self.window_choice.count() else _("Aucune fenêtre à filmer.")}
        else:
            hints = {"region": _("Après validation, dessinez la zone à filmer avec la souris "
                                 "(Échap pour annuler)."),
                     "window": _("Après validation, cliquez sur la fenêtre à filmer.")}
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
                             and not self.system_audio.isHidden(),
                             webcam=self.webcam.currentData() or "",
                             screen_index=self.screen.currentData() or 0,
                             window_title=self.window_choice.currentData() or "",
                             microphone_device=self.mic_device.currentData() or "",
                             webcam_position=self.place.currentData() or "bottom_right",
                             webcam_size=self.cam_size.value() / 100,
                             webcam_shape=self.shape.current(),
                             webcam_background=self.background.current())

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


def logical_rect(area: tuple[int, int, int, int]) -> QRect:
    """Rectangle en pixels réels (Windows) → coordonnées de Qt, d'après l'écran qui le
    contient (mise à l'échelle propre à chaque écran)."""
    x, y, w, h = area
    for screen in QGuiApplication.screens():
        g, ratio = screen.geometry(), screen.devicePixelRatio()
        # Qt garde le coin de chaque écran en pixels réels et divise le reste
        if g.x() <= x < g.x() + g.width() * ratio and g.y() <= y < g.y() + g.height() * ratio:
            return QRect(round(g.x() + (x - g.x()) / ratio), round(g.y() + (y - g.y()) / ratio),
                         round(w / ratio), round(h / ratio))
    return QRect(x, y, w, h)


class CaptureHighlight(QWidget):
    """Cadre qui clignote autour de ce qui va être filmé pendant le compte à rebours :
    on voit tout de suite si c'est le bon écran, la bonne zone ou la bonne fenêtre."""

    BORDER = 6

    def __init__(self, area: QRect) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        b = self.BORDER
        self.setGeometry(area.adjusted(-b, -b, b, b))
        self._on = True
        self._timer = QTimer(self)
        self._timer.setInterval(280)
        self._timer.timeout.connect(self._blink)

    def start(self) -> None:
        self.show()
        self._timer.start()

    def _blink(self) -> None:
        self._on = not self._on
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        color = QColor("#F7C948") if self._on else QColor("#2F7A56")
        painter.setPen(QPen(color, self.BORDER))
        b = self.BORDER / 2
        painter.drawRect(QRectF(self.rect()).adjusted(b, b, -b, -b))
        if self._on:  # léger voile pour bien voir la zone
            painter.fillRect(self.rect().adjusted(self.BORDER, self.BORDER, -self.BORDER,
                                                  -self.BORDER), QColor(247, 201, 72, 28))
        painter.end()


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
