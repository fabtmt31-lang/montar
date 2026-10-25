# SPDX-License-Identifier: GPL-3.0-or-later
"""Implémentation du moteur avec MLT 7 (bindings Python « mlt7 »)."""
from __future__ import annotations

import ctypes
import ctypes.util
import dataclasses
import locale
import logging
import math
import os
import struct
import sys
import threading
import zlib
from math import gcd

from montar.engine.base import (
    AudioOutput,
    Canvas,
    ClipSpec,
    Engine,
    EngineUnavailable,
    ExportJob,
    Source,
    SourceError,
    TimelineSpec,
    TrackSpec,
)
from montar.engine.geometry import affine_rect, crop_pixels, placement
from montar.engine.grading import grade_filters
from montar.engine.looks import color_filters, effect_filters, preset_filters
from montar.engine.sound import audio_filters

try:
    import mlt7 as mlt
except ImportError:  # pragma: no cover - dépend de l'installation
    mlt = None

log = logging.getLogger(__name__)

_init_lock = threading.Lock()
_factory_ready = False

# Modules MLT liés à Qt 5 : chargés dans montar (Qt 6), ils font cohabiter deux versions
# de Qt dans le même processus et peuvent figer l'interface. Les images passent alors par
# le module « pixbuf ».
_DENIED_MODULES = ("libmltqt", "libmltglaxnimate")

AUDIO_FREQUENCY = 48000
AUDIO_CHANNELS = 2

# Valeurs de la propriété « hide » d'une piste MLT.
_HIDE_VIDEO, _HIDE_AUDIO = 1, 2


_lib_get_image = None


def _native_get_image():
    """`mlt_frame_get_image` appelé via ctypes : contrairement aux bindings SWIG, l'appel
    libère le verrou global de Python, et l'interface reste fluide pendant le rendu."""
    global _lib_get_image
    if _lib_get_image is None:
        try:
            # Linux : libmlt-7.so.7 ; Windows (MSYS2) : libmlt-7.dll, à côté de l'exécutable
            name = ctypes.util.find_library("mlt-7") or ctypes.util.find_library("libmlt-7") \
                or ("libmlt-7.dll" if sys.platform == "win32" else "libmlt-7.so.7")
            lib = ctypes.CDLL(name)
            fn = lib.mlt_frame_get_image
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                           ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                           ctypes.POINTER(ctypes.c_int), ctypes.c_int]
            fn.restype = ctypes.c_int
            _lib_get_image = fn
        except (OSError, AttributeError) as exc:
            log.warning("rendu natif indisponible, repli sur les bindings : %s", exc)
            _lib_get_image = False
    return _lib_get_image or None


def _structure(spec: TimelineSpec) -> tuple:
    """Ce qui impose de reconstruire le graphe ; les réglages des clips en sont exclus."""
    tracks = []
    for t in spec.tracks:
        clips = tuple((c.path, c.kind, c.start, c.duration, c.source_in, c.speed, c.media_size,
                       c.reverse, c.sequence) for c in t.clips)
        tracks.append((t.kind, t.muted, t.hidden, t.volume, t.transitions, clips))
    return spec.canvas, tuple(tracks)


def _deny_qt5_modules() -> None:
    current = [m for m in os.environ.get("MLT_REPOSITORY_DENY", "").split(":") if m]
    os.environ["MLT_REPOSITORY_DENY"] = ":".join(
        current + [m for m in _DENIED_MODULES if m not in current])


def use_c_numeric() -> None:
    """MLT lit les nombres de ses propriétés (rectangle du filtre affine, valeurs animées…)
    selon la convention numérique du processus. Qt adopte celle du système au démarrage :
    en français, « 345.6 » serait lu « 345 » et l'élément transformé se retrouverait réduit
    en haut à gauche. Le moteur impose donc le point décimal."""
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except locale.Error:  # pragma: no cover - « C » existe toujours
        pass


def _ensure_factory() -> None:
    global _factory_ready
    if mlt is None:
        raise EngineUnavailable("bindings Python de MLT introuvables (paquet python3-mlt)")
    use_c_numeric()
    with _init_lock:
        if not _factory_ready:
            _deny_qt5_modules()
            if mlt.Factory().init() is None:
                raise EngineUnavailable("initialisation de MLT impossible")
            _factory_ready = True


def _profile(canvas: Canvas):
    profile = mlt.Profile()
    profile.set_explicit(1)
    profile.set_width(canvas.width)
    profile.set_height(canvas.height)
    profile.set_frame_rate(canvas.fps, 1)
    profile.set_sample_aspect(1, 1)
    d = gcd(canvas.width, canvas.height)
    profile.set_display_aspect(canvas.width // d, canvas.height // d)
    profile.set_progressive(1)
    profile.set_colorspace(709)
    return profile


MOTION = "montar.zoom"  # montar.api.ZOOM : zoom animé du cadre du clip


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def zoom_curve(duration: int, fps: int, motions: list[dict]) -> list[tuple[int, float]]:
    """Facteur de zoom aux images clés du clip, produit des mouvements demandés.

    Chaque mouvement : `start` et `end` (facteurs, 1 = taille normale), `seconds` (durée
    du mouvement depuis le début du clip ; 0 = tout le clip), `ease` (`smooth` ou
    `linear`). Le facteur final est gardé jusqu'à la fin du clip."""
    last = max(1, duration - 1)
    specs = []
    for m in motions:
        seconds = float(m.get("seconds", 0) or 0)
        frames = last if seconds <= 0 else max(1, min(last, round(seconds * fps)))
        specs.append((float(m.get("start", 1.0)), float(m.get("end", 1.0)), frames,
                      m.get("ease", "smooth") != "linear"))
    points = {0, last}
    for _a, _b, frames, _e in specs:
        points.update(round(frames * i / 12) for i in range(13))  # courbe échantillonnée
    result = []
    for f in sorted(points):
        k = 1.0
        for a, b, frames, smooth in specs:
            t = min(1.0, f / frames)
            k *= a + (b - a) * (_smooth(t) if smooth else t)
        result.append((f, k))
    return result


def zoom_value(curve: dict[int, float], frame: int) -> float:
    """Facteur de zoom à `frame`, interpolé entre les points de `zoom_curve`."""
    if frame in curve:
        return curve[frame]
    before = max((f for f in curve if f < frame), default=None)
    after = min((f for f in curve if f > frame), default=None)
    if before is None or after is None:
        return curve[before if after is None else after]
    t = (frame - before) / (after - before)
    return curve[before] + (curve[after] - curve[before]) * t


def _anim(points: list[tuple[int, float]]) -> str:
    """Valeur animée MLT « position=valeur;… » (positions relatives au filtre)."""
    return ";".join(f"{pos}={value:g}" for pos, value in points)


def _fade_points(duration: int, fade_in: int, fade_out: int, low: float,
                 high: float) -> list[tuple[int, float]] | None:
    fade_in, fade_out = min(fade_in, duration), min(fade_out, duration - min(fade_in, duration))
    if not fade_in and not fade_out:
        return None
    points = []
    if fade_in:
        points += [(0, low), (fade_in, high)]
    else:
        points.append((0, high))
    if fade_out:
        points += [(duration - fade_out - 1, high), (duration - 1, low)]
    return points


def _luma_file(kind: str) -> str:
    """Motif de balayage (dégradé horizontal) pour la transition « luma »."""
    from montar.platform.paths import cache_dir

    folder = cache_dir() / "lumas"
    path = folder / f"{kind}.pgm"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        width, height = 256, 16
        ramp = bytes(round(x * 255 / (width - 1)) for x in range(width))
        if kind == "wipe_left":
            ramp = ramp[::-1]
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(f"P5 {width} {height} 255\n".encode() + ramp * height)
        tmp.replace(path)
    return str(path)


class _TimelineGraph:
    """Tracteur MLT : fond noir, pistes vidéo puis texte composées de bas en haut, son de
    toutes les pistes mixé. Chaque clip a son propre producteur, qui porte ses filtres (ils
    s'appliquent ainsi aussi pendant les transitions). Les objets MLT doivent rester
    référencés tant que le tracteur est utilisé."""

    def __init__(self, spec: TimelineSpec) -> None:
        self.profile = _profile(spec.canvas)
        self.canvas = spec.canvas
        self.length = spec.length
        self.spec = spec
        self.tractor = mlt.Tractor(self.profile)
        self._keep: list = []
        # (piste, clip) → (producteur, filtres du clip, intervalle, type de piste)
        self.nodes: dict[tuple[int, int], tuple[object, list, tuple[int, int], str]] = {}
        self._collect: list | None = None

        background = mlt.Producer(self.profile, "color:black")
        background.set("length", max(1, self.length))
        background_track = mlt.Playlist(self.profile)
        background_track.append(background, 0, max(0, self.length - 1))
        self.tractor.set_track(background_track, 0)
        self._keep += [background, background_track]

        field = self.tractor.field()
        for index, track in enumerate(spec.tracks, start=1):
            playlist = self._build_track(track, index - 1)
            hide = 0
            if track.kind == "audio" or track.hidden:
                hide |= _HIDE_VIDEO
            if track.muted:
                hide |= _HIDE_AUDIO
            playlist.set("hide", hide)
            if track.volume != 1.0:
                self._attach(playlist, "volume", {"gain": max(0.0, track.volume)})
            self.tractor.set_track(playlist, index)
            mix = mlt.Transition(self.profile, "mix")
            mix.set("always_active", 1)
            mix.set("sum", 1)
            field.plant_transition(mix, 0, index)
            self._keep += [playlist, mix]
            if track.kind == "video":
                # superposition par transparence : chaque piste est déjà à la taille de la toile
                blend = mlt.Transition(self.profile, "frei0r.cairoblend")
                blend.set("always_active", 1)
                field.plant_transition(blend, 0, index)
                self._keep.append(blend)

    # --- pistes ---------------------------------------------------------------------

    def update_settings(self, spec: TimelineSpec) -> bool:
        """Applique de nouveaux réglages de clips sans reconstruire le graphe (curseurs,
        déplacement dans l'aperçu). Renvoie False si la structure a changé."""
        if _structure(spec) != _structure(self.spec):
            return False
        for ti, (old_track, new_track) in enumerate(zip(self.spec.tracks, spec.tracks,
                                                         strict=True)):
            for ci, (old, new) in enumerate(zip(old_track.clips, new_track.clips, strict=True)):
                if old == new:
                    continue
                producer, filters, span, kind = self.nodes[(ti, ci)]
                for f in filters:
                    producer.detach(f)
                self._attach_clip_filters(producer, new, span, kind, (ti, ci))
        self.spec = spec
        return True

    def _attach_clip_filters(self, producer, clip: ClipSpec, span: tuple[int, int],
                             track_kind: str, key: tuple[int, int]) -> None:
        self._collect = []
        if track_kind == "video":
            self._video_filters(producer, clip, span)
        self._audio_filters(producer, clip, span)
        self.nodes[key] = (producer, self._collect, span, track_kind)
        self._collect = None

    def _build_track(self, track: TrackSpec, track_index: int):
        playlist = mlt.Playlist(self.profile)
        transitions = {t.left: t for t in track.transitions}
        cursor = 0  # longueur actuelle de la playlist
        index_of: dict[int, int] = {}  # clip → position dans la playlist
        for i, clip in enumerate(track.clips):
            incoming = transitions.get(i - 1)
            if incoming is None and clip.start > cursor:
                playlist.blank(clip.start - cursor - 1)
            producer, cut_in = self._clip_producer(clip, track.kind, (track_index, i))
            index_of[i] = playlist.count()
            playlist.append(producer, cut_in, cut_in + clip.duration - 1)
            if incoming is not None:
                self._mix(playlist, index_of[i - 1], incoming, track.kind)
                index_of[i] = index_of[i - 1] + 2
            cursor = playlist.get_playtime()
        return playlist

    def _mix(self, playlist, left_index: int, t, track_kind: str) -> None:
        length = t.duration
        if track_kind == "audio":
            transition = mlt.Transition(self.profile, "mix")
        elif t.service:  # transition d'un module
            transition = mlt.Transition(self.profile, t.service)
            if transition is None or not transition.is_valid():
                log.warning("transition MLT indisponible : %s", t.service)
                transition = mlt.Transition(self.profile, "luma")
            else:
                for key, value in t.properties:
                    transition.set(key, value)
        elif t.kind in ("slide_left", "slide_right", "zoom"):
            transition = mlt.Transition(self.profile, "affine")
            start = {"slide_left": "100% 0% 100% 100% 1", "slide_right": "-100% 0% 100% 100% 1",
                     "zoom": "50% 50% 0% 0% 0"}[t.kind]
            transition.set("rect", f"0={start};{length - 1}=0% 0% 100% 100% 1")
            transition.set("fill", 1)
            transition.set("distort", 0)
        else:
            transition = mlt.Transition(self.profile, "luma")
            if t.kind in ("wipe_left", "wipe_right"):
                transition.set("resource", _luma_file(t.kind))
                transition.set("softness", 0.15)
        playlist.mix(left_index, length, transition)
        self._keep.append(transition)
        mixed = playlist.get_clip(left_index + 1)
        if track_kind != "audio":
            audio = mlt.Transition(self.profile, "mix")
            playlist.mix_add(left_index + 1, audio)
            self._keep.append(audio)
        if mixed is None:
            return
        mid = length // 2
        if t.kind == "dip_black":
            self._attach(mixed, "brightness",
                         {"level": _anim([(0, 1), (mid, 0), (length - 1, 1)])},
                         (mixed.get_in(), mixed.get_out()))
        elif t.kind == "dip_white":
            self._attach(mixed, "avfilter.eq", {
                "av.contrast": _anim([(0, 1), (mid, 0), (length - 1, 1)]),
                "av.brightness": _anim([(0, 0), (mid, 0.5), (length - 1, 0)]),
                "av.saturation": _anim([(0, 1), (mid, 0), (length - 1, 1)]),
            }, (mixed.get_in(), mixed.get_out()))

    # --- clips ------------------------------------------------------------------------

    def _clip_producer(self, clip: ClipSpec, track_kind: str, key: tuple[int, int]):
        """Producteur propre au clip, avec ses filtres ; renvoie (producteur, image d'entrée)."""
        if clip.kind == "text" and clip.sequence:  # machine à écrire : images successives
            producer = mlt.Playlist(self.profile)
            for path, frames in clip.sequence:
                step = mlt.Producer(self.profile, path)
                if step is None or not step.is_valid():
                    raise SourceError(f"MLT ne sait pas ouvrir {path}")
                step.set("length", frames)
                producer.append(step, 0, frames - 1)
                self._keep.append(step)
            span = (0, clip.duration - 1)
            self._attach_clip_filters(producer, clip, span, track_kind, key)
            self._keep.append(producer)
            return producer, 0
        if clip.kind in ("video", "audio") and clip.reverse and clip.media_length:
            # timewarp négatif : l'image j montre l'image L-1-j·k du média
            k = abs(clip.speed)
            producer = mlt.Producer(self.profile, f"timewarp:{-k:g}:{clip.path}")
            cut_in = max(0, round((clip.media_length - clip.source_in - clip.duration * k) / k))
        elif clip.kind in ("video", "audio") and clip.speed != 1.0:
            producer = mlt.Producer(self.profile, f"timewarp:{clip.speed:g}:{clip.path}")
            cut_in = round(clip.source_in / clip.speed)
        else:
            producer = mlt.Producer(self.profile, clip.path)
            cut_in = clip.source_in if clip.kind in ("video", "audio") else 0
        if producer is None or not producer.is_valid():
            raise SourceError(f"MLT ne sait pas ouvrir {clip.path}")
        if clip.kind in ("image", "text"):
            producer.set("length", clip.duration)
            producer.set_in_and_out(0, clip.duration - 1)
        span = (cut_in, cut_in + clip.duration - 1)
        self._attach_clip_filters(producer, clip, span, track_kind, key)
        self._keep.append(producer)
        return producer, cut_in

    def _attach(self, service, name: str, props: dict, span: tuple[int, int] | None = None):
        f = mlt.Filter(self.profile, name)
        if f is None or not f.is_valid():
            log.warning("filtre MLT indisponible : %s", name)
            return None
        for key, value in props.items():
            f.set(key, value)
        if span is not None:
            f.set_in_and_out(*span)
        service.attach(f)
        self._keep.append(f)
        if self._collect is not None:
            self._collect.append(f)
        return f

    def _video_filters(self, producer, clip: ClipSpec, span: tuple[int, int]) -> None:
        t = clip.transform
        mw, mh = clip.media_size
        cw, ch = self.canvas.width, self.canvas.height
        if clip.kind in ("video", "image"):
            sw, sh = clip.source_size if clip.source_size[0] else (mw, mh)
            left, right, top, bottom = crop_pixels(sw or cw, sh or ch, t)
            if left or right or top or bottom:
                self._attach(producer, "crop", {"left": left, "right": right, "top": top,
                                                "bottom": bottom})
            if t.flip_h:
                self._attach(producer, "avfilter.hflip", {})
            if t.flip_v:
                self._attach(producer, "avfilter.vflip", {})
            for name, props in (color_filters(clip.color)
                                + preset_filters(clip.preset, clip.preset_amount)
                                + effect_filters(clip.effects)
                                + grade_filters(clip.grade, clip.lut)
                                + [f for f in clip.extra_filters if f[0] != MOTION]):
                if "in" in props and "out" in props:  # partie du clip (API 1.4)
                    rest = {k: v for k, v in props.items() if k not in ("in", "out")}
                    first = span[0] + max(0, int(props["in"]))
                    last = min(span[1], span[0] + int(props["out"]))
                    if last >= first:
                        self._attach(producer, name, rest, (first, last))
                    continue
                self._attach(producer, name, props)
        motions = [props for name, props in clip.extra_filters if name == MOTION] \
            if clip.kind in ("video", "image") else []
        keys = dict(clip.keyframes) if clip.kind in ("video", "image") else {}
        animated = clip.kind == "text" and "slide" in (clip.animation_in, clip.animation_out)
        if keys:  # images clés : cadre, opacité et rotation animés
            self._attach_keyframed(producer, clip, keys, motions, span)
        elif not t.is_identity() or animated or motions:
            (x, y, w, h), distort = affine_rect(cw, ch, mw, mh, t)
            opacity = 1  # l'opacité du cadre affine est ignorée par MLT : filtre à part
            rect = f"{x:g} {y:g} {w:g} {h:g} {opacity:g}"
            if animated:
                rect = self._slide_rect(clip, x, y, w, h, 1.0)
            elif motions:  # zoom autour du centre du cadre
                cx, cy = x + w / 2, y + h / 2
                rect = ";".join(
                    f"{f}={cx - w * k / 2:.2f} {cy - h * k / 2:.2f} {w * k:.2f} {h * k:.2f} "
                    f"{opacity:g}"
                    for f, k in zoom_curve(clip.duration, self.canvas.fps, motions))
            self._attach(producer, "affine", {
                "background": "color:#00000000", "transition.rect": rect,
                "transition.fill": 1, "transition.distort": 1 if distort else 0,
                "transition.fix_rotate_x": t.rotation,
            }, span)
        opacity = keys.get("opacity")
        if opacity:  # opacité animée par les images clés
            values = ";".join(f"{round(f)}={max(0.0, min(1.0, v)):g}" for f, v in opacity)
            self._attach(producer, "brightness", {"level": 1, "alpha": values}, span)
        elif t.opacity < 1:
            self._attach(producer, "brightness",
                         {"level": 1, "alpha": max(0.0, min(1.0, t.opacity))}, span)
        fade_in, fade_out = clip.fade_in, clip.fade_out
        if clip.kind == "text":
            step = max(1, self.canvas.fps // 2)
            fade_in = max(fade_in, step if clip.animation_in in ("fade", "slide") else 0)
            fade_out = max(fade_out, step if clip.animation_out in ("fade", "slide") else 0)
        points = _fade_points(clip.duration, fade_in, fade_out, 0.0, 1.0)
        if points is not None:
            self._attach(producer, "brightness", {"level": _anim(points), "alpha": -1}, span)

    def _attach_keyframed(self, producer, clip: ClipSpec, keys: dict, motions: list,
                          span: tuple[int, int]) -> None:
        from montar.core.keyframes import value_at

        cw, ch = self.canvas.width, self.canvas.height
        mw, mh = clip.media_size
        last = max(0, clip.duration - 1)
        frames = {0, last} | {min(last, max(0, round(f))) for points in keys.values()
                              for f, _v in points}
        zoom = dict(zoom_curve(clip.duration, self.canvas.fps, motions)) if motions else {}
        frames |= set(zoom)
        points = {k: [list(p) for p in v] for k, v in keys.items()}
        rects, rotations, distorted = [], [], False
        for f in sorted(frames):
            t = dataclasses.replace(clip.transform, **{
                k: value_at(points[k], f, getattr(clip.transform, k)) for k in points})
            (x, y, w, h), distort = affine_rect(cw, ch, mw, mh, t)
            distorted = distorted or distort
            k = zoom_value(zoom, f) if zoom else 1.0
            cx, cy = x + w / 2, y + h / 2
            rects.append(f"{f}={cx - w * k / 2:.2f} {cy - h * k / 2:.2f} {w * k:.2f} "
                         f"{h * k:.2f} 1")
            rotations.append(f"{f}={t.rotation:g}")
        props = {"background": "color:#00000000", "transition.rect": ";".join(rects),
                 "transition.fill": 1, "transition.distort": 1 if distorted else 0,
                 "transition.fix_rotate_x": ";".join(rotations) if "rotation" in keys
                 else clip.transform.rotation}
        self._attach(producer, "affine", props, span)

    def _slide_rect(self, clip: ClipSpec, x: float, y: float, w: float, h: float,
                    opacity: float) -> str:
        step = max(1, self.canvas.fps // 2)
        offset = self.canvas.height * 0.06
        final = f"{x:g} {y:g} {w:g} {h:g} {opacity:g}"
        moved = f"{x:g} {y + offset:g} {w:g} {h:g} {opacity:g}"
        points = []
        if clip.animation_in == "slide":
            points += [f"0={moved}", f"{min(step, clip.duration - 1)}={final}"]
        else:
            points.append(f"0={final}")
        if clip.animation_out == "slide" and clip.duration > 2 * step:
            points += [f"{clip.duration - step - 1}={final}", f"{clip.duration - 1}={moved}"]
        return ";".join(points)

    def _audio_filters(self, producer, clip: ClipSpec, span: tuple[int, int]) -> None:
        if clip.kind in ("image", "text"):
            return
        for name, props in audio_filters(clip.audio) + list(clip.audio_filters):
            self._attach(producer, name, props)
        if clip.duck:  # atténuation sous la voix (en plus du volume et des fondus)
            self._attach(producer, "volume", {"level": _anim(list(clip.duck))}, span)
        if clip.volume <= 0.001:
            self._attach(producer, "volume", {"gain": 0})
            return
        base = 20 * math.log10(clip.volume)
        points = _fade_points(clip.duration, clip.fade_in, clip.fade_out, -60.0, base)
        if points is not None:
            self._attach(producer, "volume", {"level": _anim(points)}, span)
        elif clip.volume != 1.0:
            self._attach(producer, "volume", {"level": round(base, 3)})


class MltSource(Source):
    def __init__(self, spec: TimelineSpec) -> None:
        self._graph = _TimelineGraph(spec)

    @property
    def length(self) -> int:
        return self._graph.length

    def render(self, frame: int, width: int, height: int) -> bytes:
        expected = width * height * 4
        if self.length == 0:
            return bytes(expected)
        tractor = self._graph.tractor
        tractor.seek(max(0, min(frame, self.length - 1)))
        mlt_frame = tractor.get_frame()
        mlt_frame.set("consumer.rescale", "bilinear")
        native = _native_get_image()
        if native is not None:
            image = ctypes.c_void_p()
            fmt = ctypes.c_int(mlt.mlt_image_rgba)
            w, h = ctypes.c_int(width), ctypes.c_int(height)
            error = native(int(mlt_frame.get_frame()), ctypes.byref(image), ctypes.byref(fmt),
                           ctypes.byref(w), ctypes.byref(h), 0)
            if (error or not image.value or fmt.value != mlt.mlt_image_rgba
                    or (w.value, h.value) != (width, height)):
                raise SourceError("image non disponible")
            return ctypes.string_at(image.value, expected)
        data = mlt_frame.get_image(mlt.mlt_image_rgba, width, height)
        if data is None or len(data) < expected:
            raise SourceError("image non disponible")
        return bytes(data[:expected])

    def update(self, spec: TimelineSpec) -> bool:
        return self._graph.update_settings(spec)

    def close(self) -> None:
        self._graph = None


def _png(path: str, width: int, height: int, rgba: tuple[int, int, int, int]) -> None:
    """Écrit une image PNG unie (sans dépendance)."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
    row = b"\x00" + bytes(rgba) * width
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                                                     8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


_scaling_lock = threading.Lock()
_scaling_result: dict | None = None
_CHECK_SIZES = ((1920, 1080), (640, 360), (960, 540))


def preview_scaling_check() -> dict:
    """Diagnostic : rend un élément déplacé et réduit à plusieurs tailles d'aperçu et
    compare sa position à celle attendue. Renvoie les rectangles attendus et obtenus."""
    global _scaling_result
    with _scaling_lock:
        if _scaling_result is not None:
            return _scaling_result
        result: dict = {"ok": True, "sizes": {}}
        from montar.core.project import Transform
        from montar.platform.paths import cache_dir

        try:
            folder = cache_dir() / "selftest"
            folder.mkdir(parents=True, exist_ok=True)
            image = str(folder / "magenta.png")
            _png(image, 400, 300, (255, 0, 255, 255))
            canvas = Canvas(1920, 1080, 25)
            def spec(t: Transform) -> TimelineSpec:
                return TimelineSpec(canvas, (
                    TrackSpec("video", False, False, (ClipSpec("color:#0000ff", "image", 0, 5),)),
                    TrackSpec("video", False, False, (
                        ClipSpec(image, "image", 0, 5, media_size=(400, 300), transform=t),)),
                ))

            t = Transform(x=0.2, y=-0.1, scale=0.6)
            p = placement(1920, 1080, 400, 300, t)
            expected = (p.left, p.top, p.left + p.width, p.top + p.height)
            result["expected"] = [round(v) for v in expected]
            # comme dans l'éditeur : élément d'abord intact, puis déplacé (mise à jour rapide)
            source = MltSource(spec(Transform()))
            source.render(2, *_CHECK_SIZES[1])
            if not source.update(spec(t)):
                source = MltSource(spec(t))
            for w, h in _CHECK_SIZES:
                got = _magenta_box(source.render(2, w, h), w, h, canvas.width / w)
                result["sizes"][f"{w}x{h}"] = got
                tolerance = 4 * canvas.width / w + 2
                if got is None or max(abs(a - b) for a, b in
                                      zip(got, expected, strict=True)) > tolerance:
                    result["ok"] = False
        except Exception as exc:
            result["ok"], result["error"] = False, str(exc)
        _scaling_result = result
        return result


def _magenta_box(data: bytes, w: int, h: int, k: float) -> list[int] | None:
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            i = (y * w + x) * 4
            if data[i] > 200 and data[i + 2] > 200 and data[i + 1] < 60:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return [round(min(xs) * k), round(min(ys) * k), round((max(xs) + 2) * k),
            round((max(ys) + 2) * k)]


class MltAudioOutput(AudioOutput):
    """Son joué par le consommateur MLT « sdl2_audio » sur une copie de la timeline."""

    def __init__(self, spec: TimelineSpec) -> None:
        self._graph = _TimelineGraph(spec)
        consumer = mlt.Consumer(self._graph.profile, "sdl2_audio")
        if consumer is None or not consumer.is_valid():
            raise SourceError("sortie son SDL indisponible")
        consumer.set("video_off", 1)
        consumer.set("terminate_on_pause", 0)
        consumer.set("frequency", AUDIO_FREQUENCY)
        consumer.set("channels", AUDIO_CHANNELS)
        consumer.set("real_time", 1)
        consumer.connect(self._graph.tractor)
        self._consumer = consumer

    def start(self, frame: int) -> None:
        self.stop()
        tractor = self._graph.tractor
        tractor.seek(frame)
        tractor.set_speed(1)
        self._consumer.purge()
        if self._consumer.start() != 0:
            raise SourceError("lecture du son impossible")

    def stop(self) -> None:
        self._graph.tractor.set_speed(0)
        if not self._consumer.is_stopped():
            self._consumer.stop()

    def position(self) -> int:
        return self._consumer.position()

    def set_volume(self, volume: float) -> None:
        self._consumer.set("volume", max(0.0, min(1.0, volume)))

    def close(self) -> None:
        self.stop()
        self._consumer = None
        self._graph = None


class MltExport(ExportJob):
    """Export par le consommateur MLT « avformat » (FFmpeg), dans un fil dédié."""

    POLL = 0.2

    def __init__(self, spec: TimelineSpec, settings) -> None:
        self.spec, self.settings = spec, settings
        self.first = max(0, getattr(settings, "range_start", 0))
        last = getattr(settings, "range_end", 0) or spec.length
        self.total = max(1, min(last, spec.length) - self.first)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._consumer = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="montar-export", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.finished

    def _run(self) -> None:
        from montar.engine import export as ex

        settings = self.settings
        target = settings.path
        intermediate = None
        try:
            if settings.format == "gif":
                intermediate = f"{target}.part.mkv"
            encoder = None
            if settings.hardware and not settings.audio_only and settings.format != "gif":
                encoder = ex.hardware_encoder(settings.codec)
            output = intermediate or f"{target}.part{os.path.splitext(target)[1]}"
            ok = self._encode(output, ex.consumer_properties(settings, encoder))
            if not ok and encoder is not None and not self._stop.is_set():
                log.warning("export avec %s impossible, repli sur l'encodeur logiciel",
                            encoder)
                encoder = None
                self.done = 0
                ok = self._encode(output, ex.consumer_properties(settings, None))
            if self._stop.is_set():
                self.cancelled, self.error = True, "annulé"
                return
            if not ok:
                self.error = "l'encodage a échoué (voir le journal)"
                return
            if intermediate is not None:
                import subprocess

                done = subprocess.run(ex.gif_command(intermediate, f"{target}.part.gif",
                                                     settings.fps, settings.width),
                                      capture_output=True, text=True)
                if done.returncode != 0:
                    self.error = (done.stderr.strip().splitlines() or ["GIF impossible"])[-1]
                    return
                output = f"{target}.part.gif"
            os.replace(output, target)
        except Exception as exc:  # jamais d'exception hors du fil
            log.exception("export")
            self.error = str(exc)
        finally:
            for leftover in (f"{target}.part.mkv", f"{target}.part.gif",
                             f"{target}.part{os.path.splitext(target)[1]}"):
                if os.path.exists(leftover):
                    os.remove(leftover)
            self.finished = True

    def _encode(self, output: str, props: dict) -> bool:
        use_c_numeric()
        graph = _TimelineGraph(self.spec)
        consumer = mlt.Consumer(graph.profile, "avformat", output)
        if consumer is None or not consumer.is_valid():
            raise SourceError("consommateur avformat indisponible")
        for key, value in props.items():
            consumer.set(key, value)
        self.used_encoder = str(props.get("vcodec") or props.get("acodec", ""))
        consumer.set("real_time", -max(1, min(4, (os.cpu_count() or 2) // 2)))
        consumer.set("terminate_on_pause", 1)
        # avec un point d'entrée, les positions du tracteur partent de ce point
        graph.tractor.set_in_and_out(self.first, self.first + self.total - 1)
        consumer.connect(graph.tractor)
        graph.tractor.seek(0)
        graph.tractor.set_speed(1)
        self._consumer = consumer
        if consumer.start() != 0:
            return False
        while not consumer.is_stopped():
            if self._stop.is_set():
                consumer.stop()
                break
            self.done = min(self.total, max(self.done, graph.tractor.frame()))
            self._stop.wait(self.POLL)
        consumer.stop()
        self._consumer = None
        if self._stop.is_set():
            return False
        self.done = self.total
        return os.path.exists(output) and os.path.getsize(output) > 0


class MltEngine(Engine):
    name = "MLT"

    def __init__(self) -> None:
        _ensure_factory()

    def version(self) -> str:
        return mlt.mlt_version_get_string()

    def build(self, spec: TimelineSpec) -> Source:
        return MltSource(spec)

    def export(self, spec: TimelineSpec, settings) -> ExportJob:
        return MltExport(spec, settings)

    def audio_output(self, spec: TimelineSpec) -> AudioOutput | None:
        if spec.length == 0:
            return None
        try:
            return MltAudioOutput(spec)
        except SourceError as exc:
            log.warning("pas de son : %s", exc)
            return None
