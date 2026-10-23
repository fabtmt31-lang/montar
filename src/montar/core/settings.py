# SPDX-License-Identifier: GPL-3.0-or-later
"""Préférences utilisateur (fichier JSON local)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from montar.i18n import LANGUAGES
from montar.platform import paths

THEMES = ("light", "dark", "system")
PREVIEW_QUALITIES = {"low": 0.25, "medium": 0.5, "full": 1.0}
BACKUP_INTERVALS = (1, 2, 5, 10)  # minutes entre deux copies de sauvegarde
TRASH_DAYS = (7, 30, 90)  # durée de conservation des projets dans la corbeille
ACCENTS = ("#2F7A56", "#4E9A72", "#3A8C86", "#6F9A3A", "#5F7F6C")  # verts de la charte


@dataclass
class Settings:
    theme: str = "light"
    accent: str = ACCENTS[0]  # couleur d'accent (F-UX-01)
    language: str = "system"  # system | fr | en (pris en compte au démarrage)
    projects_dir: str = ""
    preview_quality: str = "medium"
    disabled_modules: list[str] = field(default_factory=list)
    hardware_export: bool = False  # accélération matérielle proposée à l'export
    video_waveforms: bool = True  # forme d'onde sous les vignettes des clips vidéo
    snap: bool = True  # magnétisme de la timeline à l'ouverture d'un projet
    preview_volume: float = 1.0  # volume d'écoute de l'aperçu (0 à 1)
    safe_zone: bool = False  # zone de sécurité affichée dans l'aperçu
    autosave: bool = True  # enregistrement à chaque modification (sinon Ctrl+S)
    backup_minutes: int = 2  # intervalle des copies datées dans « sauvegardes/ »
    trash_days: int = 30  # projets effacés de la corbeille après ce nombre de jours

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
        if settings.language not in ("system", *LANGUAGES):
            settings.language = "system"
        if settings.theme not in THEMES:
            settings.theme = "light"
        if settings.preview_quality not in PREVIEW_QUALITIES:
            settings.preview_quality = "medium"
        settings.preview_volume = max(0.0, min(1.0, settings.preview_volume))
        if settings.trash_days not in TRASH_DAYS:
            settings.trash_days = 30
        if settings.accent.upper() not in ACCENTS:
            settings.accent = ACCENTS[0]
        if settings.backup_minutes not in BACKUP_INTERVALS:
            settings.backup_minutes = 2
        return settings

    def save(self, file: Path) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
