# SPDX-License-Identifier: GPL-3.0-or-later
"""Ramasse-miettes de Python lancé seulement dans le fil de l'interface.

Python libère les cycles d'objets dans le fil qui alloue au moment où le seuil est
atteint : le fil de lecture de l'aperçu, celui du moteur ou ceux des imports. S'il y
détruisait un objet Qt de l'interface (fenêtre, vignette…), Qt le libérait depuis un autre
fil que le sien, d'où des plantages au hasard, plus tard, ailleurs (création d'une fenêtre,
ouverture d'un projet). Le ramassage automatique est donc coupé et fait ici,
régulièrement, dans le fil de l'interface."""
from __future__ import annotations

import gc

from PyQt6.QtCore import QObject, QTimer

INTERVAL_MS = 1000


class GarbageCollector(QObject):
    def __init__(self, parent: QObject | None = None, interval: int = INTERVAL_MS) -> None:
        super().__init__(parent)
        self._thresholds = gc.get_threshold()
        gc.disable()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(interval)

    def check(self) -> None:
        """Mêmes règles que le ramassage automatique (seuils par génération)."""
        counts = gc.get_count()
        for generation in (2, 1, 0):
            if counts[generation] > self._thresholds[generation]:
                gc.collect(generation)
                break

    def stop(self) -> None:
        self._timer.stop()
        gc.enable()


_GUARD: GarbageCollector | None = None


def install(app: QObject) -> GarbageCollector:
    """À appeler une fois, dans le fil de l'interface, après la création de l'application."""
    global _GUARD
    if _GUARD is None:
        _GUARD = GarbageCollector(app)
    return _GUARD
