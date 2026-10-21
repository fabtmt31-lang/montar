# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau de la timeline : barre d'outils + vue multipiste."""
from __future__ import annotations

import math
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QSlider, QVBoxLayout

from montar.i18n import _
from montar.ui.editor.controller import EditorController
from montar.ui.timeline.view import MAX_PPS, MIN_PPS, TimelineView
from montar.ui.widgets import button

_SLIDER_STEPS = 1000


class TimelinePanel(QFrame):
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
        self.magnet = button("", "ghost", "magnet", tooltip=_("Magnétisme"))
        self.magnet.setCheckable(True)
        self.magnet.setChecked(True)
        self.magnet.setProperty("variant", "toggle")
        self.magnet.toggled.connect(self._set_snap)
        bl.addWidget(self.magnet)
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
        layout.addWidget(bar)

        self.view = TimelineView(controller, thumbnail_for, peaks_for)
        layout.addWidget(self.view, 1)
        zoom_out.clicked.connect(lambda: self.view.set_zoom(self.view.pps / 1.5))
        zoom_in.clicked.connect(lambda: self.view.set_zoom(self.view.pps * 1.5))
        fit.clicked.connect(self.view.zoom_to_fit)
        self.zoom_slider.valueChanged.connect(self._slider_zoom)
        self.view.zoomChanged.connect(self._sync_slider)
        controller.selectionChanged.connect(lambda _id: self._update_buttons())
        controller.changed.connect(self._update_buttons)
        self._sync_slider(self.view.pps)
        self._update_buttons()

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

    def _update_buttons(self) -> None:
        has_selection = self.controller.selected_clip() is not None
        self.delete_button.setEnabled(has_selection)
        self.duplicate_button.setEnabled(has_selection)
        self.split_button.setEnabled(bool(self.controller.timeline.clips_at(self.view.playhead))
                                     or has_selection)

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

    def set_playhead(self, frame: int, follow: bool = False) -> None:
        self.view.set_playhead(frame, follow)
        self._update_buttons()
