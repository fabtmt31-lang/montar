# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences utilisateur (fichier JSON local)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from montar.platform import paths

THEMES = ("light", "dark", "system")
PREVIEW_QUALITIES = {"low": 0.25, "medium": 0.5, "full": 1.0}


@dataclass
class Settings:
    theme: str = "light"
    projects_dir: str = ""
    preview_quality: str = "medium"

    @property
    def projects_path(self) -> Path:
        return Path(self.projects_dir) if self.projects_dir else paths.default_projects_dir()

    @classmethod
    def load(cls, file: Path) -> Settings:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known and isinstance(v, str)})
        if settings.theme not in THEMES:
            settings.theme = "light"
        if settings.preview_quality not in PREVIEW_QUALITIES:
            settings.preview_quality = "medium"
        return settings

    def save(self, file: Path) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
