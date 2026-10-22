# SPDX-License-Identifier: GPL-3.0-or-later
"""Écran de montage (maquette 02)."""
from __future__ import annotations

import logging
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
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from montar.core.project import EXPORT_DIR, MediaItem, Project, ProjectError
from montar.engine.base import Engine, timeline_spec
from montar.engine.export import ExportSettings, human_size, retime
from montar.engine.geometry import offset_for_center, placement
from montar.i18n import _
from montar.media.probe import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, is_supported
from montar.media.store import is_inside
from montar.media.thumbnails import thumbnail_path
from montar.media.waveform import waveform_path
from montar.plugins import ModuleManager, default_manager
from montar.ui.dialogs.export import ExportDialog
from montar.ui.editor.busy import BusyOverlay, remaining_text
from montar.ui.editor.controller import EditorController
from montar.ui.editor.importer import MediaImporter
from montar.ui.editor.inspector import Inspector
from montar.ui.editor.media_panel import MediaPanel
from montar.ui.editor.modules import CANCELLED, EditorModules
from montar.ui.editor.panels import EffectsPanel, FiltersPanel, TextPanel, TransitionsPanel
from montar.ui.editor.player import Player
from montar.ui.editor.preview import PreviewPanel
from montar.ui.text_render import image_path as text_image_path
from montar.ui.text_render import preset_style, text_bounds
from montar.ui.timeline.panel import TimelinePanel
from montar.ui.widgets import LogoMark, button, label, set_icon

log = logging.getLogger(__name__)

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
    exportFinished = pyqtSignal(str)  # erreur (vide si réussite)

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
        self.text_panel = TextPanel()
        self.transitions_panel = TransitionsPanel(self.controller)
        self.effects_panel = EffectsPanel(self.controller)
        self.filters_panel = FiltersPanel(self.controller)
        self.side = QStackedWidget()
        self._side_index = {}
        for key, panel in (("media", self.media_panel), ("text", self.text_panel),
                           ("transitions", self.transitions_panel),
                           ("effects", self.effects_panel), ("filters", self.filters_panel)):
            self._side_index[key] = self.side.addWidget(panel)
        body.addWidget(self._build_rail())
        body.addWidget(self.side)
        self._engine_factory = engine_factory
        self.player = Player(engine_factory, self)
        self.preview = PreviewPanel(self.player, preview_quality)
        body.addWidget(self.preview, 1)
        self.inspector = Inspector(self.controller, self.modules)
        body.addWidget(self.inspector)
        self.effects_panel.set_modules(self.modules)

        self.timeline = TimelinePanel(self.controller, self.thumbnails.get, self.waveforms.get)
        self.timeline.view.badge_provider = self.modules.badges
        self.timeline.view.tool_provider = self._tool_actions
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
        self.media_panel.importRequested.connect(self.choose_files)
        self.media_panel.mediaSelected.connect(self._on_media_selected)
        self.media_panel.removeRequested.connect(self.remove_media)
        self.media_panel.addToTimelineRequested.connect(self.add_to_timeline)

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
            lambda msg: QMessageBox.information(self, _("Action impossible"), msg))
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
        self._export_timer = QTimer(self)
        self._export_timer.setInterval(250)
        self._export_timer.timeout.connect(self._poll_export)

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
        rail.setFixedWidth(76)
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
            if key in ("subtitles", "record"):
                b.setEnabled(False)
                b.setToolTip(_(SOON))
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
            if m.exists and not is_inside(m.path, folder) and m.path not in self._copies:
                self._copies[m.path] = 0.0
                self.importer.gather(m.id, m.path, folder)
        self._update_jobs()

    def _on_gathered(self, media_id: str, copy: str | None, error: str) -> None:
        media = self.project.find_media(media_id)
        if media is not None:
            self._copies.pop(media.path, None)
        self._update_jobs()
        if media is None or copy is None:
            if error:
                log.warning("copie de %s dans le projet impossible : %s",
                            media.path if media else media_id, error)
            return
        original = media.path

        def relocate(t, media_id=media_id, copy=copy, original=original):
            m = t.project.find_media(media_id)
            if m is not None:
                m.path, m.original_path = copy, m.original_path or original

        self.controller.edit(_("Copier {name} dans le projet").format(name=media.name),
                             relocate)
        moved = self.project.find_media(media_id)
        if moved is not None:
            if moved.kind != "audio":
                self.importer.ensure_thumbnail(moved)
            self._ensure_waveform(moved)

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
        if self._modules_listener in self.module_manager.listeners:
            self.module_manager.listeners.remove(self._modules_listener)
        self.modules.jobs.cancel_all()
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

    def _reload_player(self) -> None:
        self._load_timer.stop()
        self.player.load(timeline_spec(self.project, self._text_image, self.modules.hook))

    # --- modules -------------------------------------------------------------------------

    def _tool_actions(self, clip) -> list[tuple[str, Callable[[], None]]]:
        return [(_(tool.name), lambda mid=mid, t=tool, c=clip: self.modules.run_tool(mid, t, c))
                for mid, tool in self.modules.tools_for(clip)]

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

    # --- export --------------------------------------------------------------------------

    def open_export(self) -> None:
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
        dialog = ExportDialog(self.project, length, self.preview.canvas.image, folder,
                              self._hardware, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.start_export(dialog.settings())

    def start_export(self, settings: ExportSettings) -> None:
        size = None if settings.audio_only else (settings.width, settings.height)
        spec = timeline_spec(self.project, self._text_image, self.modules.hook, size)
        spec = retime(spec, settings.fps)
        Path(settings.path).parent.mkdir(parents=True, exist_ok=True)
        self._export_job = self._engine_factory().export(spec, settings)
        self._export_settings = settings
        self._export_started = time.monotonic()
        self._export_job.start()
        self._export_timer.start()
        self.export_button.setEnabled(False)
        self._update_jobs()

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

    def _on_job_finished(self, _key: str, error: str) -> None:
        if error and error != CANCELLED:
            self.modules.error(_("Un calcul en arrière-plan a échoué :\n{e}").format(e=error))
        self._reload_player()  # le fichier pré-calculé remplace l'aperçu provisoire
        self.timeline.view.viewport().update()

    def _on_modules_changed(self) -> None:
        self._reload_player()
        self.timeline.view.viewport().update()
        self.effects_panel.rebuild_modules()
        self._on_clip_selected(self.controller.selected)

    def _on_frame(self, _image, frame: int) -> None:
        self.timeline.set_playhead(frame, follow=self.player.playing)
        self._update_preview_selection()

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
        p = placement(cw, ch, media.width, media.height, clip.transform)
        return QRectF(p.left, p.top, p.width, p.height)

    def _update_preview_selection(self) -> None:
        clip = self.controller.selected_clip()
        rotation = 0.0 if clip is None or clip.is_text else clip.transform.rotation
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
            size = clip.text.size if clip.is_text else clip.transform.scale
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
            t = c.transform
            if mode == "scale":
                t.scale = round(max(0.05, min(8.0, s0 * ratio)), 4)
            mw, mh = (media.width, media.height) if media is not None else (cw, ch)
            x, y = offset_for_center(cw, ch, mw, mh, t, center.x(), center.y())
            t.x, t.y = round(x, 4), round(y, 4)

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
        view = self.timeline.view
        view.video_waveforms = settings.video_waveforms
        view.viewport().update()
        if opening:
            self.timeline.magnet.setChecked(settings.snap)

    # --- glisser-déposer de fichiers -----------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self.import_files(files)
            event.acceptProposedAction()
