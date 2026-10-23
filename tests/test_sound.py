# SPDX-License-Identifier: GPL-3.0-or-later
"""Son : réglages avancés, normalisation, réduction de bruit, atténuation sous la voix."""
import wave

import pytest

from montar.core.project import AudioAdjust, MediaItem, Project, Track
from montar.core.timeline import Timeline
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec, timeline_spec
from montar.engine.export import ExportSettings
from montar.engine.sound import audio_filters, duck_points, voice_spans

from .conftest import needs_ffmpeg


def test_filters_follow_settings():
    assert audio_filters(AudioAdjust()) == []
    names = [n for n, _p in audio_filters(AudioAdjust(
        denoise=0.5, normalize=True, bass=3, mid=-2, treble=4, highpass=80, lowpass=9000,
        compress=0.5, pitch=2, pan=-0.5, echo=0.3, reverb=0.4))]
    assert names[:3] == ["avfilter.highpass", "avfilter.lowpass", "avfilter.afftdn"]
    assert {"avfilter.dynaudnorm", "rbpitch", "avfilter.stereotools",
            "avfilter.acompressor"} <= set(names)
    assert names.count("avfilter.aecho") == 2


def test_voice_spans_and_duck_points():
    project = Project("p", fps=25)
    voice = Track("audio", "Voix", voice=True)
    music = Track("audio", "Musique")
    project.tracks = [voice, music]
    project.media = [MediaItem("/s.wav", "audio", duration=10, has_audio=True, id="s")]
    tl = Timeline(project)
    tl.add_clip(project.media[0], voice.id, 50, 25)
    tl.add_clip(project.media[0], voice.id, 80, 20)  # 5 images après : fusionnée
    assert voice_spans(project) == [(50, 75), (80, 100)]
    points = duck_points(voice_spans(project), 0, 200, 12, 25)
    assert points[0] == (0, 0.0) and points[-1] == (199, 0.0)
    assert (50, -12.0) in points and (100, -12.0) in points
    assert all(g == -12.0 for f, g in points if 50 <= f <= 100)
    assert duck_points(voice_spans(project), 300, 50, 12, 25) is None
    voice.muted = True
    assert voice_spans(project) == []


def test_timeline_spec_carries_audio_and_duck(tmp_path):
    (tmp_path / "s.wav").write_bytes(b"")
    project = Project("p", fps=25)
    voice = Track("audio", "Voix", voice=True)
    music = Track("audio", "Musique")
    project.tracks = [voice, music]
    project.media = [MediaItem(str(tmp_path / "s.wav"), "audio", duration=10, has_audio=True,
                               id="s")]
    tl = Timeline(project)
    tl.add_clip(project.media[0], voice.id, 25, 25)
    song = tl.add_clip(project.media[0], music.id, 0, 100)
    song.audio = AudioAdjust(duck=True, treble=3)
    spec = timeline_spec(project)
    clip = [t for t in spec.tracks if t.kind == "audio"][1].clips[0]
    assert clip.audio.treble == 3 and clip.duck and (25, -12.0) in clip.duck
    loaded = Project.from_dict(project.to_dict())
    assert loaded.clips[1].audio.duck and loaded.tracks[0].voice


def _levels(path, frames_per_second=25):
    """RMS par image (canaux gauche, droite) d'un WAV 16 bits stéréo."""
    import array

    with wave.open(str(path)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        data = array.array("h", w.readframes(w.getnframes()))
    step = rate // frames_per_second * channels
    out = []
    for i in range(0, len(data) - step + 1, step):
        chunk = data[i:i + step]
        left, right = chunk[0::channels], chunk[1::channels] if channels > 1 else chunk
        out.append(tuple((sum(x * x for x in c) / max(1, len(c))) ** 0.5 for c in (left, right)))
    return out


@needs_ffmpeg
def test_export_applies_sound_settings(media_dir, tmp_path):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    engine = get_engine()
    wav = str(media_dir / "son.wav")  # sinus 220 Hz, 3 s

    def export(name, **clip):
        spec = TimelineSpec(Canvas(64, 36, 25), (
            TrackSpec("audio", False, False, (ClipSpec(wav, "audio", 0, 50, **clip),)),))
        out = tmp_path / f"{name}.wav"
        job = engine.export(spec, ExportSettings(str(out), "wav", "", 0, 0, 25))
        job.start()
        assert job.wait(120) and not job.error, job.error
        return _levels(out)

    plain = export("plain")
    left = export("left", audio=AudioAdjust(pan=-1.0))
    assert left[20][1] < plain[20][1] * 0.2 and left[20][0] > plain[20][0] * 0.8
    ducked = export("duck", duck=((0, 0.0), (10, 0.0), (15, -20.0), (40, -20.0),
                                  (49, -20.0)))
    assert ducked[25][0] < plain[25][0] * 0.2 and ducked[5][0] > plain[5][0] * 0.8
    everything = export("all", audio=AudioAdjust(
        denoise=0.5, normalize=True, bass=3, mid=-2, treble=4, highpass=80, lowpass=9000,
        compress=0.5, pitch=2, echo=0.3, reverb=0.4))
    assert len(everything) >= 45 and max(r[0] for r in everything) > 100
