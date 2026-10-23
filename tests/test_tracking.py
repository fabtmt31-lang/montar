# SPDX-License-Identifier: GPL-3.0-or-later
"""Suivi de mouvement (corrélation normalisée, NumPy)."""
import subprocess

import pytest

from montar.core import tracking

from .conftest import needs_ffmpeg

np = pytest.importorskip("numpy")


def _moving_square(path, seconds=2):
    """Carré clair qui traverse l'image (de x = 40 à x = 360 sur 2 s) sur une mire."""
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=480x270:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", "color=c=white:size=40x40,"
                    "drawbox=x=12:y=12:w=16:h=16:color=red:t=fill",
                    "-filter_complex", "[0][1]overlay=x='40+160*t':y='100+30*t':shortest=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def test_match_finds_template():
    rng = np.random.default_rng(1)
    image = rng.random((80, 120)).astype(np.float32)
    template = image[30:46, 50:70].copy()
    _score, (y, x), best = tracking.match(image, template)
    assert (y, x) == (30, 50) and best > 0.99


@needs_ffmpeg
def test_track_follows_moving_square(tmp_path):
    video = tmp_path / "carre.mp4"
    _moving_square(video)
    frames = tracking.read_frames(str(video), 0, 2, 25)
    rect = (40 / 480, 100 / 270, 40 / 480, 40 / 270)
    points = tracking.track(frames, rect, total=50)
    assert len(points) >= 48
    for p in points[::10]:
        t = p.frame / 25
        assert abs(p.x * 480 - (60 + 160 * t)) < 6, (p.frame, p.x * 480)
        assert abs(p.y * 270 - (120 + 30 * t)) < 6
    assert min(p.score for p in points) > tracking.LOST
    assert len(tracking.simplify(points, 4)) == len(points[::4]) + (len(points) % 4 != 1)
    smoothed = tracking.smooth(points)
    assert len(smoothed) == len(points)


@needs_ffmpeg
def test_track_can_be_cancelled(tmp_path):
    video = tmp_path / "carre.mp4"
    _moving_square(video, 1)
    with pytest.raises(tracking.TrackingError):
        tracking.track(tracking.read_frames(str(video), 0, 1, 25), (0.1, 0.4, 0.1, 0.15),
                       cancelled=lambda: True)


def _suivi():
    import importlib

    return importlib.import_module("montar.modules.suivi")


def test_pixelate_filters_follow_points():
    effect = _suivi().TrackedPixelate()
    values = {**effect.defaults(), "piste": [[0, 0.2, 0.5], [2, 0.3, 0.5], [4, 0.4, 0.5]],
              "taille": [0.1, 0.2]}
    filters = effect.filters(values)
    assert [n for n, _p in filters] == ["obscure"] * 3
    assert (filters[0][1]["in"], filters[0][1]["out"]) == (0, 1)
    assert filters[1][1]["end"].startswith("34.25%/38.50%:11.50%x23.00%")
    assert filters[-1][1]["in"] == filters[-1][1]["out"] == 4
    assert effect.filters(effect.defaults()) == []


def test_follow_keys_keep_offset():
    from montar.core.project import MediaItem, Project
    from montar.core.timeline import Timeline
    from montar.core.tracking import Point

    project = Project("p", aspect="16:9", resolution="1080p", fps=25)
    project.media = [MediaItem("/v.mp4", "video", duration=4, width=1920, height=1080,
                               id="v"),
                     MediaItem("/i.png", "image", width=200, height=200, id="i")]
    tl = Timeline(project)
    video = tl.add_clip(project.media[0])
    track = tl.add_track("video")
    logo = tl.add_clip(project.media[1], track.id, 10, 50)
    points = [Point(0, 0.5, 0.5, 1), Point(10, 0.6, 0.5, 1), Point(20, 0.7, 0.4, 1)]
    keys = _suivi().follow_keys(project, video, logo, points, 10)
    assert [k[0] for k in keys["x"]] == [0, 10, 20]
    x0, x1, x2 = (k[1] for k in keys["x"])
    assert abs((x1 - x0) - 0.1) < 1e-3 and abs((x2 - x0) - 0.2) < 1e-3
    assert abs(keys["y"][2][1] - keys["y"][0][1] + 0.1) < 1e-3


@needs_ffmpeg
def test_pixelation_renders_on_moving_object(tmp_path):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine
    from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec

    video = tmp_path / "carre.mp4"
    _moving_square(video, 1)
    effect = _suivi().TrackedPixelate()
    values = {**effect.defaults(), "bloc": 20, "piste": [[0, 0.125, 0.44], [24, 0.45, 0.5]],
              "taille": [0.1, 0.15]}
    engine = get_engine()

    def frame(filters, n):
        clip = ClipSpec(str(video), "video", 0, 25, media_size=(480, 270),
                        extra_filters=tuple(filters))
        source = engine.build(TimelineSpec(Canvas(480, 270, 25),
                                           (TrackSpec("video", False, False, (clip,)),)))
        data = source.render(n, 480, 270)
        source.close()
        return data

    plain, hidden = frame([], 0), frame(effect.filters(values), 0)
    assert plain != hidden  # le carré est pixelisé…
    i = (20 * 480 + 400) * 4
    same = zip(plain[i:i + 3], hidden[i:i + 3], strict=True)
    assert max(abs(a - b) for a, b in same) < 4  # … pas le reste de l'image


@needs_ffmpeg
def test_uniform_area_is_widened(tmp_path):
    """Un carré tout blanc (sans détail) est suivi grâce à ses bords."""
    video = tmp_path / "blanc.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x303030:size=480x270:rate=25:duration=1", "-f", "lavfi", "-i",
                    "color=c=white:size=40x40", "-filter_complex",
                    "[0][1]overlay=x='40+160*t':y=100:shortest=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    points = tracking.track(tracking.read_frames(str(video), 0, 1, 25),
                            (45 / 480, 105 / 270, 30 / 480, 30 / 270))
    assert abs(points[-1].x * 480 - (60 + 160 * points[-1].frame / 25)) < 8
