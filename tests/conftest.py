# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")  # son joué sur un périphérique fictif

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe absents",
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Chaque test utilise des dossiers de configuration, données et cache vierges."""
    home = tmp_path / "home"
    for var, sub in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"),
                     ("XDG_DATA_HOME", ".local/share"), ("XDG_CACHE_HOME", ".cache"),
                     ("XDG_VIDEOS_DIR", "Vidéos")):
        path = home / sub if sub else home
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(var, str(path))
    return home


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=60)


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    """Petits médias de test générés par ffmpeg (vidéo avec son, vidéo verticale, image, son)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg absent")
    d = tmp_path_factory.mktemp("media")
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(d / "clip.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "vertical.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240", "-frames:v", "1", "-update", "1",
            str(d / "photo.png"))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=3", str(d / "son.wav"))
    for color in ("red", "blue"):
        _ffmpeg("-f", "lavfi", "-i", f"color=c={color}:size=64x36:rate=25:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / f"{color}.mp4"))
    return d
