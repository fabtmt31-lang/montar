# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Effets » et zoom animé (`montar.api.ZOOM`, API 1.3)."""
import pytest

from montar.api import ZOOM
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec
from montar.engine.mlt_engine import zoom_curve
from montar.plugins import ModuleManager, builtin_modules_dir

from .conftest import needs_ffmpeg


@pytest.fixture
def effects(tmp_path):
    m = ModuleManager(builtin_modules_dir(), tmp_path / "user")
    m.load_all()
    assert m.modules["effets"].active
    return {e.id: e for mid, e in m.effects() if mid == "effets"}


def test_zoom_curve():
    whole = dict(zoom_curve(101, 25, [{"start": 1.0, "end": 1.5, "ease": "linear"}]))
    assert whole[0] == 1.0 and whole[100] == pytest.approx(1.5)
    assert whole[50] == pytest.approx(1.25, abs=0.01)
    fast = dict(zoom_curve(101, 25, [{"start": 1.0, "end": 2.0, "seconds": 0.4}]))
    assert fast[10] == pytest.approx(2.0) and fast[100] == pytest.approx(2.0)  # maintenu
    assert dict(zoom_curve(1, 25, [{"start": 2, "end": 1}]))[0] == 2.0


def test_effects_list(effects):
    assert set(effects) == {"effets.vhs", "effets.zoom_lent", "effets.zoom_rapide",
                            "effets.dezoom_lent", "effets.dezoom_rapide", "effets.bd",
                            "effets.flou"}
    (name, props), = effects["effets.dezoom_rapide"].filters({"intensite": 0.5, "duree": 1})
    assert name == ZOOM and (props["start"], props["end"], props["seconds"]) == (1.5, 1.0, 1)
    assert [n for n, _p in effects["effets.flou"].filters({"style": "vertical"})] == \
        ["avfilter.dblur"]


def _render(engine, path, filters, frame, kind="video", size=(64, 36)):
    clip = ClipSpec(str(path), kind, 0, 50, media_size=size, extra_filters=tuple(filters))
    source = engine.build(TimelineSpec(Canvas(64, 36, 25),
                                       (TrackSpec("video", False, False, (clip,)),)))
    try:
        return source.render(frame, 64, 36)
    finally:
        source.close()


def _pixel(data, x, y):
    i = (y * 64 + x) * 4
    return tuple(data[i:i + 3])


@needs_ffmpeg
def test_zoom_enlarges_the_frame(media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    engine = get_engine()
    image = media_dir / "text.png"  # transparent, carré jaune de 24 à 40 × 12 à 24
    zoom = [(ZOOM, {"start": 1.0, "end": 2.0, "ease": "linear"})]
    first = _render(engine, image, zoom, 0, "image")
    last = _render(engine, image, zoom, 49, "image")
    assert _pixel(first, 18, 8)[0] < 50  # hors du carré au début
    yellow = _pixel(last, 18, 8)
    assert yellow[0] > 200 and yellow[1] > 200 and yellow[2] < 80  # dans le carré agrandi


@needs_ffmpeg
def test_every_effect_renders(effects, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    engine = get_engine()
    clip = media_dir / "clip.mp4"  # mire animée 640 × 360
    base = _render(engine, clip, [], 5, size=(640, 360))
    for effect in effects.values():  # image 5 : les zooms rapides sont en cours
        data = _render(engine, clip, effect.filters(effect.defaults()), 5, size=(640, 360))
        assert data != base, effect.id
        assert sum(data[0::4]) > 0, effect.id  # pas d'image noire
