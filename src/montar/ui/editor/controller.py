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
    # modification pendant un geste continu (glisser dans l'aperçu) : `changed` est retardé
    # jusqu'à `end_live()`, seuls les abonnés légers sont prévenus
    liveChanged = pyqtSignal()
    selectionChanged = pyqtSignal(object)  # identifiant du clip sélectionné ou None
    transitionSelected = pyqtSignal(object)  # identifiant de la transition ou None
    historyChanged = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, project: Project, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.timeline = Timeline(project)
        self.history = History()
        self.selected: str | None = None  # clip principal (inspecteur, aperçu)
        # tous les clips sélectionnés (Ctrl + clic, rectangle), le principal compris
        self.selection: list[str] = []
        self.selected_transition: str | None = None
        self.live = False
        self.live_preview = False
        self._live_pending = False

    def edit(self, label: str, operation: Callable[[Timeline], T],
             merge: object = None) -> T | None:
        """Applique une modification annulable ; sans effet, elle n'entre pas dans l'historique.

        `merge` regroupe les modifications successives de même clé en une seule étape."""
        before = snapshot(self.project)
        locked = self._locked_state()
        try:
            result = operation(self.timeline)
            self.timeline.sanitize()
            if locked and self._locked_state(set(locked[0])) != locked:
                raise TimelineError("cette piste est verrouillée : déverrouillez-la d'abord")
        except TimelineError as exc:
            restore(self.project, before)
            self.error.emit(str(exc))
            return None
        if snapshot(self.project) != before:
            self.history.record(label, before, merge)
            self._after_change()
        return result

    def _locked_state(self, track_ids: set[str] | None = None) -> tuple:
        """Clips et transitions des pistes verrouillées (avant l'opération : `track_ids`)."""
        if track_ids is None:
            track_ids = {t.id for t in self.project.tracks if t.locked}
        if not track_ids:
            return ()
        clips = sorted(repr(c) for c in self.project.clips if c.track_id in track_ids)
        transitions = sorted(repr(t) for t in self.project.transitions
                             if t.track_id in track_ids)
        return tuple(sorted(track_ids)), tuple(clips), tuple(transitions)

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
        ids = {c.id for c in self.project.clips}
        if any(cid not in ids for cid in self.selection):
            kept = [cid for cid in self.selection if cid in ids]
            primary = self.selected if self.selected in ids else (kept[-1] if kept else None)
            self.select_many(kept, primary)
        if self.selected_transition and not any(
                t.id == self.selected_transition for t in self.project.transitions):
            self.select_transition(None)
        if self.live:
            self._live_pending = True
            self.liveChanged.emit()
        else:
            self.changed.emit()
        self.historyChanged.emit()

    def begin_live(self, preview: bool = False) -> None:
        """Début d'un geste (glisser, curseur, saisie) : les modifications ne notifient que
        `liveChanged` ; avec `preview`, l'aperçu suit le geste (curseurs de l'inspecteur)."""
        self.live = True
        self.live_preview = preview

    def end_live(self) -> None:
        """Fin du geste : une seule notification complète."""
        self.live = False
        self.live_preview = False
        if self._live_pending:
            self._live_pending = False
            self.changed.emit()

    def select(self, clip_id: str | None) -> None:
        self.select_many([clip_id] if clip_id is not None else [], clip_id)

    def select_many(self, clip_ids: list[str], primary: str | None = None) -> None:
        """Sélection de plusieurs clips ; `primary` (par défaut le dernier) est celui que
        montrent l'inspecteur et l'aperçu."""
        ids = list(dict.fromkeys(clip_ids))
        if primary is None or primary not in ids:
            primary = ids[-1] if ids else None
        if ids:
            self.select_transition(None)
        changed = ids != self.selection
        self.selection = ids
        if primary != self.selected or changed:
            self.selected = primary
            self.selectionChanged.emit(primary)

    def toggle_selected(self, clip_id: str) -> None:
        """Ctrl + clic : ajoute le clip à la sélection ou l'en retire."""
        if clip_id in self.selection:
            ids = [c for c in self.selection if c != clip_id]
            self.select_many(ids, self.selected if self.selected != clip_id else None)
        else:
            self.select_many([*self.selection, clip_id], clip_id)

    def is_selected(self, clip_id: str) -> bool:
        return clip_id in self.selection

    def selected_clips(self) -> list[Clip]:
        """Clips sélectionnés, dans l'ordre de la timeline."""
        chosen = set(self.selection)
        return sorted((c for c in self.project.clips if c.id in chosen),
                      key=lambda c: (c.start, c.track_id))

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
