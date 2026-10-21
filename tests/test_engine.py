# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from montar.engine.base import Canvas

from .conftest import needs_ffmpeg

mlt = pytest.importorskip("mlt7")
pytestmark = needs_ffmpeg


@pytest.fixture(scope="module")
def engine():
    from montar.engine import get_engine

    return get_engine()


def test_video_in_canvas(engine, media_dir):
    src = engine.open(str(media_dir / "clip.mp4"), "video", Canvas(1920, 1080, 25))
    assert src.length == 50 and src.fps == 25
    data = src.render(10, 192, 108)
    assert len(data) == 192 * 108 * 4
    assert any(data[i] for i in range(0, len(data), 4 * 97))  # l'image n'est pas vide


def test_frame_count_follows_project_fps(engine, media_dir):
    src = engine.open(str(media_dir / "clip.mp4"), "video", Canvas(1920, 1080, 50))
    assert src.length == 100


def test_vertical_video_is_letterboxed(engine, media_dir):
    """Une vidéo verticale dans une toile 16:9 laisse des bandes transparentes sur les côtés."""
    src = engine.open(str(media_dir / "vertical.mp4"), "video", Canvas(320, 180, 30))
    data = src.render(0, 320, 180)
    left_alpha = data[(90 * 320 + 5) * 4 + 3]
    centre_alpha = data[(90 * 320 + 160) * 4 + 3]
    assert left_alpha == 0 and centre_alpha == 255


def test_image_duration(engine, media_dir):
    src = engine.open(str(media_dir / "photo.png"), "image", Canvas(1280, 720, 25))
    assert src.length == 5 * 25
    assert len(src.render(0, 128, 72)) == 128 * 72 * 4


def test_out_of_range_frame_is_clamped(engine, media_dir):
    src = engine.open(str(media_dir / "clip.mp4"), "video", Canvas(640, 360, 25))
    assert len(src.render(10_000, 64, 36)) == 64 * 36 * 4


def test_qt5_is_never_loaded(engine, media_dir):
    """Les modules MLT liés à Qt 5 figeaient l'interface (Qt 6) à l'ouverture d'une image."""
    import os

    src = engine.open(str(media_dir / "photo.png"), "image", Canvas(320, 180, 25))
    src.render(0, 320, 180)
    with open(f"/proc/{os.getpid()}/maps") as maps:
        assert not any("libQt5Core" in line for line in maps)
