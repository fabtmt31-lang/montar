# SPDX-License-Identifier: GPL-3.0-or-later
"""Implémentation du moteur avec MLT 7 (bindings Python « mlt7 »)."""
from __future__ import annotations

import logging
import os
import threading
from math import gcd

from montar.engine.base import (
    AudioOutput,
    Canvas,
    Engine,
    EngineUnavailable,
    Source,
    SourceError,
    TimelineSpec,
)

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


def _deny_qt5_modules() -> None:
    current = [m for m in os.environ.get("MLT_REPOSITORY_DENY", "").split(":") if m]
    os.environ["MLT_REPOSITORY_DENY"] = ":".join(
        current + [m for m in _DENIED_MODULES if m not in current])


def _ensure_factory() -> None:
    global _factory_ready
    if mlt is None:
        raise EngineUnavailable("bindings Python de MLT introuvables (paquet python3-mlt)")
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


class _TimelineGraph:
    """Tracteur MLT : fond noir, pistes vidéo composées de bas en haut, son de toutes les
    pistes mixé. Les objets MLT doivent rester référencés tant que le tracteur est utilisé."""

    def __init__(self, spec: TimelineSpec) -> None:
        self.profile = _profile(spec.canvas)
        self.length = spec.length
        self.tractor = mlt.Tractor(self.profile)
        self._keep: list = []
        producers: dict[str, object] = {}

        background = mlt.Producer(self.profile, "color:black")
        background.set("length", max(1, self.length))
        background_track = mlt.Playlist(self.profile)
        background_track.append(background, 0, max(0, self.length - 1))
        self.tractor.set_track(background_track, 0)
        self._keep += [background, background_track]

        field = self.tractor.field()
        for index, track in enumerate(spec.tracks, start=1):
            playlist = mlt.Playlist(self.profile)
            cursor = 0
            for clip in track.clips:
                producer = producers.get(clip.path)
                if producer is None:
                    producer = mlt.Producer(self.profile, clip.path)
                    if not producer.is_valid():
                        raise SourceError(f"MLT ne sait pas ouvrir {clip.path}")
                    producers[clip.path] = producer
                if clip.kind == "image":
                    needed = clip.source_in + clip.duration
                    if producer.get_int("length") < needed:
                        producer.set("length", needed)
                        producer.set_in_and_out(0, needed - 1)
                if clip.start > cursor:
                    playlist.blank(clip.start - cursor - 1)
                playlist.append(producer, clip.source_in, clip.source_in + clip.duration - 1)
                cursor = clip.start + clip.duration
            hide = 0
            if track.kind == "audio" or track.hidden:
                hide |= _HIDE_VIDEO
            if track.muted:
                hide |= _HIDE_AUDIO
            playlist.set("hide", hide)
            self.tractor.set_track(playlist, index)
            mix = mlt.Transition(self.profile, "mix")
            mix.set("always_active", 1)
            mix.set("sum", 1)
            field.plant_transition(mix, 0, index)
            self._keep += [playlist, mix]
            if track.kind == "video":
                blend = mlt.Transition(self.profile, "affine")
                blend.set("always_active", 1)
                blend.set("fill", 1)
                blend.set("distort", 0)
                field.plant_transition(blend, 0, index)
                self._keep.append(blend)
        self._keep += list(producers.values())


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
        data = mlt_frame.get_image(mlt.mlt_image_rgba, width, height)
        if data is None or len(data) < expected:
            raise SourceError("image non disponible")
        return bytes(data[:expected])

    def close(self) -> None:
        self._graph = None


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

    def close(self) -> None:
        self.stop()
        self._consumer = None
        self._graph = None


class MltEngine(Engine):
    name = "MLT"

    def __init__(self) -> None:
        _ensure_factory()

    def version(self) -> str:
        return mlt.mlt_version_get_string()

    def build(self, spec: TimelineSpec) -> Source:
        return MltSource(spec)

    def audio_output(self, spec: TimelineSpec) -> AudioOutput | None:
        if spec.length == 0:
            return None
        try:
            return MltAudioOutput(spec)
        except SourceError as exc:
            log.warning("pas de son : %s", exc)
            return None
