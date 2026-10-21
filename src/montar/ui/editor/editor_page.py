# SPDX-License-Identifier: GPL-3.0-or-later
"""Écran de montage (maquette 02)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from montar.core.project import MediaItem, Project, ProjectError
from montar.engine.base import Engine, timeline_spec
from montar.i18n import _
from montar.media.probe import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, is_supported
from montar.media.thumbnails import thumbnail_path
from montar.media.waveform import waveform_path
from montar.ui.editor.controller import EditorController
from montar.ui.editor.importer import MediaImporter
from montar.ui.editor.inspector import Inspector
from montar.ui.editor.media_panel import MediaPanel
from montar.ui.editor.player import Player
from montar.ui.editor.preview import PreviewPanel
from montar.ui.timeline.panel import TimelinePanel
from montar.ui.widgets import LogoMark, Segmented, button, label, set_icon

SOON = "Disponible dans une prochaine version"

_RAIL = (
    ("media", "Médias", "image"),
    ("audio", "Audio", "music"),
    ("text", "Texte", "type"),
    ("transitions", "Transitions", "columns-2"),
    ("effects", "Effets", "sparkles"),
    ("filters", "Filtres", "blend"),
    ("subtitles", "Sous-titres", "captions"),
    ("record", "Enregistrer", "circle-dot"),
)


def media_file_filter() -> str:
    def globs(exts: set[str]) -> str:
        return " ".join(f"*{e}" for e in sorted(exts))

    every = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
    return ";;".join([
        _("Médias") + f" ({globs(every)})",
        _("Vidéos") + f" ({globs(VIDEO_EXTENSIONS)})",
        _("Sons") + f" ({globs(AUDIO_EXTENSIONS)})",
        _("Images") + f" ({globs(IMAGE_EXTENSIONS)})",
    ])


class EditorPage(QWidget):
    backRequested = pyqtSignal()
    saved = pyqtSignal(object)  # Path

    def __init__(self, project: Project, engine_factory: Callable[[], Engine], cache: Path,
                 preview_quality: str = "medium") -> None:
        super().__init__()
        self.setObjectName("Page")
        self.setAcceptDrops(True)
        self.project = project
        self.controller = EditorController(project, self)
        self._cache = cache
        # Les analyses se terminent dans le désordre : les médias sont ajoutés dans
        # l'ordre de la demande d'import.
        self._import_queue: list[str] = []
        self._import_results: dict[str, tuple[MediaItem | None, str | None, str]] = {}
        self.thumbnails: dict[str, str] = {}
        self.waveforms: dict[str, bytes] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        top = QWidget()
        body = QHBoxLayout(top)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())
        self.media_panel = MediaPanel()
        body.addWidget(self.media_panel)
        self.player = Player(engine_factory, self)
        self.preview = PreviewPanel(self.player, preview_quality)
        body.addWidget(self.preview, 1)
        self.inspector = Inspector()
        body.addWidget(self.inspector)

        self.timeline = TimelinePanel(self.controller, self.thumbnails.get, self.waveforms.get)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.addWidget(top)
        splitter.addWidget(self.timeline)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 320])
        root.addWidget(splitter, 1)

        self.importer = MediaImporter(cache, self)
        self.importer.finished.connect(self._on_imported)
        self.importer.thumbnailReady.connect(self._on_thumbnail)
        self.importer.waveformReady.connect(self._on_waveform)
        self.media_panel.importRequested.connect(self.choose_files)
        self.media_panel.mediaSelected.connect(self._on_media_selected)
        self.media_panel.removeRequested.connect(self.remove_media)
        self.media_panel.addToTimelineRequested.connect(self.add_to_timeline)

        self.controller.changed.connect(self._on_project_changed)
        self.controller.selectionChanged.connect(self._on_clip_selected)
        self.controller.historyChanged.connect(self._update_history_buttons)
        self.controller.error.connect(
            lambda msg: QMessageBox.information(self, _("Action impossible"), msg))
        self.timeline.view.seekRequested.connect(self.player.seek)
        self.player.frameReady.connect(
            lambda _img, frame: self.timeline.set_playhead(frame, follow=self.player.playing))

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save)

        self._install_shortcuts()
        self._load_project_media()
        self._refresh_header()
        self._update_history_buttons()
        self.preview.set_canvas(*project.canvas_size)
        self.inspector.show_project(project)
        self.player.load(timeline_spec(project))

    # --- construction -------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("EditorHeader")
        header.setFixedHeight(60)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        home = QToolButton()
        home.setProperty("variant", "ghost")
        home.setToolTip(_("Retour à l'accueil"))
        home.setCursor(Qt.CursorShape.PointingHandCursor)
        home.setFixedSize(40, 40)
        hl = QHBoxLayout(home)
        hl.setContentsMargins(3, 3, 3, 3)
        mark = LogoMark(34)
        mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl.addWidget(mark)
        home.clicked.connect(self.backRequested)
        layout.addWidget(home)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_edit = QLineEdit()
        self.title_edit.setProperty("variant", "title")
        self.title_edit.setMaximumWidth(320)
        self.title_edit.editingFinished.connect(self._rename)
        self.status_label = label("", "small")
        self.status_label.setContentsMargins(5, 0, 0, 0)
        titles.addWidget(self.title_edit)
        titles.addWidget(self.status_label)
        layout.addLayout(titles)
        layout.addSpacing(12)
        self.undo_button = button("", "ghost", "undo-2")
        self.redo_button = button("", "ghost", "redo-2")
        self.undo_button.clicked.connect(self.controller.undo)
        self.redo_button.clicked.connect(self.controller.redo)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addStretch(1)

        modes = Segmented([("edit", _("Montage")), ("color", _("Couleur")),
                           ("audio", _("Audio")), ("subtitles", _("Sous-titres"))])
        for key in ("color", "audio", "subtitles"):
            modes.button(key).setEnabled(False)
            modes.button(key).setToolTip(_(SOON))
        layout.addWidget(modes)
        layout.addStretch(1)

        export = button(_("Exporter"), "primary", "download", tooltip=_(SOON))
        export.setEnabled(False)
        export.setMinimumHeight(40)
        layout.addWidget(export)
        return header

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("Rail")
        rail.setFixedWidth(76)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(4)
        group = QButtonGroup(rail)
        for key, text, icon in _RAIL:
            b = QToolButton()
            b.setText(_(text))
            b.setProperty("variant", "rail")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            set_icon(b, icon, "forest" if key == "media" else "ink", 20)
            if key == "media":
                b.setChecked(True)
            else:
                b.setEnabled(False)
                b.setToolTip(_(SOON))
            group.addButton(b)
            layout.addWidget(b)
        layout.addStretch()
        return rail

    def _install_shortcuts(self) -> None:
        tl = self.timeline
        for keys, slot in (
            ("S", tl.split),
            (QKeySequence.StandardKey.Delete, lambda: tl.delete(ripple=False)),
            ("Backspace", lambda: tl.delete(ripple=False)),
            ("Shift+Delete", lambda: tl.delete(ripple=True)),
            ("Ctrl+D", tl.duplicate),
            (QKeySequence.StandardKey.Undo, self.controller.undo),
            (QKeySequence.StandardKey.Redo, self.controller.redo),
            ("Ctrl+Y", self.controller.redo),
            ("Ctrl++", lambda: tl.view.set_zoom(tl.view.pps * 1.5)),
            ("Ctrl+=", lambda: tl.view.set_zoom(tl.view.pps * 1.5)),
            ("Ctrl+-", lambda: tl.view.set_zoom(tl.view.pps / 1.5)),
            ("Ctrl+0", tl.view.zoom_to_fit),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

    # --- projet -------------------------------------------------------------

    def _load_project_media(self) -> None:
        for m in self.project.media:
            thumb = thumbnail_path(self._cache, m.path)
            if thumb.exists():
                self.thumbnails[m.path] = str(thumb)
            elif m.exists and m.kind != "audio":
                self.importer.ensure_thumbnail(m)
            self._ensure_waveform(m)
        self.media_panel.set_media(self.project.media, self.thumbnails)
        self._shown_media = [m.id for m in self.project.media]

    def _ensure_waveform(self, media: MediaItem) -> None:
        if not media.has_audio or not media.exists:
            return
        cached = waveform_path(self._cache, media.path)
        if cached.exists():
            self.waveforms[media.path] = cached.read_bytes()
        else:
            self.importer.ensure_waveform(media.path)

    def _refresh_header(self) -> None:
        w, h = self.project.canvas_size
        self.title_edit.setText(self.project.name)
        self.status_label.setText(_("Enregistré · {w}×{h} · {fps} i/s").format(
            w=w, h=h, fps=self.project.fps))

    def _update_history_buttons(self) -> None:
        history = self.controller.history
        self.undo_button.setEnabled(history.can_undo)
        self.redo_button.setEnabled(history.can_redo)
        undo, redo = history.undo_label(), history.redo_label()
        self.undo_button.setToolTip(_("Annuler : {action} (Ctrl+Z)").format(action=undo)
                                    if undo else _("Annuler (Ctrl+Z)"))
        self.redo_button.setToolTip(_("Rétablir : {action} (Ctrl+Maj+Z)").format(action=redo)
                                    if redo else _("Rétablir (Ctrl+Maj+Z)"))

    def _rename(self) -> None:
        name = self.title_edit.text().strip()
        if name and name != self.project.name:
            self.project.name = name
            self.mark_dirty()
        elif not name:
            self.title_edit.setText(self.project.name)

    def mark_dirty(self) -> None:
        self.status_label.setText(self.status_label.text().replace(
            _("Enregistré"), _("Modifié"), 1))
        self._save_timer.start()

    def save(self) -> bool:
        self._save_timer.stop()
        try:
            path = self.project.save()
        except (OSError, ProjectError) as exc:
            QMessageBox.warning(self, _("Enregistrement impossible"), str(exc))
            return False
        self._refresh_header()
        self.saved.emit(path)
        return True

    def close_project(self) -> bool:
        """Enregistre si nécessaire et arrête la lecture ; False si l'enregistrement a échoué."""
        ok = self.save() if self._save_timer.isActive() else True
        self.player.shutdown()
        self.importer.wait(5000)
        return ok

    def _on_project_changed(self) -> None:
        self.mark_dirty()
        media_ids = [m.id for m in self.project.media]
        if media_ids != self._shown_media:
            self._shown_media = media_ids
            self.media_panel.set_media(self.project.media, self.thumbnails)
        self.player.load(timeline_spec(self.project))
        self._on_clip_selected(self.controller.selected)

    # --- import -------------------------------------------------------------

    def choose_files(self) -> None:
        files, _f = QFileDialog.getOpenFileNames(
            self, _("Importer des fichiers"), str(Path.home()), media_file_filter())
        if files:
            self.import_files(files)

    def import_files(self, paths: list[str]) -> None:
        todo = [p for p in paths if is_supported(p) and not self.project.has_media_path(p)]
        skipped = [Path(p).name for p in paths if not is_supported(p)]
        if skipped:
            QMessageBox.information(
                self, _("Fichiers ignorés"),
                _("Ces fichiers ne sont pas des médias pris en charge :\n{files}").format(
                    files="\n".join(skipped)))
        todo = [p for p in dict.fromkeys(todo) if p not in self._import_queue]
        self._import_queue.extend(todo)
        self.importer.import_files(todo)

    def _on_imported(self, path: str, item: MediaItem | None, thumb: str | None,
                     error: str) -> None:
        self._import_results[path] = (item, thumb, error)
        errors = []
        while self._import_queue and self._import_queue[0] in self._import_results:
            queued = self._import_queue.pop(0)
            item, thumb, error = self._import_results.pop(queued)
            if item is None:
                errors.append(f"{Path(queued).name} : {error}")
            elif not self.project.has_media_path(item.path):
                self._add_media(item, thumb)
        if errors:
            QMessageBox.warning(self, _("Import impossible"), "\n".join(errors))

    def _add_media(self, item: MediaItem, thumb: str | None) -> None:
        if thumb:
            self.thumbnails[item.path] = thumb
        self._ensure_waveform(item)
        self.controller.edit(_("Importer {name}").format(name=item.name),
                             lambda t: t.project.media.append(item))

    def _on_thumbnail(self, path: str, thumb: str | None) -> None:
        if not thumb:
            return
        self.thumbnails[path] = thumb
        for m in self.project.media:
            if m.path == path:
                self.media_panel.set_thumbnail(m.id, thumb)
        self.timeline.view.clear_caches()

    def _on_waveform(self, path: str, peaks: bytes | None) -> None:
        if peaks:
            self.waveforms[path] = peaks
            self.timeline.view.viewport().update()

    def remove_media(self, media: MediaItem) -> None:
        used = sum(1 for c in self.project.clips if c.media_id == media.id)
        if used:
            answer = QMessageBox.question(
                self, _("Retirer du projet"),
                _("{name} est utilisé par {n} clip(s) de la timeline, qui seront aussi "
                  "supprimés. Continuer ?").format(name=media.name, n=used))
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.controller.edit(_("Retirer {name}").format(name=media.name),
                             lambda t: t.remove_media(media.id))

    def add_to_timeline(self, media: MediaItem) -> None:
        """Ajoute le média à la suite des clips de la première piste compatible."""
        self.timeline.view.add_media(media, self._default_track(media), None)

    def _default_track(self, media: MediaItem) -> str | None:
        track = self.controller.timeline.first_track("audio" if media.kind == "audio"
                                                     else "video")
        return track.id if track is not None else None

    @property
    def pending_imports(self) -> int:
        return len(self._import_queue)

    # --- sélection ------------------------------------------------------------------

    def _on_media_selected(self, media: MediaItem | None) -> None:
        if media is not None:
            self.controller.select(None)
            self.inspector.show_media(media)
        elif self.controller.selected is None:
            self.inspector.show_project(self.project)

    def _on_clip_selected(self, clip_id: str | None) -> None:
        clip = self.controller.selected_clip()
        if clip is None:
            if clip_id is None and not self.media_panel.grid.selectedItems():
                self.inspector.show_project(self.project)
            return
        media = self.project.find_media(clip.media_id)
        if media is None:
            return
        self.media_panel.grid.clearSelection()
        label_ = self.controller.timeline.track_labels().get(clip.track_id, "")
        self.inspector.show_clip(clip, media, label_, self.project.fps)

    def set_preview_quality(self, quality: str) -> None:
        self.preview.set_quality(quality)

    # --- glisser-déposer de fichiers -----------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self.import_files(files)
            event.acceptProposedAction()
