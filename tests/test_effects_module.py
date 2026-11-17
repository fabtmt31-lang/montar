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


def test_vhs_and_comic_options(effects):
    vhs = effects["effets.vhs"]
    names = [n for n, _p in vhs.filters(vhs.defaults())]
    assert "avfilter.drawtext" in names and "frei0r.distort0r" in names
    # à zéro : image propre (seulement l'affichage demandé)
    clean = vhs.filters({**vhs.defaults(), "couleur": 0, "grain": 0, "defauts": 0,
                         "affichage": "aucun"})
    assert clean == []
    # décrochages réservés à une bande bien usée (préréglage « Vieille cassette »)
    worn = {**vhs.defaults(), **vhs.presets["vieille"][1]}
    assert "frei0r.glitch0r" in [n for n, _p in vhs.filters(worn)]
    light = {**vhs.defaults(), **vhs.presets["leger"][1]}
    assert "frei0r.glitch0r" not in [n for n, _p in vhs.filters(light)]
    dated = [p for n, p in vhs.filters({**vhs.defaults(), "affichage": "lecture_date",
                                        "date": "24 dec 1994"}) if n == "avfilter.drawtext"]
    assert [d["av.text"] for d in dated] == ["PLAY ▶", "24 DEC 1994"]
    rec = [p for n, p in vhs.filters({**vhs.defaults(), "affichage": "rec_date"})
           if n == "avfilter.drawtext"]
    assert [d["av.text"] for d in rec][:2] == ["●", "REC"] and "alpha" in str(rec[0])
    assert rec[-1]["av.text"].startswith("%{pts:gmtime")  # compteur
    # anciens réglages (intensité + case « défauts ») : relus sans socle fixe
    old = vhs.filters({"intensite": 0.0, "defauts": True, "affichage": "aucun"})
    assert old == []
    comic = effects["effets.bd"]
    calm = [n for n, _p in comic.filters(comic.defaults())]
    alive = [n for n, _p in comic.filters({**comic.defaults(), "vivant": True})]
    assert "frei0r.distort0r" not in calm and alive[0] == "avfilter.noise"


@needs_ffmpeg
def test_vhs_display_and_living_line_render(effects, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    engine = get_engine()
    clip = media_dir / "clip.mp4"
    vhs = effects["effets.vhs"]
    with_text = _render(engine, clip, vhs.filters(vhs.defaults()), 5, size=(640, 360))
    without = _render(engine, clip, vhs.filters({**vhs.defaults(), "affichage": "aucun"}), 5,
                      size=(640, 360))
    top_left = [_pixel(d, x, y) for d in (with_text, without) for x in range(4, 16)
                for y in range(3, 7)]
    assert max(sum(p) for p in top_left[:48]) > max(sum(p) for p in top_left[48:])
    comic = effects["effets.bd"]
    alive = comic.filters({**comic.defaults(), "vivant": True})
    image = media_dir / "photo.png"
    assert _render(engine, image, alive, 3, "image", (320, 240)) != \
        _render(engine, image, alive, 4, "image", (320, 240))


@needs_ffmpeg
def test_vhs_rec_dot_blinks(effects, media_dir):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    engine = get_engine()
    vhs = effects["effets.vhs"]
    values = {**vhs.defaults(), "couleur": 0, "grain": 0, "defauts": 0, "affichage": "rec"}
    clip = media_dir / "photo.png"
    on = _render(engine, clip, vhs.filters(values), 5, "image", (640, 360))
    off = _render(engine, clip, vhs.filters(values), 17, "image", (640, 360))
    assert on != off  # le point rouge s'éteint une demi-seconde sur deux
