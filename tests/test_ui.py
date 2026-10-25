# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de l'interface (plateforme Qt « offscreen »)."""
import dataclasses
import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("PyQt6.QtSvg")

from PyQt6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QMouseEvent, QShortcut  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

from montar.core import keyframes  # noqa: E402
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
    assert path == isolated_home / "Vidéos" / "Montar" / "Mon vlog" / "Mon vlog.montar"
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


def drag(widget, start: QPoint, end: QPoint,
         modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, modifiers, start)
    steps = 6
    for i in range(1, steps + 1):
        point = start + (end - start) * i / steps
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(point),
                            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, modifiers)
        QApplication.sendEvent(widget, event)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, modifiers, end)


# --- J2 ----------------------------------------------------------------------------------


@needs_ffmpeg
def test_inspector_sliders_edit_clip_and_merge_history(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    editor.controller.select(clip.id)
    inspector = editor.inspector
    assert inspector.pages.currentWidget() is inspector._clip
    scale = next(r for r in inspector._sliders if r.getter(clip) == 100 and r._max == 400)
    for value in (90, 80, 70, 60):  # glissement du curseur : une seule étape d'annulation
        scale.moved.emit(value)
    assert clip.transform.scale == pytest.approx(0.6)
    editor.controller.undo()
    assert editor.project.clips[0].transform.scale == 1.0
    assert not editor.controller.history.can_undo or \
        editor.controller.history.undo_label() != "Échelle"


@needs_ffmpeg
def test_text_transition_filter_and_detach(window, media_dir):
    editor = imported_editor(window, media_dir, ["red.mp4", "blue.mp4"])
    red, blue = editor.project.media
    editor.add_to_timeline(red)
    editor.add_to_timeline(blue)
    first, second = editor.project.clips

    # transition depuis le panneau Transitions
    editor.controller.select(first.id)
    assert editor.transitions_panel.target() == (first, second)
    editor.add_transition("dissolve")
    transition = editor.project.transitions[0]
    assert editor.controller.selected_transition == transition.id
    assert editor.inspector.pages.currentWidget() is editor.inspector._transition
    assert second.start == 50 - transition.duration

    # filtre prédéfini sur le second clip
    editor.controller.select(second.id)
    editor.filters_panel._apply("bw")
    assert second.preset == "bw"

    # texte ajouté à la tête de lecture sur une nouvelle piste T1
    editor.timeline.set_playhead(10)
    editor.add_text("lower_third")
    text = editor.controller.selected_clip()
    assert text.is_text and text.start == 10 and text.text.background == "#FFFFFF"
    assert editor.controller.timeline.track(text.track_id).kind == "text"
    assert editor.inspector.pages.currentWidget() is editor.inspector._text
    editor.inspector.text_edit.setPlainText("Fabien · Monteur")
    assert text.text.content == "Fabien · Monteur"

    # l'aperçu affiche le texte : le rendu final contient du blanc (bandeau) en bas à gauche
    frames = []
    editor.player.frameReady.connect(lambda img, f: frames.append((f, img)))
    editor._reload_player()
    editor.player.seek(20)
    assert wait_until(lambda: any(f == 20 for f, _i in frames))
    image = next(img for f, img in frames if f == 20)
    bounds = editor._selection_rect()
    assert bounds is not None
    scale = image.width() / editor.project.canvas_size[0]
    color = image.pixelColor(int((bounds.left() + 4) * scale), int(bounds.center().y() * scale))
    assert color.red() > 200 and color.green() > 200 and color.blue() > 200

    # déplacement du texte dans l'aperçu
    x0 = text.text.x
    editor._on_preview_box("move", editor._selection_rect().translated(192, 0))
    editor.preview.canvas.dragFinished.emit()
    assert text.text.x == pytest.approx(x0 + 192 / editor.project.canvas_size[0])

    # sauvegarde et relecture
    assert editor.save()
    saved = Project.load(editor.project.path)
    assert saved.transitions[0].kind == "dissolve"
    assert any(c.is_text and c.text.content == "Fabien · Monteur" for c in saved.clips)


@needs_ffmpeg
def test_detach_audio_from_menu_logic(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    editor.controller.select(clip.id)
    editor.inspector._detach_audio()
    assert clip.volume == 0
    audio = [c for c in editor.project.clips if c is not clip][0]
    assert editor.controller.timeline.track(audio.track_id).kind == "audio"
    editor.controller.undo()
    assert len(editor.project.clips) == 1 and editor.project.clips[0].volume == 1.0


@needs_ffmpeg
def test_transition_drop_on_junction(window, media_dir):
    from PyQt6.QtCore import QMimeData
    from PyQt6.QtGui import QDropEvent

    from montar.ui.editor.panels import TRANSITION_MIME

    editor = imported_editor(window, media_dir, ["red.mp4", "blue.mp4", "photo.png"])
    red, blue, photo = editor.project.media
    for m in (red, blue, photo):
        editor.add_to_timeline(m)
    a, b, c = editor.project.clips
    view = editor.timeline.view
    view.snap = False
    rect_b = view.clip_rect(b)
    # près de la jonction b|c (et non a|b) : la transition va entre b et c
    near_bc = QPoint(int(rect_b.right()) - 6, int(rect_b.center().y()))
    assert view.junction_at(near_bc) == (b, c)
    assert view.junction_at(QPoint(int(rect_b.center().x()), int(rect_b.center().y()))) is None
    mime = QMimeData()
    mime.setData(TRANSITION_MIME, b"dip_black")
    event = QDropEvent(QPointF(near_bc), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    view.dropEvent(event)
    t = editor.project.transitions[0]
    assert (t.left_id, t.right_id, t.kind) == (b.id, c.id, "dip_black")
    assert editor.controller.selected_transition == t.id


@needs_ffmpeg
def test_preview_follows_drag(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4", "photo.png"])
    clip_media, photo = editor.project.media
    editor.add_to_timeline(clip_media)
    v2 = editor.controller.edit("piste", lambda t: t.add_track("video"))
    editor.timeline.view.add_media(photo, v2.id, 0)
    image_clip = editor.controller.selected_clip()
    editor.player.seek(5)
    assert wait_until(lambda: editor.player.length > 0)
    pump(300)
    frames = []
    editor.player.frameReady.connect(lambda img, f: frames.append(f))
    start = editor._selection_rect()
    for i in range(1, 16):
        editor._on_preview_box("move", start.translated(10 * i, 0))
        pump(40)
    editor.preview.canvas.dragFinished.emit()
    assert len(frames) >= 5  # l'aperçu est mis à jour pendant le geste
    assert image_clip.transform.x == pytest.approx(150 / editor.project.canvas_size[0], abs=1e-3)
    editor.controller.undo()  # tout le geste = une seule étape
    assert editor.controller.selected_clip() is None or \
        editor.project.clips[-1].transform.x == 0


# --- J3 ----------------------------------------------------------------------------------


@needs_ffmpeg
def test_timelapse_tool_with_marked_range(window, media_dir, monkeypatch):

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])  # 50 images
    clip = editor.project.clips[0]
    editor.controller.select(clip.id)
    view = editor.timeline.view
    view.set_playhead(10)
    QTest.keyClick(window, Qt.Key.Key_I)
    view.set_playhead(42)
    QTest.keyClick(window, Qt.Key.Key_O)
    assert view.selection_range == (clip.id, 10, 42)

    tools = dict((t.id, (m, t)) for m, t in editor.modules.tools_for(clip, "speed"))
    assert "timelapse.apply" in tools
    import importlib

    dialog_module = importlib.import_module("montar_modules.timelapse.dialog")
    monkeypatch.setattr(dialog_module.TimelapseDialog, "exec",
                        lambda self: dialog_module.QDialog.DialogCode.Accepted)
    module_id, tool = tools["timelapse.apply"]
    editor.modules.run_tool(module_id, tool, clip)
    segment = editor.controller.selected_clip()
    assert segment.modules["timelapse"]["source_frames"] == 32
    assert segment.duration == 2  # ×16 par défaut
    assert [c.duration for c in sorted(editor.project.clips, key=lambda c: c.start)] == \
        [10, 2, 8]
    assert "TL ×16" in editor.modules.badges(segment)

    # le pré-calcul se lance en arrière-plan puis remplace l'aperçu provisoire
    editor._reload_player()
    assert editor.modules.jobs.jobs  # tâche en cours, aperçu provisoire par saut d'images
    assert wait_until(lambda: not editor.modules.jobs.jobs, 30)
    assert not editor.modules.jobs.failed
    override = editor.modules.hook(segment, editor.project.media[0])
    assert override is not None and override.path.endswith(".mp4") and override.speed == 1.0

    # retirer le timelapse réunit les trois morceaux
    remove = dict((t.id, (m, t)) for m, t in editor.modules.tools_for(segment))
    editor.modules.run_tool(*remove["timelapse.remove"], segment)
    assert len(editor.project.clips) == 1 and editor.project.clips[0].duration == 50
    editor.controller.undo()
    assert len(editor.project.clips) == 3


@needs_ffmpeg
def test_missing_module_keeps_settings(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    editor.controller.edit_clip("x", clip.id,
                                lambda c: c.modules.update({"inconnu.effet": {"a": 1}}))
    editor.controller.select(clip.id)
    assert editor.inspector.missing.isVisibleTo(editor.inspector)
    assert "inconnu.effet" in editor.inspector.missing.text()
    assert editor.save()
    assert Project.load(editor.project.path).clips[0].modules == {"inconnu.effet": {"a": 1}}


# --- 0.4.1 : manipulation dans l'aperçu ---------------------------------------------------


def _canvas_drag(canvas, start, end, modifiers=Qt.KeyboardModifier.NoModifier, steps=10):
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifiers, start.toPoint())
    for i in range(1, steps + 1):
        p = start + (end - start) * (i / steps)
        QApplication.sendEvent(canvas, QMouseEvent(
            QEvent.Type.MouseMove, p, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            modifiers))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifiers, end.toPoint())


@pytest.fixture
def canvas(app):
    from PyQt6.QtGui import QImage

    from montar.ui.editor.preview import PreviewCanvas

    c = PreviewCanvas()
    c.resize(640, 360)  # 1 pixel écran = 2 pixels de la toile
    c.set_canvas(1280, 720)
    image = QImage(640, 360, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkGreen)
    c.set_image(image)
    c.show()
    boxes = []
    c.boxChanged.connect(lambda mode, rect: boxes.append((mode, rect)))
    yield c, boxes
    c.close()


def test_corner_resize_keeps_opposite_corner(canvas):
    c, boxes = canvas
    c.set_selection(QRectF(200, 100, 400, 300))
    # coin bas-droit (600, 400) → (450, 400) dans la toile, soit (300, 200) → (225, 200) écran
    _canvas_drag(c, QPointF(300, 200), QPointF(225, 200),
                 Qt.KeyboardModifier.ControlModifier)
    mode, rect = boxes[-1]
    assert mode == "scale"
    assert (rect.left(), rect.top()) == pytest.approx((200, 100), abs=0.5)
    # proportions conservées
    assert rect.width() / rect.height() == pytest.approx(4 / 3, abs=1e-3)
    assert rect.right() < 600


def test_move_snaps_to_centre_with_guides(canvas):
    c, boxes = canvas
    c.set_selection(QRectF(100, 100, 400, 200))  # centre (300, 200)
    # centre amené près du centre de la toile (640, 360) à 6 px près
    _canvas_drag(c, QPointF(150, 100), QPointF(150 + 167, 100 + 77))
    mode, rect = boxes[-1]
    assert mode == "move" and (rect.center().x(), rect.center().y()) == (640, 360)
    # avec Ctrl, pas d'aimantation
    boxes.clear()
    c.set_selection(QRectF(100, 100, 400, 200))
    _canvas_drag(c, QPointF(150, 100), QPointF(150 + 167, 100 + 77),
                 Qt.KeyboardModifier.ControlModifier)
    assert boxes[-1][1].center() != QPointF(640, 360)


def test_rotated_selection_hit_test(canvas):
    c, _boxes = canvas
    c.set_selection(QRectF(440, 310, 400, 100), 90)  # bande verticale une fois tournée
    assert c._hit(QPointF(320, 180)) == ("move", -1)
    assert c._hit(QPointF(320 + 90, 180)) is None  # dans le cadre non tourné, pas tourné
    assert c._hit(QPointF(320, 180 + 90)) == ("move", -1)
    # coin haut-gauche tourné de 90° : en haut à droite
    assert c._hit(QPointF(320 + 25, 180 - 100)) == ("scale", 0)


@needs_ffmpeg
def test_preview_resize_matches_render(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4", "photo.png"])
    clip_media, photo = editor.project.media
    editor.add_to_timeline(clip_media)
    v2 = editor.controller.edit("piste", lambda t: t.add_track("video"))
    editor.timeline.view.add_media(photo, v2.id, 0)
    image_clip = editor.controller.selected_clip()
    image_clip.transform.crop_left = 0.2
    editor.player.seek(5)
    pump(200)
    start = editor._selection_rect()
    target = QRectF(start.left(), start.top(), start.width() * 0.5, start.height() * 0.5)
    editor._on_preview_box("scale", target)
    editor.preview.canvas.dragFinished.emit()
    got = editor._selection_rect()
    assert (got.left(), got.top(), got.width()) == pytest.approx(
        (target.left(), target.top(), target.width()), abs=0.5)


# --- 0.4.1 : timeline ----------------------------------------------------------------------


@needs_ffmpeg
def test_timeline_range_isolate_new_track_and_reorder(window, media_dir):
    editor = imported_editor(window, media_dir, ["red.mp4", "blue.mp4"])
    red, blue = editor.project.media
    editor.add_to_timeline(red)
    editor.add_to_timeline(blue)
    first, second = editor.project.clips
    view, panel = editor.timeline.view, editor.timeline
    view.snap = False
    vp = view.viewport()

    # Maj + glisser sur un clip : sélection d'une plage, puis « Isoler »
    r = view.clip_rect(first)
    y = int(r.center().y())
    a, b = QPoint(int(r.left() + r.width() * 0.25), y), QPoint(int(r.left() + r.width() * 0.75), y)
    drag(vp, a, b, Qt.KeyboardModifier.ShiftModifier)
    assert view.selection_range is not None and view.selection_range[0] == first.id
    assert first.start == 0  # le clip n'a pas bougé
    assert panel.isolate_button.isEnabled()
    _cid, start, end = view.selection_range
    panel.isolate_button.click()
    middle = editor.controller.selected_clip()
    assert (middle.start, middle.end) == (start, end)
    assert len(editor.project.clips) == 4 and view.selection_range is None

    # glisser un clip sur la limite haute de V1 : nouvelle piste vidéo au-dessus
    v1 = editor.controller.timeline.first_track("video")
    rect = view.clip_rect(second)
    row_top = view._row_rect(next(r for r in view.rows() if r.track.id == v1.id)).top()
    grab = QPoint(int(rect.center().x()), int(rect.center().y()))
    drag(vp, grab, QPoint(grab.x(), row_top))
    tracks = [t for t in editor.project.tracks if t.kind == "video"]
    assert len(tracks) == 2 and second.track_id == tracks[0].id != v1.id

    # glisser l'en-tête de la nouvelle piste sous V1 : l'ordre des pistes change
    new_row = next(r for r in view.rows() if r.track.id == second.track_id)
    v1_row = next(r for r in view.rows() if r.track.id == v1.id)
    start_pt = QPoint(30, view._row_rect(new_row).center().y())
    drag(vp, start_pt, QPoint(30, view._row_rect(v1_row).bottom() - 2))
    videos = [t.id for t in editor.project.tracks if t.kind == "video"]
    assert videos == [v1.id, second.track_id]
    editor.controller.undo()
    assert [t.id for t in editor.project.tracks if t.kind == "video"] == \
        [second.track_id, v1.id]


@needs_ffmpeg
def test_detached_clip_hides_waveform(window, media_dir, monkeypatch):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    view = editor.timeline.view
    painted = []
    monkeypatch.setattr(view, "_paint_waveform", lambda _p, c, *a: painted.append(c.id))
    view.viewport().repaint()
    assert clip.id in painted
    editor.controller.edit("détacher", lambda t: t.detach_audio(clip.id))
    painted.clear()
    view.viewport().repaint()
    assert clip.id not in painted and len(painted) == 1  # seul le clip audio détaché
    assert "mute" in view._badges(clip, editor.project.media[0])



@needs_ffmpeg
def test_timelapse_job_cancel_and_retry(window, media_dir, monkeypatch):
    import importlib
    import sys

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    core = importlib.import_module("montar_modules.timelapse.core")
    editor.controller.edit("tl", lambda t: core.apply(t, clip.id, 0, 40, core.Settings()))
    # ffmpeg remplacé par un processus qui ne répond plus
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    real = core.ffmpeg_command
    monkeypatch.setattr(core, "ffmpeg_command", lambda *a: (sleeper, 3))
    editor._reload_player()
    jobs = editor.modules.jobs
    assert wait_until(lambda: jobs.jobs and editor.busy.isVisibleTo(editor))
    # calcul en cours : le projet est protégé (fenêtre au-dessus, raccourcis coupés)
    assert editor.busy.geometry() == editor.rect()
    assert not any(s.isEnabled() for s in editor.findChildren(QShortcut))
    editor.busy.cancel_button.click()
    assert wait_until(lambda: not jobs.jobs, 5)
    assert editor.failed_box.isVisibleTo(editor) and "annulé" in editor.failed_label.text()
    assert not editor.busy.isVisibleTo(editor)
    assert all(s.isEnabled() for s in editor.findChildren(QShortcut))
    editor._reload_player()
    pump(200)
    assert not jobs.jobs  # une annulation n'est pas relancée d'elle-même
    monkeypatch.setattr(core, "ffmpeg_command", real)
    editor.retry_button.click()
    assert wait_until(lambda: not jobs.jobs and not jobs.failed, 30)
    assert not editor.failed_box.isVisibleTo(editor)
    segment = next(c for c in editor.project.clips if c.modules)
    assert editor.modules.hook(segment, editor.project.media[0]) is not None


# --- 0.5 : dossier de projet --------------------------------------------------------------


@needs_ffmpeg
def test_import_copies_media_into_project(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4", "photo.png"])
    folder = editor.project.path.parent / "medias"
    assert {Path(m.path) for m in editor.project.media} == {folder / "clip.mp4",
                                                              folder / "photo.png"}
    assert {m.original_path for m in editor.project.media} == {
        str(media_dir / "clip.mp4"), str(media_dir / "photo.png")}
    editor.import_files([str(media_dir / "clip.mp4")])  # déjà importé : ignoré
    pump(300)
    assert len(editor.project.media) == 2 and editor.pending_imports == 0
    assert not editor.jobs_box.isVisibleTo(editor)


@needs_ffmpeg
def test_old_project_moves_into_folder_and_gathers_media(window, isolated_home, media_dir):
    from montar.core.project import MediaItem
    from montar.media.probe import probe

    root = isolated_home / "Vidéos" / "Montar"
    root.mkdir(parents=True, exist_ok=True)
    old = Project("Ancien")
    item = probe(str(media_dir / "clip.mp4"))
    old.media.append(MediaItem(**{**item.__dict__}))
    old.save(root / "Ancien.montar")
    editor = window.open_project(root / "Ancien.montar")
    assert editor.project.path == root / "Ancien" / "Ancien.montar"
    assert not (root / "Ancien.montar").exists()
    copy = root / "Ancien" / "medias" / "clip.mp4"
    assert wait_until(lambda: editor.project.media[0].path == str(copy))
    assert editor.project.media[0].original_path == str(media_dir / "clip.mp4")
    assert copy.exists() and (media_dir / "clip.mp4").exists()  # l'original est intact
    assert editor.save()
    assert Project.load(editor.project.path).media[0].path == str(copy)


# --- J4 : export ------------------------------------------------------------------------


@needs_ffmpeg
def test_acceptance_scenario_export(window, media_dir, monkeypatch):
    """Cahier des charges §10 : projet 16:9 → 3 vidéos + 1 musique → couper, ordonner,
    2 transitions, un titre → Timelapse ×20 sur une portion → export MP4 1080p → relecture."""
    import importlib
    import json
    import shutil
    import subprocess

    from montar.ui.dialogs.export import ExportDialog

    editor = window.create_project(NewProjectParams("Recette", "16:9", "1080p", 25))
    editor.import_files([str(media_dir / n) for n in ("clip.mp4", "red.mp4", "blue.mp4",
                                                     "son.wav")])
    assert wait_until(lambda: editor.pending_imports == 0 and len(editor.project.media) == 4)
    by_name = {m.name: m for m in editor.project.media}
    for name in ("clip.mp4", "red.mp4", "blue.mp4", "son.wav"):
        editor.add_to_timeline(by_name[name])
    ctl = editor.controller
    clips = lambda: sorted((c for c in editor.project.clips  # noqa: E731
                            if ctl.timeline.track(c.track_id).kind == "video"),
                           key=lambda c: c.start)
    first, red, blue = clips()
    ctl.edit("couper", lambda t: t.split_at(25, first.id))
    ctl.edit("ordonner", lambda t: t.move_clip(blue.id, blue.track_id, 400))  # bleu à la fin
    ctl.edit("combler", lambda t: t.move_clip(blue.id, blue.track_id, red.end))
    a, b, c, d = clips()
    ctl.edit("t1", lambda t: t.add_transition(a.id, b.id, "dissolve"))
    ctl.edit("t2", lambda t: t.add_transition(c.id, d.id, "dip_black"))
    editor.add_text("title")
    core = importlib.import_module("montar_modules.timelapse.core")
    red_clip = next(x for x in clips() if x.media_id == by_name["red.mp4"].id)
    ctl.edit("tl", lambda t: core.apply(t, red_clip.id, red_clip.start + 5,
                                        red_clip.start + 45, core.Settings(factor=20)))
    editor._reload_player()
    assert wait_until(lambda: not editor.modules.jobs.jobs, 60)
    assert not editor.modules.pending_sources()

    monkeypatch.setattr(ExportDialog, "exec", lambda self: ExportDialog.DialogCode.Accepted)
    editor._notify_export = False
    results = []
    editor.exportFinished.connect(results.append)
    editor.open_export()
    assert editor._export_job is not None and not editor.export_button.isEnabled()
    assert editor.busy.isVisibleTo(editor) and "Recette.mp4" in editor.busy.title.text()
    assert wait_until(lambda: results, 180)
    assert results == [""]
    target = editor.project.path.parent / "exports" / "Recette.mp4"
    out = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height:format=duration",
                          "-of", "json", str(target)], capture_output=True, text=True,
                         check=True).stdout
    data = json.loads(out)
    streams = {s["codec_type"]: s for s in data["streams"]}
    assert (streams["video"]["codec_name"], streams["video"]["width"],
            streams["video"]["height"]) == ("h264", 1920, 1080)
    assert streams["audio"]["codec_name"] == "aac"
    length = editor.controller.timeline.length()
    assert float(data["format"]["duration"]) == pytest.approx(length / 25, abs=0.15)
    # relecture par un lecteur tiers : ffmpeg décode tout le fichier sans erreur
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-xerror", "-i", str(target),
                    "-f", "null", "-"], check=True, capture_output=True)
    assert editor.export_button.isEnabled() and not editor.busy.isVisibleTo(editor)


@needs_ffmpeg
def test_export_dialog_settings(window, media_dir):
    from montar.ui.dialogs.export import ExportDialog

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    dialog = ExportDialog(editor.project, 50, None, editor.project.path.parent / "exports")
    s = dialog.settings()
    assert (s.format, s.codec, s.width, s.height, s.fps, s.quality) == \
        ("mp4", "h264", 1280, 720, 25, "balanced")
    assert s.path.endswith("Montage.mp4") and not dialog.recommended.isHidden()
    dialog.video_formats.buttons["gif"].click()
    s = dialog.settings()
    assert s.format == "gif" and (s.width, s.height) == (854, 480) and s.path.endswith(".gif")
    assert not dialog.resolutions.buttons["1080p"].isEnabled()
    dialog.tabs.button("audio").click()
    s = dialog.settings()
    assert s.audio_only and s.format == "mp3" and s.path.endswith("Montage.mp3")
    assert dialog.summary_output.text() == "MP3" and dialog.summary_size.text().startswith("≈")
    dialog.quality.setValue(2)
    assert dialog.settings().quality == "max" and dialog.recommended.isHidden()


@needs_ffmpeg
def test_preferences_switches_apply_to_editor(window, media_dir, monkeypatch):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    view = editor.timeline.view
    painted = []
    monkeypatch.setattr(view, "_paint_waveform", lambda _p, c, *a: painted.append(c.id))
    prefs = window.preferences
    prefs.switches["video_waveforms"].click()  # désactivé
    assert window.settings.video_waveforms is False and view.video_waveforms is False
    view.viewport().repaint()
    assert painted == []
    prefs.switches["hardware_export"].click()
    assert editor._hardware is True
    prefs.switches["snap"].click()
    assert window.settings.snap is False
    assert editor.timeline.magnet.isChecked()  # projet ouvert : inchangé
    saved = Settings.load(window._settings_file)
    assert (saved.video_waveforms, saved.hardware_export, saved.snap) == (False, True, False)


# --- J5 ---------------------------------------------------------------------------------


@needs_ffmpeg
def test_media_panel_search_and_usage(window, media_dir):
    from montar.ui.thumbgrid import ROLE_USED

    editor = imported_editor(window, media_dir, ["clip.mp4", "photo.png", "son.wav"])
    clip, photo, son = editor.project.media
    panel = editor.media_panel
    editor.add_to_timeline(photo)
    item = panel._items
    assert item[photo.id].data(ROLE_USED) and not item[clip.id].data(ROLE_USED)
    shown = lambda: {m for m, it in item.items() if not it.isHidden()}  # noqa: E731
    panel.usage.button("used").click()
    assert shown() == {photo.id}
    panel.usage.button("unused").click()
    assert shown() == {clip.id, son.id}
    panel.search.setText("SON")
    assert shown() == {son.id}
    panel.usage.button("all").click()
    panel.search.clear()
    assert shown() == {clip.id, photo.id, son.id}
    editor.controller.undo()  # le clip de la photo disparaît : plus de pastille
    assert not item[photo.id].data(ROLE_USED)


@needs_ffmpeg
@pytest.mark.parametrize("mode", ["copy", "replace"])
def test_edit_media_copy_or_replace(window, media_dir, mode):
    from montar.media.edit import MediaEdit

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    media = editor.project.media[0]
    editor.add_to_timeline(media)
    clip = editor.project.clips[0]
    edit = MediaEdit(trim_in=0.0, trim_out=1.0, rotation=90)
    editor.start_media_edit(media, edit, mode)
    assert editor.busy.isVisibleTo(editor)
    assert wait_until(lambda: not editor._media_edits, 60)
    assert not editor.busy.isVisibleTo(editor)
    medias = editor.project.media
    if mode == "copy":
        assert len(medias) == 2 and medias[0].path == media.path
        new = medias[1]
        assert new.id != media.id and clip.media_id == media.id
    else:
        assert len(medias) == 1 and medias[0].id == media.id
        new = medias[0]
        assert clip.duration == 25  # le clip ne dépasse plus le média raccourci
        editor.controller.undo()
        assert editor.project.media[0].path == media.path  # l'original revient
    assert "(modifié)" in new.name and (new.width, new.height) == (360, 640)
    assert new.duration == pytest.approx(1.0, abs=0.1)


@needs_ffmpeg
def test_media_editor_dialog_preview(window, media_dir):
    from montar.engine import get_engine
    from montar.ui.dialogs.media_editor import MediaEditorDialog

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    dialog = MediaEditorDialog(editor.project.media[0], get_engine, True, editor)
    assert not dialog.replace_button.isEnabled()  # rien de modifié
    dialog.crop_rows["crop_left"].moved.emit(25)
    dialog._rotate(90)
    dialog.color_rows["saturation"].moved.emit(-100)
    dialog._render()
    assert dialog.replace_button.isEnabled()
    after = dialog.after.pixmap()
    assert after.height() > after.width()  # recadré puis tourné : image en hauteur
    assert dialog.edit.output_size(editor.project.media[0]) == (360, 480)
    dialog.position.setValue(10)
    dialog._mark("in")
    dialog.position.setValue(40)
    dialog._mark("out")
    assert dialog.edit.segment(editor.project.media[0]) == pytest.approx((0.4, 1.6))
    dialog.timelapse.setChecked(True)
    assert dialog.edit.timelapse["factor"] == 16


@needs_ffmpeg
def test_screen_recording_is_imported(window, media_dir, tmp_path, monkeypatch):
    import shutil as _shutil
    import subprocess as _subprocess

    if _shutil.which("Xvfb") is None:
        pytest.skip("Xvfb absent")
    from montar.media.recorder import RecordOptions

    xvfb = _subprocess.Popen(["Xvfb", ":96", "-screen", "0", "640x360x24"],
                             stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL)
    try:
        pump(1000)
        monkeypatch.setenv("DISPLAY", ":96")
        editor = imported_editor(window, media_dir, ["clip.mp4"])
        target = editor.project.media_dir / "Enregistrement test.mp4"
        results = []
        editor.recordingFinished.connect(results.append)
        editor.start_recording(RecordOptions(geometry=(0, 0, 640, 360), microphone=False),
                               target, countdown=0)
        assert editor._record_bar is not None and editor._recorder.running
        pump(2000)
        editor.stop_recording()
        assert results == [str(target)] and editor._record_bar is None
        assert wait_until(lambda: len(editor.project.media) == 2)
        recorded = editor.project.media[1]
        assert recorded.path == str(target) and recorded.kind == "video"
        assert (recorded.width, recorded.height) == (640, 360)
    finally:
        xvfb.terminate()
        xvfb.wait(5)


@needs_ffmpeg
def test_apply_effect_or_module(window, media_dir, monkeypatch):
    from montar.ui.dialogs.apply_effect import ROLE_ACTION, ApplyEffectDialog
    from montar.ui.editor.apply import actions_for

    editor = imported_editor(window, media_dir, ["clip.mp4", "son.wav"])
    clip_media, son = editor.project.media
    editor.add_to_timeline(clip_media)
    editor.add_to_timeline(son)
    video = next(c for c in editor.project.clips if c.media_id == clip_media.id)
    audio = next(c for c in editor.project.clips if c.media_id == son.id)
    kinds = {(a.kind, a.key) for a in actions_for(video, True, editor.modules)}
    assert {("tool", "timelapse.apply"), ("preset", "sepia"), ("effect", "blur")} <= kinds
    # pour un son : seulement les sous-titres automatiques
    assert [a.key for a in actions_for(audio, False, editor.modules)] == \
        ["transcription.sous_titres"]

    # fenêtre : recherche, catégories vides masquées
    dialog = ApplyEffectDialog(actions_for(video, True, editor.modules), "test")
    dialog.search.setText("délavées")  # cherche aussi dans les descriptions
    shown = [dialog.list.item(i) for i in range(dialog.list.count())
             if not dialog.list.item(i).isHidden()]
    assert [i.data(ROLE_ACTION).key for i in shown if i.data(ROLE_ACTION)] == ["fade"]
    assert len(shown) == 2 and dialog.apply_button.isEnabled()  # titre « FILTRES » + délavé

    # application sur une plage : le clip est coupé, seule la partie du milieu est filtrée
    editor.timeline.view.selection_range = (video.id, 10, 30)
    chosen = {}

    def fake_exec(self):
        self.select(*chosen["target"])
        self._accept()
        return ApplyEffectDialog.DialogCode.Accepted

    monkeypatch.setattr(ApplyEffectDialog, "exec", fake_exec)
    chosen["target"] = ("preset", "sepia")
    editor.open_apply(video.id)
    parts = sorted((c for c in editor.project.clips if c.media_id == clip_media.id),
                   key=lambda c: c.start)
    assert [(c.start, c.end, c.preset) for c in parts] == [(0, 10, ""), (10, 30, "sepia"),
                                                           (30, 50, "")]
    assert editor.side.currentWidget() is editor.filters_panel
    chosen["target"] = ("effect", "vignette")
    editor.open_apply(parts[0].id)
    assert parts[0].effects.vignette == 0.5 and editor.side.currentWidget() is \
        editor.effects_panel

    # outil d'un module (Timelapse) par la même fenêtre
    import importlib

    tl_dialog = importlib.import_module("montar_modules.timelapse.dialog")
    monkeypatch.setattr(tl_dialog.TimelapseDialog, "exec",
                        lambda self: tl_dialog.QDialog.DialogCode.Accepted)
    chosen["target"] = ("tool", "timelapse.apply")
    editor.open_apply(parts[2].id)
    assert any("timelapse" in c.modules for c in editor.project.clips)


def _unlink_released(editor, path: Path) -> None:
    """Supprime un média ; sous Windows, un fichier ouvert (lecteur de l'aperçu) ne peut pas
    l'être : l'aperçu le relâche d'abord."""
    def unlink() -> bool:
        try:
            path.unlink()
        except PermissionError:
            return False
        return True

    if not unlink():
        editor.player._close.emit()
        assert wait_until(unlink, 10)


@needs_ffmpeg
def test_save_as_and_relink(window, media_dir, tmp_path, monkeypatch):
    editor = imported_editor(window, media_dir, ["clip.mp4", "photo.png"])
    editor.add_to_timeline(editor.project.media[0])
    original = editor.project.path
    copy_editor = window.save_project_as("Montage bis")
    assert copy_editor is window.editor and copy_editor.project.name == "Montage bis"
    assert copy_editor.project.path.parent.name == "Montage bis"
    assert len(copy_editor.project.media) == 2 and len(copy_editor.project.clips) == 1
    assert all(str(copy_editor.project.path.parent) in m.path
               for m in copy_editor.project.media)
    assert original.exists()

    # médias supprimés du disque : bandeau, puis reliaison (avec recherche des autres)
    elsewhere = tmp_path / "ailleurs"
    elsewhere.mkdir()
    for m in copy_editor.project.media:
        _shutil = __import__("shutil")
        _shutil.copy(m.path, elsewhere / Path(m.path).name)
        _unlink_released(copy_editor, Path(m.path))
    copy_editor._update_used_media()
    panel = copy_editor.media_panel
    assert panel.missing_box.isVisibleTo(panel) and "2" in panel.missing_label.text()
    clip_media = copy_editor.project.media[0]
    copy_editor.relink(clip_media, str(elsewhere / "clip.mp4"))
    assert wait_until(lambda: not copy_editor.missing_media(), 30)
    assert all(m.exists and "medias" in m.path for m in copy_editor.project.media)
    copy_editor._update_used_media()
    assert not panel.missing_box.isVisibleTo(panel)

    # accueil : dupliquer un projet
    window.show_home()
    window.duplicate(original)
    assert "Montage (copie)" in [e.name for e in window.recent.entries()]


@needs_ffmpeg
def test_trash_and_library_pages(window, media_dir, monkeypatch):
    from montar.ui.home.library import LibraryDialog

    editor = imported_editor(window, media_dir, ["clip.mp4", "photo.png"])
    first = editor.project.path
    assert editor.save()
    other = window.create_project(NewProjectParams("Autre", "16:9", "720p", 25))
    # médiathèque : médias des autres projets, ajoutés (copiés) au projet ouvert
    items = other.library_provider()
    assert {i.media.name for i in items} == {"clip.mp4", "photo.png"}
    monkeypatch.setattr(LibraryDialog, "exec", lambda self: (
        self.library.grid.selectAll(), LibraryDialog.DialogCode.Accepted)[1])
    other.open_library()
    assert wait_until(lambda: len(other.project.media) == 2)
    assert all(str(other.project.path.parent) in m.path for m in other.project.media)
    window.show_home()
    window.shell.show_page("library")
    assert window.library_page.library.grid.count() == 2  # même fichier : une seule fois
    # corbeille : mettre, restaurer
    window.move_to_trash(first)
    assert not first.exists() and "Montage" not in [e.name for e in window.recent.entries()]
    window.shell.show_page("trash")
    assert window.trash_page.rows.count() == 1
    window.trash_page._restore(window.trash.entries()[0])
    assert first.exists() and "Montage" in [e.name for e in window.recent.entries()]


# --- J5-C : aperçu ---------------------------------------------------------------------------


def test_shuttle_speeds():
    from montar.ui.editor.player import shuttle

    assert shuttle(1, False, 1) == 1  # L à l'arrêt : lecture
    assert [shuttle(s, True, 1) for s in (1, 2, 4, 8)] == [2, 4, 8, 8]
    assert shuttle(4, True, -1) == -1  # changement de sens : ×1
    assert shuttle(-2, True, -1) == -4


@needs_ffmpeg
def test_preview_shuttle_zoom_volume_fullscreen(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    player, preview = editor.player, editor.preview
    assert wait_until(lambda: player.length == 50)

    # L, L : lecture avant ×2 ; K : pause ; J depuis la fin : lecture arrière
    QTest.keyClick(window, Qt.Key.Key_L)
    assert wait_until(lambda: player.playing)
    QTest.keyClick(window, Qt.Key.Key_L)
    assert wait_until(lambda: player.speed == 2)
    assert preview.speed_label.text() == "▶▶ ×2"
    QTest.keyClick(window, Qt.Key.Key_K)
    assert wait_until(lambda: not player.playing and player.speed == 1)
    player.seek(40)
    assert wait_until(lambda: player.position == 40)
    QTest.keyClick(window, Qt.Key.Key_J)
    assert wait_until(lambda: player.speed == -1)
    assert wait_until(lambda: not player.playing)  # arrivé au début
    assert player.position == 0

    # zoom 200 % : le cadre dépasse la zone et se déplace à la molette
    canvas = preview.canvas
    preview.set_zoom(2.0)
    assert preview.zoom_button.text() == "200 %"
    big = canvas.frame_rect()
    assert big.width() > canvas.width()
    canvas.pan_by(-10_000, 0)
    assert canvas.frame_rect().right() == pytest.approx(canvas.width(), abs=0.5)
    preview.set_zoom(None)
    assert canvas.frame_rect().width() <= canvas.width() + 0.5

    # volume : mémorisé dans les préférences
    preview.volume_slider.setValue(40)
    assert player.volume == pytest.approx(0.4)
    assert window.settings.preview_volume == pytest.approx(0.4)
    preview.mute_action.setChecked(True)
    assert player.volume == 0.0 and window.settings.preview_volume == pytest.approx(0.4)

    # plein écran, refermé par Échap
    preview.toggle_fullscreen()
    full = preview.fullscreen
    assert full is not None and full.isVisible()
    full.activateWindow()
    QTest.qWaitForWindowActive(full)
    QTest.keyClick(full, Qt.Key.Key_Escape)
    assert wait_until(lambda: preview.fullscreen is None)


# --- J5-D : sauvegarde et stockage --------------------------------------------------------------


def test_manual_save_asks_before_closing(window, monkeypatch):
    editor = window.create_project(NewProjectParams("Manuel", "16:9", "720p", 25))
    window.settings.autosave = False
    window.settings.backup_minutes = 5
    editor.apply_preferences(window.settings)
    assert editor.backup_every == 300
    editor.controller.edit("piste", lambda t: t.add_track("video"))
    assert editor.dirty and not editor._save_timer.isActive()
    saved_tracks = len(Project.load(editor.project.path).tracks)

    answers = [QMessageBox.StandardButton.Cancel]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answers.pop()))
    window.show_home()
    assert window.editor is editor  # annulé : le projet reste ouvert
    answers.append(QMessageBox.StandardButton.Discard)
    window.show_home()
    assert window.editor is None
    assert len(Project.load(editor.project.path).tracks) == saved_tracks


def test_preferences_storage_card(window, isolated_home, monkeypatch):
    prefs = window.preferences
    thumbs = window.cache / "thumbnails"
    thumbs.mkdir(parents=True, exist_ok=True)
    (thumbs / "x.jpg").write_bytes(b"0" * 2_000_000)
    prefs.refresh_storage()
    assert "2 Mo" in prefs._cache_row.subtitle_label.text()
    assert prefs.clear_cache_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    prefs.clear_cache_button.click()
    assert not thumbs.exists() and not prefs.clear_cache_button.isEnabled()
    prefs.backup_interval.button("10").click()
    assert window.settings.backup_minutes == 10
    prefs.autosave.click()
    assert window.settings.autosave is False


# --- J5-E : marqueurs et voix off ---------------------------------------------------------------


@needs_ffmpeg
def test_markers_in_timeline(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    view = editor.timeline.view
    assert wait_until(lambda: editor.player.length == 50)
    editor.player.seek(20)
    assert wait_until(lambda: view.playhead == 20)
    QTest.keyClick(window, Qt.Key.Key_M)
    assert [m.frame for m in editor.project.markers] == [20]
    editor.player.seek(0)
    assert wait_until(lambda: view.playhead == 0)
    QTest.keyClick(window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert wait_until(lambda: view.playhead == 20)

    # glisser le fanion dans la règle
    view.snap = False
    vp = view.viewport()
    x0 = int(view.frame_to_x(20))
    assert view.marker_at(QPoint(x0, 20)) is not None
    drag(vp, QPoint(x0, 20), QPoint(int(view.frame_to_x(35)), 20))
    assert editor.project.markers[0].frame == 35
    editor.controller.undo()
    assert editor.project.markers[0].frame == 20


class _FakeVoice:
    """Enregistreur de test : un vrai fichier WAV, sans micro."""

    def __init__(self, device, target):
        self.target, self.error, self.started = target, "", 0.0
        self.running = False

    def start(self):
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=300:duration=2", "-ac", "1", "-ar", "48000",
                        str(self.target)], check=True)
        self.running, self.started = True, time.monotonic()

    @property
    def elapsed(self):
        return time.monotonic() - self.started

    def captured(self):
        return 0.2

    def stop(self):
        self.running = False
        return True


@needs_ffmpeg
def test_voice_over_recording(window, media_dir, monkeypatch):
    import montar.ui.dialogs.voice_over as vo

    monkeypatch.setattr(vo, "VoiceRecorder", _FakeVoice)
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    assert wait_until(lambda: editor.player.length == 50)
    editor.player.seek(10)
    assert wait_until(lambda: editor.timeline.view.playhead == 10)
    dialog = editor.open_voice_over(countdown=0)
    dialog.record_button.click()
    assert wait_until(lambda: dialog.recording and editor.player.playing)
    dialog.record_button.click()  # Arrêter
    assert wait_until(lambda: any(c.track_id != editor.project.clips[0].track_id
                                  for c in editor.project.clips))
    voice = editor.project.clips[-1]
    track = editor.controller.timeline.track(voice.track_id)
    assert track.name == "Voix off"
    assert (voice.start, voice.source_in, voice.duration) == (10, 5, 45)
    assert not editor.player.playing
    assert Path(editor.project.find_media(voice.media_id).path).parent == editor.project.media_dir


# --- J5-F : types de modules ---------------------------------------------------------------------


@needs_ffmpeg
def test_module_types_in_editor(window, media_dir):
    from montar.ui.dialogs.export import ExportDialog

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    editor.controller.select(clip.id)

    # effet audio : appliqué depuis le panneau Modules, réglé dans le panneau Effets
    entry = next(e for e in editor.modules_panel.visible_entries()
                 if e.item.id == "essentiels.egaliseur")
    editor.use_module_entry(entry)
    panel = editor.effects_panel
    control = next(c for e, c, audio in panel._module_controls
                   if audio and e.id == "essentiels.egaliseur" and c.param.key == "graves")
    assert control.widget.isEnabled()
    control.widget.slider.setValue(1000)
    assert abs(clip.modules["essentiels.egaliseur"]["graves"] - 12) < 0.01
    assert editor.modules.hook(clip, editor.project.media[0]).audio_filters

    # fenêtre « Appliquer… » : les effets audio y figurent
    from montar.ui.editor.apply import actions_for
    kinds = {a.kind for a in actions_for(clip, True, editor.modules, True)}
    assert "audio_effect" in kinds

    # transitions des modules dans le panneau
    assert editor.transitions_panel._module_grid.count() == 3

    # générateur : image créée dans medias/ puis importée
    _m, gen = next((m, g) for m, g in editor.module_manager.generators()
                   if g.id == "essentiels.fond")
    path = editor.generate("essentiels", gen, {"couleur": "#123456"})
    assert path.parent == editor.project.media_dir
    assert wait_until(lambda: len(editor.project.media) == 2)
    assert editor.project.media[1].kind == "image"

    # format d'export d'un module
    dialog = ExportDialog(editor.project, 50, None, Path("/tmp"), parent=editor,
                          extra_formats=[f for _m, f in editor.module_manager.export_formats()])
    dialog.video_formats.buttons["essentiels.mkv"].click()
    assert dialog.target().suffix == ".mkv" and dialog.settings().format == "essentiels.mkv"
    assert "MKV" in dialog.summary_output.text()
    dialog.close()


# --- J5-G : interface en anglais -----------------------------------------------------------------


def test_english_interface(app, isolated_home, monkeypatch):
    from montar import i18n
    from montar.ui.main_window import MainWindow

    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    i18n.set_language("en")
    try:
        w = MainWindow(Settings(language="en"), isolated_home / ".config/montar/settings.json")
        w.show()
        editor = w.create_project(NewProjectParams("Movie", "16:9", "720p", 25))
        assert editor.export_button.text() == "Export"
        assert [t.name for t in editor.project.tracks] == ["Video", "Music"]
        assert editor.preview.zoom_button.text() == "Fit"
        w.show_home()
        w.close()
    finally:
        i18n.set_language("fr")


def test_language_preference(window):
    prefs = window.preferences
    prefs.language.setCurrentIndex(prefs.language.findData("en"))
    assert window.settings.language == "en"



# --- J6 : panneau Modules et effets intégrés -------------------------------------------------


@needs_ffmpeg
def test_modules_panel(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    panel = editor.modules_panel
    editor.show_side("modules")
    names = {e.item.id for e in panel.visible_entries()}
    assert {"timelapse.apply", "effets.vhs", "effets.zoom_lent", "essentiels.echo",
            "essentiels.cercle", "essentiels.fond", "essentiels.mkv"} <= names
    panel.search.setText("zoom")
    assert {e.item.id for e in panel.visible_entries()} == {
        "effets.zoom_lent", "effets.zoom_rapide", "effets.dezoom_lent", "effets.dezoom_rapide"}
    panel.search.clear()

    # appliquer un effet vidéo au clip sélectionné ; il apparaît dans le panneau Effets
    editor.controller.select(clip.id)
    vhs = next(e for e in panel.visible_entries() if e.item.id == "effets.vhs")
    editor.use_module_entry(vhs)
    assert "effets.vhs" in clip.modules
    effects = editor.effects_panel
    assert [e.id for e, _c, _a in effects._module_controls][:1] == ["effets.vhs"]
    assert editor.side.currentWidget() is effects
    editor.controller.undo()  # l'historique remplace les objets : relire le clip
    assert "effets.vhs" not in editor.project.clips[0].modules
    assert not effects._module_controls


def test_graphics_panel(window):
    from PyQt6.QtGui import QImage

    editor = window.create_project(NewProjectParams("Graphiques", "16:9", "720p", 25))
    panel = editor.graphics_panel
    graphics = {g.id: g for _t, g in panel.tiles()}
    assert len(graphics) >= 35 and "graphismes.wow" in graphics
    panel.search.setText("cœur")
    assert {g.id for _t, g in panel.tiles()} == {"graphismes.coeur", "graphismes.coeur_arc"}
    panel.search.clear()

    path = editor.insert_graphic("graphismes", graphics["graphismes.wow"])
    assert wait_until(lambda: len(editor.project.clips) == 1)
    im = QImage(str(path))
    assert im.hasAlphaChannel() and im.width() == round(720 * 0.45)
    assert im.pixelColor(0, 0).alpha() == 0  # fond transparent
    clip = editor.project.clips[0]
    assert clip.transform.scale < 1  # taille prévue, pas ajustée à la toile
    # même élément une seconde fois : le média est réutilisé, une autre piste au besoin
    editor.insert_graphic("graphismes", graphics["graphismes.wow"])
    assert len(editor.project.media) == 1 and len(editor.project.clips) == 2
    # arrière-plan plein cadre, sous les autres pistes
    editor.insert_graphic("graphismes", graphics["graphismes.coucher"])
    assert wait_until(lambda: len(editor.project.clips) == 3)
    background = editor.project.clips[-1]
    video = [t for t in editor.project.tracks if t.kind == "video"]
    assert background.track_id == video[-1].id
    im = QImage(editor.project.find_media(background.media_id).path)
    assert (im.width(), im.height()) == (1280, 720)


def test_extensions_install_folder_and_reload(window, tmp_path):
    from montar.plugins.devtools import new_module
    from montar.ui.home.extensions import provides

    card = window.preferences.extensions
    folder = new_module(tmp_path / "dev", kinds=["effet-video", "graphisme"])
    card.install_folder(str(folder), link=True)
    info = window.modules.modules["dev"]
    assert info.active and info.path.is_symlink()
    assert provides(info) == "Apporte : 1 effets vidéo, 1 graphismes"
    code = (folder / "__init__.py").read_text().replace('"Négatif"', '"Inversé"')
    (folder / "__init__.py").write_text(code)
    card.reload()
    assert window.modules.modules["dev"].loaded.effects[0].name == "Inversé"
    assert [a.text() for a in card.install_button.menu().actions()][1:] == [
        "Depuis un dossier…", "Lier un dossier (développement)…"]


# --- P2-1 -------------------------------------------------------------------------------------


@needs_ffmpeg
def test_freeze_frame_safe_zone_and_lock(window, media_dir):
    editor = imported_editor(window, media_dir, ["redblue.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    assert wait_until(lambda: editor.player.length == 50)
    editor.player.seek(30)
    assert wait_until(lambda: editor.timeline.view.playhead == 30)
    editor.controller.select(clip.id)
    editor.inspector.freeze_button.click()
    assert wait_until(lambda: len(editor.project.clips) == 3)
    still = editor.controller.selected_clip()
    media = editor.project.find_media(still.media_id)
    assert media.kind == "image" and (still.start, still.duration) == (30, 50)
    from PyQt6.QtGui import QImage
    image = QImage(media.path)
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.blue() > color.red()  # à 1,2 s la vidéo est bleue
    assert sorted(c.start for c in editor.project.clips) == [0, 30, 80]

    # lecture inversée depuis l'inspecteur
    editor.controller.select(editor.project.clips[0].id)
    editor.inspector.reverse_check.setChecked(True)
    assert editor.project.clips[0].reverse

    # zone de sécurité mémorisée
    editor.preview.safe_button.click()
    assert editor.preview.canvas.safe_zone and window.settings.safe_zone

    # verrou : clic sur le cadenas de l'en-tête, puis plus de modification possible
    view = editor.timeline.view
    row = next(r for r in view.rows() if r.track.id == still.track_id)
    lock = dict(view._header_buttons(row))["lock"]
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=lock.center())
    assert editor.controller.timeline.track(still.track_id).locked
    count = len(editor.project.clips)
    editor.controller.select(still.id)
    editor.timeline.delete()
    assert len(editor.project.clips) == count


# --- P2-2 -------------------------------------------------------------------------------------


@needs_ffmpeg
def test_export_frame_range_accent_and_trash_days(window, media_dir, tmp_path):
    from PyQt6.QtGui import QImage

    from montar.ui.dialogs.export import ExportDialog
    from montar.ui.theme import theme

    editor = imported_editor(window, media_dir, ["redblue.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    editor._notify_export = False
    dialog = ExportDialog(editor.project, 50, None, tmp_path, parent=editor,
                          selection=(10, 30), playhead=40)
    dialog.part.buttons["range"].click()
    s = dialog.settings()
    assert (s.range_start, s.range_end) == (10, 30)
    dialog.tabs.set_current("image")
    dialog._tab_changed("image")
    s = dialog.settings()
    assert s.format == "png" and s.range_start == 40 and dialog.target().suffix == ".png"
    dialog.close()
    assert editor.export_frame(s)
    image = QImage(s.path)
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert (image.width(), image.height()) == (s.width, s.height) and color.blue() > 200

    prefs = window.preferences
    prefs.accent_buttons["#3A8C86"].click()
    assert window.settings.accent == "#3A8C86" and theme().palette.forest == "#3A8C86"
    prefs.accent_buttons["#2F7A56"].click()
    prefs.trash_days.button("90").click()
    assert window.settings.trash_days == 90 and window.trash_page.days == 90


# --- P2-3 -------------------------------------------------------------------------------------


@needs_ffmpeg
def test_hover_preview_notifications_typewriter(window, media_dir, tmp_path):
    from montar.ui.thumbgrid import ROLE_PAYLOAD

    editor = imported_editor(window, media_dir, ["redblue.mp4"])
    grid = editor.media_panel.grid
    item = grid.item(0)
    original = item.data(Qt.ItemDataRole.DecorationRole)
    rect = grid.visualItemRect(item)

    def hover(x):
        pos = QPointF(rect.left() + x, rect.center().y())
        QApplication.sendEvent(grid.viewport(), QMouseEvent(
            QEvent.Type.MouseMove, pos, pos, Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    hover(2)
    assert wait_until(lambda: grid._strips.get(item.data(ROLE_PAYLOAD).path) is not None)
    hover(2)
    first = item.data(Qt.ItemDataRole.DecorationRole).toImage()
    hover(rect.width() - 2)
    last = item.data(Qt.ItemDataRole.DecorationRole).toImage()
    c1, c2 = (im.pixelColor(im.width() // 2, im.height() // 2) for im in (first, last))
    assert c1.red() > c1.blue() and c2.blue() > c2.red()  # début rouge, fin bleue
    grid.leaveEvent(QEvent(QEvent.Type.Leave))
    assert item.data(Qt.ItemDataRole.DecorationRole).cacheKey() == original.cacheKey()

    # notification d'export, cloche de l'en-tête
    editor.add_to_timeline(editor.project.media[0])
    editor._notify_export = False
    from montar.engine.export import ExportSettings
    before = window.notifications.unread
    assert editor.export_frame(ExportSettings(str(tmp_path / "i.png"), "png", "", 64, 36, 25,
                                              range_start=5, range_end=6))
    assert window.notifications.unread == before + 1
    assert editor.bell.text() == str(window.notifications.unread)
    assert "i.png" in [a.text() for a in editor.bell.build_menu().actions()][0]

    # machine à écrire proposée en animation d'entrée
    assert editor.inspector._anims["animation_in"].button("typewriter") is not None


# --- P2-4 : modèles ---------------------------------------------------------------------------


@needs_ffmpeg
def test_templates(window, media_dir, isolated_home):
    from montar.ui.home.templates import builtin_templates

    window.shell.show_page("templates")
    page = window.templates_page
    assert page.grid.count() == 3
    assert all(page.grid.item(i).data(Qt.ItemDataRole.DecorationRole) is not None
               for i in range(3))
    for template in builtin_templates():
        editor = window.use_template(template, f"Projet {template.key}")
        assert editor is not None and len(editor.project.clips) == 2
        tracks = {c.track_id for c in editor.project.clips}
        assert len(tracks) == 2  # deux textes simultanés, chacun sur sa piste
        assert editor.project.aspect == template.aspect
        assert wait_until(lambda e=editor: e.player.length > 0)
        window.show_home()

    # projet de l'utilisateur → modèle (avec ses médias) → nouveau projet
    editor = imported_editor(window, media_dir, ["red.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    assert window.save_template("Mon modèle") is not None
    window.show_home()
    window.refresh_templates()
    assert page.grid.count() == 4
    from montar.ui.thumbgrid import ROLE_PAYLOAD
    mine = page.grid.item(3).data(ROLE_PAYLOAD)
    assert mine.name == "Mon modèle" and not mine.builtin
    editor = window.use_template(mine, "Depuis le modèle")
    media = editor.project.media[0]
    assert Path(media.path).exists() and Path(media.path).is_relative_to(
        editor.project.path.parent)
    window.show_home()
    window.delete_template(mine, confirm=False)
    assert page.grid.count() == 3


@needs_ffmpeg
def test_keyframes_from_inspector(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    editor.controller.select(clip.id)
    inspector = editor.inspector
    x_row = inspector._animated[0]
    assert inspector.key_hint.isVisibleTo(inspector) and \
        not inspector.remove_key_button.isEnabled()

    editor.timeline.set_playhead(0)
    inspector.add_key_button.click()
    editor.timeline.set_playhead(40)
    x_row.moved.emit(50)  # clip animé : la valeur devient une clé à la tête de lecture
    clip = editor.project.clips[0]
    assert keyframes.key_frames(clip) == [0, 40]
    assert clip.transform.x == 0.0
    assert inspector.key_chips.count() == 2 and inspector.remove_key_button.isEnabled()

    editor.timeline.set_playhead(20)
    inspector.refresh_playhead()
    assert abs(x_row.getter(clip) - 25) < 1e-6 and not inspector.remove_key_button.isEnabled()
    rect = editor._selection_rect()
    assert rect is not None and rect.center().x() > editor.project.canvas_size[0] / 2

    seeks = []
    inspector.seekRequested.connect(seeks.append)
    inspector.key_chips.itemAt(1).widget().click()
    assert seeks == [clip.start + 40]

    editor.timeline.set_playhead(40)
    inspector.refresh_playhead()
    inspector.remove_key_button.click()
    assert keyframes.key_frames(editor.project.clips[0]) == [0]
    editor.controller.undo()
    assert keyframes.key_frames(editor.project.clips[0]) == [0, 40]


# --- P2-6 -------------------------------------------------------------------------------------


@needs_ffmpeg
def test_subtitles_panel_and_export(window, media_dir, tmp_path, monkeypatch):
    from PyQt6.QtGui import QImage

    from montar.engine.export import ExportSettings
    from montar.ui.dialogs.export import ExportDialog
    from montar.ui.editor.subtitles_panel import SubtitlesPanel

    editor = imported_editor(window, media_dir, ["redblue.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    editor._notify_export = False
    panel = editor.subtitles_panel
    assert editor.rail_buttons["subtitles"].isEnabled()
    editor.show_side("subtitles")
    assert panel.empty.isVisibleTo(panel) and not panel.editor.isEnabled()

    editor.timeline.set_playhead(10)
    panel.add_button.click()
    sub = editor.project.subtitles[0]
    assert (sub.start, sub.end) == (10, 10 + 3 * editor.project.fps)
    panel.editor.setPlainText("Bonjour")
    panel.editor.setPlainText("Bonjour à tous")
    assert editor.project.subtitles[0].text == "Bonjour à tous"
    assert editor.controller.history.undo_label() == "Texte du sous-titre"
    editor.timeline.set_playhead(40)
    panel.end_button.click()
    assert editor.project.subtitles[0].end == 40
    assert panel.list.count() == 1 and "Bonjour" in panel.list.item(0).text()

    # export SRT puis réimport (ajout)
    path = tmp_path / "s.srt"
    assert panel.export_file(path)
    assert "Bonjour à tous" in path.read_text(encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    assert panel.import_file(path)
    assert len(editor.project.subtitles) == 2

    # incrustés : le bandeau sombre apparaît en bas de l'image exportée
    def frame(mode):
        s = ExportSettings(str(tmp_path / f"{mode}.png"), "png", "", 320, 180, 25,
                           range_start=20, range_end=21, subtitles=mode)
        assert editor.export_frame(s)
        image = QImage(s.path)
        return image.pixelColor(160, int(180 * 0.88)).name()
    burnt, plain = frame("burn"), frame("none")
    assert burnt != plain

    # dialogue d'export : choix proposé seulement s'il y a des sous-titres
    dialog = ExportDialog(editor.project, 50, None, tmp_path, parent=editor)
    assert dialog.subtitles_box.isVisibleTo(dialog)
    dialog.subtitles.buttons["file"].click()
    assert dialog.settings().subtitles == "file"
    dialog.close()
    video = dataclasses.replace(dialog.settings(), path=str(tmp_path / "v.mp4"))
    editor.start_export(video)
    editor._export_job.cancel()
    editor._export_job.wait(10)
    assert "Bonjour" in (tmp_path / "v.srt").read_text(encoding="utf-8")

    panel.list.setCurrentRow(0)
    panel.delete_button.click()
    assert len(editor.project.subtitles) == 1
    panel.size.moved.emit(60)
    panel.position.changed.emit("top")
    assert editor.project.subtitle_style.size == 60 and editor.project.subtitle_style.y < 0.5
    assert isinstance(panel, SubtitlesPanel)


# --- P2-7 -------------------------------------------------------------------------------------


@needs_ffmpeg
def test_custom_shortcuts(window, media_dir):
    from PyQt6.QtGui import QKeySequence

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    card = window.preferences.shortcuts
    card.edits["split"].setKeySequence(QKeySequence("X"))
    card._edited("split")
    assert window.settings.shortcuts == {"split": "X"}
    keys = {sc.key().toString() for sc in editor._shortcuts}
    assert "X" in keys and "S" not in keys
    card.set_key("marker", "X")
    assert card.conflict.isVisibleTo(card) and "X" in card.conflict.text()
    card.edits["marker"].clear()  # bouton d'effacement : raccourci désactivé
    assert window.settings.shortcuts["marker"] == ""
    assert not card.conflict.isVisibleTo(card)
    card.set_key("play", "P")
    assert "P" in {sc.key().toString() for sc in editor.preview._shortcuts}
    card.reset_all.click()
    assert window.settings.shortcuts == {}
    assert "S" in {sc.key().toString() for sc in editor._shortcuts}
    assert card.edits["split"].keySequence().toString() == "S"


@needs_ffmpeg
def test_proxy_used_by_preview(window, tmp_path):
    import subprocess

    from montar.media.proxies import existing_proxy

    folder = tmp_path / "uhd"
    folder.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=3840x2160:rate=25:duration=0.4", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(folder / "uhd.mp4")],
                   check=True)
    editor = imported_editor(window, folder, ["uhd.mp4"])
    media = editor.project.media[0]
    assert wait_until(lambda: editor.importer.pending_proxies == 0, 60)
    proxy = existing_proxy(editor._cache, media)
    assert proxy is not None
    loaded = []
    editor.player.load = loaded.append
    editor.add_to_timeline(media)
    assert wait_until(lambda: loaded)
    assert loaded[-1].tracks[0].clips[0].path == str(proxy)
    window.preferences.switches["proxies"].setChecked(False)  # désactivés : l'original
    assert wait_until(lambda: loaded[-1].tracks[0].clips[0].path == media.path)


# --- retours 1.2 ------------------------------------------------------------------------------


@needs_ffmpeg
def test_preview_drag_keeps_background_and_defers_render(window, media_dir):
    editor = imported_editor(window, media_dir, ["red.mp4", "photo.png"])
    red, photo = editor.project.media
    editor.add_to_timeline(red)
    track = editor.controller.edit("piste", lambda t: t.add_track("video")).id
    overlay = editor.controller.edit("image", lambda t: t.add_clip(photo, track, 0, 25))
    editor.controller.edit_clip("échelle", overlay.id, lambda c: setattr(c.transform, "scale", 0.4))
    editor.controller.select(overlay.id)
    frames = []
    editor.player.frameReady.connect(lambda img, f: frames.append(f))
    editor._reload_player()
    editor.player.seek(5)
    assert wait_until(lambda: 5 in frames and editor.preview.canvas.image is not None)
    canvas = editor.preview.canvas
    box = canvas._to_widget(canvas.selection)
    start = box.center().toPoint()
    loads = []
    real_load = editor.player.load
    editor.player.load = lambda spec: (loads.append(spec), real_load(spec))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    drag = canvas._drag
    assert drag is not None and drag.background is not None and drag.ghost is not None
    # le fond est rendu sans l'image déplacée : la vidéo rouge au centre du cadre
    bg = drag.background
    color = bg.pixelColor(bg.width() // 2, bg.height() // 2)
    assert color.red() > 200 and color.green() < 60 and color.blue() < 60
    for dx in (20, 40, 60):
        point = QPointF(start.x() + dx, start.y())
        QApplication.sendEvent(canvas, QMouseEvent(
            QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier))
    pump(400)
    assert editor.project.clips[1].transform.x > 0  # le projet suit (inspecteur à jour)
    assert not loads  # mais l'aperçu n'est pas reconstruit pendant le glisser
    x_row = editor.inspector._animated[0]
    assert x_row.getter(editor.project.clips[1]) == x_row._value  # curseur à jour
    assert editor.controller._live_pending and editor.controller.live
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QPoint(start.x() + 60, start.y()))
    assert not editor.controller.live and not editor.controller._live_pending
    assert wait_until(lambda: loads)
    editor.player.load = real_load


@needs_ffmpeg
def test_timeline_maximize_and_detach(window, media_dir):
    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    panel = editor.timeline
    panel.maximize_button.click()
    assert editor._top.isHidden() and panel.maximize_button.isChecked()
    panel.maximize_button.click()
    assert not editor._top.isHidden()

    panel.maximize_button.click()  # détacher depuis l'état agrandi : l'aperçu revient
    panel.detach_button.click()
    win = editor._timeline_window
    assert win is not None and panel.window() is win and win.isVisible()
    assert not editor._top.isHidden() and editor._detached_hint.isVisibleTo(editor)
    # les raccourcis marchent aussi dans la fenêtre séparée
    hosts = {sc.parent() for sc in editor._shortcuts}
    assert win in hosts and editor in hosts
    split = [sc for sc in editor._shortcuts if sc.parent() is win
             and sc.key().toString() == "S"]
    editor.timeline.set_playhead(20)
    editor.controller.select(editor.project.clips[0].id)
    split[0].activated.emit()
    assert len(editor.project.clips) == 2
    assert any(sc.parent() is win and sc.key().toString() == "Space" for sc in editor._shortcuts)

    win.close()  # fermer la fenêtre remet la timeline en place
    pump(50)
    assert editor._timeline_window is None and panel.window() is window
    assert not panel.detach_button.isChecked() and not editor._detached_hint.isVisibleTo(editor)
    assert all(sc.parent() is editor for sc in editor._shortcuts)

    panel.detach_button.click()
    assert editor.close_project() is not None and editor._timeline_window is None


@needs_ffmpeg
def test_sound_settings_in_inspector(window, media_dir):
    editor = imported_editor(window, media_dir, ["son.wav", "clip.mp4"])
    song, video = editor.project.media
    clip = editor.add_to_timeline(song) or editor.project.clips[-1]
    editor.controller.select(clip.id)
    inspector = editor.inspector
    assert not inspector.advanced_sound.isVisibleTo(inspector)
    inspector.advanced_button.click()
    assert inspector.advanced_sound.isVisibleTo(inspector)
    rows = {r.findChild(QLabel).text(): r for r in inspector._sliders
            if r.findChild(QLabel) is not None}
    rows["Aigus"].moved.emit(6)
    rows["Coupe-haut"].moved.emit(20000)  # tout à droite : aucun filtre
    rows["Réduction de bruit"].moved.emit(50)
    duck = next(b for b, p in inspector._audio_checks if p == "duck")
    duck.click()
    clip = editor.project.clips[-1]
    assert clip.audio.treble == 6 and clip.audio.lowpass == 0 and clip.audio.denoise == 0.5
    assert clip.audio.duck and inspector.duck_row.isEnabled()
    editor.controller.undo()
    assert not editor.project.clips[-1].audio.duck

    # piste de voix : la voix off en crée une, le menu de piste permet d'en marquer une
    track = editor.controller.timeline.track(clip.track_id)
    assert not track.voice
    editor.controller.edit("voix", lambda t: setattr(t.track(track.id), "voice", True))
    assert editor.controller.timeline.track(track.id).voice


@needs_ffmpeg
def test_brand_kit_in_editor(window, media_dir, tmp_path):
    from PyQt6.QtGui import QColor, QImage

    logo = tmp_path / "logo.png"
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("#FF8800"))
    image.save(str(logo))
    page = window.brand_page
    assert page.add_logo(logo) and page.add_color("#123456")
    assert window.shell is not None and page.logos.count() == 1

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    panel = editor.graphics_panel
    assert panel._brand.isVisibleTo(panel) and len(panel._logo_tiles) == 1
    assert "#123456" in editor.inspector.text_color._buttons
    panel._logo_tiles[0][0].click()
    assert wait_until(lambda: any(m.name.startswith("Logo") for m in editor.project.media))
    clip = editor.project.clips[-1]
    w, _h = editor.project.canvas_size
    assert clip.transform.x > 0.25 and clip.transform.y < -0.25  # en haut à droite
    rect = editor._selection_rect() if editor.controller.selected == clip.id else None
    assert rect is None or abs(rect.width() - 0.18 * w) < 2

    page.remove_color("#123456")  # le kit change : l'éditeur suit
    assert "#123456" not in editor.inspector.text_color._buttons


@needs_ffmpeg
def test_auto_subtitles_tool(window, media_dir, monkeypatch):
    import sys

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    module_id, tool = next((m, t) for m, t in editor.modules.tools_for(clip)
                           if t.id == "transcription.sous_titres")
    package = sys.modules[type(tool).__module__]  # module chargé par montar
    core = package.core

    class Fake(core.Backend):
        name = "faux"

        def available(self):
            return True

        def transcribe(self, wav, model, language, progress, cancelled):
            return [core.Segment(0.1, 0.9, "Bonjour tout le monde")]

    monkeypatch.setattr(core, "BACKENDS", [Fake()])
    monkeypatch.setattr(package, "_ask", lambda parent: ("base", "fr", True))
    editor.subtitles_panel.auto_button.click()  # aucun clip sélectionné : le premier parlant
    assert wait_until(lambda: editor.project.subtitles, 30)
    sub = editor.project.subtitles[0]
    assert sub.text == "Bonjour tout le monde" and sub.start == 2
    assert editor.project.subtitles_shown
    editor.controller.undo()
    assert not editor.project.subtitles


def test_module_catalogue_card(window, monkeypatch, tmp_path):
    from pathlib import Path

    from montar.core import catalog

    root = Path(__file__).resolve().parent.parent / "catalogue"
    calls = []

    def fake_read(url, limit, timeout):
        calls.append(url)
        if url.endswith("index.json"):
            return (root / "index.json").read_bytes()
        return (root / "modules" / url.rsplit("/", 1)[1]).read_bytes()

    monkeypatch.setattr(catalog, "_read", fake_read)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    card = window.preferences.catalog
    assert not window.settings.catalog_enabled and not calls  # rien sans accord
    card.enabled.setChecked(True)
    assert window.settings.catalog_enabled
    assert wait_until(lambda: card.rows())
    row = card.rows()[0]
    assert row.entry.id == "exemple.negatif" and row.action.isEnabled()
    row.action.click()
    assert wait_until(lambda: "exemple.negatif" in window.modules.modules)
    assert wait_until(lambda: not card.rows()[0].action.isEnabled())  # « Installé »
    card.enabled.setChecked(False)
    assert not card.rows()


@needs_ffmpeg
def test_grading_panel_and_scopes(window, media_dir, tmp_path):
    from montar.ui.editor.grading import spline
    from montar.ui.editor.scopes import SCOPES

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    clip = editor.project.clips[0]
    editor.controller.select(clip.id)
    inspector = editor.inspector
    wheel, level = inspector._wheels["gain"]
    for x in (0.2, 0.4, 0.6):  # glisser la roue : une seule étape d'annulation
        wheel.moved.emit(x, 0.0)
    level.setValue(30)
    inspector.curves.changed.emit("master", [[0, 0], [0.5, 0.65], [1, 1]])
    clip = editor.project.clips[0]
    assert clip.grade.gain == [0.6, 0.0] and clip.grade.gain_level == 0.3
    assert clip.grade.curves["master"][1] == [0.5, 0.65]
    cube = tmp_path / "look.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0.5 0.5 0.5\n" * 8)
    assert inspector.set_lut(cube)
    clip = editor.project.clips[0]
    assert clip.grade.lut == "medias/look.cube" and inspector.lut_label.text() == "look"
    assert (editor.project.media_dir / "look.cube").exists()
    editor.controller.undo()  # la LUT
    editor.controller.undo()  # la courbe
    assert "master" not in editor.project.clips[0].grade.curves

    curve = spline([[0, 0], [0.5, 0.8], [1, 1]])
    assert curve[0] == (0.0, 0.0) and abs(dict(curve)[0.5] - 0.8) < 1e-6

    frames = []
    editor.player.frameReady.connect(lambda img, f: frames.append(f))
    editor._reload_player()
    editor.player.seek(5)
    assert wait_until(lambda: 5 in frames and editor.preview.canvas.image is not None)
    scopes = editor.open_scopes()
    pytest.importorskip("numpy")
    for key, _t in SCOPES:
        scopes.kind.set_current(key)
        scopes.update_frame(editor.preview.canvas.image)
        assert scopes.view.pixmap() is not None and not scopes.view.pixmap().isNull()
    scopes.close()


@needs_ffmpeg
def test_track_tool_attaches_follower(window, tmp_path, monkeypatch):
    import subprocess
    import sys

    pytest.importorskip("numpy")
    folder = tmp_path / "media"
    folder.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=480x270:rate=25:duration=2", "-f", "lavfi", "-i",
                    "color=c=white:size=40x40", "-filter_complex",
                    "[0][1]overlay=x='40+160*t':y=100:shortest=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(folder / "carre.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=64x64",
                    "-frames:v", "1", str(folder / "logo.png")], check=True)
    editor = imported_editor(window, folder, ["carre.mp4", "logo.png"])
    video_media, logo_media = editor.project.media
    editor.add_to_timeline(video_media)
    track = editor.controller.edit("piste", lambda t: t.add_track("video")).id
    logo = editor.controller.edit("logo", lambda t: t.add_clip(logo_media, track, 0, 50))
    video = next(c for c in editor.project.clips if c.media_id == video_media.id)
    module_id, tool = next((m, t) for m, t in editor.modules.tools_for(video)
                           if t.id == "suivi.suivre")
    package = sys.modules[type(tool).__module__]

    class FakeDialog:
        DialogCode = type("Code", (), {"Accepted": 1})

        def __init__(self, parent, image, followers):
            assert not image.isNull() and followers[0][0] == logo.id

        def exec(self):
            return 1

        def choice(self):
            return {"rect": (40 / 480, 100 / 270, 40 / 480, 40 / 270), "mode": "follow",
                    "target": logo.id, "block": 16}

    fake = type(sys)("dialog")
    fake.TrackDialog = FakeDialog
    monkeypatch.setitem(sys.modules, f"{package.__name__}.dialog", fake)
    editor.timeline.set_playhead(0)
    editor.modules.run_tool(module_id, tool, video)
    assert wait_until(lambda: editor.project.clips[-1].keyframes.get("x"), 60)
    keys = next(c for c in editor.project.clips if c.id == logo.id).keyframes
    xs = [v for _f, v in keys["x"]]
    assert xs[-1] - xs[0] > 0.2  # le logo part vers la droite avec le carré


@needs_ffmpeg
def test_wheel_scrolls_inspector_instead_of_sliders(window, media_dir):
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QScrollArea

    editor = imported_editor(window, media_dir, ["clip.mp4"])
    editor.add_to_timeline(editor.project.media[0])
    editor.controller.select(editor.project.clips[0].id)
    window.resize(1400, 700)  # inspecteur plus haut que l'écran : il défile
    pump(100)
    inspector = editor.inspector
    scroll = inspector.findChild(QScrollArea).verticalScrollBar()
    row = inspector._animated[2]  # échelle
    slider = row.slider
    before = slider.value()

    def wheel(widget):
        pos = QPointF(widget.width() / 2, widget.height() / 2)
        event = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)

    wheel(slider)
    assert slider.value() == before  # le réglage n'a pas bougé…
    assert scroll.value() > 0  # … le panneau a défilé
    assert editor.project.clips[0].transform.scale == 1.0
    slider.setFocus()  # après un clic, la molette règle le curseur
    wheel(slider)
    assert slider.value() != before
    zoom = editor.timeline.zoom_slider  # hors panneau défilant : molette inchangée
    z = zoom.value()
    wheel(zoom)
    assert zoom.value() != z
