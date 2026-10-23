# SPDX-License-Identifier: GPL-3.0-or-later
"""Copie dans le dossier du projet, analyse et vignettes des médias importés, en tâche
de fond."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from montar.media.probe import ProbeError, probe
from montar.media.proxies import make_proxy, proxy_path
from montar.media.store import CopyCancelled, copy_media
from montar.media.thumbnails import make_thumbnail
from montar.media.waveform import load_or_compute


class _Signals(QObject):
    done = pyqtSignal(str, object, object, str)  # chemin, MediaItem|None, vignette|None, erreur
    progress = pyqtSignal(str, float)  # chemin d'origine, avancement de la copie


class _ProbeTask(QRunnable):
    def __init__(self, path: str, cache: Path, signals: _Signals, copy_to: Path | None,
                 cancelled) -> None:
        super().__init__()
        self._path, self._cache, self._signals = path, cache, signals
        self._copy_to, self._cancelled = copy_to, cancelled

    def run(self) -> None:
        path = self._path
        try:
            if self._copy_to is not None:
                path = str(copy_media(path, self._copy_to,
                                      lambda r: self._signals.progress.emit(self._path, r),
                                      self._cancelled))
            item = probe(path)
        except CopyCancelled:
            self._signals.done.emit(self._path, None, None, "copie annulée")
            return
        except OSError as exc:
            self._signals.done.emit(self._path, None, None,
                                    f"copie dans le projet impossible : {exc.strerror or exc}")
            return
        except (ProbeError, ValueError) as exc:
            self._signals.done.emit(self._path, None, None, str(exc))
            return
        if path != self._path:
            item.original_path = self._path
        thumb = make_thumbnail(self._cache, item)
        self._signals.done.emit(self._path, item, str(thumb) if thumb else None, "")


class _GatherTask(QRunnable):
    """Copie dans le projet d'un média déjà importé (projets d'avant la copie)."""

    def __init__(self, media_id: str, path: str, folder: Path, signals: _Signals,
                 cancelled) -> None:
        super().__init__()
        self._id, self._path, self._folder = media_id, path, folder
        self._signals, self._cancelled = signals, cancelled

    def run(self) -> None:
        try:
            copy = copy_media(self._path, self._folder,
                              lambda r: self._signals.progress.emit(self._path, r),
                              self._cancelled)
        except (OSError, CopyCancelled) as exc:
            self._signals.done.emit(self._id, None, None, str(exc))
            return
        self._signals.done.emit(self._id, str(copy), None, "")


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


class _ProxyTask(QRunnable):
    def __init__(self, item, cache: Path, signals: _Signals, stopping) -> None:
        super().__init__()
        self._item, self._cache, self._signals, self._stopping = item, cache, signals, stopping

    def run(self) -> None:
        out = proxy_path(self._cache, self._item.path)
        ok = out.exists() or make_proxy(self._item, out, self._stopping)
        if not self._stopping():
            self._signals.done.emit(self._item.path, self._item, str(out) if ok else None, "")


class MediaImporter(QObject):
    """Émet `finished` pour chaque fichier : (chemin, MediaItem ou None, vignette, erreur)."""

    finished = pyqtSignal(str, object, object, str)
    thumbnailReady = pyqtSignal(str, object)  # chemin du média, vignette
    waveformReady = pyqtSignal(str, object)  # chemin du média, crêtes (bytes) ou None
    copyProgress = pyqtSignal(str, float)  # fichier d'origine, avancement de sa copie
    gathered = pyqtSignal(str, object, str)  # identifiant du média, copie ou None, erreur
    proxyReady = pyqtSignal(str, object)  # chemin du média, proxy ou None (échec)

    def __init__(self, cache: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(4, QThreadPool.globalInstance().maxThreadCount())))
        # Relais enfants de l'importateur : détruits avec lui, ils ne peuvent plus émettre
        # vers une page de montage fermée.
        self._stopping = False
        self._signals = _Signals(self)
        self._signals.done.connect(self.finished)
        self._signals.progress.connect(self.copyProgress)
        self._gather_signals = _Signals(self)
        # méthode liée (et non lambda) : Qt la déconnecte si l'importateur est détruit
        self._gather_signals.done.connect(self._gathered_done)
        self._gather_signals.progress.connect(self.copyProgress)
        self._thumb_signals = _Signals(self)
        self._thumb_signals.done.connect(self._thumbnail_done)
        self._wave_signals = _Signals(self)
        self._wave_signals.done.connect(self._waveform_done)
        # proxys : longs à calculer, un seul à la fois pour ne pas ralentir le montage
        self._proxy_pool = QThreadPool(self)
        self._proxy_pool.setMaxThreadCount(1)
        self._proxy_signals = _Signals(self)
        self._proxy_signals.done.connect(self._proxy_done)
        self._proxies: set[str] = set()

    def _gathered_done(self, media_id: str, copy, _thumb, error: str) -> None:
        self.gathered.emit(media_id, copy, error)

    def _thumbnail_done(self, path: str, _item, thumb, _error: str) -> None:
        self.thumbnailReady.emit(path, thumb)

    def _waveform_done(self, path: str, _item, peaks, _error: str) -> None:
        self.waveformReady.emit(path, peaks)

    def _proxy_done(self, path: str, _item, proxy, _error: str) -> None:
        self._proxies.discard(path)
        self.proxyReady.emit(path, proxy)

    @property
    def pending_proxies(self) -> int:
        return len(self._proxies)

    def import_files(self, paths: list[str], copy_to: Path | None = None) -> None:
        """Importe les fichiers, copiés d'abord dans `copy_to` s'il est donné."""
        for p in paths:
            self._pool.start(_ProbeTask(p, self._cache, self._signals, copy_to,
                                        lambda: self._stopping))

    def gather(self, media_id: str, path: str, folder: Path) -> None:
        self._pool.start(_GatherTask(media_id, path, folder, self._gather_signals,
                                     lambda: self._stopping))

    def ensure_thumbnail(self, item) -> None:
        self._pool.start(_ThumbTask(item, self._cache, self._thumb_signals))

    def ensure_waveform(self, path: str) -> None:
        self._pool.start(_WaveformTask(path, self._cache, self._wave_signals))

    def ensure_proxy(self, item) -> None:
        if item.path in self._proxies:
            return
        self._proxies.add(item.path)
        self._proxy_pool.start(_ProxyTask(item, self._cache, self._proxy_signals,
                                          lambda: self._stopping))

    def wait(self, msecs: int = -1) -> bool:
        """Arrête les copies et les proxys en cours et attend la fin des tâches."""
        self._stopping = True
        copies = self._pool.waitForDone(msecs)
        return self._proxy_pool.waitForDone(msecs) and copies
