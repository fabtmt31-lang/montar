# SPDX-License-Identifier: GPL-3.0-or-later
"""Module d'exemple « Super 8 » (examples/modules/super8), installé comme un module tiers."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg

FOLDER = Path(__file__).resolve().parent.parent / "examples" / "modules" / "super8"


@pytest.fixture
def effect(tmp_path):
    m = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    m.load_all()
    m.install_folder(FOLDER, link=True)
    assert m.modules["super8"].active, m.modules["super8"].error
    found = next(e for mid, e in m.effects() if mid == "super8")
    assert any(s is found for _m, s in m.sources())
    assert any(t.id == "super8.bruit" for _m, t in m.tools())
    return found


@pytest.fixture
def core(effect):
    return sys.modules[type(effect).__module__ + ".core"]


class _Context(SimpleNamespace):
    def schedule_job(self, key, title, work, done=None):
        self.jobs.setdefault(key, work)


def _context(tmp_path, width=320, height=180, fps=25):
    return _Context(project=SimpleNamespace(canvas_size=(width, height)), fps=fps,
                    cache_dir=tmp_path / "cache", jobs={})


def _clip(**kw):
    return SimpleNamespace(**{"id": "c1", "duration": 50, "source_in": 0, "speed": 1.0,
                              "modules": {}, "keyframes": {}, "transform": None, **kw})


def _filters(effect, context, clip, media, values):
    effect.resolve(context, clip, media)
    return effect.filters({**effect.defaults(), **values})


def _names(filters):
    return [n for n, _p in filters]


def test_styles_and_sliders(core):
    normal = core.Settings.from_values({})
    assert normal.pellicule == "kodachrome" and normal.cadre == "fenetre"
    assert normal.poussieres == core.STYLES["vacances"]["poussieres"]
    worn = core.Settings.from_values({"style": "abime"})
    assert worn.pellicule == "fanee" and worn.poussieres > normal.poussieres
    assert core.Settings.from_values({"grain": 0}).grain == 0
    # l'usure pilote poussières, fuites, scintillement et instabilité, pas le grain
    new = core.Settings.from_values({"usure": 0})
    assert (new.poussieres, new.fuites, new.scintillement, new.instabilite) == (0, 0, 0, 0)
    assert new.grain == normal.grain
    odd = core.Settings.from_values({"pellicule": "agfa", "cadre": "rond", "grain": "x",
                                     "variante": -3, "style": "inconnu"})
    assert (odd.pellicule, odd.cadre, odd.grain, odd.variante) == ("kodachrome", "fenetre",
                                                                   normal.grain, 1)
    assert core.Settings.from_values({"pellicule": "nb"}).pellicule == "nb"


def test_stock_filters_differ(core):
    looks = {k: core.stock_filters(core.Settings(pellicule=k)) for k in core.STOCKS}
    assert len({repr(v) for v in looks.values()}) == 4
    nb = dict(looks["nb"])["avfilter.eq"]
    assert nb["av.saturation"] == 0


def test_reel_flashes(core):
    assert core.reel_filters(core.Settings(bobine=False), 100, 25) == []
    (name, props), = core.reel_filters(core.Settings(bobine=True), 100, 25)
    assert name == "lift_gamma_gain" and (props["in"], props["out"]) == (0, 99)
    points = props["lift_r"].split(";")
    assert points[0].startswith("0=") and points[-1].startswith("99=")


def test_outside_rendering_only_colours(effect):
    assert _names(effect.filters(effect.defaults())) == ["avfilter.eq", "avfilter.colorbalance"]


@needs_ffmpeg
def test_layers_and_order(effect, core, tmp_path):
    context = _context(tmp_path)
    media = SimpleNamespace(kind="video", path="/v.mp4", width=320, height=180, fps=25,
                            duration=2)
    filters = _filters(effect, context, _clip(), media, {"style": "abime", "bobine": True,
                                                         "cadre": "perfo"})
    names = _names(filters)
    assert names[:2] == ["avfilter.eq", "avfilter.colorbalance"]
    assert "oldfilm" in names and names.count("watermark") == 3  # fuites, poussières, fenêtre
    assert names.index("lift_gamma_gain") < names.index("watermark")
    for _n, props in filters:
        if _n == "watermark":  # vidéos (jamais d'image PNG : Windows), transition imposée
            assert props["transition"] == "composite" and props["resource"].endswith(".mov")
            assert Path(props["resource"]).exists()
    # mêmes réglages : calques repris du cache ; image entière sans poussières : aucun calque
    again = _filters(effect, context, _clip(), media, {"style": "abime", "bobine": True,
                                                       "cadre": "perfo"})
    assert again == filters
    plain = _names(_filters(effect, context, _clip(), media,
                            {"cadre": "entier", "poussieres": 0, "fuites": 0}))
    assert "watermark" not in plain


def test_dust_layer_is_drawn(core, tmp_path):
    np = pytest.importorskip("numpy")
    s = core.Settings(poussieres=1.0)
    path = core.dust_layer(tmp_path, s, 320, 180, core.FULL, 10)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
                          "-pix_fmt", "rgba", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 180, 320, 4)
    assert len(frames) == core.DUST_SECONDS * 10
    alpha = frames[..., 3]
    assert alpha.max() > 100 and (alpha > 0).mean() < 0.2  # quelques taches, pas un voile
    assert (alpha[0] != alpha[1]).any()  # poussières différentes d'une image à l'autre


def test_gate_keeps_a_4_3_window(core, tmp_path):
    np = pytest.importorskip("numpy")
    path = core.gate_layer(tmp_path, core.Settings(cadre="fenetre"), 640, 360, core.FULL)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
                          "-pix_fmt", "rgba", "-"], capture_output=True, check=True).stdout
    alpha = np.frombuffer(raw, np.uint8).reshape(-1, 360, 640, 4)[0, ..., 3]
    row = alpha[180]
    open_ = np.flatnonzero(row < 128)
    width = open_[-1] - open_[0] + 1
    assert abs(width / 360 - 4 / 3) < 0.05  # fenêtre 4:3 au centre
    assert alpha[180, 5] == 255 and alpha[2, 2] == 255 and alpha[180, 320] == 0
    assert core.gate_layer(tmp_path, core.Settings(cadre="entier"), 640, 360,
                           core.FULL) is None


@needs_ffmpeg
def test_cadence_18_fps(effect, core, tmp_path):
    np = pytest.importorskip("numpy")
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=25:duration=2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    context = _context(tmp_path)
    media = SimpleNamespace(kind="video", path=str(video), width=160, height=90, fps=25,
                            duration=2)
    clip = _clip(modules={"super8": {"cadence": True}})
    first = effect.resolve(context, clip, media)
    assert first.path == str(video)  # en attendant la copie : la vidéo d'origine
    (key, work), = context.jobs.items()
    ratios = []
    work(ratios.append, lambda: False)
    assert ratios[-1] == 1.0
    ready = effect.resolve(context, clip, media)
    assert ready.path != str(video) and Path(ready.path).exists()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", ready.path, "-t", "1", "-f",
                          "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 90, 160).astype(np.float32)
    repeats = sum(float(np.abs(f[i + 1] - f[i]).mean()) < 0.5 for i in range(len(f) - 1))
    assert 5 <= repeats <= 8  # 25 images/s dont 7 répétées : 18 images différentes


def test_projector_sound(core, tmp_path):
    import wave

    path = core.projector_sound(tmp_path / "son.wav", 3.0)
    with wave.open(str(path)) as f:
        assert f.getframerate() == core.SOUND_RATE
        assert abs(f.getnframes() / f.getframerate() - 3.0) < 0.01


def test_other_clip_source_is_kept(effect, tmp_path):
    context = _context(tmp_path)
    context.manager = SimpleNamespace(sources=lambda: [("timelapse", None), ("super8", effect)],
                                      effects=lambda: [])
    clip = _clip(modules={"timelapse": {}, "super8": {"cadence": True}})
    media = SimpleNamespace(kind="video", path="/v.mp4", width=320, height=180)
    assert effect.resolve(context, clip, media) is None
    assert context.jobs == {}


@needs_ffmpeg
def test_super8_renders(effect, core, tmp_path, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    context = _context(tmp_path, 64, 36, 25)
    media = SimpleNamespace(kind="video", path=str(media_dir / "clip.mp4"), width=640,
                            height=360, fps=25, duration=2)
    filters = _filters(effect, context, _clip(), media, {"style": "abime", "bobine": True})

    def render(f, frame):
        spec = ClipSpec(media.path, "video", 0, 50, media_size=(640, 360),
                        extra_filters=tuple(f))
        source = get_engine().build(TimelineSpec(Canvas(64, 36, 25),
                                                 (TrackSpec("video", False, False, (spec,)),)))
        try:
            return source.render(frame, 64, 36)
        finally:
            source.close()

    plain, film = render([], 20), render(filters, 20)
    assert plain != film
    corner = (2 * 64 + 2) * 4  # coin hors de la fenêtre 4:3 : noir
    assert max(film[corner:corner + 3]) < 30
    burnt = render(filters, 0)  # première image de la bobine : orangée, surexposée
    middle = (18 * 64 + 32) * 4
    assert burnt[middle] > burnt[middle + 2] + 40
