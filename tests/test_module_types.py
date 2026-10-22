# SPDX-License-Identifier: GPL-3.0-or-later
"""API 1.2 : effets audio, transitions, générateurs, formats d'export (module Essentiels)."""
import dataclasses
from pathlib import Path

import pytest

from montar.core.project import Clip, MediaItem, Project, Transition
from montar.core.timeline import Timeline
from montar.engine.base import (
    Canvas,
    ClipOverride,
    ClipSpec,
    TimelineSpec,
    TrackSpec,
    TransitionSpec,
    timeline_spec,
)
from montar.engine.export import ExportSettings, consumer_properties
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg


class _Context:
    def __init__(self, cache: Path, width=64, height=36) -> None:
        self.cache_dir, self.width, self.height, self.fps = cache, width, height, 25


@pytest.fixture
def manager(tmp_path):
    m = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    m.load_all()
    return m


def test_essentials_module_types(manager, tmp_path):
    assert manager.modules["essentiels"].active
    assert {e.id for _m, e in manager.audio_effects()} == {
        "essentiels.echo", "essentiels.egaliseur", "essentiels.niveleur"}
    assert len(manager.transitions()) == 3 and len(manager.generators()) == 2
    assert manager.export_format("essentiels.mkv")[1].extension == ".mkv"
    _m, eq = next((m, e) for m, e in manager.audio_effects() if e.id == "essentiels.egaliseur")
    assert eq.filters(eq.defaults()) == []
    assert eq.filters({"graves": 6, "aigus": -3}) == [("avfilter.bass", {"av.g": 6.0}),
                                                     ("avfilter.treble", {"av.g": -3.0})]
    _m, circle = manager.transition("essentiels.cercle")
    service, props = circle.transition(_Context(tmp_path), 25)
    assert service == "luma" and Path(props["resource"]).read_bytes().startswith(b"P5 320 180")


def test_generators_write_images(manager, tmp_path):
    pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtGui import QImage

    gens = {g.id: g for _m, g in manager.generators()}
    target = tmp_path / "fond.png"
    gens["essentiels.fond"].generate(_Context(tmp_path), {"couleur": "#FF0000"}, target)
    image = QImage(str(target))
    assert (image.width(), image.height()) == (64, 36)
    assert image.pixelColor(10, 10).name() == "#ff0000"
    target = tmp_path / "degrade.png"
    gens["essentiels.degrade"].generate(
        _Context(tmp_path), {"debut": "#000000", "fin": "#FFFFFF", "sens": "horizontal"}, target)
    image = QImage(str(target))
    assert image.pixelColor(0, 5).red() == 0 and image.pixelColor(63, 5).red() == 255


def test_spec_resolves_module_transitions_and_audio_filters():
    project = Project("P", fps=25)
    media = MediaItem("/v.mp4", "video", duration=4.0, width=64, height=36, fps=25,
                      has_audio=True, id="v")
    project.media = [media]
    t = Timeline(project)
    a = t.add_clip(media)
    b = t.add_clip(media)
    a.modules["essentiels.echo"] = {"retard": 300}
    t.add_transition(a.id, b.id, "essentiels.cercle", 10)
    assert project.transitions[0].kind == "essentiels.cercle"
    media.path = __file__  # « existe »

    def hook(clip: Clip, m):
        return ClipOverride(audio_filters=(("avfilter.aecho", {"av.delays": "300"}),))

    spec = timeline_spec(project, hook=hook,
                         transition_hook=lambda kind, d: ("luma", {"softness": 0.1}))
    track = spec.tracks[0]
    assert track.clips[0].audio_filters == (("avfilter.aecho", {"av.delays": "300"}),)
    assert track.transitions[0] == TransitionSpec(0, "essentiels.cercle", 10, "luma",
                                                  (("softness", 0.1),))
    # module absent : fondu enchaîné
    assert timeline_spec(project).tracks[0].transitions[0].kind == "dissolve"
    assert isinstance(project.transitions[0], Transition)


def test_custom_export_properties():
    s = ExportSettings("/x.mkv", "essentiels.mkv", custom=(("f", "matroska"),
                                                          ("vcodec", "libx264")))
    props = consumer_properties(s)
    assert props["f"] == "matroska" and props["ar"] == 48000
    audio = dataclasses.replace(s, custom_audio_only=True)
    assert audio.audio_only and consumer_properties(audio)["vn"] == 1


@needs_ffmpeg
def test_render_with_module_transition_and_audio_effect(manager, media_dir, tmp_path):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    _m, circle = manager.transition("essentiels.cercle")
    service, props = circle.transition(_Context(tmp_path), 10)
    red, blue = str(media_dir / "red.mp4"), str(media_dir / "blue.mp4")
    clips = (ClipSpec(red, "video", 0, 50, media_size=(64, 36)),
             ClipSpec(blue, "video", 40, 50, media_size=(64, 36),
                       audio_filters=(("avfilter.aecho", {"av.delays": "200",
                                                          "av.decays": "0.4"}),)))
    track = TrackSpec("video", False, False, clips,
                      transitions=(TransitionSpec(0, "essentiels.cercle", 10, service,
                                                  tuple(sorted(props.items()))),))
    source = get_engine().build(TimelineSpec(Canvas(64, 36, 25), (track,)))
    try:
        data = source.render(45, 64, 36)  # milieu de la transition : centre bleu, coin rouge
        center = data[(18 * 64 + 32) * 4:(18 * 64 + 32) * 4 + 3]
        corner = data[0:3]
        assert center[2] > 150 and center[0] < 100
        assert corner[0] > 150 and corner[2] < 100
    finally:
        source.close()
