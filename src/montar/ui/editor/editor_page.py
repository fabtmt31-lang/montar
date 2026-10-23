# SPDX-License-Identifier: GPL-3.0-or-later
"""Écran de montage (maquette 02)."""
from __future__ import annotations

import copy
import dataclasses
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from montar.core import keyframes, subtitles
from montar.core.project import EXPORT_DIR, MediaItem, Project, ProjectError, new_id
from montar.core.project_files import backup
from montar.core.timecode import frames_to_timecode
from montar.engine.base import Engine, timeline_spec
from montar.engine.export import IMAGE_FORMATS, ExportSettings, human_size, retime
from montar.engine.geometry import offset_for_center, placement
from montar.i18n import _
from montar.media.edit import MediaEdit, output_suffix, updated_media
from montar.media.edit import apply as apply_edit
from montar.media.frames import FrameError, extract_frame, source_seconds
from montar.media.probe import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    ProbeError,
    is_supported,
    probe,
)
from montar.media.recorder import Recorder, pick_window, session_problem
from montar.media.store import is_inside
from montar.media.thumbnails import thumbnail_path
from montar.media.waveform import waveform_path
from montar.plugins import ModuleManager, default_manager
from montar.ui.dialogs.apply_effect import ApplyEffectDialog
from montar.ui.dialogs.export import ExportDialog
from montar.ui.dialogs.generator import GeneratorDialog
from montar.ui.dialogs.media_editor import MediaEditorDialog
from montar.ui.dialogs.recorder import COUNTDOWN, RecorderDialog, RecordingBar
from montar.ui.dialogs.voice_over import VoiceOverDialog
from montar.ui.editor.apply import ApplyAction, actions_for, apply_change
from montar.ui.editor.busy import BusyOverlay, remaining_text
from montar.ui.editor.controller import EditorController
from montar.ui.editor.graphics_panel import GraphicsPanel
from montar.ui.editor.importer import MediaImporter
from montar.ui.editor.inspector import Inspector
from montar.ui.editor.media_panel import MediaPanel
from montar.ui.editor.modules import CANCELLED, EditorModules
from montar.ui.editor.modules_panel import ModuleEntry, ModulesPanel
from montar.ui.editor.panels import EffectsPanel, FiltersPanel, TextPanel, TransitionsPanel
from montar.ui.editor.player import Player
from montar.ui.editor.preview import PreviewPanel
from montar.ui.editor.subtitles_panel import SubtitlesPanel
from montar.ui.graphics import graphic_size, render_graphic
from montar.ui.home.library import LibraryDialog
from montar.ui.text_render import image_path as text_image_path
from montar.ui.text_render import preset_style, text_bounds, typing_sequence
from montar.ui.timeline.panel import TimelinePanel
from montar.ui.widgets import LogoMark, button, label, set_icon

log = logging.getLogger(__name__)


_RAIL = (
    ("media", "Médias", "image"),
    ("audio", "Audio", "music"),
    ("text", "Texte", "type"),
    ("graphics", "Graphiques", "shapes"),
    ("transitions", "Transitions", "columns-2"),
    ("effects", "Effets", "sparkles"),
    ("filters", "Filtres", "blend"),
    ("modules", "Modules", "puzzle"),
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
    exportFinished = pyqtSignal(str)  # erreur (vide si réussite)
    recordingFinished = pyqtSignal(str)  # fichier enregistré (vide si échec)
    saveAsRequested = pyqtSignal(str)  # nom de la copie du projet
    disabledModulesChanged = pyqtSignal(list)  # « Gérer les modules… »
    saveTemplateRequested = pyqtSignal(str)  # nom du modèle

    def __init__(self, project: Project, engine_factory: Callable[[], Engine], cache: Path,
                 preview_quality: str = "medium", modules: ModuleManager | None = None) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.setAcceptDrops(True)
        self.project = project
        self.controller = EditorController(project, self)
        self.module_manager = modules if modules is not None else default_manager()
        self.modules = EditorModules(self.module_manager, self.controller, cache, self,
                                     lambda: self.timeline.view.playhead,
                                     lambda: self.timeline.view.selection_range)
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
        self.media_panel = MediaPanel()
        self.media_panel.grid.cache = cache
        self.text_panel = TextPanel()
        self.transitions_panel = TransitionsPanel(self.controller)
        self.effects_panel = EffectsPanel(self.controller)
        self.filters_panel = FiltersPanel(self.controller)
        self.modules_panel = ModulesPanel()
        self.graphics_panel = GraphicsPanel()
        self.subtitles_panel = SubtitlesPanel(self.controller)
        self.subtitles_panel.playhead = self._playhead
        self.side = QStackedWidget()
        self._side_index = {}
        for key, panel in (("media", self.media_panel), ("text", self.text_panel),
                           ("graphics", self.graphics_panel),
                           ("transitions", self.transitions_panel),
                           ("effects", self.effects_panel), ("filters", self.filters_panel),
                           ("modules", self.modules_panel),
                           ("subtitles", self.subtitles_panel)):
            self._side_index[key] = self.side.addWidget(panel)
        body.addWidget(self._build_rail())
        body.addWidget(self.side)
        self._engine_factory = engine_factory
        self.player = Player(engine_factory, self)
        self.preview = PreviewPanel(self.player, preview_quality)
        body.addWidget(self.preview, 1)
        self.inspector = Inspector(self.controller, self.modules)
        self.inspector.freezeRequested.connect(self.freeze_frame)
        self.inspector.playhead = self._playhead
        self.inspector.seekRequested.connect(self.player.seek)
        self.subtitles_panel.seekRequested.connect(self.player.seek)
        body.addWidget(self.inspector)
        self.effects_panel.set_modules(self.modules)
        self.effects_panel.addRequested.connect(self.open_apply)
        self.modules_panel.set_manager(self.module_manager)
        self.modules_panel.activated.connect(self.use_module_entry)
        self.modules_panel.manageRequested.connect(self.manage_modules)
        self.graphics_panel.set_graphics(self.module_manager.graphics())
        self.graphics_panel.graphicRequested.connect(self.insert_graphic)
        self.transitions_panel.set_module_transitions(self.module_manager.transitions())

        self.timeline = TimelinePanel(self.controller, self.thumbnails.get, self.waveforms.get)
        self.timeline.view.badge_provider = self.modules.badges
        self.timeline.view.applyRequested.connect(self.open_apply)
        self.timeline.voiceOverRequested.connect(self._voice_over_clicked)
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
        self.importer.copyProgress.connect(self._on_copy_progress)
        self.importer.gathered.connect(self._on_gathered)
        self._copies: dict[str, float] = {}  # fichier d'origine → avancement de la copie
        self._gathering: dict[str, tuple[str, bool]] = {}  # média → (source, reliaison)
        self.media_panel.importRequested.connect(self.choose_files)
        self.media_panel.mediaSelected.connect(self._on_media_selected)
        self.media_panel.removeRequested.connect(self.remove_media)
        self.media_panel.addToTimelineRequested.connect(self.add_to_timeline)
        self.media_panel.editRequested.connect(self.edit_media)
        self.media_panel.relinkRequested.connect(self.relink)
        self.media_panel.relinkAllRequested.connect(self.relink_first_missing)
        self.media_panel.libraryRequested.connect(self.open_library)
        self.media_panel.generateRequested.connect(self.open_generator)
        self.library_provider = lambda: []  # fourni par la fenêtre principale
        self.thumbnail_provider = lambda path: None
        self._media_edits: dict[str, tuple[str, str, Path]] = {}  # clé → (média, mode, fichier)

        self.text_panel.addRequested.connect(self.add_text)
        self.transitions_panel.applyRequested.connect(self.add_transition)
        self.controller.changed.connect(self._on_project_changed)
        self.controller.selectionChanged.connect(self._on_clip_selected)
        self.controller.transitionSelected.connect(self._on_transition_selected)
        self.preview.canvas.boxChanged.connect(self._on_preview_box)
        self.preview.canvas.dragFinished.connect(lambda: setattr(self, "_drag_origin", None))
        self._drag_origin: tuple | None = None
        self.controller.historyChanged.connect(self._update_history_buttons)
        self.controller.error.connect(
            lambda msg: QMessageBox.information(self, _("Action impossible"), _(msg)))
        self.timeline.view.seekRequested.connect(self.player.seek)
        self.player.frameReady.connect(self._on_frame)
        # Limite les mises à jour de l'aperçu pendant un réglage (sans attendre la fin du
        # geste : l'aperçu suit le curseur ou la souris).
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(30)
        self._load_timer.timeout.connect(self._reload_player)

        self._export_job = None
        self._export_settings: ExportSettings | None = None
        self._export_started = 0.0
        self._notify_export = True  # message de fin (désactivé par les tests)
        self._hardware = False  # accélération matérielle proposée par défaut
        self._recorder: Recorder | None = None
        self._record_bar: RecordingBar | None = None
        self._record_timer = QTimer(self)
        self._record_timer.setInterval(250)
        self._record_timer.timeout.connect(self._poll_recording)
        self._export_timer = QTimer(self)
        self._export_timer.setInterval(250)
        self._export_timer.timeout.connect(self._poll_export)

        self.autosave = True  # sinon : enregistrement par Ctrl+S, question à la fermeture
        self.backup_every = 120.0  # secondes entre deux copies de sauvegarde
        self._dirty = False
        self.notifications = None  # montar.core.notifications.Notifications
        self._voice_pending: dict[str, tuple[int, int]] = {}  # fichier → (début, rognage)
        self._overlay_pending: dict[str, tuple[int, bool]] = {}  # fichier → (début, dessous)
        self._freeze_pending: dict[str, tuple[str, int]] = {}  # fichier → (clip, image)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save)

        self.modules.jobs.changed.connect(self._update_jobs)
        self.modules.jobs.finished.connect(self._on_job_finished)
        self._modules_listener = self._on_modules_changed
        self.module_manager.listeners.append(self._modules_listener)

        self._install_shortcuts()
        self.busy = BusyOverlay(self)
        self.busy.cancelRequested.connect(self._cancel_jobs)
        self._load_project_media()
        self._gather_media()
        self._refresh_header()
        self._update_history_buttons()
        self.preview.set_canvas(*project.canvas_size)
        self.inspector.show_project(project)
        self._reload_player()

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
        self.jobs_box = QWidget()
        jl = QHBoxLayout(self.jobs_box)
        jl.setContentsMargins(12, 0, 0, 0)
        jl.setSpacing(6)
        self.jobs_label = label("", "small")
        self.jobs_bar = QProgressBar()
        self.jobs_bar.setRange(0, 100)
        self.jobs_bar.setFixedWidth(110)
        self.jobs_bar.setTextVisible(False)
        self.jobs_bar.setFixedHeight(6)
        jl.addWidget(self.jobs_label)
        jl.addWidget(self.jobs_bar)
        self.jobs_box.setVisible(False)
        layout.addWidget(self.jobs_box)
        self.failed_box = QWidget()
        fl = QHBoxLayout(self.failed_box)
        fl.setContentsMargins(12, 0, 0, 0)
        fl.setSpacing(6)
        self.failed_label = label("", "small")
        self.failed_label.setStyleSheet("color: #B4452F;")
        self.retry_button = button(_("Relancer"), "secondary", "rotate-cw")
        self.retry_button.clicked.connect(self._retry_jobs)
        fl.addWidget(self.failed_label)
        fl.addWidget(self.retry_button)
        self.failed_box.setVisible(False)
        layout.addWidget(self.failed_box)
        layout.addSpacing(12)
        self.undo_button = button("", "ghost", "undo-2")
        self.redo_button = button("", "ghost", "redo-2")
        self.undo_button.clicked.connect(self.controller.undo)
        self.redo_button.clicked.connect(self.controller.redo)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        self.project_button = button("", "ghost", "ellipsis", tooltip=_("Projet"))
        menu = QMenu(self.project_button)
        menu.addAction(_("Enregistrer (Ctrl+S)"), self.save)
        menu.addAction(_("Enregistrer sous…"), self.save_as)
        menu.addAction(_("Enregistrer comme modèle…"), self.save_as_template)
        menu.addAction(_("Ouvrir le dossier du projet"), self._open_project_folder)
        self.project_button.setMenu(menu)
        layout.addWidget(self.project_button)
        layout.addStretch(1)

        self.export_button = button(_("Exporter"), "primary", "download",
                                    tooltip=_("Exporter la vidéo (Ctrl+E)"))
        self.export_button.setMinimumHeight(40)
        self.export_button.clicked.connect(self.open_export)
        layout.addWidget(self.export_button)
        return header

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("Rail")
        rail.setFixedWidth(84)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(4)
        group = QButtonGroup(rail)
        self.rail_buttons: dict[str, QToolButton] = {}
        for key, text, icon in _RAIL:
            b = QToolButton()
            b.setText(_(text))
            b.setProperty("variant", "rail")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            set_icon(b, icon, "ink", 20)
            if key == "record":
                b.setCheckable(False)
                b.setToolTip(_("Enregistrer l'écran"))
                b.clicked.connect(self.open_recorder)
            else:
                b.clicked.connect(lambda _=False, k=key: self.show_side(k))
            b.setChecked(key == "media")
            group.addButton(b)
            layout.addWidget(b)
            self.rail_buttons[key] = b
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
            ("Ctrl+E", self.open_export),
            ("Ctrl+S", self.save),
            (QKeySequence.StandardKey.Undo, self.controller.undo),
            (QKeySequence.StandardKey.Redo, self.controller.redo),
            ("Ctrl+Y", self.controller.redo),
            ("Ctrl++", lambda: tl.view.set_zoom(tl.view.pps * 1.5)),
            ("Ctrl+=", lambda: tl.view.set_zoom(tl.view.pps * 1.5)),
            ("Ctrl+-", lambda: tl.view.set_zoom(tl.view.pps / 1.5)),
            ("Ctrl+0", tl.view.zoom_to_fit),
            ("I", tl.view.mark_in),
            ("O", tl.view.mark_out),
            ("Escape", tl.view.clear_range),
            ("M", tl.toggle_marker),
            ("Ctrl+Left", lambda: tl.go_to_marker(-1)),
            ("Ctrl+Right", lambda: tl.go_to_marker(1)),
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
        self._used_media: set[str] = set()
        self._update_used_media()

    def _gather_media(self) -> None:
        """Projets d'avant la copie des médias : les fichiers encore hors du dossier du
        projet y sont copiés en tâche de fond."""
        folder = self.project.media_dir
        if folder is None:
            return
        for m in self.project.media:
            if m.exists and not is_inside(m.path, folder):
                self._copy_into_project(m, m.path)

    def _copy_into_project(self, media: MediaItem, source: str, relink: bool = False) -> None:
        if media.id in self._gathering or self.project.media_dir is None:
            return
        self._gathering[media.id] = (source, relink)
        self._copies[source] = 0.0
        self.importer.gather(media.id, source, self.project.media_dir)
        self._update_jobs()

    def _on_gathered(self, media_id: str, copy: str | None, error: str) -> None:
        source, relink = self._gathering.pop(media_id, ("", False))
        self._copies.pop(source, None)
        self._update_jobs()
        media = self.project.find_media(media_id)
        if media is None or copy is None:
            if error:
                log.warning("copie de %s dans le projet impossible : %s", source, error)
                if relink:
                    QMessageBox.warning(self, _("Relier le média"), error)
            return
        probed = None
        if relink:
            try:
                probed = probe(copy)
            except ProbeError as exc:
                QMessageBox.warning(self, _("Relier le média"), str(exc))
                return
            if probed.kind != media.kind:
                QMessageBox.warning(self, _("Relier le média"),
                                    _("{name} n'est pas du même type que le média "
                                      "manquant.").format(name=Path(source).name))
                return

        def relocate(t, media_id=media_id, copy=copy, source=source, probed=probed):
            m = t.project.find_media(media_id)
            if m is None:
                return
            if probed is not None:  # nouveau fichier : ses propres mesures
                for name in ("duration", "width", "height", "fps", "has_audio",
                             "video_codec", "audio_codec"):
                    setattr(m, name, getattr(probed, name))
                m.original_path = source
            else:
                m.original_path = m.original_path or source
            m.path = copy

        label_ = (_("Relier {name}") if relink else _("Copier {name} dans le projet")).format(
            name=media.name)
        self.controller.edit(label_, relocate)
        moved = self.project.find_media(media_id)
        if moved is not None:
            if moved.kind != "audio":
                self.importer.ensure_thumbnail(moved)
            self._ensure_waveform(moved)
            if relink:
                for clip in [c for c in self.project.clips if c.media_id == media_id]:
                    self.controller.timeline.fit_to_media(clip.id)
                self.media_panel.set_media(self.project.media, self.thumbnails)
                self._reload_player()

    # --- médias manquants ------------------------------------------------------------

    def missing_media(self) -> list[MediaItem]:
        return [m for m in self.project.media if not m.exists]

    def relink(self, media: MediaItem, path: str | None = None) -> None:
        """Relie un média introuvable à un fichier (copié dans le projet)."""
        if path is None:
            path, _f = QFileDialog.getOpenFileName(
                self, _("Où se trouve {name} ?").format(name=media.name),
                str(Path(media.original_path or media.path).parent), media_file_filter())
            if not path:
                return
        self._copy_into_project(media, path, relink=True)
        # les autres médias manquants sont cherchés dans le même dossier
        folder = Path(path).parent
        for other in self.missing_media():
            if other.id == media.id or other.id in self._gathering:
                continue
            for name in (Path(other.path).name, Path(other.original_path).name):
                if name and (folder / name).is_file():
                    self._copy_into_project(other, str(folder / name), relink=True)
                    break

    def open_library(self) -> None:
        items = self.library_provider()
        if not items:
            QMessageBox.information(self, _("Médiathèque"),
                                    _("Aucun média dans vos autres projets pour l'instant."))
            return
        dialog = LibraryDialog(items, self.thumbnail_provider, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_files(dialog.paths())

    def relink_first_missing(self) -> None:
        missing = self.missing_media()
        if missing:
            self.relink(missing[0])

    def _on_copy_progress(self, path: str, ratio: float) -> None:
        if path in self._copies:
            self._copies[path] = ratio
            self._update_jobs()

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
        self._dirty = True
        if self.autosave:
            self._save_timer.start()

    def save_as(self) -> None:
        name, ok = QInputDialog.getText(self, _("Enregistrer sous"),
                                        _("Nom de la copie du projet :"),
                                        text=_("{name} (copie)").format(name=self.project.name))
        if ok and name.strip() and self.save():
            self.saveAsRequested.emit(name.strip())

    def save_as_template(self) -> None:
        name, ok = QInputDialog.getText(self, _("Enregistrer comme modèle"),
                                        _("Nom du modèle :"), text=self.project.name)
        if ok and name.strip() and self.save():
            self.saveTemplateRequested.emit(name.strip())

    def _open_project_folder(self) -> None:
        if self.project.path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.path.parent)))

    def save(self) -> bool:
        self._save_timer.stop()
        try:
            path = self.project.save()
            backup(self.project, every=self.backup_every)
        except (OSError, ProjectError) as exc:
            QMessageBox.warning(self, _("Enregistrement impossible"), str(exc))
            return False
        self._dirty = False
        self._refresh_header()
        self.saved.emit(path)
        return True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def confirm_close(self) -> bool:
        """Sans sauvegarde automatique, propose d'enregistrer les modifications ; False si
        l'utilisateur annule la fermeture."""
        if self.autosave or not self._dirty:
            return True
        answer = QMessageBox.question(
            self, _("Modifications non enregistrées"),
            _("Enregistrer les modifications de « {name} » ?").format(name=self.project.name),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        if answer == QMessageBox.StandardButton.Discard:
            self._save_timer.stop()
            self._dirty = False
            return True
        return False

    def close_project(self) -> bool:
        """Enregistre si nécessaire et arrête la lecture ; False si l'enregistrement a échoué."""
        ok = self.save() if self._save_timer.isActive() else True
        if self._modules_listener in self.module_manager.listeners:
            self.module_manager.listeners.remove(self._modules_listener)
        self.modules.jobs.cancel_all()
        if self._recorder is not None:
            self.stop_recording()
        if self._export_job is not None:
            self._export_job.cancel()
            self._export_job.wait(10)
            self._export_job = None
        self.player.shutdown()
        self.importer.wait(5000)
        return ok

    def show_side(self, key: str) -> None:
        """Affiche un panneau du rail ; « Audio » montre les sons du projet."""
        if key in self.rail_buttons:
            self.rail_buttons[key].setChecked(True)
        if key == "audio":
            self.media_panel.set_filter("audio")
            key = "media"
        elif key == "media":
            self.media_panel.set_filter("all")
        self.side.setCurrentIndex(self._side_index[key])

    def _text_image(self, clip, width: int, height: int) -> str:
        return text_image_path(self._cache, clip, width, height)

    def _text_sequence(self, clip, width: int, height: int) -> list[tuple[str, int]]:
        return typing_sequence(self._cache, clip, width, height, self.project.fps)

    def _reload_player(self) -> None:
        self._load_timer.stop()
        self.player.load(timeline_spec(self.project, self._text_image, self.modules.hook,
                                       transition_hook=self.modules.transition_hook,
                                       text_sequence=self._text_sequence))

    # --- modules -------------------------------------------------------------------------

    def _is_visual(self, clip) -> bool:
        media = self.project.find_media(clip.media_id) if clip.media_id else None
        return (media is not None and media.kind in ("video", "image")
                and self.controller.timeline.track(clip.track_id).kind == "video")

    def _has_sound(self, clip) -> bool:
        media = self.project.find_media(clip.media_id) if clip.media_id else None
        return media is not None and media.kind in ("video", "audio") and media.has_audio

    def open_apply(self, clip_id: str) -> None:
        """« Appliquer un effet ou un module… » sur le clip (ou sa plage sélectionnée)."""
        clip = self.controller.timeline.clip(clip_id)
        actions = actions_for(clip, self._is_visual(clip), self.modules, self._has_sound(clip))
        view = self.timeline.view
        found = view.valid_range()
        on_range = found is not None and found[0].id == clip_id
        name = (clip.text.content.split("\n")[0] if clip.is_text else
                self.project.find_media(clip.media_id).name)
        fps = self.project.fps
        if on_range:
            target = _("Sur la plage {a} → {b} de « {name} »").format(
                a=frames_to_timecode(found[1], fps), b=frames_to_timecode(found[2], fps),
                name=name)
        else:
            target = _("Sur le clip « {name} »").format(name=name)
        if not actions:
            QMessageBox.information(self, _("Appliquer un effet ou un module"),
                                    _("Aucun effet ni module ne s'applique à ce clip."))
            return
        dialog = ApplyEffectDialog(actions, target, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.chosen is None:
            return
        self.apply_action(dialog.chosen, clip_id)

    def apply_action(self, action: ApplyAction, clip_id: str) -> None:
        clip = self.controller.timeline.clip(clip_id)
        if action.kind == "tool":
            self.modules.run_tool(action.module_id, action.tool, clip)  # gère la plage
            return
        view = self.timeline.view
        found = view.valid_range()
        if found is not None and found[0].id == clip_id and \
                (found[1], found[2]) != (clip.start, clip.end):
            view.isolate_range()  # l'effet ne porte que sur la plage
            clip = self.controller.selected_clip() or clip
        defaults = None
        if action.kind in ("module_effect", "audio_effect"):
            effects = self.module_manager.effects() + self.module_manager.audio_effects()
            found_effect = next((e for _m, e in effects if e.id == action.key), None)
            defaults = found_effect.defaults() if found_effect else {}
        self.controller.edit_clip(action.title, clip.id, apply_change(action, defaults))
        self.controller.select(clip.id)
        self.show_side("filters" if action.kind == "preset" else "effects")

    def _update_jobs(self) -> None:
        """Calculs longs (module, export) : fenêtre d'avancement qui bloque le projet ;
        copies de médias : petit indicateur dans l'en-tête."""
        modules = self.modules.jobs.summary()
        job = getattr(self, "_export_job", None)
        busy = None
        if job is not None:
            name = Path(self._export_settings.path).name if self._export_settings else ""
            busy = (_("Export de {name}").format(name=name), job.progress,
                    remaining_text(time.monotonic() - self._export_started, job.progress))
        elif modules is not None:
            title, ratio = modules
            busy = (_("{title} : calcul en cours").format(title=title), ratio,
                    remaining_text(self.modules.jobs.elapsed(), ratio))
        overlay = getattr(self, "busy", None)
        if overlay is not None:
            if busy is not None:
                overlay.show_progress(*busy)
            elif overlay.isVisible():
                overlay.hide()
            self._set_shortcuts_enabled(busy is None)
        copying = getattr(self, "_copies", None)
        self.jobs_box.setVisible(bool(copying))
        if copying:
            ratio = sum(copying.values()) / len(copying)
            title = (_("Copie des médias ({n})").format(n=len(copying)) if len(copying) > 1
                     else _("Copie des médias"))
            self.jobs_label.setText(_("{title} : {p} %").format(title=title,
                                                                p=round(ratio * 100)))
            self.jobs_bar.setValue(round(ratio * 100))
        failure = self.modules.jobs.failure_summary() if busy is None else None
        self.failed_box.setVisible(failure is not None)
        if failure is not None:
            title, cancelled = failure
            text = _("{title} annulé") if cancelled else _("{title} : échec")
            self.failed_label.setText(text.format(title=title))

    def _set_shortcuts_enabled(self, enabled: bool) -> None:
        for shortcut in self.findChildren(QShortcut):
            shortcut.setEnabled(enabled)

    def _cancel_jobs(self) -> None:
        if self._export_job is not None:
            self._export_job.cancel()
        else:
            self.modules.jobs.cancel()

    # --- édition d'un média ------------------------------------------------------------

    def _timelapse_render(self):
        """Fonction de calcul du module Timelapse, s'il est actif."""
        import sys

        if not self.module_manager.is_active("timelapse"):
            return None
        core = sys.modules.get("montar_modules.timelapse.core")
        return getattr(core, "render", None)

    def edit_media(self, media: MediaItem) -> None:
        if not media.exists or self.project.media_dir is None:
            return
        dialog = MediaEditorDialog(media, self._engine_factory,
                                   self._timelapse_render() is not None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_mode:
            return
        self.start_media_edit(media, dialog.edit, dialog.result_mode)

    def start_media_edit(self, media: MediaItem, edit: MediaEdit, mode: str) -> None:
        """Calcule le média modifié, puis remplace l'original (« replace ») ou ajoute une
        copie (« copy ») ; calcul en tâche de fond, sous la fenêtre d'avancement."""
        folder = self.project.media_dir
        stem = Path(media.path).stem
        target = folder / f"{stem} ({_('modifié')}){output_suffix(media)}"
        n = 2
        while target.exists() or any(m.path == str(target) for m in self.project.media):
            target = folder / f"{stem} ({_('modifié')} {n}){output_suffix(media)}"
            n += 1
        key = f"edit:{media.id}:{target.name}"
        self._media_edits[key] = (media.id, mode, target)
        source, frozen, render = media.path, copy.deepcopy(media), self._timelapse_render()
        edit = copy.deepcopy(edit)

        def work(progress, cancelled):
            apply_edit(source, target, frozen, edit, progress, cancelled, render)

        self.modules.jobs.schedule(key, _("Modification de {name}").format(name=media.name),
                                   work)

    def _media_edit_done(self, key: str, error: str) -> None:
        media_id, mode, target = self._media_edits.pop(key)
        self.modules.jobs.failed.pop(key, None)  # rien à relancer : il suffit de refaire
        self._update_jobs()
        if error:
            if error != CANCELLED:
                QMessageBox.warning(self, _("Modification impossible"), error)
            return
        try:
            probed = probe(target)
        except ProbeError as exc:
            QMessageBox.warning(self, _("Modification impossible"), str(exc))
            return
        original = self.project.find_media(media_id)
        if original is None:
            return
        if mode == "replace":
            new = updated_media(original, probed, target)

            def replace(t, new=new):
                index = next(i for i, m in enumerate(t.project.media) if m.id == new.id)
                t.project.media[index] = new
                for clip in [c for c in t.project.clips if c.media_id == new.id]:
                    t.fit_to_media(clip.id)

            self.controller.edit(_("Modifier {name}").format(name=original.name), replace)
        else:
            new = updated_media(original, probed, target)
            new.id = new_id()
            self.controller.edit(_("Importer {name}").format(name=new.name),
                                 lambda t, new=new: t.project.media.append(new))
        if new.kind != "audio":
            self.importer.ensure_thumbnail(new)
        self._ensure_waveform(new)
        self.media_panel.set_media(self.project.media, self.thumbnails)
        self.media_panel.select(new.id)
        self._reload_player()

    # --- enregistrement de l'écran -----------------------------------------------------

    def open_recorder(self) -> None:
        problem = session_problem()
        if problem:
            QMessageBox.information(self, _("Enregistrer l'écran"),
                                    _("Enregistrement impossible : {why}.").format(why=_(problem)))
            return
        if self._recorder is not None or self.project.media_dir is None:
            return
        dialog = RecorderDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        target = self.project.media_dir / f"{_('Enregistrement')} {stamp}.mp4"
        self.start_recording(dialog.options(), target)

    def start_recording(self, options, target: Path, countdown: int = COUNTDOWN) -> None:
        self._recorder = Recorder(options, target)
        self._record_bar = RecordingBar()
        self._record_bar.stopRequested.connect(self.stop_recording)
        self._record_bar.countdownFinished.connect(self._begin_recording)
        self.window().showMinimized()
        self._record_bar.start_countdown(countdown)

    def _begin_recording(self) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        if recorder.options.source == "window":
            recorder.options.window_id = pick_window()
        recorder.start()
        self._record_timer.start()

    def _poll_recording(self) -> None:
        recorder = self._recorder
        if recorder is None:
            self._record_timer.stop()
            return
        if recorder.started and not recorder.running:  # ffmpeg s'est arrêté seul
            self.stop_recording()
            return
        self._record_bar.set_elapsed(recorder.elapsed)

    def stop_recording(self) -> None:
        recorder, self._recorder = self._recorder, None
        self._record_timer.stop()
        if self._record_bar is not None:
            self._record_bar.close()
            self._record_bar.deleteLater()
            self._record_bar = None
        window = self.window()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        if recorder is None or not recorder.started:
            return
        if recorder.stop():
            self.import_files([str(recorder.target)])
            self.recordingFinished.emit(str(recorder.target))
        else:
            self.recordingFinished.emit("")
            QMessageBox.warning(self, _("Enregistrer l'écran"),
                                _("L'enregistrement a échoué : {error}").format(
                                    error=recorder.error))

    # --- notifications ----------------------------------------------------------------------

    def set_notifications(self, notifications) -> None:
        """Cloche dans l'en-tête ; les fins d'export et les échecs y sont signalés."""
        from montar.ui.notifications import NotificationButton

        self.notifications = notifications
        self.bell = NotificationButton(notifications)
        layout = self.export_button.parentWidget().layout()
        layout.insertWidget(layout.indexOf(self.export_button), self.bell)

    def notify(self, title: str, text: str = "", kind: str = "info", path: str = "") -> None:
        if self.notifications is not None:
            self.notifications.add(title, text, kind, path)

    # --- panneau Modules --------------------------------------------------------------------

    def use_module_entry(self, entry: ModuleEntry) -> None:
        """Clic dans le panneau Modules : appliquer au clip sélectionné, placer la
        transition, créer le média ou ouvrir l'export."""
        if entry.kind == "transition":
            if self.transitions_panel.target() is None:
                QMessageBox.information(self, _("Modules"), _(
                    "Sélectionnez un clip suivi (ou précédé) d'un autre clip collé à lui, ou "
                    "glissez la transition depuis le panneau Transitions."))
                return
            self.add_transition(entry.item.id)
            return
        if entry.kind == "generator":
            dialog = GeneratorDialog(self.module_manager.generators(), self)
            dialog.select(entry.item.id)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen is not None:
                self.generate(*dialog.chosen, dialog.values)
            return
        if entry.kind == "export_format":
            self.open_export(entry.item.id)
            return
        clip = self.controller.selected_clip()
        if clip is None:
            QMessageBox.information(self, _("Modules"),
                                    _("Sélectionnez d'abord un clip dans la timeline."))
            return
        if entry.kind == "tool":
            usable = any(t is entry.item for _m, t in self.modules.tools_for(clip))
        elif entry.kind == "audio_effect":
            usable = self._has_sound(clip)
        else:
            usable = self._is_visual(clip)
        if not usable:
            QMessageBox.information(self, _("Modules"), _(
                "« {name} » ne s'applique pas à ce clip.").format(name=entry.name))
            return
        action = ApplyAction(entry.kind, entry.item.id, entry.name, entry.description,
                             entry.icon, entry.module_id, "",
                             entry.item if entry.kind == "tool" else None)
        self.apply_action(action, clip.id)

    def manage_modules(self) -> None:
        """Préférences → Extensions, dans une fenêtre, sans quitter le montage."""
        from montar.ui.home.extensions import ExtensionsCard

        dialog = QDialog(self)
        dialog.setObjectName("ExportDialog")
        dialog.setWindowTitle(_("Modules"))
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        card = ExtensionsCard(self.module_manager)
        card.disabledChanged.connect(self.disabledModulesChanged)
        layout.addWidget(card, 1)
        close = button(_("Fermer"), "secondary")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    # --- image fixe ------------------------------------------------------------------------

    FREEZE_SECONDS = 2

    def freeze_frame(self, clip_id: str) -> Path | None:
        """Image fixe : l'image affichée à la tête de lecture est extraite dans medias/ puis
        insérée dans le clip, pendant FREEZE_SECONDS secondes."""
        clip = self.controller.timeline.clip(clip_id)
        media = self.project.find_media(clip.media_id) if clip.media_id else None
        frame = self.timeline.view.playhead
        if media is None or media.kind != "video" or self.project.media_dir is None:
            return None
        if not clip.start <= frame < clip.end:
            QMessageBox.information(self, _("Image fixe"),
                                    _("Placez la tête de lecture sur le clip."))
            return None
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        target = self.project.media_dir / f"{_('Image fixe')} {stamp}.png"
        try:
            extract_frame(media.path, source_seconds(clip, frame, self.project.fps), target)
        except FrameError as exc:
            QMessageBox.warning(self, _("Image fixe"), str(exc))
            return None
        self._freeze_pending[str(target)] = (clip_id, frame)
        self.import_files([str(target)])
        return target

    def _place_freeze(self, item: MediaItem, clip_id: str, frame: int) -> None:
        duration = self.FREEZE_SECONDS * self.project.fps

        def add(t):
            t.project.media.append(item)
            return t.insert_freeze(clip_id, frame, item, duration)

        still = self.controller.edit(_("Image fixe"), add)
        if still is not None:
            self.controller.select(still.id)

    # --- graphismes ------------------------------------------------------------------------

    def insert_graphic(self, module_id: str, graphic) -> Path | None:
        """Panneau Graphiques : l'élément (image PNG à la taille du projet, dans medias/) est
        placé à la tête de lecture, au-dessus de la vidéo ou, pour un arrière-plan, dessous."""
        if self.project.media_dir is None:
            return None
        w, h = graphic_size(graphic, self.project.canvas_size)
        name = graphic.id.replace("/", "_").replace(".", "-")
        target = self.project.media_dir / f"{_('Graphique')} {name} {w}x{h}.png"
        start = self.timeline.view.playhead
        below = graphic.category == "arriere-plans"
        existing = next((m for m in self.project.media if Path(m.path) == target), None)
        if existing is not None:
            self._place_overlay(existing, None, start, below, add_media=False)
            return target
        try:
            if not target.exists():
                render_graphic(graphic, (w, h), target)
        except OSError as exc:
            QMessageBox.warning(self, _("Graphiques"), str(exc))
            return None
        self._overlay_pending[str(target)] = (start, below)
        self.import_files([str(target)])
        return target

    def _place_overlay(self, item: MediaItem, thumb: str | None, start: int, below: bool,
                       add_media: bool = True) -> None:
        if add_media:
            if thumb:
                self.thumbnails[item.path] = thumb

        def add(t):
            if add_media:
                t.project.media.append(item)
            clip = t.add_overlay(item, start, below)
            # une image est ajustée à la toile : l'élément garde sa taille prévue
            cw, ch = self.project.canvas_size
            if item.width and item.height:
                clip.transform.scale = round(min(1.0, 1 / min(cw / item.width,
                                                              ch / item.height)), 4)
            return clip

        clip = self.controller.edit(_("Ajouter un graphisme"), add)
        if clip is not None:
            self.controller.select(clip.id)

    # --- générateurs des modules ---------------------------------------------------------

    def open_generator(self) -> None:
        generators = self.module_manager.generators()
        if not generators:
            QMessageBox.information(self, _("Créer un média"),
                                    _("Aucun module actif ne propose de générateur."))
            return
        dialog = GeneratorDialog(generators, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen is not None:
            self.generate(*dialog.chosen, dialog.values)

    def generate(self, module_id: str, generator, values: dict) -> Path | None:
        """Écrit le média du générateur dans le dossier du projet, puis l'importe."""
        if self.project.media_dir is None:
            return None
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        suffix = generator.suffix if generator.suffix.startswith(".") else f".{generator.suffix}"
        target = self.project.media_dir / f"{_(generator.name)} {stamp}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        merged = {**generator.defaults(), **values}
        ok = self.module_manager.guarded(
            module_id, lambda: generator.generate(self.modules, merged, target) or True, False)
        if not ok or not target.exists():
            QMessageBox.warning(self, _("Créer un média"),
                                _("Le module « {m} » n'a pas pu créer le média.").format(
                                    m=module_id))
            return None
        self.import_files([str(target)])
        return target

    # --- voix off -------------------------------------------------------------------------

    def _voice_over_clicked(self) -> None:
        self.open_voice_over()

    def open_voice_over(self, countdown: int = COUNTDOWN) -> VoiceOverDialog | None:
        if shutil.which("ffmpeg") is None:
            QMessageBox.information(self, _("Voix off"), _("ffmpeg est introuvable."))
            return None
        if self.project.media_dir is None:
            return None
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        target = self.project.media_dir / f"{_('Voix off')} {stamp}.wav"
        start = self.timeline.view.playhead
        dialog = VoiceOverDialog(self.player, start, self.project.fps, target, self, countdown)
        dialog.recorded.connect(lambda path, lead: self._voice_recorded(path, start, lead))
        dialog.failed.connect(self._voice_failed)
        dialog.open()
        return dialog

    def _voice_recorded(self, path: str, start: int, lead: float) -> None:
        self._voice_pending[path] = (start, round(lead * self.project.fps))
        self.import_files([path])

    def _voice_failed(self, error: str) -> None:
        QMessageBox.warning(self, _("Voix off"),
                            _("L'enregistrement a échoué : {error}").format(error=error))

    def _add_voice_over(self, item: MediaItem, thumb: str | None, start: int,
                        trim: int) -> None:
        self._ensure_waveform(item)

        def add(t):
            t.project.media.append(item)
            return t.add_voice_over(item, start, trim)

        clip = self.controller.edit(_("Enregistrer une voix off"), add)
        if clip is not None:
            self.controller.select(clip.id)

    # --- export --------------------------------------------------------------------------

    def open_export(self, fmt: str | None = None) -> None:
        if self._export_job is not None:
            QMessageBox.information(self, _("Exporter la vidéo"),
                                    _("Un export est déjà en cours."))
            return
        length = self.controller.timeline.length()
        if length == 0:
            QMessageBox.information(self, _("Exporter la vidéo"),
                                    _("La timeline est vide : ajoutez des médias avant "
                                      "d'exporter."))
            return
        pending = self.modules.pending_sources()
        if pending or self.modules.jobs.jobs or self._copies:
            QMessageBox.information(
                self, _("Exporter la vidéo"),
                _("Des calculs sont en cours (copie des médias ou timelapse). L'export sera "
                  "possible dès qu'ils seront terminés."))
            self._reload_player()  # relance les calculs manquants
            return
        folder = self.project.path.parent / EXPORT_DIR if self.project.path else Path.home()
        found = self.timeline.view.valid_range()
        dialog = ExportDialog(self.project, length, self.preview.canvas.image, folder,
                              self._hardware, self,
                              [f for _m, f in self.module_manager.export_formats()],
                              (found[1], found[2]) if found else None,
                              min(self.timeline.view.playhead, length - 1))
        if fmt:
            dialog.choose_format(fmt)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.start_export(dialog.settings())

    def start_export(self, settings: ExportSettings) -> None:
        if settings.format in IMAGE_FORMATS:
            self.export_frame(settings)
            return
        found = self.module_manager.export_format(settings.format)
        if found is not None:  # format d'un module : il fournit les réglages de l'encodeur
            module_id, fmt = found
            props = self.module_manager.guarded(
                module_id, lambda: dict(fmt.properties(settings)), None)
            if not props:
                QMessageBox.warning(self, _("Exporter la vidéo"),
                                    _("Le module « {m} » n'a pas pu préparer l'export.").format(
                                        m=module_id))
                return
            settings = dataclasses.replace(settings, custom=tuple(props.items()),
                                           hardware=False)
        size = None if settings.audio_only else (settings.width, settings.height)
        spec = timeline_spec(self.project, self._text_image, self.modules.hook, size,
                             self.modules.transition_hook, self._text_sequence,
                             subtitles=settings.subtitles == "burn")
        if settings.subtitles == "file" and self.project.subtitles:
            try:
                srt = Path(settings.path).with_suffix(".srt")
                srt.parent.mkdir(parents=True, exist_ok=True)
                srt.write_text(subtitles.to_srt(self.project.subtitles, self.project.fps,
                                                settings.range_start, settings.range_end),
                               encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, _("Export impossible"), str(exc))
                return
        if settings.fps != self.project.fps and (settings.range_start or settings.range_end):
            k = settings.fps / self.project.fps  # la partie suit la nouvelle fréquence
            settings = dataclasses.replace(settings, range_start=round(settings.range_start * k),
                                           range_end=round(settings.range_end * k))
        spec = retime(spec, settings.fps)
        Path(settings.path).parent.mkdir(parents=True, exist_ok=True)
        self._export_job = self._engine_factory().export(spec, settings)
        self._export_settings = settings
        self._export_started = time.monotonic()
        self._export_job.start()
        self._export_timer.start()
        self.export_button.setEnabled(False)
        self._update_jobs()

    def export_frame(self, settings: ExportSettings) -> bool:
        """Export d'une image fixe (PNG ou JPEG) de la tête de lecture, à la taille choisie."""
        from PyQt6.QtGui import QImage

        spec = timeline_spec(self.project, self._text_image, self.modules.hook,
                             (settings.width, settings.height), self.modules.transition_hook,
                             self._text_sequence, subtitles=settings.subtitles == "burn")
        try:
            source = self._engine_factory().build(spec)
            try:
                data = source.render(settings.range_start, settings.width, settings.height)
            finally:
                source.close()
            image = QImage(data, settings.width, settings.height, settings.width * 4,
                           QImage.Format.Format_RGBA8888)
            Path(settings.path).parent.mkdir(parents=True, exist_ok=True)
            fmt = "JPG" if settings.format == "jpg" else "PNG"
            if settings.format == "jpg":
                image = image.convertToFormat(QImage.Format.Format_RGB888)
            if not image.save(settings.path, fmt, 92):
                raise OSError(settings.path)
        except Exception as exc:  # moteur ou écriture : message, jamais de plantage
            QMessageBox.warning(self, _("Export impossible"), str(exc))
            return False
        self.exportFinished.emit("")
        self.notify(_("Export terminé"), Path(settings.path).name, "success", settings.path)
        if self._notify_export:
            QMessageBox.information(self, _("Export terminé"), _("{name} est prêt ({size}).")
                                    .format(name=Path(settings.path).name,
                                            size=human_size(Path(settings.path).stat().st_size)))
        return True

    def _poll_export(self) -> None:
        job = self._export_job
        if job is None:
            self._export_timer.stop()
            return
        self._update_jobs()
        if not job.finished:
            return
        self._export_timer.stop()
        self._export_job = None
        self.export_button.setEnabled(True)
        self._update_jobs()
        self.exportFinished.emit(job.error)
        if job.cancelled:
            return
        target = Path(self._export_settings.path)
        if job.error:
            self.notify(_("Export impossible"), _("L'export de {name} a échoué : {error}")
                        .format(name=target.name, error=job.error), "error")
        else:
            self.notify(_("Export terminé"), target.name, "success", str(target))
        if job.error:
            QMessageBox.warning(self, _("Export impossible"),
                                _("L'export de {name} a échoué : {error}").format(
                                    name=target.name, error=job.error))
            return
        if not self._notify_export:
            return
        box = QMessageBox(self)
        box.setWindowTitle(_("Export terminé"))
        box.setText(_("{name} est prêt ({size}).").format(
            name=target.name, size=human_size(target.stat().st_size).lstrip("≈ ")))
        play = box.addButton(_("Lire"), QMessageBox.ButtonRole.ActionRole)
        folder = box.addButton(_("Ouvrir le dossier"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(_("Fermer"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is play:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        elif box.clickedButton() is folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _retry_jobs(self) -> None:
        self.modules.jobs.retry()
        self._reload_player()  # les sources des modules relancent leur calcul

    def _on_job_finished(self, key: str, error: str) -> None:
        if key in self._media_edits:
            self._media_edit_done(key, error)
            return
        if error and error != CANCELLED:
            self.notify(_("Calcul en arrière-plan échoué"), error, "error")
            self.modules.error(_("Un calcul en arrière-plan a échoué :\n{e}").format(e=error))
        self._reload_player()  # le fichier pré-calculé remplace l'aperçu provisoire
        self.timeline.view.viewport().update()

    def _on_modules_changed(self) -> None:
        self._reload_player()
        self.timeline.view.viewport().update()
        self.effects_panel.rebuild_modules()
        self.transitions_panel.set_module_transitions(self.module_manager.transitions())
        self.modules_panel.set_manager(self.module_manager)
        self.graphics_panel.set_graphics(self.module_manager.graphics())
        self._on_clip_selected(self.controller.selected)

    def _on_frame(self, _image, frame: int) -> None:
        self.timeline.set_playhead(frame, follow=self.player.playing)
        self._update_preview_selection()
        self.inspector.refresh_playhead()

    def _playhead(self) -> int:
        return self.timeline.view.playhead

    def _clip_transform(self, clip):
        """Transformation du clip à la tête de lecture (images clés comprises)."""
        return keyframes.transform_at(clip, self.timeline.view.playhead - clip.start)

    def _selection_rect(self) -> QRectF | None:
        """Cadre de l'élément sélectionné dans la toile, s'il est visible à la tête de lecture."""
        clip = self.controller.selected_clip()
        if clip is None or not clip.start <= self.timeline.view.playhead < clip.end:
            return None
        cw, ch = self.project.canvas_size
        if clip.is_text:
            return text_bounds(clip.text, cw, ch)
        media = self.project.find_media(clip.media_id)
        if media is None or media.kind == "audio" or \
                self.controller.timeline.track(clip.track_id).kind != "video":
            return None
        p = placement(cw, ch, media.width, media.height, self._clip_transform(clip))
        return QRectF(p.left, p.top, p.width, p.height)

    def _update_preview_selection(self) -> None:
        clip = self.controller.selected_clip()
        rotation = 0.0 if clip is None or clip.is_text else self._clip_transform(clip).rotation
        self.preview.canvas.set_selection(self._selection_rect(), rotation)

    def _on_preview_box(self, mode: str, rect: QRectF) -> None:
        """Le cadre de l'aperçu a été déplacé ou redimensionné : met à jour le clip."""
        clip = self.controller.selected_clip()
        if clip is None:
            return
        if self._drag_origin is None or self._drag_origin[0] != clip.id:
            start = self._selection_rect()
            if start is None:
                return
            size = clip.text.size if clip.is_text else self._clip_transform(clip).scale
            self._drag_origin = (clip.id, size, start.width())
        _cid, s0, w0 = self._drag_origin
        ratio = rect.width() / max(1e-6, w0)
        cw, ch = self.project.canvas_size
        media = None if clip.is_text else self.project.find_media(clip.media_id)
        center = rect.center()

        def change(c):
            if c.is_text:
                if mode == "scale":
                    c.text.size = round(max(8.0, min(600.0, s0 * ratio)), 1)
                c.text.x = round(max(0.0, min(1.0, center.x() / cw)), 4)
                c.text.y = round(max(0.0, min(1.0, center.y() / ch)), 4)
                return
            local = self.timeline.view.playhead - c.start
            t = copy.copy(keyframes.transform_at(c, local))
            if mode == "scale":
                t.scale = round(max(0.05, min(8.0, s0 * ratio)), 4)
                keyframes.set_property(c, "scale", t.scale, local)
            mw, mh = (media.width, media.height) if media is not None else (cw, ch)
            x, y = offset_for_center(cw, ch, mw, mh, t, center.x(), center.y())
            keyframes.set_property(c, "x", round(x, 4), local)
            keyframes.set_property(c, "y", round(y, 4), local)

        label_ = _("Déplacer") if mode == "move" else _("Redimensionner")
        self.controller.edit_clip(label_, clip.id, change, merge=(clip.id, f"preview:{mode}"))

    def add_text(self, preset: str) -> None:
        style = preset_style(preset)
        playhead = self.timeline.view.playhead
        clip = self.controller.edit(_("Ajouter un texte"), lambda t: t.add_text(style, playhead))
        if clip is not None:
            self.controller.select(clip.id)

    def add_transition(self, kind: str) -> None:
        pair = self.transitions_panel.target()
        if pair is None:
            return
        left, right = pair[0].id, pair[1].id
        transition = self.controller.edit(_("Ajouter une transition"),
                                          lambda t: t.add_transition(left, right, kind))
        if transition is not None:
            self.controller.select_transition(transition.id)

    def _on_transition_selected(self, transition_id: str | None) -> None:
        transition = self.controller.selected_transition_obj()
        if transition is not None:
            self.media_panel.grid.clearSelection()
            self.inspector.show_transition(transition)
        elif self.controller.selected is None:
            self.inspector.show_project(self.project)
        self.timeline.view.viewport().update()

    def _on_project_changed(self) -> None:
        self.mark_dirty()
        media_ids = [m.id for m in self.project.media]
        if media_ids != self._shown_media:
            self._shown_media = media_ids
            self.media_panel.set_media(self.project.media, self.thumbnails)
        self._update_used_media()
        if not self._load_timer.isActive():
            self._load_timer.start()
        if self.controller.selected_transition:
            self._on_transition_selected(self.controller.selected_transition)
        else:
            self._on_clip_selected(self.controller.selected)
        self._update_preview_selection()

    def _update_used_media(self) -> None:
        self.media_panel.set_missing(len(self.missing_media()))
        used = {c.media_id for c in self.project.clips if c.media_id}
        if used != self._used_media:
            self._used_media = used
            self.media_panel.set_used(used)

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
        for p in todo:
            self._copies[p] = 0.0
        self._update_jobs()
        self.importer.import_files(todo, self.project.media_dir)

    def _on_imported(self, path: str, item: MediaItem | None, thumb: str | None,
                     error: str) -> None:
        self._copies.pop(path, None)
        self._update_jobs()
        self._import_results[path] = (item, thumb, error)
        errors = []
        while self._import_queue and self._import_queue[0] in self._import_results:
            queued = self._import_queue.pop(0)
            item, thumb, error = self._import_results.pop(queued)
            if item is None:
                errors.append(f"{Path(queued).name} : {error}")
            elif queued in self._freeze_pending:
                self._place_freeze(item, *self._freeze_pending.pop(queued))
            elif queued in self._overlay_pending:
                self._place_overlay(item, thumb, *self._overlay_pending.pop(queued))
            elif queued in self._voice_pending:
                self._add_voice_over(item, thumb, *self._voice_pending.pop(queued))
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
        self._update_preview_selection()
        clip = self.controller.selected_clip()
        if clip is None:
            if (clip_id is None and not self.media_panel.grid.selectedItems()
                    and self.controller.selected_transition is None):
                self.inspector.show_project(self.project)
            return
        media = self.project.find_media(clip.media_id)
        if media is None and not clip.is_text:
            return
        self.media_panel.grid.clearSelection()
        label_ = self.controller.timeline.track_labels().get(clip.track_id, "")
        self.inspector.show_clip(clip, media, label_, self.project.fps)

    def set_preview_quality(self, quality: str) -> None:
        self.preview.set_quality(quality)

    def apply_preferences(self, settings, opening: bool = False) -> None:
        """Préférences de l'utilisateur ; le magnétisme n'est réglé qu'à l'ouverture (il se
        change ensuite dans la barre de la timeline)."""
        self._hardware = settings.hardware_export
        self.autosave = settings.autosave
        self.backup_every = settings.backup_minutes * 60.0
        if self.autosave and self._dirty:
            self._save_timer.start()
        view = self.timeline.view
        view.video_waveforms = settings.video_waveforms
        view.viewport().update()
        if opening:
            self.timeline.magnet.setChecked(settings.snap)
            self.preview.set_volume(settings.preview_volume)
            self.preview.set_safe_zone(settings.safe_zone)

    # --- glisser-déposer de fichiers -----------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self.import_files(files)
            event.acceptProposedAction()
