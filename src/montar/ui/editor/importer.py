# SPDX-License-Identifier: GPL-3.0-or-later
"""Analyse et vignettes des médias importés, en tâche de fond."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from montar.media.probe import ProbeError, probe
from montar.media.thumbnails import make_thumbnail
from montar.media.waveform import load_or_compute


class _Signals(QObject):
    done = pyqtSignal(str, object, object, str)  # chemin, MediaItem|None, vignette|None, erreur


class _ProbeTask(QRunnable):
    def __init__(self, path: str, cache: Path, signals: _Signals) -> None:
        super().__init__()
        self._path, self._cache, self._signals = path, cache, signals

    def run(self) -> None:
        try:
            item = probe(self._path)
        except (ProbeError, ValueError) as exc:
            self._signals.done.emit(self._path, None, None, str(exc))
            return
        thumb = make_thumbnail(self._cache, item)
        self._signals.done.emit(self._path, item, str(thumb) if thumb else None, "")


class _ThumbTask(QRunnable):
    def __init__(self, item, cache: Path, signals: _Signals) -> None:
        super().__init__()
        self._item, self._cache, self._signals = item, cache, signals

    def run(self) -> None:
        thumb = make_thumbnail(self._cache, self._item)
        self._signals.done.emit(self._item.path, self._item, str(thumb) if thumb else None, "")


class _WaveformTask(QRunnable):
    def __init__(self, path: str, cache: Path, signals: _Signals) -> None:
        super().__init__()
        self._path, self._cache, self._signals = path, cache, signals

    def run(self) -> None:
        peaks = load_or_compute(self._cache, self._path)
        self._signals.done.emit(self._path, None, peaks, "")


class MediaImporter(QObject):
    """Émet `finished` pour chaque fichier : (chemin, MediaItem ou None, vignette, erreur)."""

    finished = pyqtSignal(str, object, object, str)
    thumbnailReady = pyqtSignal(str, object)  # chemin du média, vignette
    waveformReady = pyqtSignal(str, object)  # chemin du média, crêtes (bytes) ou None

    def __init__(self, cache: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(4, QThreadPool.globalInstance().maxThreadCount())))
        self._signals = _Signals()
        self._signals.done.connect(self.finished)
        self._thumb_signals = _Signals()
        self._thumb_signals.done.connect(lambda p, _i, t, _e: self.thumbnailReady.emit(p, t))
        self._wave_signals = _Signals()
        self._wave_signals.done.connect(lambda p, _i, w, _e: self.waveformReady.emit(p, w))

    def import_files(self, paths: list[str]) -> None:
        for p in paths:
            self._pool.start(_ProbeTask(p, self._cache, self._signals))

    def ensure_thumbnail(self, item) -> None:
        self._pool.start(_ThumbTask(item, self._cache, self._thumb_signals))

    def ensure_waveform(self, path: str) -> None:
        self._pool.start(_WaveformTask(path, self._cache, self._wave_signals))

    def wait(self, msecs: int = -1) -> bool:
        return self._pool.waitForDone(msecs)
