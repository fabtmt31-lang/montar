# SPDX-License-Identifier: GPL-3.0-or-later
"""Kit de marque (F-PRJ-13) : logos, couleurs et polices de l'utilisateur, communs à tous
les projets. Rangé dans un dossier (copies des fichiers + `marque.json`)."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
FONT_EXTENSIONS = {".ttf", ".otf"}
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandError(ValueError):
    pass


@dataclass
class BrandKit:
    folder: Path
    colors: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, folder: Path) -> BrandKit:
        kit = cls(folder)
        try:
            data = json.loads((folder / "marque.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            kit.colors = [c.upper() for c in data.get("colors", [])
                          if isinstance(c, str) and _COLOR.match(c)]
        return kit

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "marque.json").write_text(
            json.dumps({"colors": self.colors}, indent=2), encoding="utf-8")

    @property
    def logos_dir(self) -> Path:
        return self.folder / "logos"

    @property
    def fonts_dir(self) -> Path:
        return self.folder / "polices"

    def logos(self) -> list[Path]:
        if not self.logos_dir.is_dir():
            return []
        return sorted(p for p in self.logos_dir.iterdir()
                      if p.suffix.lower() in LOGO_EXTENSIONS)

    def fonts(self) -> list[Path]:
        if not self.fonts_dir.is_dir():
            return []
        return sorted(p for p in self.fonts_dir.iterdir()
                      if p.suffix.lower() in FONT_EXTENSIONS)

    def _copy(self, source: Path, folder: Path, allowed: set[str]) -> Path:
        if source.suffix.lower() not in allowed:
            raise BrandError(f"format non pris en charge : {source.suffix or source.name}")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / source.name
        n = 2
        while target.exists():
            target = folder / f"{source.stem} ({n}){source.suffix}"
            n += 1
        shutil.copy2(source, target)
        return target

    def add_logo(self, source: Path) -> Path:
        return self._copy(Path(source), self.logos_dir, LOGO_EXTENSIONS)

    def add_font(self, source: Path) -> Path:
        return self._copy(Path(source), self.fonts_dir, FONT_EXTENSIONS)

    def remove(self, path: Path) -> None:
        path = Path(path)
        if path.parent in (self.logos_dir, self.fonts_dir):
            path.unlink(missing_ok=True)

    def add_color(self, color: str) -> bool:
        color = color.upper()
        if not _COLOR.match(color):
            raise BrandError(f"couleur invalide : {color}")
        if color in self.colors:
            return False
        self.colors.append(color)
        self.save()
        return True

    def remove_color(self, color: str) -> None:
        if color.upper() in self.colors:
            self.colors.remove(color.upper())
            self.save()
