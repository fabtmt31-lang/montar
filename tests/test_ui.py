# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de l'interface (plateforme Qt « offscreen »)."""
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("PyQt6.QtSvg")

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from montar.core.project import Project  # noqa: E402
from montar.core.settings import Settings  # noqa: E402
from montar.ui.dialogs.new_project import NewProjectDialog, NewProjectParams  # noqa: E402

from .conftest import needs_ffmpeg  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from montar.ui.theme import theme
    from montar.ui.theme.manager import load_fonts

    instance = QApplication.instance() or QApplication(["montar-tests"])
    load_fonts()
    theme().apply("light")
    return instance


@pytest.fixture
def window(app, isolated_home, monkeypatch):
    from montar.ui.main_window import MainWindow

    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    w = MainWindow(Settings(), isolated_home / ".config/montar/settings.json")
    w.show()
    yield w
    w.close()


def pump(ms: int = 50) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        pump(50)
    return predicate()


def test_new_project_dialog(app):
    d = NewProjectDialog(aspect="9:16")
    d.name_edit.setText("  Teaser  ")
    p = d.params()
    assert (p.name, p.aspect, p.resolution, p.fps) == ("Teaser", "9:16", "1080p", 25)
    assert "1080 × 1920" in d.info.text()
    d.name_edit.setText("")
    assert not d.create_button.isEnabled()


def test_create_project_and_back_home(window, isolated_home):
    editor = window.create_project(NewProjectParams("Mon vlog", "1:1", "720p", 30))
    assert editor is not None
    path = editor.project.path
    assert path == isolated_home / "Vidéos" / "Montar" / "Mon vlog.montar"
    assert Project.load(path).canvas_size == (720, 720)
    window.show_home()
    assert window.editor is None
    assert [e.name for e in window.recent.entries()] == ["Mon vlog"]
    assert window.home.projects.grid.count() == 1


def test_theme_switch(window):
    from montar.ui.theme import theme

    window.preferences._set_theme("dark")
    assert theme().palette.dark and window.settings.theme == "dark"
    window.preferences._set_theme("light")
    assert not theme().palette.dark


@needs_ffmpeg
def test_import_preview_and_save(window, media_dir):
    pytest.importorskip("mlt7")
    editor = window.create_project(NewProjectParams("Import", "16:9", "1080p", 25))
    files = [str(media_dir / n) for n in ("son.wav", "clip.mp4", "photo.png", "vertical.mp4")]
    editor.import_files(files + [str(media_dir / "clip.mp4")])  # doublon ignoré
    assert wait_until(lambda: editor.pending_imports == 0 and len(editor.project.media) == 4)
    # ordre d'import respecté malgré l'analyse en parallèle
    assert [m.name for m in editor.project.media] == ["son.wav", "clip.mp4", "photo.png",
                                                       "vertical.mp4"]
    # premier média visuel sélectionné et affiché
    assert wait_until(lambda: editor.preview.canvas._image is not None)
    assert editor.player.length == 50
    frames = []
    editor.player.frameReady.connect(lambda _img, f: frames.append(f))
    editor.player.seek(30)
    assert wait_until(lambda: 30 in frames)
    assert editor.preview.timecode.text() == "00:00:01:05"
    editor.player.play()
    assert wait_until(lambda: not editor.player.playing and editor.player.position == 49, 10)

    editor.media_panel.select(editor.project.media[0].id)  # son : pas d'image
    pump(100)
    assert editor.preview.canvas._image is None

    editor.remove_media(editor.project.media[3])
    assert editor.save()
    saved = Project.load(editor.project.path)
    assert [m.name for m in saved.media] == ["son.wav", "clip.mp4", "photo.png"]
    window.show_home()
    entries = window.recent.entries()
    assert entries[0].thumbnail_media.endswith("clip.mp4")
