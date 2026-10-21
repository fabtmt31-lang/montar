# SPDX-License-Identifier: GPL-3.0-or-later
"""Lecture de l'aperçu dans un fil dédié : le moteur n'est jamais appelé depuis l'interface.

Pendant la lecture, l'horloge est la position de la sortie son ; sans sortie son
(aucun périphérique audio), l'horloge système prend le relais.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from montar.engine.base import AudioOutput, Engine, Source, TimelineSpec

log = logging.getLogger(__name__)


class PlaybackWorker(QObject):
    frameReady = pyqtSignal(QImage, int)
    loaded = pyqtSignal(int, float)  # nombre d'images, i/s
    failed = pyqtSignal(str)
    playingChanged = pyqtSignal(bool)

    def __init__(self, engine_factory: Callable[[], Engine]) -> None:
        super().__init__()
        self._engine_factory = engine_factory
        self._engine: Engine | None = None
        self._spec: TimelineSpec | None = None
        self._source: Source | None = None
        self._audio: AudioOutput | None = None
        self._audio_stale = True
        self._size = (320, 180)
        self._position = 0
        self._pending_seek: int | None = None
        self._pending_spec: TimelineSpec | None = None
        self._playing = False
        self._play_origin = (0.0, 0)  # (instant, image) du début de lecture sans son
        self._timer: QTimer | None = None

    @pyqtSlot()
    def setup(self) -> None:
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def _ensure_engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._engine_factory()
        return self._engine

    @property
    def _length(self) -> int:
        return self._source.length if self._source is not None else 0

    @pyqtSlot(object)
    def load(self, spec: TimelineSpec) -> None:
        # Les demandes accumulées pendant un rendu sont regroupées : seule la dernière compte.
        first = self._pending_spec is None
        self._pending_spec = spec
        if first:
            QTimer.singleShot(0, self._apply_load)

    def _apply_load(self) -> None:
        spec, self._pending_spec = self._pending_spec, None
        if spec is None:
            return
        if self._source is not None and self._spec is not None and self._source.update(spec):
            # seuls des réglages de clips ont changé : pas de reconstruction
            self._spec = spec
            self._audio_stale = True
            if self._playing:
                self._position = self._clock()
                if self._audio is not None:
                    self._audio.stop()
                self._start_clock()
            else:
                self._render(self._position)
            return
        self._rebuild(spec)

    def _rebuild(self, spec: TimelineSpec) -> None:
        """Reconstruit la timeline ; une lecture en cours continue sans interruption visible."""
        was_playing = self._playing
        if was_playing:  # pause silencieuse : l'interface reste en mode lecture
            self._position = self._clock()
            if self._timer is not None:
                self._timer.stop()
            if self._audio is not None:
                self._audio.stop()
        self._close()
        self._spec = spec
        try:
            self._source = self._ensure_engine().build(spec)
        except Exception as exc:  # moteur absent ou média illisible
            self._source = None
            if was_playing:
                self._playing = False
                self.playingChanged.emit(False)
            self.failed.emit(str(exc))
            return
        self._audio_stale = True
        self._position = max(0, min(self._position, self._length - 1))
        self.loaded.emit(self._length, float(spec.canvas.fps))
        self._render(self._position)
        if was_playing:
            if self._length == 0:
                self._playing = False
                self.playingChanged.emit(False)
                return
            self._start_clock()
            self._timer.start(max(1, int(500 / max(1, spec.canvas.fps))))

    def _close(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None
        if self._audio is not None:
            self._audio.close()
            self._audio = None

    @pyqtSlot()
    def close(self) -> None:
        self._stop()
        self._close()

    @pyqtSlot(int, int)
    def set_render_size(self, width: int, height: int) -> None:
        size = (max(2, width - width % 2), max(2, height - height % 2))
        if size != self._size:
            self._size = size
            if self._source is not None and not self._playing:
                self._render(self._position)

    @pyqtSlot(int)
    def seek(self, frame: int) -> None:
        # Les demandes successives (glissement de la tête de lecture) sont regroupées :
        # seule la dernière est rendue.
        first = self._pending_seek is None
        self._pending_seek = frame
        if first:
            QTimer.singleShot(0, self._apply_seek)

    def _apply_seek(self) -> None:
        frame, self._pending_seek = self._pending_seek, None
        if frame is None or self._source is None:
            return
        self._position = max(0, min(frame, max(0, self._length - 1)))
        self._render(self._position)
        if self._playing:
            self._start_clock()

    @pyqtSlot()
    def play(self) -> None:
        if self._source is None or self._playing or self._timer is None or self._length == 0:
            return
        if self._position >= self._length - 1:
            self._position = 0
        self._playing = True
        self._start_clock()
        self._timer.start(max(1, int(500 / max(1, self._spec.canvas.fps))))
        self.playingChanged.emit(True)

    def _start_clock(self) -> None:
        if self._audio_stale and self._spec is not None:
            if self._audio is not None:
                self._audio.close()
            try:
                self._audio = self._ensure_engine().audio_output(self._spec)
            except Exception as exc:
                log.warning("sortie son indisponible : %s", exc)
                self._audio = None
            self._audio_stale = False
        if self._audio is not None:
            try:
                self._audio.start(self._position)
            except Exception as exc:
                log.warning("lecture du son impossible : %s", exc)
                self._audio.close()
                self._audio = None
        self._play_origin = (time.perf_counter(), self._position)

    @pyqtSlot()
    def pause(self) -> None:
        self._stop()

    def _stop(self) -> None:
        if self._playing:
            self._playing = False
            if self._timer is not None:
                self._timer.stop()
            if self._audio is not None:
                self._audio.stop()
            self.playingChanged.emit(False)

    def _clock(self) -> int:
        start_t, start_f = self._play_origin
        elapsed = time.perf_counter() - start_t
        wall = start_f + int(elapsed * self._spec.canvas.fps)
        if self._audio is not None and elapsed > 0.25:
            # Juste après un démarrage, la sortie son peut encore annoncer son ancienne
            # position : elle ne sert d'horloge que si elle est cohérente.
            heard = self._audio.position()
            if abs(heard - wall) <= self._spec.canvas.fps:
                return heard
        return wall

    def _tick(self) -> None:
        if self._source is None:
            self._stop()
            return
        target = self._clock()
        last = self._length - 1
        if target >= last:
            self._position = last
            self._render(last)
            self._stop()
            return
        if target > self._position:
            self._position = target  # les images en retard sont sautées
            self._render(target)

    def _render(self, frame: int) -> None:
        if self._source is None or self._spec is None:
            return
        w, h = self._fit(self._size)
        try:
            data = self._source.render(frame, w, h)
        except Exception as exc:
            self.failed.emit(str(exc))
            self._stop()
            return
        image = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        self.frameReady.emit(image, frame)

    def _fit(self, size: tuple[int, int]) -> tuple[int, int]:
        """Plus grande taille au format de la toile tenant dans `size`, sans dépasser la toile."""
        assert self._spec is not None
        cw, ch = self._spec.canvas.width, self._spec.canvas.height
        scale = min(size[0] / cw, size[1] / ch, 1.0)
        w, h = max(2, int(cw * scale)), max(2, int(ch * scale))
        return w - w % 2, h - h % 2


class Player(QObject):
    """Façade côté interface ; toutes les commandes sont transmises au fil de lecture."""

    frameReady = pyqtSignal(QImage, int)
    loaded = pyqtSignal(int, float)
    failed = pyqtSignal(str)
    playingChanged = pyqtSignal(bool)

    _load = pyqtSignal(object)
    _close = pyqtSignal()
    _seek = pyqtSignal(int)
    _play = pyqtSignal()
    _pause = pyqtSignal()
    _size = pyqtSignal(int, int)

    def __init__(self, engine_factory: Callable[[], Engine], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("montar-preview")
        self._worker = PlaybackWorker(engine_factory)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.setup)
        self._load.connect(self._worker.load)
        self._close.connect(self._worker.close)
        self._seek.connect(self._worker.seek)
        self._play.connect(self._worker.play)
        self._pause.connect(self._worker.pause)
        self._size.connect(self._worker.set_render_size)
        self._worker.frameReady.connect(self._on_frame)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self.failed)
        self._worker.playingChanged.connect(self._on_playing)
        self._thread.start()
        self.length = 0
        self.fps = 25.0
        self.position = 0
        self.playing = False

    def load(self, spec: TimelineSpec) -> None:
        self._load.emit(spec)

    def seek(self, frame: int) -> None:
        self.position = max(0, int(frame))
        self._seek.emit(self.position)

    def play(self) -> None:
        self._play.emit()

    def pause(self) -> None:
        self._pause.emit()

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def set_render_size(self, width: int, height: int) -> None:
        self._size.emit(width, height)

    def shutdown(self) -> None:
        self._close.emit()
        self._thread.quit()
        self._thread.wait(5000)

    def _on_frame(self, image: QImage, frame: int) -> None:
        self.position = frame
        self.frameReady.emit(image, frame)

    def _on_loaded(self, length: int, fps: float) -> None:
        self.length, self.fps = length, fps
        self.loaded.emit(length, fps)

    def _on_playing(self, playing: bool) -> None:
        self.playing = playing
        self.playingChanged.emit(playing)
