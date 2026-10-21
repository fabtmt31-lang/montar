# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from montar.core.project import MediaItem, Project
from montar.core.timeline import Timeline, TimelineError
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg


@pytest.fixture(scope="module")
def tl_core(tmp_path_factory):
    manager = ModuleManager(builtin_modules_dir(), tmp_path_factory.mktemp("user"))
    manager.load_all()
    assert manager.is_active("timelapse")
    return sys.modules["montar_modules.timelapse.core"]


def project_with_video(seconds: float, fps: int = 30, path: str = "/v.mp4"):
    p = Project("TL", resolution="1080p", fps=fps)
    media = MediaItem(path, "video", duration=seconds, width=1920, height=1080, fps=fps,
                      has_audio=True, id="v")
    p.media = [media]
    t = Timeline(p)
    clip = t.add_clip(media)
    return p, t, clip


def test_one_frame_every_n(tl_core):
    assert tl_core.frame_indices(400, 40) == list(range(0, 400, 40))
    assert len(tl_core.frame_indices(10800, 40)) == 270
    ramp = tl_core.frame_indices(3000, 20, 30, 30)
    steps = [b - a for a, b in zip(ramp, ramp[1:], strict=False)]
    assert steps[0] <= 2 and max(steps) >= 19 and steps[-1] <= 2  # ×1 → ×20 → ×1
    assert all(s > 0 for s in steps) and ramp[-1] <= 2999


def test_acceptance_duration(tl_core):
    """Cahier des charges §3.9.4 : 10 min à 30 i/s, ×40 de 2 à 8 min → 4 min 9 s."""
    p, t, clip = project_with_video(600)
    segment = tl_core.apply(t, clip.id, 2 * 60 * 30, 8 * 60 * 30, tl_core.Settings(factor=40))
    assert t.length() == (4 * 60 + 9) * 30
    assert segment.duration == 9 * 30 and segment.source_in == 2 * 60 * 30
    assert segment.volume == 0.0  # son coupé par défaut
    before, after = sorted((c for c in p.clips if c is not segment), key=lambda c: c.start)
    assert (before.duration, after.start, after.source_in) == (3600, 3870, 14400)


def test_segment_is_locked_and_removal_merges_back(tl_core):
    p, t, clip = project_with_video(60)
    segment = tl_core.apply(t, clip.id, 300, 900, tl_core.Settings(factor=10))
    assert t.trim_bounds(segment.id, "end") == (segment.end, segment.end)
    assert t.split(segment.id, segment.start + 5) is None
    with pytest.raises(TimelineError):
        t.set_speed(segment.id, 2.0)
    restored = tl_core.remove(t, segment.id)
    assert len(p.clips) == 1 and restored.duration == 1800 and restored.modules == {}
    assert restored.volume == 1.0 and restored.speed == 1.0


def test_reapply_on_existing_segment(tl_core):
    p, t, clip = project_with_video(60)
    segment = tl_core.apply(t, clip.id, 300, 900, tl_core.Settings(factor=10))
    again = tl_core.apply(t, segment.id, segment.start, segment.end, tl_core.Settings(factor=20))
    assert again.duration == 30 and t.length() == 300 + 30 + 900


def test_whole_clip_and_ramps(tl_core):
    p, t, clip = project_with_video(20)
    s = tl_core.Settings(factor=8, ramp="both", ramp_seconds=1.0)
    segment = tl_core.apply(t, clip.id, clip.start, clip.end, s)
    assert len(p.clips) == 1
    assert segment.duration == tl_core.output_frames(600, s, 30)
    assert segment.duration > 600 / 8  # les rampes allongent un peu le segment


@needs_ffmpeg
def test_render_selects_exact_frames(tl_core, tmp_path):
    """Vidéo dont la luminance de l'image n vaut n mod 256 : le pré-calcul doit garder
    exactement les images 300, 340, 380… (×40 à partir de 10 s)."""
    numbered = tmp_path / "numerotee.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=64x36:r=30:d=40,format=gray,geq=lum='mod(N\\,256)'",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(numbered)],
                   check=True, timeout=120)
    p, t, clip = project_with_video(40, path=str(numbered))
    segment = tl_core.apply(t, clip.id, 300, 900, tl_core.Settings(factor=40))
    data = tl_core.settings_of(segment)
    out = tl_core.cache_path(tmp_path, str(numbered), segment.source_in, data, 30)
    progress = []
    tl_core.render(str(numbered), out, segment.source_in, data, 30, progress.append)
    assert progress[-1] == 1.0
    raw = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(out), "-f",
                          "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    frames = [raw[i:i + 64 * 36] for i in range(0, len(raw), 64 * 36)]
    assert len(frames) == segment.duration == 15
    lumas = [f[18 * 64 + 32] for f in frames]
    expected = [(300 + 40 * j) % 256 for j in range(15)]
    assert all(abs(a - b) <= 3 for a, b in zip(lumas, expected, strict=True)), lumas


@needs_ffmpeg
def test_render_blend_and_audio(tl_core, media_dir, tmp_path):
    p, t, clip = project_with_video(2, fps=25, path=str(media_dir / "clip.mp4"))
    s = tl_core.Settings(factor=4, method="blend", audio="speed", deflicker=True)
    segment = tl_core.apply(t, clip.id, clip.start, clip.end, s)
    data = tl_core.settings_of(segment)
    out = tl_core.render(str(media_dir / "clip.mp4"),
                         tmp_path / "blend.mp4", segment.source_in, data, 25)
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-count_frames",
                            "-show_entries", "stream=codec_type,nb_read_frames", "-of",
                            "csv=p=0", str(out)], capture_output=True, text=True).stdout
    streams = dict(line.split(",")[:2] for line in probe.split())
    assert int(streams["video"]) == segment.duration  # son accéléré conservé
    assert "audio" in streams


@needs_ffmpeg
def test_render_can_be_cancelled(tl_core, media_dir, tmp_path):
    p, t, clip = project_with_video(2, fps=25, path=str(media_dir / "clip.mp4"))
    segment = tl_core.apply(t, clip.id, clip.start, clip.end, tl_core.Settings(factor=2))
    out = tmp_path / "annule.mp4"
    with pytest.raises(tl_core.Cancelled):
        tl_core.render(str(media_dir / "clip.mp4"), out, segment.source_in,
                       tl_core.settings_of(segment), 25, cancelled=lambda: True)
    assert not out.exists() and not list(tmp_path.glob("*.part.mp4"))


def _numbered(tmp_path, seconds=40):
    numbered = tmp_path / "numerotee.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:s=64x36:r=30:d={seconds},format=gray,"
                    "geq=lum='mod(N\\,256)'",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(numbered)],
                   check=True, timeout=120)
    return numbered


def _lumas(path):
    raw = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(path), "-f",
                          "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    return [raw[i + 18 * 64 + 32] for i in range(0, len(raw), 64 * 36)]


@needs_ffmpeg
@pytest.mark.parametrize("settings", [
    {"factor": 7.5},
    {"factor": 6, "ramp": "both", "ramp_seconds": 1.0},
    {"factor": 12.3, "ramp": "in", "ramp_seconds": 2.0},
])
def test_render_matches_planned_frames(tl_core, tmp_path, settings):
    """Facteur non entier et rampes : ffmpeg garde exactement les images prévues (la
    sélection est une formule, pas une liste de milliers de termes)."""
    numbered = _numbered(tmp_path, 20)
    p, t, clip = project_with_video(20, path=str(numbered))
    segment = tl_core.apply(t, clip.id, 0, 600, tl_core.Settings(**settings))
    data = tl_core.settings_of(segment)
    cmd, produced = tl_core.ffmpeg_command(str(numbered), tmp_path / "x.mp4", 0, data, 30)
    assert len(cmd[cmd.index("-vf") + 1]) < 4000
    out = tl_core.render(str(numbered), tmp_path / "out.mp4", 0, data, 30)
    lumas = _lumas(out)
    expected = [i % 256 for i in tl_core.frame_indices(
        600, data["factor"], *tl_core.Settings.from_dict(data).ramp_frames(30))]
    assert len(lumas) == produced == segment.duration == len(expected)
    assert all(abs(a - b) <= 3 for a, b in zip(lumas, expected, strict=True)), lumas


def test_long_segment_selection_stays_small(tl_core):
    data = {"factor": 2.7, "ramp": "both", "ramp_seconds": 3.0, "source_frames": 16333}
    cmd, produced = tl_core.ffmpeg_command("x.mp4", Path("y.mp4"), 0, data, 25)
    assert produced > 5000 and len(cmd[cmd.index("-vf") + 1]) < 6000


@needs_ffmpeg
def test_blend_large_factor_is_quick(tl_core, tmp_path):
    numbered = _numbered(tmp_path, 40)
    p, t, clip = project_with_video(40, path=str(numbered))
    segment = tl_core.apply(t, clip.id, 0, 1200, tl_core.Settings(factor=300, method="blend",
                                                                   ramp="both"))
    data = tl_core.settings_of(segment)
    assert data["ramp"] == "none"  # pas de rampe avec la fusion
    out = tl_core.render(str(numbered), tmp_path / "blend.mp4", 0, data, 30)
    assert len(_lumas(out)) == segment.duration == 4


def test_stalled_ffmpeg_is_stopped_and_cancel_works(tl_core, tmp_path, monkeypatch):
    import sys
    import time

    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    monkeypatch.setattr(tl_core, "ffmpeg_command", lambda *a: (sleeper, 10))
    monkeypatch.setattr(tl_core, "STALL_SECONDS", 1)
    data = {"factor": 4, "source_frames": 40}
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="n'avance plus"):
        tl_core.render("x.mp4", tmp_path / "a.mp4", 0, data, 25)
    assert time.monotonic() - start < 6
    monkeypatch.setattr(tl_core, "STALL_SECONDS", 60)
    deadline = time.monotonic() + 0.5
    start = time.monotonic()
    with pytest.raises(tl_core.Cancelled):
        tl_core.render("x.mp4", tmp_path / "b.mp4", 0, data, 25,
                       cancelled=lambda: time.monotonic() > deadline)
    assert time.monotonic() - start < 3
