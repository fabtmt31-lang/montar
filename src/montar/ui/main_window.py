# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre principale : accueil ↔ montage."""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox, QStackedWidget

from montar import __version__
from montar.core.library import library
from montar.core.project import Project, ProjectError, unique_project_folder
from montar.core.project_files import Session
from montar.core.project_files import duplicate as duplicate_project
from montar.core.recent import RecentProjects
from montar.core.settings import Settings
from montar.core.trash import Trash
from montar.engine import get_engine
from montar.i18n import _
from montar.media.thumbnails import thumbnail_path
from montar.platform import paths
from montar.plugins import default_manager
from montar.ui.dialogs.new_project import NewProjectDialog, NewProjectParams
from montar.ui.editor.editor_page import EditorPage, media_file_filter
from montar.ui.home.home_page import HomePage, HomeShell
from montar.ui.home.library import LibraryPage, TrashPage
from montar.ui.home.preferences_page import PreferencesPage
from montar.ui.theme import theme

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_file: Path) -> None:
        super().__init__()
        self.settings, self._settings_file = settings, settings_file
        self.recent = RecentProjects(paths.data_dir() / "recent.json")
        self.session = Session(paths.data_dir() / "session.json")
        self.cache = paths.cache_dir()
        self.setWindowTitle("montar")
        self.setMinimumSize(QSize(1100, 680))
        self.resize(1440, 900)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.home = HomePage()
        self.projects = HomePage(compact=True)
        self.modules = default_manager(settings.disabled_modules)
        self.preferences = PreferencesPage(settings, self.modules)
        self.trash = Trash(paths.data_dir() / "corbeille")
        self.trash.purge()
        self.library_page = LibraryPage(self._thumbnail_for)
        self.trash_page = TrashPage(self.trash)
        self.trash_page.restored.connect(self._restored)
        self.shell = HomeShell(self.home, self.projects, self.preferences, [
            ("library", _("Médiathèque"), "library", self.library_page),
            ("trash", _("Corbeille"), "trash-2", self.trash_page),
        ])
        self.shell.pageShown.connect(self._page_shown)
        self.stack.addWidget(self.shell)
        for page in (self.home, self.projects):
            page.newProjectRequested.connect(self.new_project)
            page.importRequested.connect(self.import_into_new_project)
            page.openRequested.connect(self.open_project)
            page.projects.set_thumbnail_provider(self._thumbnail_for)
            page.projects.duplicateRequested.connect(self.duplicate)
            page.projects.deleteRequested.connect(self.move_to_trash)
        self.home.showAllRequested.connect(lambda: self.shell.show_page("projects"))
        self.preferences.themeChanged.connect(theme().apply)
        self.preferences.settingsChanged.connect(self._save_settings)
        self.editor: EditorPage | None = None
        self.refresh_recent()

    # --- accueil -------------------------------------------------------------

    def _thumbnail_for(self, media_path: str) -> str | None:
        thumb = thumbnail_path(self.cache, media_path)
        return str(thumb) if thumb.exists() else None

    def refresh_recent(self) -> None:
        entries = self.recent.entries()
        self.home.set_entries(entries)
        self.projects.set_entries(entries)

    def _volume_changed(self, volume: float) -> None:
        self.settings.preview_volume = round(volume, 2)
        try:
            self.settings.save(self._settings_file)
        except OSError as exc:
            log.warning("préférences non enregistrées : %s", exc)

    def _save_settings(self) -> None:
        try:
            self.settings.save(self._settings_file)
        except OSError as exc:
            QMessageBox.warning(self, _("Préférences"), str(exc))
        if self.editor is not None:
            self.editor.set_preview_quality(self.settings.preview_quality)
            self.editor.apply_preferences(self.settings)

    # --- projets ---------------------------------------------------------------

    def new_project(self, aspect: str | None = None) -> EditorPage | None:
        dialog = NewProjectDialog(self, aspect=aspect or "16:9")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return self.create_project(dialog.params())

    def create_project(self, params: NewProjectParams) -> EditorPage | None:
        project = Project(name=params.name, aspect=params.aspect,
                          resolution=params.resolution, fps=params.fps)
        target = unique_project_folder(self.settings.projects_path, params.name)
        try:
            project.save(target)
        except (OSError, ProjectError) as exc:
            QMessageBox.warning(self, _("Création impossible"),
                                _("Le projet n'a pas pu être enregistré dans {dir} : {error}")
                                .format(dir=target.parent, error=exc))
            return None
        self.recent.add(target)
        return self._show_editor(project)

    def import_into_new_project(self) -> None:
        files, _f = QFileDialog.getOpenFileNames(
            self, _("Importer des fichiers"), str(Path.home()), media_file_filter())
        if not files:
            return
        editor = self.new_project()
        if editor is not None:
            editor.import_files(files)

    def open_project(self, path: Path) -> EditorPage | None:
        try:
            project = Project.load(path)
        except ProjectError as exc:
            QMessageBox.warning(self, _("Ouverture impossible"), str(exc))
            self.recent.remove(Path(path))
            self.refresh_recent()
            return None
        project = self._move_into_own_folder(project)
        self.recent.add(project.path)
        return self._show_editor(project)

    def _move_into_own_folder(self, project: Project) -> Project:
        """Projets enregistrés directement dans le dossier des projets (avant la 0.5) :
        le fichier est rangé dans un dossier à son nom, où ses médias seront copiés."""
        path = project.path
        root = self.settings.projects_path
        try:
            if path is None or path.parent.resolve() != root.resolve():
                return project
            target = unique_project_folder(root, path.stem)
            target.parent.mkdir(parents=True)
            project.save(target)  # chemins des médias réécrits pour le nouvel emplacement
            path.unlink()
        except OSError as exc:
            log.warning("projet laissé à son emplacement (%s) : %s", path, exc)
            return project
        self.recent.remove(path)
        return project

    def _show_editor(self, project: Project) -> EditorPage:
        self._close_editor()
        editor = EditorPage(project, get_engine, self.cache, self.settings.preview_quality,
                            self.modules)
        editor.apply_preferences(self.settings, opening=True)
        editor.backRequested.connect(self.show_home)
        editor.saved.connect(lambda _p: None)
        editor.saveAsRequested.connect(self.save_project_as)
        editor.preview.volumeChanged.connect(self._volume_changed)
        editor.library_provider = lambda: self.library_items(project.path)
        editor.thumbnail_provider = self._thumbnail_for
        self.editor = editor
        if project.path is not None:
            self.session.open(project.path)
        self.stack.addWidget(editor)
        self.stack.setCurrentWidget(editor)
        self.setWindowTitle(f"{project.name} — montar")
        return editor

    def save_project_as(self, name: str) -> EditorPage | None:
        """Copie complète du projet ouvert sous un autre nom, puis ouverture de la copie."""
        if self.editor is None or self.editor.project.path is None or not self.editor.save():
            return None
        try:
            copy = duplicate_project(self.editor.project.path, name, self.settings.projects_path)
        except (OSError, ProjectError) as exc:
            QMessageBox.warning(self, _("Enregistrer sous"), str(exc))
            return None
        return self.open_project(copy)

    def duplicate(self, path: Path) -> None:
        """Accueil : copie d'un projet, ajoutée aux projets récents."""
        try:
            name = Project.load(path).name
            copy = duplicate_project(path, _("{name} (copie)").format(name=name),
                                     self.settings.projects_path)
        except (OSError, ProjectError) as exc:
            QMessageBox.warning(self, _("Dupliquer"), str(exc))
            return
        self.recent.add(copy)
        self.refresh_recent()

    def move_to_trash(self, path: Path) -> None:
        if self.editor is not None and self.editor.project.path == path:
            return
        try:
            self.trash.put(path)
        except OSError as exc:
            QMessageBox.warning(self, _("Corbeille"), str(exc))
            return
        self.recent.remove(path)
        self.refresh_recent()
        self.trash_page.refresh()

    def _restored(self, path: Path) -> None:
        self.recent.add(path)
        self.refresh_recent()

    def library_items(self, exclude: Path | None = None):
        paths = [p for p in self.recent.paths() if p != exclude]
        return library(paths)

    def _page_shown(self, key: str) -> None:
        if key == "library":
            self.library_page.set_items(self.library_items())
        elif key == "trash":
            self.trash_page.refresh()

    def check_interrupted(self) -> None:
        """Au démarrage : montar s'est-il arrêté brutalement la fois précédente ?"""
        project = self.session.interrupted()
        self.session.close()
        if project is None:
            return
        answer = QMessageBox.question(
            self, _("Récupération"),
            _("montar ne s'est pas fermé normalement la dernière fois. Rouvrir le projet "
              "« {name} » ?\n\nLe projet est enregistré automatiquement à chaque "
              "modification ; des versions plus anciennes se trouvent dans son dossier "
              "« sauvegardes ».").format(name=project.stem))
        if answer == QMessageBox.StandardButton.Yes:
            self.open_project(project)

    def _close_editor(self) -> None:
        if self.editor is not None:
            self.session.close()
            self.editor.close_project()
            self.stack.removeWidget(self.editor)
            self.editor.deleteLater()
            self.editor = None

    def show_home(self) -> None:
        self._close_editor()
        self.refresh_recent()
        self.stack.setCurrentWidget(self.shell)
        self.setWindowTitle("montar")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._close_editor()
        super().closeEvent(event)


def about_text() -> str:
    return f"montar {__version__}"
