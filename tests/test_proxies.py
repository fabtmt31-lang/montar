# SPDX-License-Identifier: GPL-3.0-or-later
"""Proxys des vidéos 4K (F-MED-05)."""
import shutil
import subprocess

import pytest

from montar.core.project import MediaItem, Project
from montar.core.timeline import Timeline
from montar.engine.base import timeline_spec
from montar.media import proxies
from montar.media.probe import probe

from .conftest import needs_ffmpeg


def test_size_and_threshold():
    assert proxies.proxy_size(3840, 2160) == (960, 540)
    assert proxies.proxy_size(2160, 3840) == (540, 960)
    assert proxies.needs_proxy(MediaItem("/a.mp4", "video", width=3840, height=2160))
    assert not proxies.needs_proxy(MediaItem("/a.mp4", "video", width=1920, height=1080))
    assert not proxies.needs_proxy(MediaItem("/a.png", "image", width=4000, height=3000))


@pytest.fixture
def uhd(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg absent")
    path = tmp_path / "uhd.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=3840x2160:rate=25:duration=0.4", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@needs_ffmpeg
def test_make_proxy_and_preview_spec(uhd, tmp_path):
    media = probe(str(uhd))
    out = proxies.proxy_path(tmp_path / "cache", media.path)
    assert proxies.existing_proxy(tmp_path / "cache", media) is None
    assert proxies.make_proxy(media, out)
    small = probe(str(out))
    assert (small.width, small.height) == (960, 540)
    assert proxies.existing_proxy(tmp_path / "cache", media) == out
    assert not proxies.make_proxy(media, tmp_path / "x.mp4", stopping=lambda: True)
    assert not (tmp_path / "x.tmp.mp4").exists()

    project = Project("p", fps=25)
    project.media = [media]
    Timeline(project).add_clip(media)
    hook = lambda m: (str(out), (960, 540))  # noqa: E731
    clip = timeline_spec(project, proxy=hook).tracks[0].clips[0]
    assert clip.path == str(out) and clip.source_size == (960, 540)
    assert clip.media_size == (3840, 2160)
    assert timeline_spec(project).tracks[0].clips[0].path == media.path  # export : original
