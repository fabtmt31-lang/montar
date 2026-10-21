# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de l'interface (plateforme Qt « offscreen »)."""
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("PyQt6.QtSvg")

from PyQt6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
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


def imported_editor(window, media_dir, names):
    pytest.importorskip("mlt7")
    editor = window.create_project(NewProjectParams("Montage", "16:9", "720p", 25))
    editor.import_files([str(media_dir / n) for n in names])
    assert wait_until(lambda: editor.pending_imports == 0
                      and len(editor.project.media) == len(names))
    return editor


@needs_ffmpeg
def test_import_order_and_duplicates(window, media_dir):
    names = ["son.wav", "clip.mp4", "photo.png", "vertical.mp4"]
    editor = imported_editor(window, media_dir, names)
    editor.import_files([str(media_dir / "clip.mp4")])  # déjà importé : ignoré
    pump(200)
    assert [m.name for m in editor.project.media] == names
    assert editor.media_panel.grid.count() == 4


@needs_ffmpeg
def test_timeline_editing_and_preview(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4", "son.wav", "red.mp4"])
    clip_media, sound, red = editor.project.media
    view = editor.timeline.view

    # double-clic / « Ajouter à la timeline »
    editor.add_to_timeline(clip_media)
    editor.add_to_timeline(red)
    editor.add_to_timeline(sound)
    clips = editor.project.clips
    assert [(c.start, c.duration) for c in clips] == [(0, 50), (50, 50), (0, 75)]
    assert wait_until(lambda: editor.player.length == 100)

    # aperçu : image rouge au milieu du second clip
    frames = []
    editor.player.frameReady.connect(lambda img, f: frames.append((f, img)))
    editor.player.seek(75)
    assert wait_until(lambda: any(f == 75 for f, _i in frames))
    image = next(img for f, img in frames if f == 75)
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.red() > 200 and color.blue() < 60
    assert editor.preview.timecode.text() == "00:00:03:00"
    assert view.playhead == 75

    # raccourci S : coupe le clip sous la tête de lecture
    editor.controller.select(None)
    QTest.keyClick(window, Qt.Key.Key_S)
    assert len(editor.project.clips) == 4
    assert editor.undo_button.isEnabled()
    QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(editor.project.clips) == 3

    # glisser le second clip vers la droite avec la souris
    view.snap = False
    second = editor.project.clips[1]
    rect = view.clip_rect(second)
    start = QPoint(int(rect.center().x()), int(rect.center().y()))
    end = start + QPoint(int(20 * view.ppf), 0)
    drag(view.viewport(), start, end)
    assert editor.controller.selected == second.id
    moved = editor.controller.selected_clip()
    assert moved.start == 70

    # rogner la fin du premier clip
    first = editor.project.clips[0]
    rect = view.clip_rect(first)
    edge = QPoint(int(rect.right()) - 2, int(rect.center().y()))
    drag(view.viewport(), edge, edge - QPoint(int(10 * view.ppf), 0))
    assert editor.project.clips[0].duration == 40

    # couper le son de la piste A1 via son en-tête
    a1 = editor.controller.timeline.first_track("audio")
    row = next(r for r in view.rows() if r.track.id == a1.id)
    (key, button_rect), *_ = view._header_buttons(row)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=button_rect.center())
    assert a1.muted

    # lecture
    editor.player.seek(0)
    editor.player.play()
    assert wait_until(lambda: editor.player.playing)
    assert wait_until(lambda: not editor.player.playing, 10)
    assert editor.player.position == editor.player.length - 1

    # enregistrement automatique
    assert editor.save()
    saved = Project.load(editor.project.path)
    assert [(c.start, c.duration) for c in saved.clips] == [(0, 40), (70, 50), (0, 75)]
    assert next(t for t in saved.tracks if t.id == a1.id).muted


@needs_ffmpeg
def test_remove_media_removes_its_clips(window, media_dir, monkeypatch):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    editor.remove_media(editor.project.media[0])
    assert editor.project.media == [] and editor.project.clips == []
    editor.controller.undo()
    assert len(editor.project.media) == 1 and len(editor.project.clips) == 1


def drag(widget, start: QPoint, end: QPoint) -> None:
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    steps = 6
    for i in range(1, steps + 1):
        point = start + (end - start) * i / steps
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(point),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
