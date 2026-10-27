# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
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
    if sys.platform == "win32":
        import ctypes

        assert not ctypes.WinDLL("kernel32").GetModuleHandleW("Qt5Core.dll")
        return
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


def test_round_shape(engine, media_dir):
    """Forme ronde (webcam d'un enregistrement) : coins transparents, centre visible."""
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    round_ = Transform(crop_left=0.21875, crop_right=0.21875, shape="round")
    src = engine.build(spec(video(ClipSpec(red, "video", 0, 10, media_size=(64, 36))),
                            video(ClipSpec(blue, "video", 0, 10, media_size=(64, 36),
                                           transform=round_))))
    assert near(rgb(src, 0, 32, 18), BLUE)
    assert near(rgb(src, 0, 19, 2), RED)  # coin du carré gardé : hors du rond


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


def test_pattern_transitions(engine, media_dir):
    """Transitions à motif, à mi-parcours : la seconde vidéo apparaît d'abord là où le
    motif l'annonce (centre pour le cercle et l'ouverture, bords pour la fermeture)."""
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    cases = (("circle", (32, 18), (2, 2)), ("barn_vertical", (32, 18), (2, 18)),
             ("close", (2, 18), (32, 18)), ("wipe_down", (32, 3), (32, 33)),
             ("diamond", (32, 18), (2, 2)))
    for kind, new_at, old_at in cases:
        track = TrackSpec("video", False, False,
                          (ClipSpec(red, "video", 0, 40), ClipSpec(blue, "video", 20, 40)),
                          transitions=(TransitionSpec(0, kind, 20),))
        src = engine.build(spec(track))
        assert near(rgb(src, 30, *new_at), BLUE), kind
        assert near(rgb(src, 30, *old_at), RED), kind


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


def test_preview_scaling_self_check(engine):
    from montar.engine.mlt_engine import preview_scaling_check

    check = preview_scaling_check()
    assert check["ok"], check


def test_comma_locale_does_not_break_placement(media_dir):
    """Qt adopte la convention du système (virgule décimale en français) : MLT lirait mal
    le rectangle du filtre affine. Le moteur doit rétablir le point décimal."""
    import locale

    from montar.engine import get_engine

    try:
        locale.setlocale(locale.LC_NUMERIC, "fr_FR.UTF-8")
    except locale.Error:
        pytest.skip("locale fr_FR.UTF-8 absente")
    try:
        engine = get_engine()
        assert locale.localeconv()["decimal_point"] == "."
        blue = str(media_dir / "blue.mp4")
        t = Transform(scale=0.5, x=0.123, y=-0.077)
        src = engine.build(spec(video(ClipSpec(blue, "video", 0, 10, media_size=(64, 36),
                                               transform=t)), w=1280, h=720))
        p = placement(1280, 720, 64, 36, t)
        data = src.render(0, 640, 360)
        inside = pixel(data, 640, int(p.cx / 2), int(p.cy / 2))[:3]
        outside = pixel(data, 640, int((p.left - 10) / 2), int(p.cy / 2))[:3]
        assert near(inside, BLUE) and outside == BLACK
    finally:
        locale.setlocale(locale.LC_NUMERIC, "C")


@needs_ffmpeg
def test_reverse_playback(engine, media_dir):
    # rouge pendant 1 s puis bleu : à l'envers, le clip commence en bleu
    path = str(media_dir / "redblue.mp4")
    normal = ClipSpec(path, "video", 0, 50, media_size=(64, 36), media_length=50)
    reverse = ClipSpec(path, "video", 0, 50, media_size=(64, 36), reverse=True, media_length=50)
    for clip, first in ((normal, "red"), (reverse, "blue")):
        source = engine.build(TimelineSpec(Canvas(64, 36, 25),
                                           (TrackSpec("video", False, False, (clip,)),)))
        try:
            r, _g, b, _a = pixel(source.render(5, 64, 36), 64, 32, 18)
        finally:
            source.close()
        assert (r > b) == (first == "red")


def test_typing_steps():
    pytest.importorskip("PyQt6.QtGui")
    from montar.ui.text_render import typing_steps

    steps = typing_steps(10, 125, 25)
    assert [s for s, _f in steps] == list(range(1, 11))
    assert sum(f for _s, f in steps) == 125 and steps[-1][1] > 100  # texte tenu jusqu'à la fin
    long = typing_steps(300, 50, 25)  # beaucoup de texte : plusieurs caractères par étape
    assert long[-1][0] == 300 and sum(f for _s, f in long) >= 50
    assert sum(f for _s, f in long[:-1]) <= 50 * 0.7 + 2


@needs_ffmpeg
def test_typewriter_text(engine, tmp_path):
    pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtWidgets import QApplication

    from montar.core.project import Clip, TextStyle
    from montar.ui.text_render import typing_sequence

    app = QApplication.instance() or QApplication(["t"])  # garder la référence
    assert app is not None
    clip = Clip("", "t", 0, 50, text=TextStyle("ABCDEFGH", color="#FFFFFF", size=120,
                                               animation_in="typewriter"))
    sequence = typing_sequence(tmp_path, clip, 160, 90, 25)
    spec = ClipSpec(sequence[-1][0], "text", 0, 50, media_size=(160, 90),
                    sequence=tuple(sequence))
    source = engine.build(TimelineSpec(Canvas(160, 90, 25),
                                       (TrackSpec("video", False, False, (spec,)),)))
    try:
        early, late = source.render(1, 160, 90), source.render(49, 160, 90)
    finally:
        source.close()
    lit = [sum(1 for i in range(0, len(d), 4) if d[i] > 200) for d in (early, late)]
    assert 0 < lit[0] < lit[1] / 3  # au début, une seule lettre est tapée


@needs_ffmpeg
def test_text_motion_animations(engine, tmp_path):
    """Entrée « par la gauche » puis sortie « zoom » : le texte se déplace puis rapetisse ;
    la durée réglée des animations est respectée."""
    pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtWidgets import QApplication

    from montar.core.project import Clip, TextStyle
    from montar.ui.text_render import render

    app = QApplication.instance() or QApplication(["t"])
    assert app is not None
    style = TextStyle("HHHH", color="#FFFFFF", size=200, animation_in="slide_left",
                      animation_out="zoom", animation_in_duration=1.0,
                      animation_out_duration=0.4)
    png = str(tmp_path / "t.png")
    render(style, 320, 180).save(png)
    clip = Clip("", "t", 0, 75, text=style)
    from montar.engine.base import _clip_spec

    spec_ = _clip_spec(clip, png, "text", (320, 180), fps=25)
    assert (spec_.animation_in_frames, spec_.animation_out_frames) == (25, 10)
    source = engine.build(TimelineSpec(Canvas(320, 180, 25),
                                       (TrackSpec("video", False, False, (spec_,)),)))

    def lit_columns(frame):
        data = source.render(frame, 320, 180)
        cols = [x for x in range(320) if any(data[(y * 320 + x) * 4] > 8
                                             for y in range(0, 180, 3))]
        return (min(cols), max(cols)) if cols else None

    try:
        entering, settled, leaving = lit_columns(6), lit_columns(40), lit_columns(71)
    finally:
        source.close()
    assert entering[0] < settled[0] - 10  # encore décalé vers la gauche
    width = lambda span: span[1] - span[0]  # noqa: E731
    assert leaving is None or width(leaving) < width(settled) * 0.9  # rapetisse en sortant
