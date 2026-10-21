# SPDX-License-Identifier: GPL-3.0-or-later
"""Point unique de modification du projet ouvert : historique, sélection, notifications."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from PyQt6.QtCore import QObject, pyqtSignal

from montar.core.history import History
from montar.core.project import Clip, Project, Transition
from montar.core.timeline import Timeline, TimelineError, restore, snapshot

T = TypeVar("T")


class EditorController(QObject):
    changed = pyqtSignal()  # pistes, clips ou médias modifiés
    selectionChanged = pyqtSignal(object)  # identifiant du clip sélectionné ou None
    transitionSelected = pyqtSignal(object)  # identifiant de la transition ou None
    historyChanged = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, project: Project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.timeline = Timeline(project)
        self.history = History()
        self.selected: str | None = None
        self.selected_transition: str | None = None

    def edit(self, label: str, operation: Callable[[Timeline], T],
             merge: object = None) -> T | None:
        """Applique une modification annulable ; sans effet, elle n'entre pas dans l'historique.

        `merge` regroupe les modifications successives de même clé en une seule étape."""
        before = snapshot(self.project)
        try:
            result = operation(self.timeline)
            self.timeline.sanitize()
        except TimelineError as exc:
            restore(self.project, before)
            self.error.emit(str(exc))
            return None
        if snapshot(self.project) != before:
            self.history.record(label, before, merge)
            self._after_change()
        return result

    def edit_clip(self, label: str, clip_id: str, change: Callable[[Clip], None],
                  merge: object = None) -> None:
        """Modifie les réglages d'un clip (curseurs de l'inspecteur…)."""
        self.edit(label, lambda t: change(t.clip(clip_id)), merge)

    def undo(self) -> None:
        if self.history.undo(self.project) is not None:
            self._after_change()

    def redo(self) -> None:
        if self.history.redo(self.project) is not None:
            self._after_change()

    def _after_change(self) -> None:
        if self.selected and not any(c.id == self.selected for c in self.project.clips):
            self.select(None)
        if self.selected_transition and not any(
                t.id == self.selected_transition for t in self.project.transitions):
            self.select_transition(None)
        self.changed.emit()
        self.historyChanged.emit()

    def select(self, clip_id: str | None) -> None:
        if clip_id is not None:
            self.select_transition(None)
        if clip_id != self.selected:
            self.selected = clip_id
            self.selectionChanged.emit(clip_id)

    def select_transition(self, transition_id: str | None) -> None:
        if transition_id is not None:
            self.select(None)
        if transition_id != self.selected_transition:
            self.selected_transition = transition_id
            self.transitionSelected.emit(transition_id)

    def selected_transition_obj(self) -> Transition | None:
        return next((t for t in self.project.transitions
                     if t.id == self.selected_transition), None)

    def selected_clip(self) -> Clip | None:
        return next((c for c in self.project.clips if c.id == self.selected), None)
