# SPDX-License-Identifier: GPL-3.0-or-later
"""Finition pro : réglages, filtres, analyse et export en plusieurs passes."""
import json
import shutil
import subprocess

import pytest

from montar.core import mastering as cm
from montar.core.project import Project
from montar.engine import mastering as mst
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.engine.export import ExportSettings
from montar.engine.master_job import (
    MasteredExport,
    analyse,
    measure_loudness,
    parse_ebur128,
)

from .conftest import needs_ffmpeg


def test_settings_round_trip_and_old_projects():
    p = Project("Film")
    assert not p.mastering.enabled
    p.mastering = cm.preset("cinema")
    p.mastering.enabled = True
    p.mastering.video.matches = {"abc": [1.1, 1.0, 0.9, 0.01, 0.0, -0.01]}
    again = Project.from_dict(json.loads(json.dumps(p.to_dict())))
    assert again.mastering == p.mastering
    data = p.to_dict()
    del data["mastering"]  # projet d'une version précédente
    assert Project.from_dict(data).mastering == cm.Mastering()
    data["mastering"] = {"enabled": True, "video": {"look": "bw", "inconnu": 1},
                         "audio": {"eq": [1, 2]}}  # champ inconnu, égaliseur incomplet
    loaded = Project.from_dict(data).mastering
    assert loaded.enabled and loaded.video.look == "bw" and loaded.audio.eq == [0.0] * 5
    assert Project.from_dict({**data, "mastering": "n'importe quoi"}).mastering == cm.Mastering()


def test_presets_and_summaries():
    current = cm.preset("youtube")
    current.enabled, current.video.match_reference = True, "ref"
    tv = cm.preset("tv", current)
    assert (tv.audio.lufs, tv.audio.true_peak, tv.audio.destination) == (-23.0, -1.0, "tv")
    assert tv.enabled and tv.video.match_reference == "ref"
    assert cm.preset("cinema").audio.layout == "surround"
    assert "−23 LUFS" in tv.summary_audio() and "Naturel" in tv.summary_video()
    a = cm.AudioMaster()
    cm.set_tone(a, "warm")
    assert a.eq == list(cm.TONES["warm"][1])
    cm.set_destination(a, "inconnue")
    assert a.destination == "custom"


def test_user_presets(isolated_home):
    m = cm.preset("podcast")
    m.enabled = True
    m.video.matches = {"x": [1, 1, 1, 0, 0, 0]}
    cm.save_user_preset("Émission", m)
    saved = cm.user_presets()["Émission"]
    assert saved.audio.lufs == -16.0 and saved.preset == "Émission"
    assert not saved.enabled and saved.video.matches == {}  # propre au projet : non gardé


def test_video_filters():
    v = cm.VideoMaster(look="teal_orange", look_amount=0.5, tint=0.3, grain=0.2, vignette=0.5)
    names = [n for n, _p in mst.video_master_filters(v)]
    assert names[-1] == "avfilter.lutrgb"  # niveaux légaux en dernier
    assert {"avfilter.colorbalance", "avfilter.noise", "avfilter.vignette"} <= set(names)
    v.legal = False
    assert mst.video_master_filters(cm.VideoMaster(legal=False)) == []
    assert mst.look_filters("lut", 1, "") == []
    assert mst.look_filters("lut", 0.2, "/l.cube")[0][1]["av.file"] == "/l.cube"
    assert mst.look_filters("cinema", 0) == []
    assert mst.consumer_color(cm.VideoMaster(color_space="srgb"))["color_trc"] == "iec61966-2-1"
    props = mst.match_filter([1.2, 1.0, 0.8, 0.1, 0.0, -0.1], 0.5)[1]
    assert props["av.r"] == "clip(val*1.1000+0.0500*maxval,0,maxval)"


def test_audio_filters():
    a = cm.AudioMaster(eq=[3, 0, -2, 0, 4], compress=0.5, width=1.5, true_peak=-1)
    filters = mst.audio_master_filters(a, gain_db=4.5)
    names = [n for n, _p in filters]
    # l'égaliseur biquad de FFmpeg est sans effet via MLT : il passe par sox
    effects = [p["effect"] for n, p in filters if n == "sox"]
    assert effects == ["highpass 70", "bass 3 60", "equalizer 1000 1.2q -2", "treble 4 12000"]
    assert names[-2:] == ["volume", "avfilter.alimiter"]
    assert filters[-2][1]["level"] == 4.5
    assert filters[-1][1]["av.limit"] == pytest.approx(10 ** (-2 / 20), abs=1e-4)
    assert "avfilter.alimiter" not in [n for n, _p in mst.audio_master_filters(a, limiter=False)]
    assert mst.loudness_gain(-20.0, -14.0) == 6.0 and mst.loudness_gain(-70.0, -14.0) == 0.0
    assert mst.loudness_gain(None, -14.0) == 0.0 and mst.loudness_gain(-80.0, -14) == 0.0


def _spec(voice: bool = True) -> TimelineSpec:
    return TimelineSpec(Canvas(320, 180, 25), (
        TrackSpec("video", False, False, (ClipSpec("a.mp4", "video", 0, 50, key="a"),
                                          ClipSpec("b.png", "image", 50, 25, key="b")),
                  role="video"),
        TrackSpec("audio", False, False, (ClipSpec("v.wav", "audio", 0, 75),),
                  role="voice" if voice else "music"),
        TrackSpec("audio", False, False, (ClipSpec("m.wav", "audio", 0, 75),), role="music"),
    ))


def test_apply_master_roles_stems_and_matches():
    spec = _spec()
    assert mst.dialog_tracks(spec) == {1}
    assert mst.dialog_tracks(_spec(voice=False)) == {0}  # le son des vidéos
    m = cm.Mastering()
    m.audio.voice_front = 1.0
    m.video.match_shots = True
    m.video.matches = {"a": [1.1, 1, 1, 0, 0, 0], "b": [1, 1, 1, 0, 0, 0.1], "x": [1]}
    out = mst.apply_master(spec, m, gain_db=3)
    assert out.tracks[1].volume == pytest.approx(10 ** (2 / 20))
    assert out.tracks[2].volume == pytest.approx(10 ** (-8 / 20))
    assert all(c.extra_filters[-1][0] == "avfilter.lutrgb" for c in out.tracks[0].clips)
    assert ("volume", {"level": 3}) in out.master.audio and out.master.video
    dialog = mst.apply_master(spec, m, stem="dialog", video=False)
    assert [t.muted for t in dialog.tracks] == [True, False, True] and not dialog.master.video
    music = mst.apply_master(spec, m, stem="music")
    assert [t.muted for t in music.tracks] == [False, True, False]
    assert mst.has_sound(spec, "dialog") and not mst.has_sound(TimelineSpec(spec.canvas, ()))


def test_match_values_and_stats():
    ref = [0.5, 0.5, 0.5, 0.2, 0.2, 0.2]
    shot = [0.4, 0.5, 0.6, 0.1, 0.2, 0.4]
    values = mst.match_values(ref, shot)
    assert values[:3] == [1.33, 1.0, 0.75]  # gain borné
    assert values[3] == pytest.approx(0.5 - 1.33 * 0.4, abs=1e-3)
    assert mst.deviation(ref, ref) == 0 and mst.deviation(ref, shot) > 0.1
    white = bytes([255, 255, 255, 255]) * 4
    assert mst.clipped_fraction(white, 2, 2) == 1.0
    assert mst.frame_stats(white, 2, 2)[:3] == [1.0, 1.0, 1.0]


def test_parse_ebur128():
    log = ("[Parsed_ebur128_0 @ 0x1] t: 0.1 TARGET:-23 LUFS M:-30.0 S:-120.7 I: -70.0 LUFS\n"
           "[Parsed_ebur128_0 @ 0x1] t: 0.2 TARGET:-23 LUFS M:-20.0 S:-18.5 I: -19.0 LUFS\n"
           "[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n    I:  -19.2 LUFS\n"
           "    Threshold: -29.3 LUFS\n\n  Loudness range:\n    LRA:   6.4 LU\n\n"
           "  True peak:\n    Peak:  -2.5 dBFS\n")
    found = parse_ebur128(log)
    assert (found.integrated, found.lra, found.true_peak) == (-19.2, 6.4, -2.5)
    assert found.curve == [-70.0, -18.5]
    assert parse_ebur128("rien") is None


# --- moteur ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    return get_engine()


def _media_spec(media_dir) -> TimelineSpec:
    clip, red = str(media_dir / "clip.mp4"), str(media_dir / "red.mp4")
    return TimelineSpec(Canvas(320, 180, 25), (
        TrackSpec("video", False, False, (
            ClipSpec(clip, "video", 0, 50, media_size=(640, 360), key="clip"),
            ClipSpec(red, "video", 50, 50, media_size=(64, 36), key="red")), role="video"),
        TrackSpec("audio", False, False, (ClipSpec(str(media_dir / "son.wav"), "audio", 0, 75,
                                                   key="son"),), role="music"),
    ))


def _probe(path) -> list[dict]:
    out = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                          "stream=codec_type,channels,color_transfer", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


@needs_ffmpeg
def test_master_filters_apply_in_engine(engine, media_dir):
    spec = _media_spec(media_dir)
    m = cm.Mastering()
    m.video.look, m.video.look_amount = "bw", 1.0
    source = engine.build(mst.apply_master(spec, m))
    data = source.render(60, 32, 18)  # plan rouge, passé en noir et blanc
    r, g, b = data[0], data[1], data[2]
    assert abs(r - g) <= 4 and abs(g - b) <= 4
    m.video.look = ""
    assert source.update(mst.apply_master(spec, m))  # finition changée sans reconstruction
    r, g, b = source.render(60, 32, 18)[:3]
    assert r > 150 and g < 80


@needs_ffmpeg
def test_analyse_measures_and_matches(engine, media_dir):
    spec = _media_spec(media_dir)
    result = analyse(engine, spec, cm.preset("youtube"), full=True)
    assert [s.key for s in result.shots] == ["clip", "red"] and result.reference == "clip"
    assert result.matches["clip"] == [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    assert result.shots[1].deviation > 0.1 and len(result.shots[0].thumb) == 96 * 54 * 4
    assert result.loudness is not None and result.spectrum
    assert result.gain_db == pytest.approx(-14 - result.loudness.integrated, abs=0.01)
    assert result.dialog_lufs is not None and result.music_lufs is not None
    assert result.clipped is not None


@needs_ffmpeg
@pytest.mark.parametrize("fmt,codec,layout,channels", [
    ("mp4", "h264", "stereo", 2),
    ("mp4", "h264", "surround", 6),
    ("webm", "vp9", "surround", 6),
    ("mov", "h264", "stems", 2),
    ("wav", "", "surround", 6),
    ("mp3", "", "surround", 2),  # 5.1 impossible : repli en stéréo, signalé
])
def test_mastered_export(engine, media_dir, tmp_path, fmt, codec, layout, channels):
    m = cm.preset("youtube")
    m.enabled, m.audio.layout = True, layout
    target = tmp_path / f"film.{fmt}"
    size = (0, 0) if fmt in ("wav", "mp3") else (320, 180)
    job = MasteredExport(engine, _media_spec(media_dir),
                         ExportSettings(str(target), fmt, codec, *size, 25), m, "", "Film")
    job.start()
    assert job.wait(180) and not job.error, job.error
    assert job.progress == 1.0 and job.phase == "check"
    streams = {s["codec_type"]: s for s in _probe(target)}
    assert streams["audio"]["channels"] == channels
    if size[0]:
        assert streams["video"].get("color_transfer") == "bt709"
    loud = measure_loudness(str(target))
    assert loud.integrated == pytest.approx(-14, abs=1.0) and loud.true_peak <= -0.8
    assert job.conform, job.report_text()
    report = (tmp_path / "film.rapport.txt").read_text(encoding="utf-8")
    assert "Film" in report and "Loudness intégrée" in report and "Conforme" in report
    if layout == "stems":
        names = sorted(p.name for p in tmp_path.glob("*.wav"))
        assert names == ["film - Dialogues.wav", "film - Musique et effets.wav"]
    if fmt == "mp3":
        assert any("5.1" in n for n in job.notes)


@needs_ffmpeg
def test_mastered_export_cancel(engine, media_dir, tmp_path):
    m = cm.preset("youtube")
    target = tmp_path / "film.mp4"
    job = MasteredExport(engine, _media_spec(media_dir),
                         ExportSettings(str(target), "mp4", "h264", 320, 180, 25), m)
    job.cancel()
    job.start()
    assert job.wait(60) and job.cancelled and not target.exists()
