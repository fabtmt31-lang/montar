# SPDX-License-Identifier: GPL-3.0-or-later
"""Export (cahier des charges §3.10)."""
import dataclasses
import json
import shutil
import subprocess

import pytest

from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec, TransitionSpec
from montar.engine.export import (
    ExportSettings,
    consumer_properties,
    estimated_bytes,
    export_size,
    human_size,
    retime,
)

from .conftest import needs_ffmpeg


def probe(path) -> dict:
    out = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-count_frames",
                          "-show_entries", "stream=codec_type,codec_name,width,height,"
                          "nb_read_frames,r_frame_rate:format=duration", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    streams = {s["codec_type"]: s for s in data["streams"]}
    return {"streams": streams, "duration": float(data["format"]["duration"])}


def test_sizes_and_estimates():
    assert export_size((1920, 1080), "720p") == (1280, 720)
    assert export_size((1080, 1920), "1080p") == (1080, 1920)
    assert export_size((1280, 720), "4K") == (3840, 2160)
    one_minute = 60 * 25
    s = ExportSettings("x.mp4", width=1920, height=1080, fps=25)
    size = estimated_bytes(s, one_minute, 25)
    assert 40e6 < size < 80e6  # ~1 min en 1080p équilibré
    assert estimated_bytes(ExportSettings("x.mp4", quality="max"), one_minute, 25) > size
    assert estimated_bytes(ExportSettings("x.wav", "wav"), one_minute, 25) == 60 * 48000 * 4
    assert human_size(186_000_000) == "≈ 186 Mo" and human_size(2_500_000_000) == "≈ 2,5 Go"


def test_consumer_properties():
    props = consumer_properties(ExportSettings("x.mp4", quality="light"))
    assert (props["vcodec"], props["crf"], props["acodec"]) == ("libx264", 28, "aac")
    assert consumer_properties(ExportSettings("x.mp3", "mp3"))["video_off"] == 1
    nv = consumer_properties(ExportSettings("x.mp4", hardware=True), "h264_nvenc")
    assert nv["vcodec"] == "h264_nvenc" and "crf" not in nv
    assert consumer_properties(ExportSettings("x.webm", "webm", "vp9"))["vcodec"] == "libvpx-vp9"


def test_retime_converts_positions():
    clip = ClipSpec("a.mp4", "video", 50, 100, source_in=25, fade_in=10)
    spec = TimelineSpec(Canvas(64, 36, 25), (TrackSpec(
        "video", False, False, (clip, ClipSpec("b.mp4", "video", 140, 50)),
        transitions=(TransitionSpec(0, "dissolve", 10),)),))
    out = retime(spec, 50)
    a, b = out.tracks[0].clips
    assert out.canvas.fps == 50 and (a.start, a.duration, a.source_in, a.fade_in) == \
        (100, 200, 50, 20)
    assert (b.start, b.duration) == (280, 100) and out.tracks[0].transitions[0].duration == 20
    assert retime(spec, 25) is spec


@pytest.fixture(scope="module")
def engine():
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    return get_engine()


def _spec(media_dir, fps=25, w=320, h=180):
    clip = str(media_dir / "clip.mp4")  # 2 s, 640×360, avec son
    return TimelineSpec(Canvas(w, h, fps), (
        TrackSpec("video", False, False, (ClipSpec(clip, "video", 0, 2 * fps,
                                                   media_size=(640, 360)),)),
        TrackSpec("audio", False, False, (ClipSpec(str(media_dir / "son.wav"), "audio", 0,
                                                   2 * fps),)),
    ))


def _run(engine, spec, settings):
    job = engine.export(spec, settings)
    job.start()
    assert job.wait(120)
    return job


@needs_ffmpeg
@pytest.mark.parametrize("fmt,codec,ext,vcodec", [
    ("mp4", "h264", ".mp4", "h264"),
    ("mov", "h265", ".mov", "hevc"),
    ("webm", "vp9", ".webm", "vp9"),
])
def test_export_video(engine, media_dir, tmp_path, fmt, codec, ext, vcodec):
    out = tmp_path / "exports"
    out.mkdir()
    target = out / f"film{ext}"
    job = _run(engine, _spec(media_dir), ExportSettings(str(target), fmt, codec, 320, 180, 25))
    assert job.error == "" and job.progress == 1.0
    info = probe(target)
    video = info["streams"]["video"]
    assert (video["codec_name"], video["width"], video["height"]) == (vcodec, 320, 180)
    assert int(video["nb_read_frames"]) == 50
    assert "audio" in info["streams"] and info["duration"] == pytest.approx(2.0, abs=0.1)
    assert sorted(p.name for p in out.iterdir()) == [target.name]  # pas de reste


@needs_ffmpeg
@pytest.mark.parametrize("fmt,ext,acodec", [("mp3", ".mp3", "mp3"), ("wav", ".wav", "pcm_s16le"),
                                             ("aac", ".m4a", "aac")])
def test_export_audio_only(engine, media_dir, tmp_path, fmt, ext, acodec):
    target = tmp_path / f"son{ext}"
    job = _run(engine, _spec(media_dir), ExportSettings(str(target), fmt, "", 0, 0, 25))
    assert job.error == ""
    info = probe(target)
    assert "video" not in info["streams"]
    assert info["streams"]["audio"]["codec_name"] == acodec
    assert info["duration"] == pytest.approx(2.0, abs=0.15)


@needs_ffmpeg
def test_export_gif_and_other_fps(engine, media_dir, tmp_path):
    target = tmp_path / "anim.gif"
    job = _run(engine, _spec(media_dir), ExportSettings(str(target), "gif", "gif", 320, 180, 25))
    assert job.error == "" and probe(target)["streams"]["video"]["codec_name"] == "gif"
    target = tmp_path / "trente.mp4"
    spec = retime(_spec(media_dir), 30)
    job = _run(engine, spec, ExportSettings(str(target), "mp4", "h264", 320, 180, 30))
    video = probe(target)["streams"]["video"]
    assert video["r_frame_rate"] == "30/1" and int(video["nb_read_frames"]) == 60


@needs_ffmpeg
def test_export_cancel(engine, media_dir, tmp_path):
    out = tmp_path / "exports"
    out.mkdir()
    target = out / "annule.mp4"
    spec = _spec(media_dir, w=1280, h=720)
    job = engine.export(spec, ExportSettings(str(target), "mp4", "h264", 1280, 720, 25, "max"))
    job.start()
    job.cancel()
    assert job.wait(30) and job.cancelled
    assert not list(out.iterdir())  # ni fichier final ni fichier partiel


@needs_ffmpeg
def test_hardware_falls_back_to_software(engine, media_dir, tmp_path, monkeypatch):
    from montar.engine import export, mlt_engine

    monkeypatch.setattr(export, "hardware_encoder", lambda codec: "h264_nvenc")
    real = mlt_engine.MltExport._encode
    calls = []

    def encode(self, output, props):
        calls.append(props["vcodec"])
        return False if props["vcodec"] == "h264_nvenc" else real(self, output, props)

    monkeypatch.setattr(mlt_engine.MltExport, "_encode", encode)
    target = tmp_path / "repli.mp4"
    job = _run(engine, _spec(media_dir),
               ExportSettings(str(target), "mp4", "h264", 320, 180, 25, hardware=True))
    assert calls == ["h264_nvenc", "libx264"]  # carte graphique refusée : logiciel
    assert job.error == "" and job.used_encoder == "libx264"
    assert probe(target)["streams"]["video"]["codec_name"] == "h264"


@needs_ffmpeg
def test_export_module_format(engine, media_dir, tmp_path):
    from montar.plugins import ModuleManager, builtin_modules_dir

    manager = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    manager.load_all()
    _m, fmt = manager.export_format("essentiels.mkv")
    target = tmp_path / "film.mkv"
    base = ExportSettings(str(target), fmt.id, "h264", 320, 180, 25)
    settings = dataclasses.replace(base, custom=tuple(fmt.properties(base).items()))
    job = _run(engine, _spec(media_dir), settings)
    assert job.error == ""
    info = probe(target)
    assert info["streams"]["video"]["codec_name"] == "h264"
    assert info["streams"]["audio"]["codec_name"] == "aac"


@needs_ffmpeg
def test_export_range(engine, media_dir, tmp_path):
    target = tmp_path / "partie.mp4"
    settings = ExportSettings(str(target), "mp4", "h264", 320, 180, 25, range_start=10,
                              range_end=35)
    job = _run(engine, _spec(media_dir), settings)
    assert job.error == "" and job.total == 25
    info = probe(target)
    assert int(info["streams"]["video"]["nb_read_frames"]) == 25
    assert info["duration"] == pytest.approx(1.0, abs=0.1)
