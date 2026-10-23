# SPDX-License-Identifier: GPL-3.0-or-later
"""Notifications locales (F-PRJ-14) : export terminé, calcul échoué, module désactivé…
Gardées dans un petit fichier JSON (les 50 dernières)."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_KEPT = 50


@dataclass
class Notification:
    title: str
    text: str = ""
    kind: str = "info"  # info | success | error
    time: float = 0.0
    read: bool = False
    path: str = ""  # fichier à ouvrir (export terminé)


class Notifications:
    def __init__(self, file: Path | None = None) -> None:
        self.file = file
        self.items: list[Notification] = []
        self.listeners: list[Callable[[], None]] = []
        self._load()

    def _load(self) -> None:
        if self.file is None:
            return
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        fields = Notification.__dataclass_fields__
        self.items = [Notification(**{k: v for k, v in d.items() if k in fields})
                      for d in data if isinstance(d, dict) and isinstance(d.get("title"), str)]

    def _save(self) -> None:
        if self.file is None:
            return
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps([asdict(n) for n in self.items], ensure_ascii=False),
                                 encoding="utf-8")
        except OSError:
            pass

    def _changed(self) -> None:
        self._save()
        for listener in list(self.listeners):
            listener()

    def add(self, title: str, text: str = "", kind: str = "info", path: str = "") -> None:
        self.items.insert(0, Notification(title, text, kind, time.time(), False, path))
        del self.items[MAX_KEPT:]
        self._changed()

    @property
    def unread(self) -> int:
        return sum(1 for n in self.items if not n.read)

    def mark_all_read(self) -> None:
        if self.unread:
            for n in self.items:
                n.read = True
            self._changed()

    def clear(self) -> None:
        self.items = []
        self._changed()
