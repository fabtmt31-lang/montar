# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistrement en deux calques (écran + webcam liés), format libre de la toile."""
import pytest

from montar.core import formats
from montar.core.history import History
from montar.core.project import MediaItem, Project
from montar.core.recording import layout_transforms
from montar.core.timeline import Timeline, TimelineError, snapshot
from montar.engine.geometry import placement

FPS = 25


def recording_project(layout: dict | None = None) -> Project:
    p = Project("Tuto", fps=FPS)
    p.media = [
        MediaItem("/rec.mp4", "video", duration=20.0, width=1920, height=1080, fps=30,
                  has_audio=True, id="screen",
                  webcam={"media": "cam", "screen_in": 0.4, "webcam_in": 2.0,
                          "layout": layout or {"position": "bottom_right", "size": 0.25,
                                               "shape": "round"}}),
        MediaItem("/rec.webcam.mkv", "video", duration=23.0, width=1280, height=720, fps=30,
                  id="cam", role="webcam"),
        MediaItem("/v.mp4", "video", duration=4.0, width=1366, height=768, fps=30, id="other"),
    ]
    return p


def test_format_for_known_and_custom_sizes():
    assert formats.format_for(1920, 1080) == ("16:9", "1080p", (1920, 1080))
    assert formats.format_for(1080, 1920) == ("9:16", "1080p", (1080, 1920))
    assert formats.format_for(3840, 2160)[:2] == ("16:9", "4K")
    assert formats.format_for(1366, 1025) == ("custom", "1080p", (1366, 1024))
    assert formats.custom_size(5, 99999) == (16, 8192)


def test_custom_format_is_saved_and_undone(tmp_path):
    p = recording_project()
    tl = Timeline(p)
    history = History()
    before = snapshot(p)
    tl.fit_canvas_to("other")
    history.record("cadre", before)
    assert (p.aspect, p.canvas_size, p.format_label) == ("custom", (1366, 768),
                                                          "1366 × 768")
    path = p.save(tmp_path / "p.montar")
    assert Project.load(path).canvas_size == (1366, 768)
    history.undo(p)
    assert (p.aspect, p.canvas_size) == ("16:9", (1920, 1080))


def test_fit_canvas_with_frame_rate_retimes_clips():
    p = recording_project()
    tl = Timeline(p)
    clip = tl.add_clip(p.find_media("other"))
    tl.fit_canvas_to("other", with_fps=True)
    assert p.fps == 30
    assert clip.duration == 120  # 4 s à 30 i/s


def test_recording_lands_as_two_linked_clips():
    p = recording_project()
    tl = Timeline(p)
    screen = tl.add_clip(p.find_media("screen"))
    assert len(p.clips) == 2
    cam = next(c for c in p.clips if c.media_id == "cam")
    assert screen.group and cam.group == screen.group
    assert screen.source_in == 10  # 0,4 s de l'écran avant le vrai départ
    assert cam.source_in == 50  # 2 s de webcam ouverte pendant le compte à rebours
    assert cam.start == screen.start and cam.duration == screen.duration == 490
    # piste de la webcam au-dessus de celle de l'écran
    order = [t.id for t in p.tracks]
    assert order.index(cam.track_id) < order.index(screen.track_id)
    assert cam.transform.shape == "round"
    box = placement(1920, 1080, 1280, 720, cam.transform)
    assert box.width == pytest.approx(480) and box.height == pytest.approx(480)
    assert box.left + box.width == pytest.approx(1920 - 24)
    assert box.top + box.height == pytest.approx(1080 - 24)


def test_split_layout_places_screen_and_camera_side_by_side():
    screen_t, cam_t = layout_transforms((1920, 1080), (1920, 1080), (1280, 720),
                                        {"position": "split_right", "size": 0.3})
    s = placement(1920, 1080, 1920, 1080, screen_t)
    c = placement(1920, 1080, 1280, 720, cam_t)
    assert s.left == pytest.approx(0) and s.width == pytest.approx(1344)
    assert c.left == pytest.approx(1344) and c.width == pytest.approx(576)
    assert c.height == pytest.approx(1080)


def test_cut_keeps_each_side_linked():
    p = recording_project()
    tl = Timeline(p)
    screen = tl.add_clip(p.find_media("screen"))
    tl.split_at(100, screen.id)
    assert len(p.clips) == 4
    before = {c.group for c in p.clips if c.start < 100}
    after = {c.group for c in p.clips if c.start >= 100}
    assert len(before) == len(after) == 1 and before != after


def test_remove_webcam_on_a_range():
    p = recording_project()
    tl = Timeline(p)
    screen = tl.add_clip(p.find_media("screen"))
    tl.remove_webcam(screen.id, 100, 200)
    cams = sorted((c for c in p.clips if c.media_id == "cam"), key=lambda c: c.start)
    assert [(c.start, c.end) for c in cams] == [(0, 100), (200, 490)]
    assert cams[0].fade_out == round(0.3 * FPS) and cams[1].fade_in == round(0.3 * FPS)
    assert all(c.group == screen.group for c in cams)
    # sans webcam : refusé
    with pytest.raises(TimelineError):
        tl.remove_webcam(tl.add_clip(p.find_media("other")).id, 0, 10)


def test_remove_webcam_in_split_layout_gives_the_screen_full_frame():
    p = recording_project({"position": "split_left", "size": 0.3})
    tl = Timeline(p)
    screen = tl.add_clip(p.find_media("screen"))
    tl.remove_webcam(screen.id, 100, 200)
    screens = sorted((c for c in p.clips if c.media_id == "screen"), key=lambda c: c.start)
    assert [(c.start, c.end) for c in screens] == [(0, 100), (100, 200), (200, 490)]
    middle = screens[1]
    assert middle.transform.scale == 1.0 and middle.transform.x == 0.0
    assert middle.keyframes["scale"][0][1] == pytest.approx(0.7)  # part de l'écran
    assert middle.keyframes["scale"][1][1] == 1.0


def test_webcam_fullscreen_on_a_range():
    p = recording_project()
    tl = Timeline(p)
    screen = tl.add_clip(p.find_media("screen"))
    tl.webcam_fullscreen(screen.id, 100, 200)
    middle = next(c for c in p.clips if c.media_id == "cam" and c.start == 100)
    assert middle.transform.shape == "rect" and middle.transform.crop_left == 0
    box = placement(1920, 1080, 1280, 720, middle.transform)
    assert box.width == pytest.approx(1920)
    assert middle.keyframes["scale"][0][1] < middle.transform.scale


def test_removing_the_recording_removes_its_webcam():
    p = recording_project()
    tl = Timeline(p)
    tl.add_clip(p.find_media("screen"))
    tl.remove_media("screen")
    assert [m.id for m in p.media] == ["other"] and not p.clips
    assert [m.id for m in recording_project().visible_media()] == ["screen", "other"]
