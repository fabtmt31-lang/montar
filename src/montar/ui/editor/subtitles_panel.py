# SPDX-License-Identifier: GPL-3.0-or-later
"""Panneau « Sous-titres » (F-TXT-05) : liste, édition à la tête de lecture, import et export
SRT, style commun. Les sous-titres sont incrustés au-dessus de toutes les pistes."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
)

from montar.core import subtitles
from montar.core.timecode import frames_to_timecode
from montar.i18n import _
from montar.ui.editor.controller import EditorController
from montar.ui.editor.controls import SliderRow, section
from montar.ui.editor.panels import _Panel
from montar.ui.widgets import Segmented, button, shrink

POSITIONS = {"bottom": 0.88, "top": 0.12}


class SubtitlesPanel(_Panel):
    seekRequested = pyqtSignal(int)

    def __init__(self, controller: EditorController) -> None:
        super().__init__(_("Sous-titres"))
        self.controller = controller
        self.playhead: Callable[[], int] = lambda: 0  # fourni par l'éditeur
        self.current: str | None = None  # sous-titre en cours d'édition
        self._refreshing = False

        self.add_button = button(_("Ajouter à la tête de lecture"), "primary", "plus")
        self.add_button.clicked.connect(self.add)
        self.body.addWidget(self.add_button)
        files = QHBoxLayout()
        self.import_button = button(_("Importer"), "secondary", "upload",
                                    tooltip=_("Importer un fichier .srt"))
        self.import_button.clicked.connect(self._choose_import)
        self.export_button = button(_("Exporter"), "secondary", "download",
                                    tooltip=_("Exporter un fichier .srt"))
        self.export_button.clicked.connect(self._choose_export)
        files.addWidget(self.import_button)
        files.addWidget(self.export_button)
        self.body.addLayout(files)

        self.list = QListWidget()
        self.list.setObjectName("SubtitleList")
        self.list.setMinimumHeight(160)
        self.list.currentItemChanged.connect(self._on_current)
        self.body.addWidget(self.list, 1)
        self.empty = self.hint(_("Aucun sous-titre. Placez la tête de lecture puis « Ajouter », "
                                 "ou importez un fichier .srt."))
        self.body.addWidget(self.empty)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(_("Texte du sous-titre"))
        self.editor.setFixedHeight(70)
        self.editor.textChanged.connect(self._text_changed)
        self.body.addWidget(self.editor)
        bounds = QHBoxLayout()
        self.start_button = button(_("Début ici"), "secondary",
                                   tooltip=_("Le sous-titre commence à la tête de lecture"))
        self.start_button.clicked.connect(lambda: self._set_bound("start"))
        self.end_button = button(_("Fin ici"), "secondary",
                                 tooltip=_("Le sous-titre finit à la tête de lecture"))
        self.end_button.clicked.connect(lambda: self._set_bound("end"))
        self.delete_button = button("", "secondary", "trash-2",
                                    tooltip=_("Supprimer le sous-titre"))
        self.delete_button.clicked.connect(self.delete)
        bounds.addWidget(self.start_button)
        bounds.addWidget(self.end_button)
        bounds.addWidget(shrink(self.delete_button))
        self.body.addLayout(bounds)

        self.body.addWidget(section(_("STYLE")))
        self.shown = QCheckBox(_("Afficher dans l'aperçu"))
        self.shown.toggled.connect(self._toggle_shown)
        self.body.addWidget(self.shown)
        self.size = SliderRow(_("Taille"), 24, 96, lambda v: f"{v:.0f}")
        self.size.moved.connect(self._size_changed)
        self.body.addWidget(self.size)
        self.position = Segmented([("bottom", _("En bas")), ("top", _("En haut"))],
                                  compact=True)
        self.position.changed.connect(self._position_changed)
        self.body.addWidget(self.position)
        controller.changed.connect(self.refresh)
        self.refresh()

    # --- affichage ----------------------------------------------------------------------

    @property
    def project(self):
        return self.controller.project

    def refresh(self) -> None:
        self._refreshing = True
        fps = self.project.fps
        subs = subtitles.ordered(self.project)
        if self.current and not any(s.id == self.current for s in subs):
            self.current = None
        self.list.clear()
        for sub in subs:
            first = sub.text.split("\n")[0] or _("(vide)")
            item = QListWidgetItem(f"{frames_to_timecode(sub.start, fps)} → "
                                   f"{frames_to_timecode(sub.end, fps)}\n{first}")
            item.setData(Qt.ItemDataRole.UserRole, sub.id)
            self.list.addItem(item)
            if sub.id == self.current:
                self.list.setCurrentItem(item)
        self.list.setVisible(bool(subs))
        self.empty.setVisible(not subs)
        self.export_button.setEnabled(bool(subs))
        sub = self._current()
        for w in (self.editor, self.start_button, self.end_button, self.delete_button):
            w.setEnabled(sub is not None)
        text = sub.text if sub is not None else ""
        if self.editor.toPlainText() != text:
            self.editor.setPlainText(text)
        style = self.project.subtitle_style
        self.shown.setChecked(self.project.subtitles_shown)
        self.size.set_value(style.size)
        self.position.set_current("top" if style.y < 0.5 else "bottom")
        self._refreshing = False

    def _current(self):
        return next((s for s in self.project.subtitles if s.id == self.current), None)

    def _on_current(self, item, _previous=None) -> None:
        if self._refreshing or item is None:
            return
        self.current = item.data(Qt.ItemDataRole.UserRole)
        sub = self._current()
        self._refreshing = True
        self.editor.setPlainText(sub.text if sub else "")
        for w in (self.editor, self.start_button, self.end_button, self.delete_button):
            w.setEnabled(sub is not None)
        self._refreshing = False
        if sub is not None:
            self.seekRequested.emit(sub.start)

    # --- édition --------------------------------------------------------------------------

    def _edit(self, label_: str, change: Callable, merge: object = None):
        return self.controller.edit(label_, lambda _t: change(self.project), merge)

    def add(self) -> None:
        frame = self.playhead()
        existing = subtitles.at(self.project, frame)
        if existing is not None:  # déjà un sous-titre ici : on l'édite
            self.current = existing.id
            self.refresh()
            self.editor.setFocus()
            return
        sub = self._edit(_("Ajouter un sous-titre"), lambda p: subtitles.add(p, frame))
        if sub is not None:
            self.current = sub.id
            self.refresh()
            self.editor.setFocus()

    def delete(self) -> None:
        sid = self.current
        if sid is not None:
            self._edit(_("Supprimer le sous-titre"), lambda p: p.subtitles.remove(
                subtitles.find(p, sid)))

    def _text_changed(self) -> None:
        sid = self.current
        if self._refreshing or sid is None:
            return
        text = self.editor.toPlainText()
        self._edit(_("Texte du sous-titre"),
                   lambda p: setattr(subtitles.find(p, sid), "text", text), ("subtitle", sid))

    def _set_bound(self, edge: str) -> None:
        sid, frame = self.current, self.playhead()
        if sid is not None:
            self._edit(_("Durée du sous-titre"), lambda p: subtitles.set_bounds(
                subtitles.find(p, sid), **{edge: frame}))

    def _toggle_shown(self, on: bool) -> None:
        if not self._refreshing:
            self._edit(_("Afficher les sous-titres"), lambda p: setattr(p, "subtitles_shown", on))

    def _size_changed(self, value: float) -> None:
        if not self._refreshing:
            self._edit(_("Taille des sous-titres"), lambda p: setattr(
                p.subtitle_style, "size", round(value)), "subtitle-size")

    def _position_changed(self, key: str) -> None:
        if not self._refreshing:
            self._edit(_("Position des sous-titres"), lambda p: setattr(
                p.subtitle_style, "y", POSITIONS[key]))

    # --- fichiers SRT -----------------------------------------------------------------------

    def import_file(self, path: Path) -> bool:
        try:
            found = subtitles.read_srt(path, self.project.fps)
        except (OSError, subtitles.SrtError) as exc:
            QMessageBox.warning(self, _("Importer des sous-titres"),
                                _("Impossible de lire {name} : {error}").format(
                                    name=path.name, error=exc))
            return False
        replace = False
        if self.project.subtitles:
            replace = QMessageBox.question(
                self, _("Importer des sous-titres"),
                _("Remplacer les sous-titres actuels ? (Non : les ajouter)")) == \
                QMessageBox.StandardButton.Yes
        self._edit(_("Importer des sous-titres"), lambda p: setattr(
            p, "subtitles", found if replace else [*p.subtitles, *found]))
        return True

    def export_file(self, path: Path) -> bool:
        try:
            path.write_text(subtitles.to_srt(self.project.subtitles, self.project.fps),
                            encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, _("Exporter les sous-titres"), str(exc))
            return False
        return True

    def _start_dir(self) -> str:
        path = self.project.path
        return str(path.parent) if path is not None else str(Path.home())

    def _choose_import(self) -> None:
        name, _f = QFileDialog.getOpenFileName(self, _("Importer des sous-titres"),
                                               self._start_dir(),
                                               _("Sous-titres SRT") + " (*.srt)")
        if name:
            self.import_file(Path(name))

    def _choose_export(self) -> None:
        default = str(Path(self._start_dir()) / f"{self.project.name}.srt")
        name, _f = QFileDialog.getSaveFileName(self, _("Exporter les sous-titres"), default,
                                               _("Sous-titres SRT") + " (*.srt)")
        if name:
            self.export_file(Path(name))
