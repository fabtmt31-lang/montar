# SPDX-License-Identifier: GPL-3.0-or-later
"""Lien entre les modules et l'écran de montage : contexte des outils, tâches de fond,
crochet de rendu (sources de remplacement, filtres des effets), badges."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from montar.api import Tool
from montar.core.project import Clip, MediaItem
from montar.engine.base import ClipOverride
from montar.i18n import _
from montar.plugins import ModuleManager
from montar.ui.editor.controller import EditorController

log = logging.getLogger(__name__)

CANCELLED = "annulé"


class _JobSignals(QObject):
    progress = pyqtSignal(str, float)
    done = pyqtSignal(str, str)  # clé, message d'erreur (vide si réussite)


class _Job(QRunnable):
    def __init__(self, key: str, work, signals: _JobSignals, cancel: threading.Event) -> None:
        super().__init__()
        self.key, self.work, self.signals, self.cancel = key, work, signals, cancel

    def run(self) -> None:
        try:
            self.work(lambda r: self.signals.progress.emit(self.key, float(r)),
                      self.cancel.is_set)
            self.signals.done.emit(self.key, "")
        except Exception as exc:  # erreur du module : signalée, jamais fatale
            if self.cancel.is_set():
                self.signals.done.emit(self.key, CANCELLED)
            else:
                log.exception("tâche de fond %s", self.key)
                self.signals.done.emit(self.key, f"{type(exc).__name__} : {exc}")


class JobRunner(QObject):
    """Tâches de fond des modules (une seule par clé), avec avancement."""

    changed = pyqtSignal()  # liste ou avancement des tâches modifié
    finished = pyqtSignal(str, str)  # clé, erreur

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signals = _JobSignals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_done)
        self.jobs: dict[str, dict] = {}  # clé → {title, progress, cancel}
        self.failed: dict[str, tuple[str, str]] = {}  # clé → (titre, erreur)

    def schedule(self, key: str, title: str, work) -> None:
        if key in self.jobs or key in self.failed:
            return
        cancel = threading.Event()
        self.jobs[key] = {"title": title, "progress": 0.0, "cancel": cancel,
                          "started": time.monotonic()}
        self._pool.start(_Job(key, work, self._signals, cancel))
        self.changed.emit()

    def _on_progress(self, key: str, ratio: float) -> None:
        if key in self.jobs:
            self.jobs[key]["progress"] = ratio
            self.changed.emit()

    def _on_done(self, key: str, error: str) -> None:
        job = self.jobs.pop(key, None)
        if job is not None and job["cancel"].is_set():
            error = CANCELLED
        if error and job is not None:
            # ni relancé automatiquement, ni oublié : « Relancer » le reprend
            self.failed[key] = (job["title"], error)
        self.changed.emit()
        self.finished.emit(key, error)

    def cancel(self) -> None:
        """Interrompt les calculs en cours (ffmpeg est arrêté en moins d'une seconde)."""
        for job in self.jobs.values():
            job["cancel"].set()

    def retry(self) -> None:
        """Oublie les échecs et annulations : les calculs reprennent au prochain rendu."""
        self.failed.clear()
        self.changed.emit()

    def failure_summary(self) -> tuple[str, bool] | None:
        """(titre, annulé) des calculs interrompus, ou None."""
        if not self.failed:
            return None
        titles = {title for title, _e in self.failed.values()}
        cancelled = all(e == CANCELLED for _t, e in self.failed.values())
        return (titles.pop() if len(titles) == 1 else _("Calculs")), cancelled

    def elapsed(self) -> float:
        """Temps écoulé depuis le début du plus ancien calcul en cours."""
        if not self.jobs:
            return 0.0
        return time.monotonic() - min(j["started"] for j in self.jobs.values())

    def summary(self) -> tuple[str, float] | None:
        if not self.jobs:
            return None
        titles = {j["title"] for j in self.jobs.values()}
        ratio = sum(j["progress"] for j in self.jobs.values()) / len(self.jobs)
        title = titles.pop() if len(titles) == 1 else _("Calculs")
        if len(self.jobs) > 1:
            title = f"{title} ({len(self.jobs)})"
        return title, ratio

    def cancel_all(self, wait_ms: int = 3000) -> None:
        for job in self.jobs.values():
            job["cancel"].set()
        self._pool.waitForDone(wait_ms)


class EditorModules:
    """Contexte (`montar.api.EditorContext`) offert aux modules par une page de montage."""

    def __init__(self, manager: ModuleManager, controller: EditorController, cache: Path,
                 parent: QWidget, playhead: Callable[[], int],
                 selection_range: Callable[[], tuple[str, int, int] | None]) -> None:
        self.manager = manager
        self.controller = controller
        self.cache_dir = cache
        self.parent = parent
        self._playhead, self._range = playhead, selection_range
        self.jobs = JobRunner(parent)

    # --- EditorContext ----------------------------------------------------------------

    @property
    def project(self):
        return self.controller.project

    @property
    def timeline(self):
        return self.controller.timeline

    @property
    def fps(self) -> int:
        return self.project.fps

    @property
    def playhead(self) -> int:
        return self._playhead()

    @property
    def selection_range(self):
        return self._range()

    def edit(self, label: str, operation):
        return self.controller.edit(label, operation)

    def select(self, clip_id: str | None) -> None:
        self.controller.select(clip_id)

    def error(self, message: str) -> None:
        QMessageBox.warning(self.parent, _("Module"), message)

    def schedule_job(self, key: str, title: str, work) -> None:
        self.jobs.schedule(key, title, work)

    # --- rendu ----------------------------------------------------------------------------

    def hook(self, clip: Clip, media: MediaItem) -> ClipOverride | None:
        """Crochet de `timeline_spec` : source de remplacement et filtres des modules."""
        path = source_in = speed = None
        for module_id, source in self.manager.sources():
            if module_id not in clip.modules:
                continue
            found = self.manager.guarded(module_id,
                                         lambda s=source: s.resolve(self, clip, media), None)
            if found is not None:
                path, source_in, speed = found.path, found.source_in, found.speed
        filters = []
        for module_id, effect in self.manager.effects():
            values = clip.modules.get(effect.id)
            if isinstance(values, dict):
                filters += self.manager.guarded(
                    module_id, lambda e=effect, v=values: list(e.filters({**e.defaults(), **v})),
                    [])
        if path is None and not filters:
            return None
        return ClipOverride(path, source_in, speed, tuple(filters))

    def pending_sources(self) -> list[Clip]:
        """Clips dont la source de remplacement (ex. timelapse) n'est pas encore calculée."""
        pending = []
        for clip in self.project.clips:
            media = self.project.find_media(clip.media_id) if clip.media_id else None
            if media is None or not clip.modules:
                continue
            if any(module_id in clip.modules for module_id, _s in self.manager.sources()):
                override = self.hook(clip, media)
                if override is None or override.path is None:
                    pending.append(clip)
        return pending

    def badges(self, clip: Clip) -> list[str]:
        result = []
        for module_id, source in self.manager.sources():
            settings = clip.modules.get(module_id)
            if isinstance(settings, dict):
                text = self.manager.guarded(module_id, lambda s=source, d=settings: s.badge(d),
                                            None)
                if text:
                    result.append(text)
        return result

    def missing(self, clip: Clip) -> list[str]:
        """Modules dont le clip porte des réglages mais qui ne sont pas actifs."""
        known = {mid for mid, _s in self.manager.sources()} | {
            e.id for _m, e in self.manager.effects()}
        return [k for k in clip.modules if k not in known]

    # --- outils ---------------------------------------------------------------------------

    def tools_for(self, clip: Clip | None, section: str | None = None) -> list[tuple[str, Tool]]:
        if clip is None:
            return []
        return [(mid, tool) for mid, tool in self.manager.tools()
                if (section is None or tool.section == section)
                and self.manager.guarded(mid, lambda t=tool: bool(t.available(self, clip)),
                                         False)]

    def run_tool(self, module_id: str, tool: Tool, clip: Clip) -> None:
        def call():
            tool.run(self, clip)

        try:
            call()
        except Exception as exc:
            self.manager.report_failure(module_id, exc)
            self.error(_("Le module « {m} » a rencontré une erreur et a été désactivé :\n{e}")
                       .format(m=module_id, e=exc))
