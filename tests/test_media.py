# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from montar.media.probe import ProbeError, is_supported, probe
from montar.media.thumbnails import make_thumbnail, thumbnail_path

from .conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def test_probe_video(media_dir):
    m = probe(media_dir / "clip.mp4")
    assert m.kind == "video"
    assert (m.width, m.height) == (640, 360)
    assert m.fps == pytest.approx(25)
    assert m.duration == pytest.approx(2, abs=0.1)
    assert m.has_audio and m.video_codec == "h264" and m.audio_codec == "aac"


def test_probe_image_and_audio(media_dir):
    img = probe(media_dir / "photo.png")
    assert (img.kind, img.width, img.height, img.duration) == ("image", 320, 240, 0.0)
    snd = probe(media_dir / "son.wav")
    assert snd.kind == "audio" and snd.duration == pytest.approx(3, abs=0.1)


def test_probe_rejects_non_media(tmp_path):
    f = tmp_path / "notes.mp4"
    f.write_text("ceci n'est pas une vidéo")
    with pytest.raises(ProbeError):
        probe(f)


def test_is_supported():
    assert is_supported("a.MP4") and is_supported("b.flac") and is_supported("c.jpeg")
    assert not is_supported("d.txt") and not is_supported("e")


def test_thumbnails(media_dir, tmp_path):
    for name in ("clip.mp4", "photo.png"):
        item = probe(media_dir / name)
        thumb = make_thumbnail(tmp_path, item)
        assert thumb is not None and thumb.stat().st_size > 0
        assert thumb == thumbnail_path(tmp_path, item.path)
    assert make_thumbnail(tmp_path, probe(media_dir / "son.wav")) is None
