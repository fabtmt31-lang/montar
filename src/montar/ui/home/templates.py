# SPDX-License-Identifier: GPL-3.0-or-later
"""Modèles de projet (F-PRJ-12) : modèles de démonstration fournis (textes seulement, aucun
média externe) et modèles de l'utilisateur (copies de projets, avec leurs médias)."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QInputDialog, QListWidgetItem, QMenu, QMessageBox, QVBoxLayout, QWidget

from montar.core import formats
from montar.core.project import PROJECT_SUFFIX, Project, ProjectError, unique_project_folder
from montar.core.project_files import duplicate
from montar.core.timeline import Timeline
from montar.i18n import N_, _
from montar.ui.text_render import preset_style, render
from montar.ui.thumbgrid import ROLE_ICON, ROLE_PAYLOAD, ROLE_PLACEHOLDER, ROLE_SUBTITLE, ThumbGrid
from montar.ui.widgets import label


@dataclass(frozen=True)
class Template:
    key: str  # identifiant (modèle fourni) ou chemin du fichier (modèle de l'utilisateur)
    name: str
    description: str
    aspect: str
    builtin: bool
    path: Path | None = None  # fichier .montar d'un modèle de l'utilisateur


def _text(t: Timeline, preset: str, content: str, start: int, seconds: int,
          new_track: bool = False, **changes):
    """Texte d'un modèle ; `new_track` le met sur sa propre piste (textes simultanés)."""
    style = replace(preset_style(preset), content=content, **changes)
    track = t.add_track("text").id if new_track else None
    clip = t.add_text(style, start, track, seconds * t.fps)
    return clip


def _intro(t: Timeline) -> None:
    _text(t, "title", _("Mon titre"), 0, 4, y=0.44, animation_in="fade", animation_out="fade")
    _text(t, "subtitle", _("Le sous-titre de la vidéo"), t.fps // 2, 3, new_track=True,
          y=0.62, animation_in="slide", animation_out="fade")


def _outro(t: Timeline) -> None:
    _text(t, "title", _("Merci d'avoir regardé !"), 0, 5, y=0.42, animation_in="typewriter",
          animation_out="fade")
    _text(t, "subscribe", _("S'abonner"), t.fps, 4, new_track=True, x=0.5, y=0.62,
          animation_in="slide")


def _story(t: Timeline) -> None:
    _text(t, "bold", _("À la une"), 0, 5, y=0.18, size=120, animation_in="slide")
    _text(t, "lower_third", _("Prénom Nom · Rôle"), t.fps, 4, new_track=True, x=0.5, y=0.8,
          align="center", animation_in="fade")


# (clé, nom, description, format, construction)
BUILTIN: tuple[tuple[str, str, str, str, Callable[[Timeline], None]], ...] = (
    ("intro", N_("Intro titre"), N_("Titre et sous-titre qui apparaissent en fondu."),
     "16:9", _intro),
    ("outro", N_("Fin de vidéo"), N_("Remerciement tapé à la machine et bouton « S'abonner »."),
     "16:9", _outro),
    ("story", N_("Story verticale"), N_("Format 9:16 : titre en haut, bandeau nom en bas."),
     "9:16", _story),
)


def builtin_templates() -> list[Template]:
    return [Template(key, _(name), _(desc), aspect, True)
            for key, name, desc, aspect, _b in BUILTIN]


def user_templates(folder: Path) -> list[Template]:
    result = []
    if not folder.is_dir():
        return result
    for path in sorted(folder.glob(f"*/*{PROJECT_SUFFIX}")):
        try:
            project = Project.load(path)
        except ProjectError:
            continue
        result.append(Template(str(path), project.name, _("Votre modèle"), project.format_label,
                               False, path))
    return result


def save_as_template(project_path: Path, name: str, folder: Path) -> Path:
    """Copie du projet (fichier et médias) rangée parmi les modèles."""
    folder.mkdir(parents=True, exist_ok=True)
    return duplicate(project_path, name, folder)


def create_from_template(template: Template, name: str, root: Path,
                         resolution: str = formats.DEFAULT_RESOLUTION) -> Path:
    """Nouveau projet `name` dans `root` à partir du modèle ; renvoie son fichier."""
    if template.path is not None:
        return duplicate(template.path, name, root)
    _key, _n, _d, aspect, build = next(b for b in BUILTIN if b[0] == template.key)
    project = Project(name=name, aspect=aspect, resolution=resolution)
    build(Timeline(project))
    target = unique_project_folder(root, name)
    project.save(target)
    return target


def delete_template(template: Template) -> None:
    if template.path is not None and not template.builtin:
        shutil.rmtree(template.path.parent, ignore_errors=True)


PREVIEW_SIZE = QSize(320, 180)


def preview(template: Template, size: QSize = PREVIEW_SIZE) -> QPixmap | None:
    """Aperçu d'un modèle fourni : son premier texte sur fond sombre."""
    if not template.builtin:
        return None
    _key, _n, _d, aspect, build = next(b for b in BUILTIN if b[0] == template.key)
    project = Project(name="", aspect=aspect, resolution="720p")
    build(Timeline(project))
    w, h = project.canvas_size
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#17261E"))
    painter = QPainter(image)
    for clip in sorted(project.clips, key=lambda c: c.start):
        painter.drawImage(0, 0, render(clip.text, w, h))
    painter.end()
    # toile entière dans une vignette 16:9 (un format vertical garde ses bandes)
    frame = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(QColor("#0E1A14"))
    fitted = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(frame)
    painter.drawImage((size.width() - fitted.width()) // 2,
                      (size.height() - fitted.height()) // 2, fitted)
    painter.end()
    return QPixmap.fromImage(frame)


class TemplatesPage(QWidget):
    """Accueil → Modèles : un clic crée un projet à partir du modèle."""

    useRequested = pyqtSignal(object)  # Template
    deleteRequested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(14)
        layout.addWidget(label(_("Modèles"), "h1"))
        hint = label(_("Partez d'un modèle pour gagner du temps. Pour créer le vôtre : dans un "
                       "projet, menu « ⋯ » → « Enregistrer comme modèle… »."), "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.grid = ThumbGrid(min_width=220, aspect=16 / 11, title_px=14, radius=12)
        self.grid.itemClicked.connect(lambda item: self.useRequested.emit(
            item.data(ROLE_PAYLOAD)))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.grid, 1)

    def set_templates(self, templates: list[Template]) -> None:
        self.grid.clear()
        for t in templates:
            item = QListWidgetItem(t.name)
            item.setData(ROLE_SUBTITLE, f"{t.aspect} · {t.description}")
            item.setData(ROLE_PLACEHOLDER, "mint" if t.builtin else "water")
            item.setData(ROLE_ICON, "layout-grid")
            item.setData(ROLE_PAYLOAD, t)
            pm = preview(t)
            if pm is not None:
                item.setData(Qt.ItemDataRole.DecorationRole, pm)
            self.grid.addItem(item)

    def _context_menu(self, pos) -> None:
        item = self.grid.itemAt(pos)
        if item is None:
            return
        template = item.data(ROLE_PAYLOAD)
        menu = QMenu(self)
        menu.addAction(_("Créer un projet"), lambda: self.useRequested.emit(template))
        if not template.builtin:
            menu.addAction(_("Supprimer le modèle"), lambda: self.deleteRequested.emit(template))
        menu.exec(self.grid.viewport().mapToGlobal(pos))


def ask_name(parent, title: str, default: str) -> str | None:
    name, ok = QInputDialog.getText(parent, title, _("Nom :"), text=default)
    return name.strip() if ok and name.strip() else None


def confirm_delete(parent, template: Template) -> bool:
    return QMessageBox.question(parent, _("Supprimer le modèle"), _(
        "Supprimer le modèle « {name} » ?").format(name=template.name)) == \
        QMessageBox.StandardButton.Yes
