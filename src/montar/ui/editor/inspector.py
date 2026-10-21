# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspecteur (panneau de droite) : propriétés de l'élément sélectionné."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from montar.core.project import Clip, MediaItem, Project
from montar.core.timecode import frames_to_timecode, seconds_to_short
from montar.i18n import _
from montar.ui.widgets import label

_KIND = {"video": "Clip vidéo", "image": "Image", "audio": "Son"}


class Inspector(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Inspector")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(4)
        self.title = label("", "h3")
        self.title.setWordWrap(True)
        self.subtitle = label("", "small")
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addSpacing(18)
        self.section = label("", "section")
        layout.addWidget(self.section)
        layout.addSpacing(6)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(10)
        self._grid.setColumnStretch(1, 1)
        layout.addWidget(self._grid_host)
        layout.addStretch()

    def _set_rows(self, rows: list[tuple[str, str]]) -> None:
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, (key, value) in enumerate(rows):
            k = label(key, "muted")
            v = QLabel(value)
            v.setProperty("role", "mono")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(k, i, 0, Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(v, i, 1)

    def show_project(self, project: Project) -> None:
        w, h = project.canvas_size
        self.title.setText(project.name)
        self.subtitle.setText(_("Projet"))
        self.section.setText(_("PROJET"))
        self._set_rows([
            (_("Format"), project.aspect),
            (_("Toile"), f"{w} × {h}"),
            (_("Images/s"), str(project.fps)),
            (_("Médias"), str(len(project.media))),
            (_("Fichier"), str(project.path or "—")),
        ])

    def show_media(self, media: MediaItem) -> None:
        self.title.setText(media.name)
        kind = _(_KIND.get(media.kind, media.kind))
        self.subtitle.setText(kind if media.kind == "image"
                              else f"{kind} · {seconds_to_short(media.duration)}")
        self.section.setText(_("PROPRIÉTÉS DU MÉDIA"))
        rows: list[tuple[str, str]] = []
        if media.kind != "audio":
            rows.append((_("Résolution"), f"{media.width} × {media.height}"))
        if media.kind == "video":
            rows.append((_("Images/s"), f"{media.fps:.3g}"))
        if media.kind != "image":
            rows.append((_("Durée"), f"{media.duration:.2f} s"))
        if media.video_codec and media.kind != "audio":
            rows.append((_("Codec vidéo"), media.video_codec))
        if media.has_audio:
            rows.append((_("Codec audio"), media.audio_codec or "—"))
        rows.append((_("Fichier"), media.path))
        if not media.exists:
            rows.append((_("État"), _("introuvable")))
        self._set_rows(rows)

    def show_clip(self, clip: Clip, media: MediaItem, track_label: str, fps: int) -> None:
        self.title.setText(media.name)
        kind = _(_KIND.get(media.kind, media.kind))
        self.subtitle.setText(f"{kind} · {_('piste')} {track_label}")
        self.section.setText(_("CLIP"))
        tc = lambda f: frames_to_timecode(f, fps)  # noqa: E731
        rows = [
            (_("Début"), tc(clip.start)),
            (_("Fin"), tc(clip.end)),
            (_("Durée"), tc(clip.duration)),
        ]
        if media.kind != "image":
            rows.append((_("Point d'entrée"), tc(clip.source_in)))
        rows.append((_("Fichier"), media.path))
        self._set_rows(rows)
