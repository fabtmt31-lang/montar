# SPDX-License-Identifier: GPL-3.0-or-later
"""Historique annuler / rétablir, par instantanés de l'état du projet."""
from __future__ import annotations

import time

from montar.core.project import Project
from montar.core.timeline import restore, snapshot

HISTORY_LIMIT = 200


class History:
    def __init__(self, limit: int = HISTORY_LIMIT) -> None:
        self._undo: list[tuple[str, tuple]] = []
        self._redo: list[tuple[str, tuple]] = []
        self._limit = limit
        self._merge: tuple[object, float] | None = None  # (clé, instant) du dernier ajout

    MERGE_SECONDS = 1.5

    def record(self, label: str, state: tuple, merge: object = None) -> None:
        """Mémorise l'état d'avant une modification.

        Des modifications successives portant la même clé `merge` (déplacement d'un
        curseur, par exemple) ne forment qu'une seule étape d'annulation."""
        now = time.monotonic()
        if (merge is not None and self._merge is not None and self._merge[0] == merge
                and now - self._merge[1] < self.MERGE_SECONDS and self._undo
                and not self._redo):
            self._merge = (merge, now)
            return
        self._merge = (merge, now) if merge is not None else None
        self._undo.append((label, state))
        del self._undo[:-self._limit]
        self._redo.clear()

    def discard_last(self) -> None:
        """Oublie le dernier enregistrement (modification finalement sans effet)."""
        if self._undo:
            self._undo.pop()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str | None:
        return self._undo[-1][0] if self._undo else None

    def redo_label(self) -> str | None:
        return self._redo[-1][0] if self._redo else None

    def undo(self, project: Project) -> str | None:
        if not self._undo:
            return None
        label, state = self._undo.pop()
        self._merge = None
        self._redo.append((label, snapshot(project)))
        restore(project, state)
        return label

    def redo(self, project: Project) -> str | None:
        if not self._redo:
            return None
        label, state = self._redo.pop()
        self._undo.append((label, snapshot(project)))
        restore(project, state)
        return label
