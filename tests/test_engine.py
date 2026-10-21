# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

import pytest

from montar.core.project import Project
from montar.core.timeline import Timeline
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec, timeline_spec
from montar.media.probe import probe

from .conftest import needs_ffmpeg

mlt = pytest.importorskip("mlt7")
pytestmark = needs_ffmpeg


@pytest.fixture(scope="module")
def engine():
    from montar.engine import get_engine

    return get_engine()


def pixel(data: bytes, width: int, x: int, y: int) -> tuple[int, ...]:
    i = (y * width + x) * 4
    return tuple(data[i:i + 4])


def spec(*tracks, w=64, h=36, fps=25):
    return TimelineSpec(Canvas(w, h, fps), tuple(tracks))


def video(*clips):
    return TrackSpec("video", False, False, tuple(clips))


def test_clips_and_gaps(engine, media_dir):
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    s = spec(video(ClipSpec(red, "video", 0, 20, 0), ClipSpec(blue, "video", 30, 10, 5)))
    src = engine.build(s)
    assert src.length == 40
    assert pixel(src.render(5, 64, 36), 64, 32, 18)[:3] == pytest.approx((255, 0, 0), abs=12)
    assert pixel(src.render(25, 64, 36), 64, 32, 18)[:3] == (0, 0, 0)  # blanc → fond noir
    assert pixel(src.render(35, 64, 36), 64, 32, 18)[:3] == pytest.approx((0, 0, 255), abs=12)


def test_upper_track_covers_lower(engine, media_dir):
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    lower = video(ClipSpec(red, "video", 0, 40, 0))
    upper = video(ClipSpec(blue, "video", 10, 10, 0))
    src = engine.build(spec(lower, upper))
    assert pixel(src.render(15, 64, 36), 64, 32, 18)[:3] == pytest.approx((0, 0, 255), abs=12)
    assert pixel(src.render(25, 64, 36), 64, 32, 18)[:3] == pytest.approx((255, 0, 0), abs=12)
    hidden = TrackSpec("video", False, True, upper.clips)
    src = engine.build(spec(lower, hidden))
    assert pixel(src.render(15, 64, 36), 64, 32, 18)[:3] == pytest.approx((255, 0, 0), abs=12)


def test_vertical_video_is_letterboxed(engine, media_dir):
    s = spec(video(ClipSpec(str(media_dir / "vertical.mp4"), "video", 0, 30, 0)),
             w=320, h=180, fps=30)
    data = engine.build(s).render(0, 320, 180)
    assert pixel(data, 320, 5, 90)[:3] == (0, 0, 0)  # bandes noires (fond)
    assert pixel(data, 320, 160, 90)[3] == 255


def test_image_can_last_longer_than_default(engine, media_dir):
    s = spec(video(ClipSpec(str(media_dir / "photo.png"), "image", 0, 1000, 0)))
    src = engine.build(s)
    assert src.length == 1000
    assert len(src.render(999, 64, 36)) == 64 * 36 * 4


def test_empty_timeline(engine):
    src = engine.build(spec())
    assert src.length == 0
    assert src.render(0, 8, 8) == bytes(8 * 8 * 4)


def test_spec_from_project(media_dir):
    p = Project("p", resolution="720p", fps=30)
    clip = probe(media_dir / "clip.mp4")
    p.media = [clip]
    tl = Timeline(p)
    v2 = tl.add_track("video")
    tl.add_clip(clip, v2.id, 10)
    tl.add_clip(clip)
    tl.first_track("audio").muted = True
    s = timeline_spec(p)
    assert s.canvas == Canvas(1280, 720, 30)
    assert [t.kind for t in s.tracks] == ["video", "video", "audio"]  # V1, V2, A1
    assert s.tracks[0].clips[0].start == 0 and s.tracks[1].clips[0].start == 10
    assert s.tracks[2].muted
    assert s.length == 10 + 60


def test_audio_output_follows_time(engine, media_dir, monkeypatch):
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    s = spec(TrackSpec("audio", False, False,
                       (ClipSpec(str(media_dir / "son.wav"), "audio", 0, 75, 0),)))
    out = engine.audio_output(s)
    if out is None:
        pytest.skip("pas de sortie son SDL")
    out.start(10)
    time.sleep(0.8)
    position = out.position()
    out.stop()
    out.close()
    assert 20 <= position <= 40


def test_qt5_is_never_loaded(engine, media_dir):
    """Les modules MLT liés à Qt 5 figeaient l'interface (Qt 6) à l'ouverture d'une image."""
    s = spec(video(ClipSpec(str(media_dir / "photo.png"), "image", 0, 25, 0)))
    engine.build(s).render(0, 64, 36)
    with open(f"/proc/{os.getpid()}/maps") as maps:
        assert not any("libQt5Core" in line for line in maps)
