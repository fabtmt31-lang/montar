# SPDX-License-Identifier: GPL-3.0-or-later
"""Moteur de rendu. L'interface (base.py) isole l'application de MLT."""
from __future__ import annotations

from montar.engine.base import Engine, EngineUnavailable, Source, TimelineSpec, timeline_spec


def get_engine() -> Engine:
    from montar.engine.mlt_engine import MltEngine

    return MltEngine()


__all__ = ["Engine", "EngineUnavailable", "Source", "TimelineSpec", "get_engine", "timeline_spec"]
