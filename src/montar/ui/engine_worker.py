# SPDX-License-Identifier: GPL-3.0-or-later
"""Fil du moteur pour l'interface : les rendus que l'interface demande au moteur (aperçu
de la finition pro, images d'un glisser dans l'aperçu…) s'y font un par un, jamais dans
le fil de l'interface, qui ne se fige plus ; le résultat revient dans le fil de
l'interface par un signal Qt.

Une demande porte une clé : une nouvelle demande de même clé remplace celle qui attendait
encore (seule la dernière position d'un curseur compte)."""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class _Task:
    __slots__ = ("work", "done", "failed", "key", "cancelled")

    def __init__(self, work, done, failed, key) -> None:
        self.work, self.done, self.failed, self.key = work, done, failed, key
        self.cancelled = False


class EngineWorker(QObject):
    """Exécute des fonctions dans un fil unique ; `done(résultat)` ou `failed(exception)`
    sont appelés dans le fil de l'interface."""

    _finished = pyqtSignal(object, object, object)  # tâche, résultat, exception

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[_Task | None] = queue.Queue()
        self._pending: dict[Any, _Task] = {}
        self._lock = threading.Lock()
        self._finished.connect(self._deliver)
        self._thread = threading.Thread(target=self._run, name="montar-moteur", daemon=True)
        self._thread.start()

    def submit(self, work: Callable[[], Any], done: Callable[[Any], None] | None = None,
               failed: Callable[[BaseException], None] | None = None, key: Any = None) -> _Task:
        task = _Task(work, done, failed, key)
        with self._lock:
            if key is not None:
                previous = self._pending.get(key)
                if previous is not None:
                    previous.cancelled = True  # remplacée par la nouvelle demande
                self._pending[key] = task
        self._queue.put(task)
        return task

    def cancel(self, key: Any) -> None:
        with self._lock:
            task = self._pending.pop(key, None)
        if task is not None:
            task.cancelled = True

    def idle(self) -> bool:
        """Plus rien à faire (essais)."""
        return self._queue.unfinished_tasks == 0

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                if task.cancelled:
                    continue
                try:
                    result, error = task.work(), None
                except Exception as exc:  # remis au demandeur
                    result, error = None, exc
                self._finished.emit(task, result, error)
            finally:
                self._queue.task_done()

    def _deliver(self, task: _Task, result, error) -> None:
        with self._lock:
            if task.key is not None and self._pending.get(task.key) is task:
                del self._pending[task.key]
        if task.cancelled:
            return
        if error is not None:
            if task.failed is not None:
                task.failed(error)
            else:
                log.warning("rendu en tâche de fond impossible : %s", error)
        elif task.done is not None:
            task.done(result)


_WORKER: EngineWorker | None = None


def engine_worker() -> EngineWorker:
    """Le fil du moteur de l'interface (créé au premier usage, dans le fil de l'interface)."""
    global _WORKER
    if _WORKER is None:
        _WORKER = EngineWorker()
    return _WORKER
