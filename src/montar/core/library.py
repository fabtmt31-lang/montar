# SPDX-License-Identifier: GPL-3.0-or-later
"""Médiathèque (F-MED-04) : les médias de tous les projets connus, réutilisables dans un
autre projet (ils y sont copiés à l'import, comme tout média)."""
from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from montar.core.project import MediaItem, Project, ProjectError


@dataclass
class LibraryItem:
    media: MediaItem
    projects: list[str]  # noms des projets qui l'utilisent

    @property
    def path(self) -> str:
        return self.media.path


def library(project_paths: Iterable[Path]) -> list[LibraryItem]:
    """Médias existants des projets, sans doublon (même nom de fichier d'origine et même
    taille), du plus récemment modifié au plus ancien."""
    items: dict[tuple, LibraryItem] = {}
    for path in project_paths:
        try:
            project = Project.load(path)
        except ProjectError:
            continue
        for media in project.media:
            if not media.exists:
                continue
            try:
                size = os.path.getsize(media.path)
            except OSError:
                continue
            # une copie reprise d'un autre projet garde le nom de son original
            key = (Path(media.original_path or media.path).name, size)
            if key in items:
                if project.name not in items[key].projects:
                    items[key].projects.append(project.name)
            else:
                items[key] = LibraryItem(media, [project.name])
    return sorted(items.values(), key=lambda i: os.path.getmtime(i.path), reverse=True)
