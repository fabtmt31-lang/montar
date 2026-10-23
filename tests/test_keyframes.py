# SPDX-License-Identifier: GPL-3.0-or-later
"""Images clés (F-EDT-10) : interpolation, édition, coupe et rendu."""
import pytest

from montar.core import keyframes
from montar.core.project import Clip, MediaItem, Project
from montar.core.timeline import Timeline
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec

from .conftest import needs_ffmpeg


def test_value_at_interpolates_and_holds():
    points = [[10, 0.0], [20, 1.0]]
    assert keyframes.value_at(points, 0, 5) == 0.0
    assert keyframes.value_at(points, 15, 5) == pytest.approx(0.5)
    assert keyframes.value_at(points, 30, 5) == 1.0
    assert keyframes.value_at([], 3, 5) == 5


def test_add_set_remove():
    clip = Clip(media_id="m", track_id="t", start=0, duration=50)
    keyframes.set_property(clip, "x", 0.2, 0)  # pas encore animé : valeur fixe
    assert clip.transform.x == 0.2 and not clip.keyframes
    keyframes.add_keyframe(clip, 0)
    keyframes.add_keyframe(clip, 40)
    keyframes.set_property(clip, "x", 0.8, 40)
    assert keyframes.key_frames(clip) == [0, 40]
    assert keyframes.transform_at(clip, 20).x == pytest.approx(0.5)
    assert clip.transform.x == 0.2  # la valeur de base n'est pas touchée
    keyframes.remove_keyframe(clip, 0)
    assert keyframes.transform_at(clip, 0).x == pytest.approx(0.8)
    keyframes.remove_keyframe(clip, 40)
    assert not clip.keyframes and clip.transform.x == pytest.approx(0.8)


def _timeline():
    project = Project("p", fps=25)
    project.media = [MediaItem("/i.png", "image", width=64, height=36, id="image")]
    tl = Timeline(project)
    return tl, tl.add_clip(project.media[0], duration=50)


def test_split_and_trim_shift_keys():
    tl, clip = _timeline()
    keyframes.add_keyframe(clip, 10)
    keyframes.add_keyframe(clip, 30)
    second = tl.split(clip.id, 20)
    assert keyframes.key_frames(second) == [-10, 10]
    tl.trim(second.id, "start", second.start + 5)
    assert keyframes.key_frames(second) == [-15, 5]


def test_keyframes_roundtrip(tmp_path):
    tl, clip = _timeline()
    keyframes.add_keyframe(clip, 5)
    loaded = Project.load(tl.project.save(tmp_path / "p.montar"))
    assert loaded.clips[0].keyframes == clip.keyframes


def _render(engine, path, keys, frame):
    clip = ClipSpec(str(path), "image", 0, 50, media_size=(64, 36), keyframes=keys)
    source = engine.build(TimelineSpec(Canvas(64, 36, 25),
                                       (TrackSpec("video", False, False, (clip,)),)))
    try:
        return source.render(frame, 64, 36)
    finally:
        source.close()


@needs_ffmpeg
def test_keyframed_position_moves_the_image(media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    engine = get_engine()
    image = media_dir / "text.png"  # carré jaune de 24 à 40 × 12 à 24
    keys = (("x", ((0.0, 0.0), (40.0, 0.5))),)
    first = _render(engine, image, keys, 0)
    last = _render(engine, image, keys, 49)
    assert first != last
    i = (16 * 64 + 30) * 4
    assert first[i] > 200 and last[i] < 50  # le carré a quitté le centre


def _over_blue(engine, media_dir, fg, frame):
    bg = ClipSpec(str(media_dir / "blue.mp4"), "video", 0, 50, media_size=(64, 36))
    source = engine.build(TimelineSpec(Canvas(64, 36, 25), (
        TrackSpec("video", False, False, (bg,)), TrackSpec("video", False, False, (fg,)))))
    try:
        data = source.render(frame, 64, 36)
    finally:
        source.close()
    i = (18 * 64 + 32) * 4
    return tuple(data[i:i + 3])


@needs_ffmpeg
def test_opacity_blends_with_lower_track(media_dir):
    pytest.importorskip("mlt7")
    from montar.core.project import Transform
    from montar.engine import get_engine

    engine = get_engine()
    red = str(media_dir / "red.mp4")
    r, _g, b = _over_blue(engine, media_dir, ClipSpec(
        red, "video", 0, 50, media_size=(64, 36), transform=Transform(opacity=0.3)), 5)
    assert 50 < r < 110 and 150 < b < 210
    r, _g, b = _over_blue(engine, media_dir, ClipSpec(
        red, "video", 0, 50, media_size=(64, 36),
        keyframes=(("opacity", ((0.0, 0.0), (40.0, 1.0))),)), 20)
    assert 100 < r < 150 and 100 < b < 150  # moitié du chemin entre les clés
    r, _g, b = _over_blue(engine, media_dir, ClipSpec(red, "video", 0, 50, media_size=(64, 36)), 5)
    assert r > 240 and b < 20
