# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences utilisateur (fichier JSON local)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from montar.platform import paths

THEMES = ("light", "dark", "system")
PREVIEW_QUALITIES = {"low": 0.25, "medium": 0.5, "full": 1.0}


@dataclass
class Settings:
    theme: str = "light"
    projects_dir: str = ""
    preview_quality: str = "medium"
    disabled_modules: list[str] = field(default_factory=list)
    hardware_export: bool = False  # accélération matérielle proposée à l'export
    video_waveforms: bool = True  # forme d'onde sous les vignettes des clips vidéo
    snap: bool = True  # magnétisme de la timeline à l'ouverture d'un projet

    @property
    def projects_path(self) -> Path:
        return Path(self.projects_dir) if self.projects_dir else paths.default_projects_dir()

    @classmethod
    def load(cls, file: Path) -> Settings:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data
                  and type(data[f.name]) is type(getattr(defaults, f.name))
                  and not isinstance(data[f.name], list)}
        disabled = data.get("disabled_modules")
        if isinstance(disabled, list):
            values["disabled_modules"] = [m for m in disabled if isinstance(m, str)]
        settings = cls(**values)
        if settings.theme not in THEMES:
            settings.theme = "light"
        if settings.preview_quality not in PREVIEW_QUALITIES:
            settings.preview_quality = "medium"
        return settings

    def save(self, file: Path) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
