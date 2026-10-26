# SPDX-License-Identifier: GPL-3.0-or-later
"""Module d'exemple « Pluie » (examples/modules/pluie), installé comme un module tiers."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg

FOLDER = Path(__file__).resolve().parent.parent / "examples" / "modules" / "pluie"


@pytest.fixture
def rain(tmp_path):
    m = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    m.load_all()
    m.install_folder(FOLDER, link=True)
    assert m.modules["pluie"].active, m.modules["pluie"].error
    effect = next(e for mid, e in m.effects() if mid == "pluie")
    assert any(s is effect for _m, s in m.sources())
    return effect


@pytest.fixture
def core(rain):
    import sys
    return sys.modules[type(rain).__module__ + ".core"]


class _Context(SimpleNamespace):
    def schedule_job(self, key, title, work, done=None):
        self.jobs.setdefault(key, work)


def _context(tmp_path, width=160, height=90, fps=10):
    return _Context(project=SimpleNamespace(canvas_size=(width, height)), fps=fps,
                    cache_dir=tmp_path / "cache", jobs={})


MEDIA = SimpleNamespace(kind="video", path="/v.mp4")


def _filters(rain, context, clip, values, applied=True):
    """Comme le crochet de rendu de montar : resolve, puis filters. `applied` : comme après
    l'outil « Appliquer la pluie »."""
    import sys

    core = sys.modules[type(rain).__module__ + ".core"]
    override = rain.resolve(context, clip, MEDIA)
    assert (override.path, override.source_in, override.speed) == ("/v.mp4", clip.source_in,
                                                                   clip.speed)
    values = {**rain.defaults(), **values}
    if applied:
        values["_gouttes"] = core.drop_state(core.Settings.from_values(values))
    return rain.filters(values)


def _names(filters):
    return [name for name, _p in filters]


def _clip(**kw):
    return SimpleNamespace(**{"id": "c1", "duration": 40, "source_in": 3, "speed": 1.0, **kw})


def test_weather_and_sliders(core):
    normal = core.Settings.from_values({})
    assert normal.volume == core.PRESETS["pluie"]["volume"] and not normal.eclairs
    storm = core.Settings.from_values({"temps": "orage"})
    assert storm.eclairs and storm.ambiance == 1.0
    assert core.Settings.from_values({"volume": 0}).volume == 0
    assert core.Settings.from_values({"volume": 1}).volume == 1.0
    assert core.Settings.from_values({"temps": "bruine", "volume": 1}).volume == 0.4
    odd = core.Settings.from_values({"volume": "x", "surface": "toit", "variante": -4,
                                     "temps": "neige"})
    assert (odd.volume, odd.surface, odd.variante) == (0.5, "objectif", 1)
    # glisser d'un curseur : des positions proches donnent les mêmes gouttes
    assert core.Settings.from_values({"volume": 0.51}) == core.Settings.from_values(
        {"volume": 0.49})


def test_ambiance_darkens_and_cools(core):
    assert core.ambiance_filters(core.Settings(ambiance=0)) == []
    (eq, eq_props), (levels, lv) = core.ambiance_filters(core.Settings(ambiance=1))
    assert (eq, levels) == ("avfilter.eq", "avfilter.colorlevels")
    assert eq_props["av.saturation"] < 1 and eq_props["av.gamma"] < 1
    assert lv["av.romin"] > 0 and lv["av.romax"] < lv["av.bomax"] <= 1  # plus froid


def test_flashes(core):
    points = core.flash_points(500, 25, 3)
    assert points == core.flash_points(500, 25, 3)  # même variante : mêmes éclairs
    assert points[0] == (0, 1.0) and points[-1] == (499, 1.0)
    frames = [f for f, _v in points]
    assert frames == sorted(set(frames)) and max(v for _f, v in points) > 1.5
    (name, props), = core.lightning_filters(core.Settings(eclairs=True), 500, 25)
    assert name == "brightness" and (props["in"], props["out"]) == (0, 499)
    assert core.lightning_filters(core.Settings(eclairs=False), 500, 25) == []


def test_loop_and_cache_key(core, tmp_path):
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


def test_outside_rendering_only_ambiance(rain):
    assert _names(rain.filters(rain.defaults())) == ["avfilter.eq", "avfilter.colorlevels"]
    assert rain.resolve(_context(Path("/tmp")), _clip(), SimpleNamespace(kind="audio",
                                                                         path="a")) is None


def test_drop_scene_is_drawn(core):
    np = pytest.importorskip("numpy")
    s = core.Settings(volume=1, chute=1)
    mask, over = core._Scene(s, 320, 180, 20).frame(3, True, True)
    assert mask.shape == (180, 320) and over.shape == (180, 320, 4)
    assert mask.max() == 255 and 0.02 < (mask > 0).mean() < 0.8
    assert over[..., 3].max() > 100 and not np.isnan(over).any()
    again, _o = core._Scene(s, 320, 180, 20).frame(3, True, True)
    assert (again == mask).all()  # même variante : mêmes gouttes
    other, _o = core._Scene(core.Settings(volume=1, chute=1, variante=2), 320, 180,
                            20).frame(3, True, True)
    assert (other != mask).any()


@needs_ffmpeg
def test_layers_are_computed_then_used(rain, core, tmp_path):
    context = _context(tmp_path)
    values = {"temps": "averse"}
    first = _filters(rain, context, _clip(), values)
    assert "mask_start" not in _names(first)  # gouttes pas encore calculées
    (key, work), = context.jobs.items()
    assert key.startswith("pluie:")
    _filters(rain, context, _clip(), values)
    assert len(context.jobs) == 1  # une seule tâche par réglage
    ratios = []
    work(ratios.append, lambda: False)
    assert ratios[-1] == 1.0
    names = _names(_filters(rain, context, _clip(), values))
    assert names[:2] == ["avfilter.eq", "avfilter.colorlevels"]
    assert names.index("mask_start") < names.index("mask_apply") < len(names) - 1
    assert names[-1] == "watermark"  # le calque des gouttes, par-dessus tout
    folder = core.cache_folder(context.cache_dir, core.Settings.from_values(values), 160, 90,
                               10)
    leftovers = [p for p in folder.parent.iterdir() if p.is_dir() and p != folder]
    assert core.ready(folder) and not leftovers  # aucun dossier de travail laissé
    assert _names(_filters(rain, context, _clip(), {**values, "eclairs": True}))[-1] == \
        "brightness"


@needs_ffmpeg
def test_outdated_layers_are_abandoned(rain, tmp_path):
    context = _context(tmp_path)
    _filters(rain, context, _clip(), {"volume": 0.3})
    _filters(rain, context, _clip(), {"volume": 0.9})  # curseur glissé
    old, new = context.jobs.values()
    old(lambda r: None, lambda: False)  # abandonné sans erreur
    assert not [p for p in (context.cache_dir / "pluie").iterdir() if p.is_dir()]
    new(lambda r: None, lambda: False)
    assert "mask_start" in _names(_filters(rain, context, _clip(), {"volume": 0.9}))


@needs_ffmpeg
def test_layer_job_can_be_cancelled(core, tmp_path):
    folder = tmp_path / "pluie" / "abc"
    with pytest.raises(core.Cancelled):
        core.render_layers(folder, core.Settings(), 160, 90, 10, cancelled=lambda: True)
    assert not folder.exists() and not list((tmp_path / "pluie").iterdir())


@needs_ffmpeg
def test_rain_renders(rain, core, tmp_path, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    context = _context(tmp_path, 64, 36, 25)
    values = {"temps": "averse", "brume": 0}
    clip = _clip(duration=50)
    _filters(rain, context, clip, values)
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
    wet = render(_filters(rain, context, clip, values))
    assert brightness(mood) < brightness(plain) * 0.85  # jour de pluie : plus sombre
    assert wet != mood  # les gouttes sont posées sur l'image


def test_settings_preview_then_apply(rain, core, tmp_path):
    """Les réglages montrent un aperçu immédiat ; seul « Appliquer » lance le calcul."""
    import sys

    context = _context(tmp_path)
    clip = _clip()
    for volume in (0.2, 0.4, 0.6, 0.8):  # curseur déplacé plusieurs fois
        filters = _filters(rain, context, clip, {"volume": volume}, applied=False)
        shape = next(p for n, p in filters if n == "mask_start")
        assert shape["filter.resource"].endswith(core.PREVIEW_MASK)
        assert Path(shape["filter.resource"]).exists()
    assert context.jobs == {}  # aucun calcul lourd pendant les réglages
    values = {**rain.defaults(), "volume": 0.8}
    assert rain.badge(values) == "Pluie · aperçu"

    tool_module = sys.modules[type(rain).__module__]
    tool = tool_module.ApplyRain()
    project_clip = SimpleNamespace(id="c1", modules={"pluie": dict(values)})
    assert tool.available(None, project_clip)
    timeline = SimpleNamespace(clip=lambda clip_id: project_clip)
    editor = SimpleNamespace(edit=lambda label, op: op(timeline))
    tool.run(editor, project_clip)
    applied = project_clip.modules["pluie"]
    assert not tool.available(None, project_clip) and rain.badge(applied) == "Pluie"
    rain.resolve(context, clip, MEDIA)
    rain.filters(applied)
    assert len(context.jobs) == 1  # le calcul complet est demandé
    # l'ambiance ne touche pas aux gouttes : rien à réappliquer
    assert not tool.available(None, SimpleNamespace(modules={"pluie": {**applied,
                                                                     "ambiance": 0.1}}))
    assert tool.available(None, SimpleNamespace(modules={"pluie": {**applied,
                                                                 "volume": 0.1}}))


@needs_ffmpeg
def test_rain_on_webp_image(rain, core, tmp_path):
    """Une image WebP (ouverte par le moteur comme une vidéo d'une image) disparaissait
    derrière la pluie : le module en utilise une copie PNG."""
    pytest.importorskip("mlt7")
    import subprocess

    from montar.engine import get_engine

    image = tmp_path / "photo.webp"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240", "-frames:v", "1", str(image)], check=True)
    context = _context(tmp_path, 64, 36, 25)
    clip = _clip(duration=125, source_in=0)
    override = rain.resolve(context, clip, SimpleNamespace(kind="image", path=str(image)))
    assert override.path.endswith(".png") and Path(override.path).exists()
    assert rain.resolve(context, clip, SimpleNamespace(kind="image", path=str(image))).path \
        == override.path  # copie faite une seule fois
    jpeg = SimpleNamespace(kind="image", path="/photos/chien.jpg")
    assert rain.resolve(context, clip, jpeg).path == "/photos/chien.jpg"
    rain.resolve(context, clip, SimpleNamespace(kind="image", path=str(image)))
    filters = rain.filters(rain.defaults())
    spec = ClipSpec(override.path, "image", 0, 125, media_size=(320, 240),
                    extra_filters=tuple(filters))
    source = get_engine().build(TimelineSpec(Canvas(64, 36, 25),
                                             (TrackSpec("video", False, False, (spec,)),)))
    try:
        data = source.render(56, 64, 36)
    finally:
        source.close()
    middle = [tuple(data[i:i + 3]) for i in range(0, len(data), 4)
              if 14 <= (i // 4) % 64 < 50]
    assert len(set(middle)) > 300  # l'image est bien là (fond gris uni : < 100 couleurs)
