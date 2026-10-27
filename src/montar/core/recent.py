# SPDX-License-Identifier: GPL-3.0-or-later
"""Liste des projets récents, stockée localement."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from montar.core.project import Project, ProjectError

MAX_RECENT = 50


@dataclass
class RecentEntry:
    path: Path
    name: str
    aspect: str
    modified: float  # horodatage du fichier
    thumbnail_media: str | None  # chemin du premier média visuel, pour la vignette


class RecentProjects:
    def __init__(self, store: Path) -> None:
        self._store = store

    def paths(self) -> list[Path]:
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            return [Path(p) for p in data if isinstance(p, str)]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def _write(self, paths: list[Path]) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        self._store.write_text(
            json.dumps([str(p) for p in paths[:MAX_RECENT]], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    def add(self, path: Path) -> None:
        path = path.resolve()
        self._write([path] + [p for p in self.paths() if p != path])

    def remove(self, path: Path) -> None:
        path = path.resolve()
        self._write([p for p in self.paths() if p != path])

    def entries(self) -> list[RecentEntry]:
        """Projets existants, du plus récemment modifié au plus ancien."""
        result = []
        for path in self.paths():
            try:
                project = Project.load(path)
                modified = path.stat().st_mtime
            except (ProjectError, OSError):
                continue
            visual = next((m.path for m in project.media if m.kind in ("video", "image")), None)
            result.append(RecentEntry(path, project.name, project.format_label, modified, visual))
        result.sort(key=lambda e: e.modified, reverse=True)
        return result
