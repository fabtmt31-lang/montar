# SPDX-License-Identifier: GPL-3.0-or-later
"""Édition d'un média avant le montage (F-MED-07)."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from montar.core.project import ColorAdjust
from montar.media.edit import MediaEdit, apply, command, video_filters
from montar.media.probe import probe

from .conftest import needs_ffmpeg


def _info(path):
    out = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-count_frames",
                          "-show_entries", "stream=codec_type,width,height,nb_read_frames:"
                          "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    return ({s["codec_type"]: s for s in data["streams"]},
            float(data["format"].get("duration", 0)))


def test_filters():
    edit = MediaEdit(crop_left=0.1, crop_right=0.2, rotation=90, flip_h=True,
                     color=ColorAdjust(saturation=-1.0), speed=2.0)
    chain = video_filters(edit)
    assert chain[0].startswith("crop=iw*0.700000:ih*1.000000:iw*0.100000")
    assert chain[1:3] == ["transpose=1", "hflip"]
    assert any(c.startswith("eq=") and "saturation=0.0" in c for c in chain)
    assert "setpts=PTS/2.000000" in chain
    assert MediaEdit().is_identity() and not edit.is_identity()


@needs_ffmpeg
def test_video_edit(media_dir, tmp_path):
    media = probe(media_dir / "clip.mp4")  # 2 s, 640×360, avec son
    edit = MediaEdit(trim_in=0.4, trim_out=1.6, crop_top=0.25, crop_bottom=0.25,
                     rotation=270, speed=2.0, volume=0.5)
    assert edit.output_size(media) == (180, 640)
    progress = []
    out = apply(media.path, tmp_path / "modif.mp4", media, edit, progress.append)
    streams, duration = _info(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (180, 640)
    assert duration == pytest.approx(0.6, abs=0.1) and "audio" in streams
    assert progress[-1] == 1.0
    assert not list(tmp_path.glob("*.part*"))


@needs_ffmpeg
def test_mute_image_and_audio(media_dir, tmp_path):
    media = probe(media_dir / "clip.mp4")
    streams, _d = _info(apply(media.path, tmp_path / "muet.mp4", media, MediaEdit(mute=True)))
    assert "audio" not in streams
    photo = probe(media_dir / "photo.png")  # 320×240
    out = apply(photo.path, tmp_path / "photo.png", photo,
                MediaEdit(crop_left=0.25, crop_right=0.25, rotation=90))
    streams, _d = _info(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (240, 160)
    son = probe(media_dir / "son.wav")  # 3 s
    streams, duration = _info(apply(son.path, tmp_path / "son.wav", son,
                                    MediaEdit(trim_in=1.0, speed=0.5)))
    assert "video" not in streams and duration == pytest.approx(4.0, abs=0.1)
    assert command(son.path, "x.wav", son, MediaEdit())[-1] == "x.wav"


@needs_ffmpeg
def test_edit_with_timelapse(media_dir, tmp_path):
    path = Path(__file__).parents[1] / "src/montar/modules/timelapse/core.py"
    spec = importlib.util.spec_from_file_location("tl_core_for_edit", path)
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core  # nécessaire aux dataclasses du module
    spec.loader.exec_module(core)
    media = probe(media_dir / "clip.mp4")  # 2 s à 25 i/s = 50 images
    edit = MediaEdit(timelapse={"factor": 10})
    out = apply(media.path, tmp_path / "tl.mp4", media, edit, timelapse_render=core.render)
    streams, _d = _info(out)
    assert int(streams["video"]["nb_read_frames"]) == 5
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "home") == ["tl.mp4"]
