# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogue « Nouveau projet » (maquette 04)."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from montar.core import formats
from montar.i18n import _
from montar.ui.theme import theme
from montar.ui.widgets import button, label, set_icon

_SWATCHES = {
    "16:9": ("mist", 66, 37), "9:16": ("pistachio", 36, 62), "1:1": ("water", 52, 52),
    "4:5": ("voiceover", 46, 57), "21:9": ("mist", 72, 31),
}


@dataclass
class NewProjectParams:
    name: str
    aspect: str
    resolution: str
    fps: int


class _FormatCard(QPushButton):
    def __init__(self, ar: formats.AspectRatio) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setProperty("variant", "tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(130, 138)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(2)
        role, w, h = _SWATCHES[ar.id]
        self._swatch = QFrame()
        self._swatch.setFixedSize(w, h)
        self._role = role
        holder = QWidget()
        holder.setFixedHeight(66)
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self._swatch, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(holder)
        layout.addSpacing(6)
        for text, role_name in ((ar.id, "h3"), (_(ar.label), "small")):
            lbl = label(text, role_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(lbl)
        for w_ in (holder, self._swatch):
            w_.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        theme().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        p = theme().palette
        self._swatch.setStyleSheet(f"background: {getattr(p, self._role)}; border-radius: 6px;"
                                   f"border: 1px solid {p.sage};")


def _choice_row(values: list[str], current: str) -> tuple[QHBoxLayout, QButtonGroup]:
    row = QHBoxLayout()
    row.setSpacing(8)
    group = QButtonGroup(row)
    for v in values:
        b = QPushButton(v)
        b.setCheckable(True)
        b.setProperty("variant", "chip")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setChecked(v == current)
        b.setMinimumHeight(40)
        b.setStyleSheet("QPushButton { border-radius: 10px; padding: 6px 16px; }")
        group.addButton(b)
        row.addWidget(b)
    row.addStretch()
    return row, group


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, name: str = "",
                 aspect: str = formats.DEFAULT_ASPECT) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Nouveau projet"))
        self.setModal(True)
        self.setMinimumWidth(860)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("DialogCard")
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 26, 28, 0)
        layout.setSpacing(0)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label(_("Nouveau projet"), "h2"))
        titles.addWidget(label(_("Choisissez un format. Vous pourrez le modifier à tout moment."),
                               "muted"))
        head.addLayout(titles, 1)
        close = button("", "tonal", "x", tooltip=_("Fermer"))
        close.setFixedSize(40, 40)
        set_icon(close, "x", "ink", 18)
        close.clicked.connect(self.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)
        layout.addSpacing(22)

        layout.addWidget(label(_("Nom du projet")))
        layout.addSpacing(8)
        self.name_edit = QLineEdit(name or _("Sans titre"))
        self.name_edit.setMinimumHeight(46)
        self.name_edit.selectAll()
        layout.addWidget(self.name_edit)
        layout.addSpacing(22)

        layout.addWidget(label(_("Format")))
        layout.addSpacing(8)
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(12)
        self._format_group = QButtonGroup(self)
        self._format_cards: dict[str, _FormatCard] = {}
        for ar in formats.ASPECT_RATIOS:
            c = _FormatCard(ar)
            c.setChecked(ar.id == aspect)
            c.clicked.connect(self._update_info)
            self._format_group.addButton(c)
            self._format_cards[ar.id] = c
            fmt_row.addWidget(c, 1)
        layout.addLayout(fmt_row)
        layout.addSpacing(22)

        opts = QHBoxLayout()
        res_col = QVBoxLayout()
        res_col.addWidget(label(_("Résolution")))
        res_col.addSpacing(8)
        res_row, self._res_group = _choice_row(list(formats.RESOLUTIONS),
                                               formats.DEFAULT_RESOLUTION)
        res_col.addLayout(res_row)
        fps_col = QVBoxLayout()
        fps_col.addWidget(label(_("Images par seconde")))
        fps_col.addSpacing(8)
        fps_row, self._fps_group = _choice_row([str(f) for f in formats.FRAME_RATES],
                                               str(formats.DEFAULT_FPS))
        fps_col.addLayout(fps_row)
        opts.addLayout(res_col, 1)
        opts.addLayout(fps_col, 1)
        layout.addLayout(opts)
        for g in (self._res_group, self._fps_group):
            g.buttonClicked.connect(self._update_info)
        layout.addSpacing(22)

        info = QFrame()
        info.setObjectName("InfoBox")
        il = QHBoxLayout(info)
        il.setContentsMargins(16, 12, 16, 12)
        self._info_icon = QLabel()
        il.addWidget(self._info_icon)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        il.addWidget(self.info, 1)
        layout.addWidget(info)
        layout.addSpacing(24)

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 18, 0, 18)
        fl.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.setStyleSheet("")
        cancel.clicked.connect(self.reject)
        self.create_button = button(_("Créer le projet"), "primary")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._accept)
        for b in (cancel, self.create_button):
            b.setMinimumHeight(44)
            fl.addWidget(b)
        layout.addWidget(footer)
        self.name_edit.textChanged.connect(
            lambda t: self.create_button.setEnabled(bool(t.strip())))
        theme().changed.connect(self._update_info)
        self._update_info()

    def _accept(self) -> None:
        if self.name_edit.text().strip():
            self.accept()

    def params(self) -> NewProjectParams:
        aspect = next(k for k, c in self._format_cards.items() if c.isChecked())
        return NewProjectParams(
            name=self.name_edit.text().strip(),
            aspect=aspect,
            resolution=self._res_group.checkedButton().text(),
            fps=int(self._fps_group.checkedButton().text()),
        )

    def _update_info(self) -> None:
        from montar.ui.theme.icons import pixmap

        p = self.params()
        w, h = formats.canvas_size(p.aspect, p.resolution)
        mono = "font-family: 'JetBrains Mono'; font-weight: 700;"
        self.info.setText(
            _("Taille de la toile : {size} · {fps} i/s").format(
                size=f"<span style=\"{mono}\">{w} × {h}</span>", fps=p.fps))
        self._info_icon.setPixmap(pixmap("info", theme().palette.forest, 18))
