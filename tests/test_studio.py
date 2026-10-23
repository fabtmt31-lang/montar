# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Studio » : fond vert et stabilisation."""
import subprocess

import pytest

from montar.core.project import Clip
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg


@pytest.fixture
def studio(tmp_path):
    m = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    m.load_all()
    assert m.modules["studio"].active
    return m


def test_studio_registers(studio):
    effects = {e.id: e for mid, e in studio.effects() if mid == "studio"}
    tools = {t.id for mid, t in studio.tools() if mid == "studio"}
    assert set(effects) == {"studio.fond_vert"}
    assert tools == {"studio.stabiliser", "studio.retirer_stabilisation"}
    key = effects["studio.fond_vert"]
    (name, props), (spill, _p) = key.filters(key.defaults())
    assert name == "avfilter.colorkey" and props["av.color"] == "0x00FF00"
    blue = key.filters({**key.defaults(), "couleur": "bleu", "debordement": 0})
    assert len(blue) == 1 and blue[0][1]["av.color"] == "0x0047BB"


@needs_ffmpeg
def test_green_screen_shows_lower_track(studio, tmp_path, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    green = tmp_path / "green.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x00FF00:size=64x36:rate=25:duration=1,"
                    "drawbox=x=24:y=12:w=16:h=12:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(green)], check=True)
    key = next(e for mid, e in studio.effects() if e.id == "studio.fond_vert")
    lower = ClipSpec(str(media_dir / "blue.mp4"), "video", 0, 20, media_size=(64, 36))
    upper = ClipSpec(str(green), "video", 0, 20, media_size=(64, 36),
                     extra_filters=tuple(key.filters(key.defaults())))
    source = get_engine().build(TimelineSpec(Canvas(64, 36, 25), (
        TrackSpec("video", False, False, (lower,)), TrackSpec("video", False, False, (upper,)))))
    data = source.render(5, 64, 36)
    source.close()

    def px(x, y):
        i = (y * 64 + x) * 4
        return tuple(data[i:i + 3])
    assert px(4, 4)[2] > 200 and px(4, 4)[1] < 60  # fond vert remplacé par le bleu
    assert px(32, 18)[0] > 200  # sujet rouge conservé


@needs_ffmpeg
def test_stabilize_produces_steadier_video(tmp_path):
    from montar.modules.studio import core

    if not core.available():
        pytest.skip("ffmpeg sans vid.stab")
    shaky = tmp_path / "shaky.mp4"
    # mire décalée d'un côté à l'autre une image sur deux : tremblement artificiel
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=25:duration=2",
                    "-vf", "crop=280:160:x='20+12*mod(n\\,2)':y='10+8*mod(n\\,2)',scale=320:180",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(shaky)], check=True)
    target = core.cache_path(tmp_path / "cache", str(shaky), 0.5)
    steps = []
    core.stabilize(str(shaky), target, 0.5, 2.0, steps.append, lambda: False)
    assert target.exists() and steps[-1] == 1.0
    assert len(steps) > 2 and all(0 <= s <= 1 for s in steps)  # avancement au fil de l'eau
    with pytest.raises(core.StabilizeError):
        core.stabilize(str(shaky), tmp_path / "x.mp4", 0.5, 2.0, lambda p: None, lambda: True)
    assert not (tmp_path / "x.mp4").exists()


def test_stabilize_settings_and_source(tmp_path):
    from montar.modules.studio import StabilizedSource, core

    clip = Clip("m", "t", 0, 50, source_in=10)
    assert core.settings_of(clip) is None
    clip.modules["studio"] = {"stabilize": 0.5}
    assert core.strength_of(core.settings_of(clip)) == 0.5

    class Media:
        path = str(tmp_path / "a.mp4")
        duration = 2.0

    class Context:
        cache_dir = tmp_path / "cache"
        fps = 25
        jobs = []

        def schedule_job(self, key, title, work):
            self.jobs.append(key)

    (tmp_path / "a.mp4").write_bytes(b"x")
    context = Context()
    assert StabilizedSource().resolve(context, clip, Media) is None and context.jobs
    path = core.cache_path(context.cache_dir, Media.path, 0.5)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    override = StabilizedSource().resolve(context, clip, Media)
    assert override.path == str(path) and override.source_in == 10
    assert StabilizedSource().badge(clip.modules["studio"]) == "STAB"
