# SPDX-License-Identifier: GPL-3.0-or-later
"""Implémentation du moteur avec MLT 7 (bindings Python « mlt7 »)."""
from __future__ import annotations

import os
import threading
from math import gcd

from montar.engine.base import (
    IMAGE_PREVIEW_SECONDS,
    Canvas,
    Engine,
    EngineUnavailable,
    Source,
    SourceError,
)

try:
    import mlt7 as mlt
except ImportError:  # pragma: no cover - dépend de l'installation
    mlt = None

_init_lock = threading.Lock()
_factory_ready = False

# Modules MLT liés à Qt 5 : chargés dans montar (Qt 6), ils font cohabiter deux versions
# de Qt dans le même processus et peuvent figer l'interface. Les images passent alors par
# le module « pixbuf ».
_DENIED_MODULES = ("libmltqt", "libmltglaxnimate")


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


class MltSource(Source):
    def __init__(self, path: str, kind: str, canvas: Canvas) -> None:
        self._profile = _profile(canvas)
        self._producer = mlt.Producer(self._profile, path)
        if not self._producer.is_valid():
            raise SourceError(f"MLT ne sait pas ouvrir {path}")
        if kind == "image":
            frames = IMAGE_PREVIEW_SECONDS * canvas.fps
            self._producer.set("length", frames)
            self._producer.set_in_and_out(0, frames - 1)
        self._fps = float(canvas.fps)

    @property
    def length(self) -> int:
        return max(1, self._producer.get_playtime())

    @property
    def fps(self) -> float:
        return self._fps

    def render(self, frame: int, width: int, height: int) -> bytes:
        self._producer.seek(max(0, min(frame, self.length - 1)))
        mlt_frame = self._producer.get_frame()
        mlt_frame.set("consumer.rescale", "bilinear")
        data = mlt_frame.get_image(mlt.mlt_image_rgba, width, height)
        expected = width * height * 4
        if data is None or len(data) < expected:
            raise SourceError("image non disponible")
        return bytes(data[:expected])

    def close(self) -> None:
        self._producer = None


class MltEngine(Engine):
    name = "MLT"

    def __init__(self) -> None:
        _ensure_factory()

    def version(self) -> str:
        return mlt.mlt_version_get_string()

    def open(self, path: str, kind: str, canvas: Canvas) -> Source:
        return MltSource(path, kind, canvas)
