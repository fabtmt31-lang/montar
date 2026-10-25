# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Pluie » : préréglages, filtres de l'ambiance, calques des gouttes."""
from types import SimpleNamespace

import pytest

from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.modules.pluie import core
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg


@pytest.fixture
def rain(tmp_path):
    m = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    m.load_all()
    assert m.modules["pluie"].active
    return next(e for mid, e in m.effects() if e.id == "pluie.pluie")


class _Context(SimpleNamespace):
    def schedule_job(self, key, title, work, done=None):
        self.jobs.setdefault(key, work)


def _context(tmp_path, width=160, height=90, fps=10):
    return _Context(width=width, height=height, fps=fps, cache_dir=tmp_path / "cache", jobs={})


def _names(filters):
    return [name for name, _p in filters]


def test_presets_set_the_sliders(rain):
    values = rain.adjust({**rain.defaults(), "preset": "orage"}, "preset")
    assert values["eclairs"] is True and values["volume"] == core.PRESETS["orage"]["volume"]
    same = rain.adjust({**values, "volume": core.PRESETS["orage"]["volume"]}, "volume")
    assert same["preset"] == "orage"
    moved = rain.adjust({**values, "volume": 0.1}, "volume")
    assert moved["preset"] == core.CUSTOM and moved["volume"] == 0.1
    assert rain.adjust({**moved, "surface": "vitre"}, "surface")["preset"] == core.CUSTOM
    defaults = rain.defaults()
    assert all(defaults[k] == v for k, v in core.PRESETS["pluie"].items())


def test_settings_are_clamped():
    s = core.Settings.from_values({"volume": 3, "taille": "x", "surface": "toit",
                                   "variante": -4, "brume": -1})
    assert (s.volume, s.taille, s.surface, s.variante, s.brume) == (1.0, 0.5, "objectif", 1, 0)


def test_ambiance_darkens_and_cools():
    assert core.ambiance_filters(core.Settings(ambiance=0)) == []
    (eq, eq_props), (levels, lv) = core.ambiance_filters(core.Settings(ambiance=1))
    assert (eq, levels) == ("avfilter.eq", "avfilter.colorlevels")
    assert eq_props["av.saturation"] < 1 and eq_props["av.gamma"] < 1
    assert lv["av.romin"] > 0 and lv["av.romax"] < lv["av.bomax"] <= 1  # plus froid


def test_flashes():
    points = core.flash_points(500, 25, 3)
    assert points == core.flash_points(500, 25, 3)  # même variante : mêmes éclairs
    assert points[0] == (0, 1.0) and points[-1] == (499, 1.0)
    frames = [f for f, _v in points]
    assert frames == sorted(set(frames)) and max(v for _f, v in points) > 1.5
    (name, props), = core.lightning_filters(core.Settings(eclairs=True), 500, 25)
    assert name == "brightness" and (props["in"], props["out"]) == (0, 499)
    assert core.lightning_filters(core.Settings(eclairs=False), 500, 25) == []


def test_loop_and_cache_key(tmp_path):
    assert core.loop_frames(core.Settings(anime=False, chute=0), 25) == (1, 1)
    assert core.loop_frames(core.Settings(anime=False, chute=0.5), 25) == (1, 125)
    assert core.loop_frames(core.Settings(), 25) == (125, 125)
    base = core.cache_folder(tmp_path, core.Settings(), 1920, 1080, 25)
    # l'ambiance est faite de filtres instantanés : les gouttes ne sont pas recalculées
    assert core.cache_folder(tmp_path, core.Settings(ambiance=0.1, brume=0.9), 1920, 1080,
                             25) == base
    assert core.cache_folder(tmp_path, core.Settings(volume=0.9), 1920, 1080, 25) != base
    assert core.cache_folder(tmp_path, core.Settings(variante=2), 1920, 1080, 25) != base
    assert core.layer_size(3840, 2160) == (1920, 1080)


def test_without_context_only_ambiance(rain):
    assert _names(rain.filters(rain.defaults())) == ["avfilter.eq", "avfilter.colorlevels"]


def test_drop_scene_is_drawn():
    np = pytest.importorskip("numpy")
    scene = core._Scene(core.Settings(volume=1, chute=1), 320, 180, 20)
    mask, over = scene.frame(3, True, True)
    assert mask.shape == (180, 320) and over.shape == (180, 320, 4)
    assert mask.max() == 255 and 0.02 < (mask > 0).mean() < 0.8
    assert over[..., 3].max() > 100 and not np.isnan(over).any()
    again, _o = core._Scene(core.Settings(volume=1, chute=1), 320, 180, 20).frame(3, True, True)
    assert (again == mask).all()  # même variante : mêmes gouttes
    other, _o = core._Scene(core.Settings(volume=1, chute=1, variante=2), 320, 180,
                            20).frame(3, True, True)
    assert (other != mask).any()


@needs_ffmpeg
def test_layers_are_computed_then_used(rain, tmp_path):
    context = _context(tmp_path)
    values = rain.adjust({**rain.defaults(), "preset": "averse"}, "preset")
    clip = SimpleNamespace(duration=40)
    first = rain.clip_filters(context, clip, values)
    assert "mask_start" not in _names(first)  # gouttes pas encore calculées
    (key, work), = context.jobs.items()
    assert key.startswith("pluie:")
    rain.clip_filters(context, clip, values)
    assert len(context.jobs) == 1  # une seule tâche par réglage
    ratios = []
    work(ratios.append, lambda: False)
    assert ratios[-1] == 1.0
    filters = rain.clip_filters(context, clip, values)
    names = _names(filters)
    assert names[:2] == ["avfilter.eq", "avfilter.colorlevels"]
    assert names.index("mask_start") < names.index("mask_apply") < len(names) - 1
    assert names[-1] == "watermark"  # le calque des gouttes, par-dessus tout
    folder = core.cache_folder(context.cache_dir, core.Settings.from_values(values), 160, 90,
                               10)
    leftovers = [p for p in folder.parent.iterdir() if p.is_dir() and p != folder]
    assert core.ready(folder) and not leftovers  # aucun dossier de travail laissé
    stormy = rain.adjust({**values, "preset": "orage"}, "preset")
    assert _names(rain.clip_filters(context, clip, stormy))[-1] == "brightness"


@needs_ffmpeg
def test_layer_job_can_be_cancelled(tmp_path):
    folder = tmp_path / "pluie" / "abc"
    with pytest.raises(core.Cancelled):
        core.render_layers(folder, core.Settings(), 160, 90, 10, cancelled=lambda: True)
    assert not folder.exists() and not list((tmp_path / "pluie").iterdir())


@needs_ffmpeg
def test_rain_renders(rain, tmp_path, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    context = _context(tmp_path, 64, 36, 25)
    values = rain.adjust({**rain.defaults(), "preset": "averse", "brume": 0}, "preset")
    clip = SimpleNamespace(duration=50)
    rain.clip_filters(context, clip, values)
    for work in context.jobs.values():
        work(lambda r: None, lambda: False)
    engine = get_engine()

    def render(filters):
        spec = ClipSpec(str(media_dir / "clip.mp4"), "video", 0, 50, media_size=(640, 360),
                        extra_filters=tuple(filters))
        source = engine.build(TimelineSpec(Canvas(64, 36, 25),
                                           (TrackSpec("video", False, False, (spec,)),)))
        try:
            return source.render(10, 64, 36)
        finally:
            source.close()

    def brightness(data):
        return sum(data[i] + data[i + 1] + data[i + 2] for i in range(0, len(data), 4))

    plain = render([])
    mood = render(core.ambiance_filters(core.Settings.from_values(values)))
    wet = render(rain.clip_filters(context, clip, values))
    assert brightness(mood) < brightness(plain) * 0.85  # jour de pluie : plus sombre
    assert wet != mood  # les gouttes sont posées sur l'image


@needs_ffmpeg
def test_outdated_layers_are_abandoned(rain, tmp_path):
    context = _context(tmp_path)
    clip = SimpleNamespace(id="c1", duration=40)
    rain.clip_filters(context, clip, {**rain.defaults(), "volume": 0.3})
    rain.clip_filters(context, clip, {**rain.defaults(), "volume": 0.9})  # curseur glissé
    old, new = context.jobs.values()
    old(lambda r: None, lambda: False)  # abandonné sans erreur
    assert not [p for p in (context.cache_dir / "pluie").iterdir() if p.is_dir()]
    new(lambda r: None, lambda: False)
    assert "mask_start" in _names(rain.clip_filters(context, clip,
                                                    {**rain.defaults(), "volume": 0.9}))
    # glisser d'un curseur : des positions proches donnent les mêmes calques
    assert core.Settings.from_values({"volume": 0.51}) == core.Settings.from_values(
        {"volume": 0.49})
