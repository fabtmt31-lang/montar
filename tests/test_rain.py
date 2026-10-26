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


def _filters(rain, context, clip, values, animated=True):
    """Comme le crochet de rendu de montar : resolve, puis filters. `animated` : comme après
    le bouton « Appliquer la pluie »."""
    import sys

    core = sys.modules[type(rain).__module__ + ".core"]
    override = rain.resolve(context, clip, MEDIA)
    assert (override.path, override.source_in, override.speed) == ("/v.mp4", clip.source_in,
                                                                   clip.speed)
    values = {**rain.defaults(), **values}
    if animated:
        values["_gouttes"] = core.drop_state(core.Settings.from_values(values))
    return rain.filters(values)


def _mask(filters) -> str:
    """Masque des gouttes utilisé : aperçu (dossier « apercu-… ») ou gouttes calculées."""
    return next(p["filter.resource"] for n, p in filters if n == "mask_start")


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
    assert core.loop_frames(core.Settings(volume=0, chute=0), 25) == (1, 1)
    assert core.loop_frames(core.Settings(volume=0, chute=0.5), 25) == (1, 125)
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
    assert "/apercu-" in _mask(first)  # pas encore calculées : l'aperçu
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
    leftovers = [p for p in folder.parent.iterdir()
                 if p.is_dir() and p != folder and not p.name.startswith("apercu-")]
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
    assert not [p for p in (context.cache_dir / "pluie").iterdir()
                if p.is_dir() and not p.name.startswith("apercu-")]
    new(lambda r: None, lambda: False)
    assert "/apercu-" not in _mask(_filters(rain, context, _clip(), {"volume": 0.9}))


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


def test_preview_until_applied(rain, core, tmp_path):
    """Les réglages montrent un aperçu immédiat ; seul « Appliquer la pluie » lance le
    calcul, et toucher ensuite un réglage des gouttes revient à l'aperçu."""
    context = _context(tmp_path)
    clip = _clip()
    for volume in (0.2, 0.4, 0.6, 0.8):  # curseur déplacé plusieurs fois
        filters = _filters(rain, context, clip, {"volume": volume}, animated=False)
        shape = next(p for n, p in filters if n == "mask_start")
        assert shape["filter.resource"].endswith(core.PREVIEW_MASK)
    assert context.jobs == {}  # aucun calcul lourd pendant les réglages
    assert rain.badge(rain.defaults()) == "Pluie · aperçu"

    project_clip = SimpleNamespace(id="c1", modules={"pluie": {"volume": 0.8}})
    timeline = SimpleNamespace(clip=lambda clip_id: project_clip)
    context.edit = lambda label, op: op(timeline)
    rain.apply(context, "c1")
    applied = project_clip.modules["pluie"]
    assert rain.badge(applied) == "Pluie"
    rain.resolve(context, clip, MEDIA)
    filters = rain.filters({**rain.defaults(), **applied})
    assert len(context.jobs) == 1  # le calcul complet est demandé
    assert rain.job_of(context, "c1") is None  # (le contexte de test n'a pas de file)
    # en attendant la fin du calcul, l'aperçu reste affiché
    assert any(p.get("filter.resource", "").endswith(core.PREVIEW_MASK) for _n, p in filters)
    # l'ambiance ne touche pas aux gouttes ; le volume, si
    assert rain.badge({**applied, "ambiance": 0.1}) == "Pluie"
    assert rain.badge({**applied, "volume": 0.1}) == "Pluie · aperçu"


def test_other_clip_source_is_kept(rain, tmp_path):
    """Sur un clip en timelapse, la source pré-calculée du timelapse reste utilisée."""
    context = _context(tmp_path)
    context.manager = SimpleNamespace(sources=lambda: [("timelapse", None), ("pluie", rain)],
                                      effects=lambda: [])
    clip = _clip(modules={"timelapse": {}, "pluie": {}})
    assert rain.resolve(context, clip, MEDIA) is None
    assert "mask_start" in _names(rain.filters(rain.defaults()))  # la pluie est appliquée


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


def test_clip_frame(core):
    from montar.core.project import Transform

    # photo 4:3 dans une toile 16:9 : bandes à gauche et à droite
    assert core.clip_area(1280, 720, 1024, 768) == (0.125, 0.0, 0.75, 1.0)
    assert core.clip_area(1280, 720, 1920, 1080) == core.FULL
    cropped = core.clip_area(1280, 720, 1280, 720, Transform(crop_top=0.25, crop_bottom=0.25))
    assert cropped == (0.0, 0.25, 1.0, 0.5)  # recadrée : bandes en haut et en bas
    # sans transformation : la toile entière, la pluie limitée à la zone de l'image
    assert core.clip_frame(1280, 720, 1024, 768) == ((1280, 720), (0.125, 0.0, 0.75, 1.0),
                                                     1.0)
    # clip placé : le moteur donne l'image seule aux filtres
    assert core.clip_frame(1280, 720, 1024, 768, placed=True) == ((960, 720), core.FULL, 1.0)


def test_placed_clip_is_detected(rain):
    import sys

    from montar.core.project import Transform

    placed = sys.modules[type(rain).__module__]._placed
    assert not placed(None, _clip(transform=Transform(), keyframes={}, modules={}))
    assert placed(None, _clip(transform=Transform(scale=0.5), keyframes={}, modules={}))
    assert placed(None, _clip(transform=Transform(), keyframes={"x": [(0, 0.1)]}, modules={}))


@needs_ffmpeg
def test_preview_rain_falls(rain, core, tmp_path):
    """Pendant les réglages, les gouttes sont figées mais la pluie tombe."""
    folder = core.preview_layers(tmp_path, core.Settings(chute=0.6), 320, 180)
    assert (folder / core.PREVIEW_RAIN).exists()
    names = [p.get("resource", "") for _n, p in core.drop_filters(folder, core.Settings(chute=0.6),
                                                                  180, preview=True)]
    assert any(n.endswith(core.PREVIEW_RAIN) for n in names)
    dry = core.preview_layers(tmp_path, core.Settings(chute=0.0), 320, 180)
    assert not (dry / core.PREVIEW_RAIN).exists()


@needs_ffmpeg
def test_rain_stays_inside_the_image(rain, core, tmp_path):
    """Photo 4:3 dans une toile 16:9, sur une piste au-dessus d'une vidéo rouge : la pluie
    ne déborde pas sur les bandes, qui laissent voir la piste du dessous, et l'image garde
    sa taille, qu'elle soit posée telle quelle ou réduite."""
    pytest.importorskip("mlt7")
    import subprocess

    from montar.core.project import Transform
    from montar.engine import get_engine

    def make(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", *args], check=True)

    photo, red = tmp_path / "photo.jpg", tmp_path / "rouge.mp4"
    make("-i", "color=c=gray:size=400x300", "-frames:v", "1", str(photo))
    make("-i", "color=c=red:size=160x90:rate=25:duration=2", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(red))
    context = _context(tmp_path, 160, 90, 25)
    media = SimpleNamespace(kind="image", path=str(photo), width=400, height=300)
    engine = get_engine()

    def content(transform, filters):
        spec = TimelineSpec(Canvas(160, 90, 25), (
            TrackSpec("video", False, False, (ClipSpec(str(red), "video", 0, 50,
                                                       media_size=(160, 90)),)),
            TrackSpec("video", False, False, (ClipSpec(str(photo), "image", 0, 50,
                                                       media_size=(400, 300),
                                                       transform=transform,
                                                       extra_filters=tuple(filters)),))))
        source = engine.build(spec)
        try:
            data = source.render(10, 160, 90)
        finally:
            source.close()
        row = [tuple(data[(45 * 160 + x) * 4:(45 * 160 + x) * 4 + 3]) for x in range(160)]
        inside = [x for x, (r, g, b) in enumerate(row) if not (r > 200 and g < 60 and b < 60)]
        return inside[0], inside[-1]

    for transform in (Transform(), Transform(scale=0.6)):
        clip = _clip(duration=50, transform=transform, keyframes={}, modules={})
        values = {"temps": "averse", "_gouttes": core.drop_state(
            core.Settings.from_values({"temps": "averse"}))}
        rain.resolve(context, clip, media)
        rain.filters({**rain.defaults(), **values})
        for work in list(context.jobs.values()):
            work(lambda r: None, lambda: False)
        rain.resolve(context, clip, media)
        filters = rain.filters({**rain.defaults(), **values})
        assert "mask_start" in _names(filters)
        expected = content(transform, [])
        got = content(transform, filters)
        assert abs(got[0] - expected[0]) <= 1 and abs(got[1] - expected[1]) <= 1, \
            (transform, expected, got)


_WINDOWS_LIKE = r"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from montar.core.project import Transform
from montar.engine import get_engine
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.plugins import ModuleManager, builtin_modules_dir
tmp = Path(sys.argv[2])
m = ModuleManager(builtin_modules_dir(), tmp / "user")
m.load_all()
m.install_folder(Path(sys.argv[3]), link=True)
rain = next(e for mid, e in m.effects() if mid == "pluie")
jobs = []
ctx = SimpleNamespace(project=SimpleNamespace(canvas_size=(320, 180)), fps=25,
                      cache_dir=tmp / "cache", jobs=None,
                      schedule_job=lambda k, t, w, d=None: jobs.append(w))
clip = SimpleNamespace(id="c", duration=100, source_in=0, speed=1.0, transform=Transform(),
                       keyframes={}, modules={})
media = SimpleNamespace(kind="video", path=sys.argv[4], width=160, height=160)
rain.resolve(ctx, clip, media)
filters = rain.filters(rain.defaults())
source = get_engine().build(TimelineSpec(Canvas(320, 180, 25), (TrackSpec(
    "video", False, False, (ClipSpec(media.path, "video", 0, 100, media_size=(160, 160),
                                     extra_filters=tuple(filters)),)),)))
data = source.render(60, 320, 180)
white = sum(1 for i in range(0, len(data), 4) if min(data[i:i + 3]) > 235)
print("BLANCS", white)
"""


@needs_ffmpeg
def test_no_white_area_without_gdk(tmp_path):
    """Sous Windows, MLT n'a pas le module « gdk » : les images PNG sont ouvertes comme
    des vidéos d'une image, et superposées elles devenaient blanches au-delà de la
    première image du clip (carré blanc). Les calques fixes sont donc des vidéos."""
    pytest.importorskip("mlt7")
    import os
    import subprocess
    import sys

    video = tmp_path / "carre.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x160:rate=25:duration=4", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    src = Path(__file__).resolve().parent.parent / "src"
    env = {**os.environ, "MLT_REPOSITORY_DENY": "libmltgdk"}
    done = subprocess.run([sys.executable, "-c", _WINDOWS_LIKE, str(src), str(tmp_path),
                           str(FOLDER), str(video)], capture_output=True, text=True,
                          env=env, timeout=120)
    line = [x for x in done.stdout.splitlines() if x.startswith("BLANCS")]
    assert line, done.stderr[-2000:]
    assert int(line[0].split()[1]) < 50
