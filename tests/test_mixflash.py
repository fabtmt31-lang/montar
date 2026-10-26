# SPDX-License-Identifier: GPL-3.0-or-later
"""Module d'exemple « Mix Flash » (examples/modules/mixflash)."""
import importlib
import random
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from montar.core.project import MediaItem, Project
from montar.core.timeline import Timeline
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg

FOLDER = Path(__file__).resolve().parent.parent / "examples" / "modules" / "mixflash"


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    manager = ModuleManager(builtin_modules_dir(), tmp_path_factory.mktemp("user"))
    info = manager.install_folder(FOLDER, link=True)
    assert info.active, info.error
    return info.loaded, sys.modules["montar_modules.fab_mixflash.core"]


@pytest.fixture
def core(loaded):
    return loaded[1]


def project(*seconds, fps=25):
    p = Project("Mix", resolution="1080p", fps=fps)
    t = Timeline(p)
    clips = []
    for i, s in enumerate(seconds):
        media = MediaItem(f"/v{i}.mp4", "video", duration=s, width=1920, height=1080, fps=fps,
                          has_audio=True, id=f"m{i}")
        p.media.append(media)
        clips.append(t.add_clip(media))
    return p, t, clips


def coverage(core, clips, created):
    """Images source (média, image) montrées par les extraits."""
    shown = []
    for c in created:
        if c.modules[core.MODULE_ID]["role"] == "piece":
            shown += [(c.media_id, c.source_in + k) for k in range(c.duration)]
    return sorted(shown)


def test_split_lengths_bounds_and_sum(core):
    rng = random.Random(3)
    for total in [*range(1, 400, 7), 1000, 2501]:
        parts = core.split_lengths(total, 12, 125, rng)
        assert sum(parts) == total
        if total > 125:
            assert all(12 <= p <= 125 for p in parts), (total, parts)


def test_split_lengths_tight_bounds(core):
    rng = random.Random(1)
    for total in range(80, 300):
        parts = core.split_lengths(total, 75, 100, rng)
        assert sum(parts) == total


def test_plan_covers_everything_and_respects_settings(core):
    settings = core.Settings(seed=7, probability=1.0, fade_color="white", transition="mix")
    lengths = [355, 240, 275]
    items = core.plan(lengths, 25, settings)
    assert core.covers(lengths, items)
    assert all(12 <= i.length <= 125 for i in items)
    assert sum(i.length for i in items) == sum(lengths)  # transitions par-dessus les images
    for item, following in pairwise(items):
        if item.after == "fade":  # fondus dès 1 s, éclats dès 0,5 s
            assert item.length >= 25 and item.color == "white" and item.fade_out
            assert following.fade_in and following.fade_in_color == "white"
        elif item.after == "burst":
            assert item.length >= 12 and item.burst_out and following.burst_in
            assert following.burst_in >= item.burst_out  # retombée plus longue que la montée
        else:
            assert item.length < 12  # fréquence 100 % : seuls les trop courts n'ont rien
    kinds = {i.after for i in items}
    assert {"fade", "burst"} <= kinds and items[-1].after == ""
    assert core.plan(lengths, 25, settings) == items  # même tirage, même résultat


def test_short_excerpts_get_bursts_not_fades(core):
    settings = core.Settings(seed=3, probability=1.0, transition="mix", min_seconds=0.5,
                             max_seconds=0.9)
    items = core.plan([400], 25, settings)
    assert all(i.length < 25 for i in items)
    assert all(i.after == "burst" for i in items[:-1]) and not any(i.fade_out for i in items)
    fades_only = core.plan([400], 25, core.Settings.from_dict(
        {**settings.__dict__, "transition": "fade"}))
    assert not any(i.after for i in fades_only)


def test_no_adjacent_pieces(core):
    for seed in range(20):
        items = core.plan([500, 300], 25, core.Settings(seed=seed, transition="none"))
        order = [i.piece for i in items]
        assert not any(core._adjacent(a, b) for a, b in pairwise(order))


def test_fades_keep_duration(core):
    settings = core.Settings(seed=2, probability=1.0, transition="fade", max_seconds=5.0,
                             min_seconds=3.0)
    items = core.plan([1000], 25, settings)
    assert all(i.piece is not None for i in items)
    assert sum(i.length for i in items) == 1000
    faded = [i for i in items if i.fade_out]
    assert faded and all(i.fade_out == 10 for i in faded)
    for a, b in pairwise(items):
        assert bool(a.fade_out) == bool(b.fade_in)


def test_apply_replaces_clips_without_losing_frames(core):
    p, t, (a, b, c) = project(14.2, 9.6, 11.0)
    before = [(x.media_id, x.source_in + k) for x in (a, b) for k in range(x.duration)]
    settings = core.Settings(seed=11, probability=1.0)
    created = core.apply(t, [b.id, a.id], settings)
    assert coverage(core, [a, b], created) == sorted(before)
    assert created[0].start == 0
    for x, y in pairwise(created):
        assert x.end == y.start
    assert all(x.volume == 0 for x in created)
    # le clip non choisi est poussé après le mélange
    assert t.clip(c.id).start == created[-1].end
    # le son d'origine est détaché, intact, sur une piste audio
    audio = [x for x in p.clips if t.track(x.track_id).kind == "audio"]
    assert sorted((x.media_id, x.duration) for x in audio) == [("m0", a.duration),
                                                               ("m1", b.duration)]
    # restauration
    restored = core.restore(t, created[3].id)
    assert [(x.media_id, x.start, x.duration) for x in restored] == [
        ("m0", 0, a.duration), ("m1", a.duration, b.duration)]
    assert t.clip(c.id).start == a.duration + b.duration
    assert not any(core.group_of(x) for x in p.clips)


def test_remix_does_not_detach_twice(core):
    p, t, (a,) = project(20.0)
    created = core.apply(t, [a.id], core.Settings(seed=1))
    remixed = core.remix(t, created[0].id, core.Settings(seed=2))
    audio = [x for x in p.clips if t.track(x.track_id).kind == "audio"]
    assert len(audio) == 1
    assert sum(x.duration for x in remixed if core.group_of(x)["role"] == "piece") == 500


def test_reverse_and_speed_sources(core):
    p, t, (a,) = project(30.0)
    t.set_speed(a.id, 2.0)
    clip = t.clip(a.id)
    clip.reverse = True
    created = core.apply(t, [a.id], core.Settings(seed=5, transition="none"))
    starts = sorted(x.source_in for x in created)
    assert starts[0] == clip.source_in
    assert all(x.reverse and x.speed == 2.0 for x in created)


def test_effect_filters(loaded):
    api, core = loaded
    effect = next(e for e in api.effects if e.id == core.MODULE_ID)
    values = {**effect.defaults(), "color": "white", "fade_out": 4, "length": 100,
              "fade_in": 2, "fade_in_color": "black"}
    (white, props), (black, dark) = effect.filters({**values, "fade_in_color": "white",
                                                     "color": "black"})
    assert white == "lift_gamma_gain" and props["lift_r"] == "0=1;2=0"
    assert black == "brightness" and dark["level"] == "95=1;99=0"
    assert (props["in"], props["out"]) == (0, 99)
    (_name, same), = effect.filters(values | {"fade_in_color": "white"})
    assert same["lift_g"] == "0=1;2=0;95=0;99=1"
    full = effect.filters({**effect.defaults(), "full": True, "color": "white"})
    assert full == [("avfilter.lutrgb", {"av.r": "maxval", "av.g": "maxval",
                                         "av.b": "maxval"})]
    assert effect.filters(effect.defaults()) == []
    (name, light), = effect.filters({**effect.defaults(), "length": 50, "burst_out": 2,
                                     "burst_in": 4})
    assert name == "lift_gamma_gain" and (light["in"], light["out"]) == (0, 49)
    assert light["lift_r"] == ("0=1.000;1=0.562;2=0.250;3=0.062;4=0.000;"
                               "47=0.000;48=0.250;49=1.000")
    assert light["gain_b"].startswith("0=1.600;") and light["gain_b"].endswith("49=1.600")
    assert {t.id for t in api.tools} == {"fab.mixflash.apply", "fab.mixflash.remix",
                                         "fab.mixflash.restore"}


def test_dialog_builds(core):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(["montar-tests"])
    dialog_mod = importlib.import_module("montar_modules.fab_mixflash.dialog")
    p, t, clips = project(14.2, 9.6)
    dialog = dialog_mod.MixFlashDialog(None, clips, {clips[0].id}, 25, core.Settings(), False,
                                       names=lambda c: t.media_of(c).name, skipped=1)
    assert dialog.chosen_ids() == [clips[0].id] and not dialog.whole.isChecked()
    assert dialog.ok.isEnabled()
    dialog.whole.click()  # « Toute la piste »
    assert dialog.chosen_ids() == [c.id for c in clips] and dialog.whole.isChecked()
    dialog._reshuffle()
    assert "✓" in dialog.summary.text()
    dialog.transition.button("burst").click()
    assert dialog.settings().transition == "burst" and not dialog.color.isEnabled()
    dialog.whole.click()
    assert dialog.chosen_ids() == [] and not dialog.ok.isEnabled()
    dialog.boxes[clips[1].id].setChecked(True)
    assert dialog.chosen_ids() == [clips[1].id] and not dialog.whole.isChecked()


@needs_ffmpeg
def test_fades_and_bursts_render(loaded, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine
    from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec

    api, core = loaded
    effect = next(e for e in api.effects if e.id == core.MODULE_ID)
    engine = get_engine()

    def render(values, frame):
        filters = effect.filters({**effect.defaults(), **values})
        clip = ClipSpec(str(media_dir / "clip.mp4"), "video", 0, 50, media_size=(640, 360),
                        extra_filters=tuple(filters))
        source = engine.build(TimelineSpec(Canvas(64, 36, 25),
                                           (TrackSpec("video", False, False, (clip,)),)))
        try:
            data = source.render(frame, 64, 36)
        finally:
            source.close()
        return [data[i] for i in range(0, len(data), 4)]  # composante rouge de chaque pixel

    plain = render({}, 25)
    white = render({"full": True, "color": "white"}, 25)
    black = render({"full": True, "color": "black"}, 25)
    assert min(white) >= 250 and max(black) <= 5 and 30 < sum(plain) / len(plain) < 230
    for start, end in (("black", "white"), ("white", "black"), ("white", "white")):
        fading = {"color": end, "fade_out": 10, "length": 50, "fade_in": 10,
                  "fade_in_color": start}
        assert render(fading, 25) == plain  # milieu du clip : intact
        first, last = render(fading, 0), render(fading, 49)
        assert (min(first) >= 250) if start == "white" else (max(first) <= 5)
        assert (min(last) >= 250) if end == "white" else (max(last) <= 5)
        middle = sum(render(fading, 44)) / len(plain)  # à mi-fondu
        assert 5 < middle < 250 and middle != sum(plain) / len(plain)
    burst = {"length": 50, "burst_out": 4, "burst_in": 8}
    mean = sum(plain) / len(plain)
    levels = [sum(render(burst, f)) / len(plain) for f in (25, 46, 48, 49, 0, 3, 8)]
    assert levels[0] == mean  # milieu du clip : intact
    assert mean < levels[1] < levels[2] < levels[3]  # montée jusqu'à la coupe
    assert levels[3] >= 250 and levels[4] >= 250  # pic blanc de part et d'autre de la coupe
    assert levels[4] > levels[5] > levels[6] and abs(levels[6] - mean) < 2  # retombée
