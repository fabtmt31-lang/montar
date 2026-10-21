# SPDX-License-Identifier: GPL-3.0-or-later
"""Lecture de l'aperçu dans un fil dédié : le moteur n'est jamais appelé depuis l'interface."""
from __future__ import annotations

import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from montar.engine.base import Canvas, Engine


class PlaybackWorker(QObject):
    frameReady = pyqtSignal(QImage, int)
    opened = pyqtSignal(int, float)  # nombre d'images, i/s
    failed = pyqtSignal(str)
    playingChanged = pyqtSignal(bool)

    def __init__(self, engine_factory: Callable[[], Engine]) -> None:
        super().__init__()
        self._engine_factory = engine_factory
        self._engine: Engine | None = None
        self._source = None
        self._canvas: Canvas | None = None
        self._size = (320, 180)
        self._position = 0
        self._pending_seek: int | None = None
        self._playing = False
        self._play_origin = (0.0, 0)  # (instant, image) du début de lecture
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

    @pyqtSlot(str, str, int, int, int)
    def open(self, path: str, kind: str, width: int, height: int, fps: int) -> None:
        self._stop()
        self._close_source()
        try:
            self._canvas = Canvas(width, height, fps)
            self._source = self._ensure_engine().open(path, kind, self._canvas)
        except Exception as exc:  # moteur absent ou média illisible
            self._source = None
            self.failed.emit(str(exc))
            return
        self._position = 0
        self.opened.emit(self._source.length, self._source.fps)
        self._render(0)

    @pyqtSlot()
    def close(self) -> None:
        self._stop()
        self._close_source()

    def _close_source(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None

    @pyqtSlot(int, int)
    def set_render_size(self, width: int, height: int) -> None:
        size = (max(2, width - width % 2), max(2, height - height % 2))
        if size != self._size:
            self._size = size
            if self._source is not None and not self._playing:
                self._render(self._position)

    @pyqtSlot(int)
    def seek(self, frame: int) -> None:
        # Les demandes successives (glissement du curseur) sont regroupées : seule la
        # dernière est rendue.
        first = self._pending_seek is None
        self._pending_seek = frame
        if first:
            QTimer.singleShot(0, self._apply_seek)

    def _apply_seek(self) -> None:
        frame, self._pending_seek = self._pending_seek, None
        if frame is None or self._source is None:
            return
        self._position = max(0, min(frame, self._source.length - 1))
        if self._playing:
            self._play_origin = (time.perf_counter(), self._position)
        self._render(self._position)

    @pyqtSlot()
    def play(self) -> None:
        if self._source is None or self._playing or self._timer is None:
            return
        if self._position >= self._source.length - 1:
            self._position = 0
        self._playing = True
        self._play_origin = (time.perf_counter(), self._position)
        self._timer.start(max(1, int(500 / max(1.0, self._source.fps))))
        self.playingChanged.emit(True)

    @pyqtSlot()
    def pause(self) -> None:
        self._stop()

    def _stop(self) -> None:
        if self._playing:
            self._playing = False
            if self._timer is not None:
                self._timer.stop()
            self.playingChanged.emit(False)

    def _tick(self) -> None:
        if self._source is None:
            self._stop()
            return
        start_t, start_f = self._play_origin
        target = start_f + int((time.perf_counter() - start_t) * self._source.fps)
        last = self._source.length - 1
        if target >= last:
            self._render(last)
            self._position = last
            self._stop()
            return
        if target != self._position:
            self._position = target  # les images en retard sont sautées
            self._render(target)

    def _render(self, frame: int) -> None:
        if self._source is None or self._canvas is None:
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
        assert self._canvas is not None
        cw, ch = self._canvas.width, self._canvas.height
        scale = min(size[0] / cw, size[1] / ch, 1.0)
        w, h = max(2, int(cw * scale)), max(2, int(ch * scale))
        return w - w % 2, h - h % 2


class Player(QObject):
    """Façade côté interface ; toutes les commandes sont transmises au fil de lecture."""

    frameReady = pyqtSignal(QImage, int)
    opened = pyqtSignal(int, float)
    failed = pyqtSignal(str)
    playingChanged = pyqtSignal(bool)

    _open = pyqtSignal(str, str, int, int, int)
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
        self._open.connect(self._worker.open)
        self._close.connect(self._worker.close)
        self._seek.connect(self._worker.seek)
        self._play.connect(self._worker.play)
        self._pause.connect(self._worker.pause)
        self._size.connect(self._worker.set_render_size)
        self._worker.frameReady.connect(self._on_frame)
        self._worker.opened.connect(self._on_opened)
        self._worker.failed.connect(self.failed)
        self._worker.playingChanged.connect(self._on_playing)
        self._thread.start()
        self.length = 0
        self.fps = 25.0
        self.position = 0
        self.playing = False

    def open(self, path: str, kind: str, canvas: Canvas) -> None:
        self._open.emit(path, kind, canvas.width, canvas.height, canvas.fps)

    def close(self) -> None:
        self.length = 0
        self.position = 0
        self._close.emit()

    def seek(self, frame: int) -> None:
        self._seek.emit(int(frame))

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
        self._thread.wait(3000)

    def _on_frame(self, image: QImage, frame: int) -> None:
        self.position = frame
        self.frameReady.emit(image, frame)

    def _on_opened(self, length: int, fps: float) -> None:
        self.length, self.fps = length, fps
        self.opened.emit(length, fps)

    def _on_playing(self, playing: bool) -> None:
        self.playing = playing
        self.playingChanged.emit(playing)
