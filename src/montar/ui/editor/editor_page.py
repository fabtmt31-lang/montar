# SPDX-License-Identifier: GPL-3.0-or-later
"""Écran de montage (maquette 02)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from montar.core.project import MediaItem, Project, ProjectError
from montar.engine.base import Canvas, Engine
from montar.i18n import _
from montar.media.probe import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, is_supported
from montar.media.thumbnails import thumbnail_path
from montar.ui.editor.importer import MediaImporter
from montar.ui.editor.inspector import Inspector
from montar.ui.editor.media_panel import MediaPanel
from montar.ui.editor.player import Player
from montar.ui.editor.preview import PreviewPanel
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
        self._cache = cache
        # Les analyses se terminent dans le désordre : les médias sont ajoutés dans
        # l'ordre de la demande d'import.
        self._import_queue: list[str] = []
        self._import_results: dict[str, tuple[MediaItem | None, str | None, str]] = {}
        self.thumbnails: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
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
        root.addLayout(body, 1)

        self.importer = MediaImporter(cache, self)
        self.importer.finished.connect(self._on_imported)
        self.importer.thumbnailReady.connect(self._on_thumbnail)
        self.media_panel.importRequested.connect(self.choose_files)
        self.media_panel.mediaSelected.connect(self._on_media_selected)
        self.media_panel.removeRequested.connect(self.remove_media)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save)

        self._load_project_media()
        self._refresh_header()
        self.preview.set_canvas(*project.canvas_size)
        self.inspector.show_project(project)

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
        for icon, tip in (("undo-2", _("Annuler")), ("redo-2", _("Rétablir"))):
            b = button("", "ghost", icon, tooltip=f"{tip} — {_(SOON)}")
            b.setEnabled(False)
            layout.addWidget(b)
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

    # --- projet -------------------------------------------------------------

    def _load_project_media(self) -> None:
        for m in self.project.media:
            thumb = thumbnail_path(self._cache, m.path)
            if thumb.exists():
                self.thumbnails[m.path] = str(thumb)
            elif m.exists and m.kind != "audio":
                self.importer.ensure_thumbnail(m)
        self.media_panel.set_media(self.project.media, self.thumbnails)

    def _refresh_header(self) -> None:
        w, h = self.project.canvas_size
        self.title_edit.setText(self.project.name)
        self.status_label.setText(_("Enregistré · {w}×{h} · {fps} i/s").format(
            w=w, h=h, fps=self.project.fps))

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
        had_visual = any(m.kind != "audio" for m in self.project.media)
        self.project.media.append(item)
        if thumb:
            self.thumbnails[item.path] = thumb
        self.media_panel.add_media(item, thumb)
        if not had_visual and item.kind != "audio":
            self.media_panel.select(item.id)
        self.mark_dirty()

    def _on_thumbnail(self, path: str, thumb: str | None) -> None:
        if not thumb:
            return
        self.thumbnails[path] = thumb
        for m in self.project.media:
            if m.path == path:
                self.media_panel.set_thumbnail(m.id, thumb)

    def remove_media(self, media: MediaItem) -> None:
        self.project.media = [m for m in self.project.media if m.id != media.id]
        self.media_panel.remove_media(media.id)
        self.mark_dirty()

    @property
    def pending_imports(self) -> int:
        return len(self._import_queue)

    # --- sélection et aperçu ----------------------------------------------------

    def _on_media_selected(self, media: MediaItem | None) -> None:
        if media is None:
            self.inspector.show_project(self.project)
            self.preview.clear(_("Sélectionnez un média pour l'afficher ici"))
            return
        self.inspector.show_media(media)
        if not media.exists:
            self.preview.clear(_("Fichier introuvable : {path}").format(path=media.path))
            return
        if media.kind == "audio":
            self.preview.clear(_("{name} est un fichier son : aucune image à afficher")
                               .format(name=media.name))
            return
        w, h = self.project.canvas_size
        self.player.open(media.path, media.kind, Canvas(w, h, self.project.fps))

    def set_preview_quality(self, quality: str) -> None:
        self.preview.set_quality(quality)

    # --- glisser-déposer ----------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            self.import_files(files)
            event.acceptProposedAction()
