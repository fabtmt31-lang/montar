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


# --- J2 ----------------------------------------------------------------------------------

from montar.core.project import ColorAdjust, Transform  # noqa: E402
from montar.engine.base import TransitionSpec  # noqa: E402
from montar.engine.geometry import affine_rect, placement  # noqa: E402


def rgb(src, frame, x=32, y=18):
    return pixel(src.render(frame, 64, 36), 64, x, y)[:3]


def near(color, expected, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(color, expected, strict=True))


RED, BLUE, BLACK, WHITE = (255, 0, 0), (0, 0, 255), (0, 0, 0), (255, 255, 255)


def test_geometry():
    t = Transform()
    assert affine_rect(1920, 1080, 1280, 720, t) == ((0, 0, 1920, 1080), False)
    t = Transform(scale=0.5, x=0.25)
    p = placement(1920, 1080, 1920, 1080, t)
    assert (p.cx, p.cy, p.width, p.height) == (1440, 540, 960, 540)
    # vidéo verticale « remplir » : couvre toute la largeur
    p = placement(1920, 1080, 1080, 1920, Transform(fit="fill"))
    assert p.width == pytest.approx(1920)
    rect, distort = affine_rect(1920, 1080, 1080, 1920, Transform(fit="stretch"))
    assert distort
    # rognage de la moitié gauche : la moitié droite reste à sa place
    p = placement(1920, 1080, 1920, 1080, Transform(crop_left=0.45))
    assert (p.left, p.width) == pytest.approx((0.45 * 1920, 0.55 * 1920))


def test_speed(engine, media_dir):
    s = spec(video(ClipSpec(str(media_dir / "redblue.mp4"), "video", 0, 25, 0, speed=2.0)))
    src = engine.build(s)
    assert near(rgb(src, 5), RED) and near(rgb(src, 18), BLUE)


def test_scale_flip_crop(engine, media_dir):
    blue = str(media_dir / "blue.mp4")
    small = engine.build(spec(video(ClipSpec(blue, "video", 0, 10, media_size=(64, 36),
                                             transform=Transform(scale=0.5)))))
    assert near(rgb(small, 0), BLUE) and rgb(small, 0, 2, 2) == BLACK
    half = str(media_dir / "half.mp4")
    flipped = engine.build(spec(video(ClipSpec(half, "video", 0, 10, media_size=(64, 36),
                                               transform=Transform(flip_h=True)))))
    assert near(rgb(flipped, 0, 8, 18), WHITE) and near(rgb(flipped, 0, 56, 18), RED)
    cropped = engine.build(spec(video(ClipSpec(half, "video", 0, 10, media_size=(64, 36),
                                               transform=Transform(crop_left=0.45)))))
    assert rgb(cropped, 0, 8, 18) == BLACK and near(rgb(cropped, 0, 56, 18), WHITE)


def test_color_and_preset(engine, media_dir):
    red = str(media_dir / "red.mp4")
    grey = engine.build(spec(video(ClipSpec(red, "video", 0, 10,
                                            color=ColorAdjust(saturation=-1)))))
    r, g, b = rgb(grey, 0)
    assert abs(r - g) < 15 and abs(g - b) < 15
    bw = engine.build(spec(video(ClipSpec(red, "video", 0, 10, preset="bw"))))
    r, g, b = rgb(bw, 0)
    assert abs(r - g) < 15
    half = engine.build(spec(video(ClipSpec(red, "video", 0, 10, preset="bw",
                                            preset_amount=0.5))))
    r, g, _ = rgb(half, 0)
    assert r - g > 40  # à moitié désaturé


def test_fades(engine, media_dir):
    s = spec(video(ClipSpec(str(media_dir / "red.mp4"), "video", 0, 40, fade_in=10,
                            fade_out=10)))
    src = engine.build(s)
    assert rgb(src, 0) == BLACK and near(rgb(src, 20), RED) and rgb(src, 39) == BLACK
    assert 20 < rgb(src, 5)[0] < 230  # à mi-fondu


@pytest.mark.parametrize(("kind", "middle"), [
    ("dissolve", (128, 0, 128)), ("dip_black", BLACK), ("dip_white", WHITE),
])
def test_transitions(engine, media_dir, kind, middle):
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    track = TrackSpec("video", False, False,
                      (ClipSpec(red, "video", 0, 40), ClipSpec(blue, "video", 20, 40)),
                      transitions=(TransitionSpec(0, kind, 20),))
    src = engine.build(spec(track))
    assert src.length == 60
    assert near(rgb(src, 10), RED) and near(rgb(src, 50), BLUE)
    assert near(rgb(src, 30), middle, 60)


def test_slide_and_wipe(engine, media_dir):
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    for kind, left, right in (("slide_left", RED, BLUE), ("wipe_right", BLUE, RED)):
        track = TrackSpec("video", False, False,
                          (ClipSpec(red, "video", 0, 40), ClipSpec(blue, "video", 20, 40)),
                          transitions=(TransitionSpec(0, kind, 20),))
        src = engine.build(spec(track))
        assert near(rgb(src, 30, 4, 18), left), kind
        assert near(rgb(src, 30, 60, 18), right), kind


def test_text_overlay(engine, media_dir):
    lower = video(ClipSpec(str(media_dir / "blue.mp4"), "video", 0, 30))
    text = video(ClipSpec(str(media_dir / "text.png"), "text", 5, 20, media_size=(64, 36)))
    src = engine.build(spec(lower, text))
    assert near(rgb(src, 10), (255, 255, 0))  # texte jaune au centre
    assert near(rgb(src, 10, 4, 4), BLUE)  # transparent ailleurs
    assert near(rgb(src, 2), BLUE)  # avant le texte


def test_volume_and_audio_build(engine, media_dir):
    s = spec(TrackSpec("audio", False, False,
                       (ClipSpec(str(media_dir / "son.wav"), "audio", 0, 40, volume=0.5,
                                 fade_in=10),
                        ClipSpec(str(media_dir / "son.wav"), "audio", 30, 40, speed=1.5)),
                       volume=0.8, transitions=(TransitionSpec(0, "dissolve", 10),)))
    assert engine.build(s).length == 70
    out = engine.audio_output(s)
    if out is not None:
        out.start(0)
        out.stop()
        out.close()


def test_settings_update_without_rebuild(engine, media_dir):
    blue = str(media_dir / "blue.mp4")
    clip = ClipSpec(blue, "video", 0, 20, media_size=(64, 36))
    src = engine.build(spec(video(clip)))
    assert near(rgb(src, 5, 4, 4), BLUE)
    smaller = ClipSpec(blue, "video", 0, 20, media_size=(64, 36), transform=Transform(scale=0.5))
    assert src.update(spec(video(smaller)))  # même structure : mise à jour sur place
    assert rgb(src, 5, 4, 4) == BLACK and near(rgb(src, 5), BLUE)
    grey = ClipSpec(blue, "video", 0, 20, media_size=(64, 36), color=ColorAdjust(saturation=-1))
    assert src.update(spec(video(grey)))
    r, g, b = rgb(src, 5)
    assert abs(r - b) < 20 and rgb(src, 5, 4, 4) != BLACK  # filtres précédents retirés
    longer = ClipSpec(blue, "video", 0, 30, media_size=(64, 36))
    assert not src.update(spec(video(longer)))  # durée changée : reconstruction nécessaire


def test_placement_is_independent_of_preview_size(engine, media_dir):
    """L'aperçu est rendu plus petit que la toile : le placement doit rester proportionnel."""
    blue = str(media_dir / "blue.mp4")
    t = Transform(scale=0.5, x=0.25, y=-0.1)
    src = engine.build(spec(video(ClipSpec(blue, "video", 0, 10, media_size=(64, 36),
                                           transform=t)), w=1280, h=720))
    p = placement(1280, 720, 64, 36, t)
    for w, h in ((1280, 720), (640, 360), (320, 180)):
        data = src.render(0, w, h)
        k = w / 1280
        inside = pixel(data, w, int(p.cx * k), int(p.cy * k))[:3]
        outside = pixel(data, w, int((p.left - 10) * k), int(p.cy * k))[:3]
        assert near(inside, BLUE) and outside == BLACK, (w, h)
