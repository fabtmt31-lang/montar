# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau de la timeline : barre d'outils + vue multipiste."""
from __future__ import annotations

import math
from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QSlider, QVBoxLayout

from montar.i18n import _
from montar.ui.editor.controller import EditorController
from montar.ui.timeline.view import MAX_PPS, MIN_PPS, TimelineView
from montar.ui.widgets import button, set_icon

_SLIDER_STEPS = 1000


class TimelinePanel(QFrame):
    voiceOverRequested = pyqtSignal()
    maximizeToggled = pyqtSignal(bool)  # timeline sur toute la hauteur de l'écran de montage
    detachToggled = pyqtSignal(bool)  # timeline dans une fenêtre à part (autre écran)

    def __init__(self, controller: EditorController,
                 thumbnail_for: Callable[[str], str | None],
                 peaks_for: Callable[[str], bytes | None]) -> None:
        super().__init__()
        self.setObjectName("TimelinePanel")
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("TimelineBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 16, 6)
        bl.setSpacing(4)
        self.split_button = button("", "ghost", "scissors", tooltip=_("Couper (S)"))
        self.delete_button = button("", "ghost", "trash-2", tooltip=_("Supprimer (Suppr)"))
        self.duplicate_button = button("", "ghost", "copy", tooltip=_("Dupliquer (Ctrl+D)"))
        self.split_button.clicked.connect(self.split)
        self.delete_button.clicked.connect(lambda: self.delete(ripple=False))
        self.duplicate_button.clicked.connect(self.duplicate)
        for b in (self.split_button, self.delete_button, self.duplicate_button):
            bl.addWidget(b)
        bl.addSpacing(8)
        self.range_button = button("", "ghost", "brackets", tooltip=_(
            "Sélectionner une partie d'un clip en glissant (ou Maj + glisser, ou I / O)"))
        self.range_button.setCheckable(True)
        self.range_button.setProperty("variant", "toggle")
        self.range_button.toggled.connect(self._set_range_tool)
        self.isolate_button = button(_("Isoler"), "ghost", "square-split-horizontal",
                                     tooltip=_("Couper le clip aux bornes de la sélection"))
        bl.addWidget(self.range_button)
        bl.addWidget(self.isolate_button)
        bl.addSpacing(8)
        self.magnet = button("", "ghost", "magnet", tooltip=_("Magnétisme"))
        self.magnet.setCheckable(True)
        self.magnet.setChecked(True)
        self.magnet.setProperty("variant", "toggle")
        self.magnet.toggled.connect(self._set_snap)
        bl.addWidget(self.magnet)
        self.marker_button = button("", "ghost", "bookmark",
                                    tooltip=_("Ajouter / retirer un marqueur (M) — Ctrl+← / "
                                              "Ctrl+→ : marqueur précédent / suivant"))
        self.marker_button.clicked.connect(self.toggle_marker)
        self.voice_button = button("", "ghost", "mic", tooltip=_("Enregistrer une voix off"))
        self.voice_button.clicked.connect(self.voiceOverRequested)
        bl.addWidget(self.marker_button)
        bl.addWidget(self.voice_button)
        add_track = button(_("Piste"), "ghost", "list-plus", tooltip=_("Ajouter une piste"))
        menu = QMenu(add_track)
        menu.addAction(_("Piste vidéo"), lambda: self._add_track("video"))
        menu.addAction(_("Piste audio"), lambda: self._add_track("audio"))
        add_track.setMenu(menu)
        bl.addWidget(add_track)
        bl.addStretch()
        zoom_out = button("", "ghost", "zoom-out", tooltip=_("Dézoomer (Ctrl + molette)"))
        zoom_in = button("", "ghost", "zoom-in", tooltip=_("Zoomer (Ctrl + molette)"))
        fit = button("", "ghost", "move-horizontal", tooltip=_("Ajuster à la fenêtre"))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, _SLIDER_STEPS)
        self.zoom_slider.setFixedWidth(160)
        bl.addWidget(zoom_out)
        bl.addWidget(self.zoom_slider)
        bl.addWidget(zoom_in)
        bl.addWidget(fit)
        bl.addSpacing(8)
        self.maximize_button = button("", "ghost", "maximize",
                                      tooltip=_("Agrandir la timeline (voir toutes les pistes)"))
        self.maximize_button.setCheckable(True)
        self.maximize_button.toggled.connect(self._maximize_toggled)
        self.detach_button = button("", "ghost", "external-link",
                                    tooltip=_("Ouvrir la timeline dans une fenêtre séparée"))
        self.detach_button.setCheckable(True)
        self.detach_button.toggled.connect(self._detach_toggled)
        bl.addWidget(self.maximize_button)
        bl.addWidget(self.detach_button)
        layout.addWidget(bar)

        self.view = TimelineView(controller, thumbnail_for, peaks_for)
        layout.addWidget(self.view, 1)
        self.isolate_button.clicked.connect(self.view.isolate_range)
        self.view.rangeChanged.connect(self._update_buttons)
        zoom_out.clicked.connect(lambda: self.view.set_zoom(self.view.pps / 1.5))
        zoom_in.clicked.connect(lambda: self.view.set_zoom(self.view.pps * 1.5))
        fit.clicked.connect(self.view.zoom_to_fit)
        self.zoom_slider.valueChanged.connect(self._slider_zoom)
        self.view.zoomChanged.connect(self._sync_slider)
        controller.selectionChanged.connect(lambda _id: self._update_buttons())
        controller.changed.connect(self._update_buttons)
        self._sync_slider(self.view.pps)
        self._update_buttons()

    def _maximize_toggled(self, on: bool) -> None:
        set_icon(self.maximize_button, "minimize" if on else "maximize", "ink", 20)
        self.maximize_button.setToolTip(_("Réduire la timeline") if on else
                                        _("Agrandir la timeline (voir toutes les pistes)"))
        self.maximizeToggled.emit(on)

    def _detach_toggled(self, on: bool) -> None:
        set_icon(self.detach_button, "panel-bottom" if on else "external-link", "ink", 20)
        self.detach_button.setToolTip(_("Remettre la timeline dans l'écran de montage") if on
                                      else _("Ouvrir la timeline dans une fenêtre séparée"))
        self.maximize_button.setVisible(not on)
        self.detachToggled.emit(on)

    def set_maximized(self, on: bool) -> None:
        self.maximize_button.setChecked(on)

    def set_detached(self, on: bool) -> None:
        self.detach_button.setChecked(on)

    # zoom logarithmique : le curseur couvre MIN_PPS → MAX_PPS
    def _slider_zoom(self, value: int) -> None:
        ratio = value / _SLIDER_STEPS
        self.view.set_zoom(MIN_PPS * (MAX_PPS / MIN_PPS) ** ratio)

    def _sync_slider(self, pps: float) -> None:
        value = round(math.log(pps / MIN_PPS) / math.log(MAX_PPS / MIN_PPS) * _SLIDER_STEPS)
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(value)
        self.zoom_slider.blockSignals(False)

    def _set_snap(self, on: bool) -> None:
        self.view.snap = on

    def _set_range_tool(self, on: bool) -> None:
        self.view.range_tool = on

    def _update_buttons(self) -> None:
        has_selection = self.controller.selected_clip() is not None
        self.delete_button.setEnabled(has_selection)
        self.duplicate_button.setEnabled(has_selection)
        self.split_button.setEnabled(bool(self.controller.timeline.clips_at(self.view.playhead))
                                     or has_selection)
        self.isolate_button.setEnabled(self.view.valid_range() is not None)

    def _add_track(self, kind: str) -> None:
        self.controller.edit(_("Ajouter une piste"), lambda t: t.add_track(kind))

    # --- actions (aussi appelées par les raccourcis clavier) -------------------------

    def split(self) -> None:
        playhead = self.view.playhead
        selected = self.controller.selected
        clip = self.controller.selected_clip()
        target = selected if clip is not None and clip.start < playhead < clip.end else None
        self.controller.edit(_("Couper"), lambda t: t.split_at(playhead, target))

    def delete(self, ripple: bool = False) -> None:
        clip_id = self.controller.selected
        if clip_id is None:
            return
        label = _("Supprimer et refermer l'espace") if ripple else _("Supprimer")
        self.controller.edit(label, lambda t: t.delete(clip_id, ripple=ripple))

    def duplicate(self) -> None:
        clip_id = self.controller.selected
        if clip_id is None:
            return
        copy_ = self.controller.edit(_("Dupliquer"), lambda t: t.duplicate(clip_id))
        if copy_ is not None:
            self.controller.select(copy_.id)

    def toggle_marker(self) -> None:
        frame = self.view.playhead
        self.controller.edit(_("Marqueur"), lambda t: t.toggle_marker(frame))

    def go_to_marker(self, direction: int) -> None:
        marker = self.controller.timeline.adjacent_marker(self.view.playhead, direction)
        if marker is not None:
            self.view.set_playhead(marker.frame, follow=True)
            self.view.seekRequested.emit(marker.frame)

    def set_playhead(self, frame: int, follow: bool = False) -> None:
        self.view.set_playhead(frame, follow)
        self._update_buttons()
