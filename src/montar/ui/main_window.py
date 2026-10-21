# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre principale : accueil ↔ montage."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox, QStackedWidget

from montar import __version__
from montar.core.project import Project, ProjectError, unique_project_path
from montar.core.recent import RecentProjects
from montar.core.settings import Settings
from montar.engine import get_engine
from montar.i18n import _
from montar.media.thumbnails import thumbnail_path
from montar.platform import paths
from montar.ui.dialogs.new_project import NewProjectDialog, NewProjectParams
from montar.ui.editor.editor_page import EditorPage, media_file_filter
from montar.ui.home.home_page import HomePage, HomeShell
from montar.ui.home.preferences_page import PreferencesPage
from montar.ui.theme import theme


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, settings_file: Path) -> None:
        super().__init__()
        self.settings, self._settings_file = settings, settings_file
        self.recent = RecentProjects(paths.data_dir() / "recent.json")
        self.cache = paths.cache_dir()
        self.setWindowTitle("montar")
        self.setMinimumSize(QSize(1100, 680))
        self.resize(1440, 900)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.home = HomePage()
        self.projects = HomePage(compact=True)
        self.preferences = PreferencesPage(settings)
        self.shell = HomeShell(self.home, self.projects, self.preferences)
        self.stack.addWidget(self.shell)
        for page in (self.home, self.projects):
            page.newProjectRequested.connect(self.new_project)
            page.importRequested.connect(self.import_into_new_project)
            page.openRequested.connect(self.open_project)
            page.projects.set_thumbnail_provider(self._thumbnail_for)
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

    def _save_settings(self) -> None:
        try:
            self.settings.save(self._settings_file)
        except OSError as exc:
            QMessageBox.warning(self, _("Préférences"), str(exc))
        if self.editor is not None:
            self.editor.set_preview_quality(self.settings.preview_quality)

    # --- projets ---------------------------------------------------------------

    def new_project(self, aspect: str | None = None) -> EditorPage | None:
        dialog = NewProjectDialog(self, aspect=aspect or "16:9")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return self.create_project(dialog.params())

    def create_project(self, params: NewProjectParams) -> EditorPage | None:
        project = Project(name=params.name, aspect=params.aspect,
                          resolution=params.resolution, fps=params.fps)
        target = unique_project_path(self.settings.projects_path, params.name)
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
        self.recent.add(project.path)
        return self._show_editor(project)

    def _show_editor(self, project: Project) -> EditorPage:
        self._close_editor()
        editor = EditorPage(project, get_engine, self.cache, self.settings.preview_quality)
        editor.backRequested.connect(self.show_home)
        editor.saved.connect(lambda _p: None)
        self.editor = editor
        self.stack.addWidget(editor)
        self.stack.setCurrentWidget(editor)
        self.setWindowTitle(f"{project.name} — montar")
        return editor

    def _close_editor(self) -> None:
        if self.editor is not None:
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
