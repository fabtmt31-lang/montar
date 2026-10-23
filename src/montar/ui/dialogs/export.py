# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogue « Exporter la vidéo » (maquette 05)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from montar.core import formats
from montar.core.project import Project
from montar.core.timecode import frames_to_timecode, seconds_to_short
from montar.engine.export import (
    AUDIO_FORMATS,
    CODEC_LABELS,
    FORMAT_LABELS,
    IMAGE_FORMATS,
    QUALITIES,
    QUALITY_LABELS,
    RECOMMENDED_QUALITY,
    RESOLUTIONS,
    VIDEO_FORMATS,
    ExportSettings,
    estimated_bytes,
    export_size,
    human_size,
)
from montar.i18n import _
from montar.ui.widgets import Segmented, button, label, rounded_pixmap

GIF_RESOLUTIONS = ("480p",)  # un GIF plus grand pèse vite des centaines de Mo
PREVIEW_SIZE = QSize(380, 214)


def _safe_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in '/\\:*?"<>|').strip()
    return cleaned or _("Sans titre")


def _resolution_for(project: Project) -> str:
    short = min(project.canvas_size)
    return min(RESOLUTIONS, key=lambda k: abs(RESOLUTIONS[k] - short))


class _Chips(QWidget):
    """Rangée de choix exclusifs (Format, Résolution)."""

    def __init__(self, options: list[tuple[str, str]], current: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("variant", "choice")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(40)
            b.setChecked(key == current)
            self.group.addButton(b)
            self.buttons[key] = b
            layout.addWidget(b)
        layout.addStretch()

    def current(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())

    def set_current(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class ExportDialog(QDialog):
    def __init__(self, project: Project, frames: int, preview: QImage | None,
                 folder: Path, hardware: bool = False, parent: QWidget | None = None,
                 extra_formats=(), selection: tuple[int, int] | None = None,
                 playhead: int = 0) -> None:
        super().__init__(parent)
        self.project, self.frames = project, frames
        self.selection, self.playhead = selection, playhead
        # formats des modules (montar.api.ExportFormat), par identifiant
        self.extra = {f.id: f for f in extra_formats}
        self.setObjectName("ExportDialog")
        self.setWindowTitle(_("Exporter la vidéo"))
        self.setModal(True)
        self.setMinimumWidth(1000)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- aperçu et récapitulatif ---------------------------------------------------
        side = QFrame()
        side.setObjectName("ExportSide")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(28, 28, 28, 28)
        sl.setSpacing(18)
        sl.addWidget(label(_("Exporter la vidéo"), "h2"))
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("ExportPreview")
        if preview is not None and not preview.isNull():
            self.preview.setPixmap(rounded_pixmap(QPixmap.fromImage(preview), PREVIEW_SIZE, 12))
        else:
            self.preview.setStyleSheet("background: #0B120E; border-radius: 12px;")
        sl.addWidget(self.preview)
        duration = QLabel(seconds_to_short(frames / max(1, project.fps)), self.preview)
        duration.setObjectName("ExportDuration")
        duration.adjustSize()
        duration.move(PREVIEW_SIZE.width() - duration.width() - 10,
                      PREVIEW_SIZE.height() - duration.height() - 10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.summary_output = label("", "mono")
        self.summary_size = label("")
        self.summary_size.setStyleSheet("font-weight: 600;")
        for row, (title, value) in enumerate(((_("Projet"), label(project.name)),
                                              (_("Sortie"), self.summary_output),
                                              (_("Taille estimée"), self.summary_size))):
            grid.addWidget(label(title, "muted"), row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        sl.addLayout(grid)
        sl.addStretch()
        side.setFixedWidth(440)
        outer.addWidget(side)

        # --- réglages ------------------------------------------------------------------
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(28, 28, 28, 28)
        ml.setSpacing(8)
        self.tabs = Segmented([("file", _("Fichier")), ("audio", _("Audio seul")),
                               ("image", _("Image"))])
        self.tabs.changed.connect(self._tab_changed)
        ml.addWidget(self.tabs)
        ml.addSpacing(10)

        ml.addWidget(label(_("Nom du fichier")))
        self.name_edit = QLineEdit(_safe_filename(project.name))
        self.name_edit.setMinimumHeight(44)
        self.name_edit.textChanged.connect(self._update)
        ml.addWidget(self.name_edit)
        ml.addSpacing(8)
        ml.addWidget(label(_("Dossier")))
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(folder))
        self.folder_edit.setMinimumHeight(40)
        self.folder_edit.setReadOnly(True)
        change = button(_("Modifier…"), "secondary")
        change.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(change)
        ml.addLayout(folder_row)
        ml.addSpacing(8)

        ml.addWidget(label(_("Format")))
        extra_video = [(f.id, _(f.name)) for f in self.extra.values() if not f.audio_only]
        extra_audio = [(f.id, _(f.name)) for f in self.extra.values() if f.audio_only]
        self.video_formats = _Chips([(k, FORMAT_LABELS[k]) for k in VIDEO_FORMATS]
                                    + extra_video, "mp4")
        self.audio_formats = _Chips([(k, FORMAT_LABELS[k]) for k in AUDIO_FORMATS]
                                    + extra_audio, "mp3")
        for key, fmt in self.extra.items():
            chips = self.audio_formats if fmt.audio_only else self.video_formats
            chips.buttons[key].setToolTip(_(fmt.description))
        self.image_formats = _Chips([(k, FORMAT_LABELS[k]) for k in IMAGE_FORMATS], "png")
        self.audio_formats.setVisible(False)
        self.image_formats.setVisible(False)
        for chips in (self.video_formats, self.audio_formats, self.image_formats):
            chips.group.buttonClicked.connect(self._format_changed)
            ml.addWidget(chips)
        ml.addSpacing(8)

        self.range_box = QWidget()
        rl = QVBoxLayout(self.range_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(label(_("Partie exportée")))
        fps = project.fps
        span = (_("Sélection {a} → {b}").format(a=frames_to_timecode(selection[0], fps),
                                                b=frames_to_timecode(selection[1], fps))
                if selection else _("Sélection (touches I et O)"))
        self.part = _Chips([("all", _("Toute la vidéo")), ("range", span)], "all")
        self.part.buttons["range"].setEnabled(selection is not None)
        if selection is None:
            self.part.buttons["range"].setToolTip(_("Marquez d'abord une plage dans la "
                                                    "timeline avec I et O"))
        self.part.group.buttonClicked.connect(self._update)
        rl.addWidget(self.part)
        ml.addWidget(self.range_box)
        self.frame_hint = label(_("Image affichée à la tête de lecture ({tc}).").format(
            tc=frames_to_timecode(playhead, fps)), "muted")
        self.frame_hint.setVisible(False)
        ml.addWidget(self.frame_hint)
        ml.addSpacing(8)

        self.video_box = QWidget()
        vl = QVBoxLayout(self.video_box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)
        vl.addWidget(label(_("Résolution")))
        self.resolutions = _Chips([(k, k) for k in RESOLUTIONS], _resolution_for(project))
        self.resolutions.group.buttonClicked.connect(self._update)
        vl.addWidget(self.resolutions)
        ml.addWidget(self.video_box)
        ml.addSpacing(8)

        head = QHBoxLayout()
        head.addWidget(label(_("Qualité")))
        head.addStretch()
        self.recommended = label(_("Recommandée"), "muted")
        head.addWidget(self.recommended)
        ml.addLayout(head)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(0, len(QUALITIES) - 1)
        self.quality.setPageStep(1)
        self.quality.setValue(QUALITIES.index(RECOMMENDED_QUALITY))
        self.quality.valueChanged.connect(self._update)
        ml.addWidget(self.quality)
        marks = QHBoxLayout()
        for i, key in enumerate(QUALITIES):
            m = label(_(QUALITY_LABELS[key]), "small")
            m.setAlignment((Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignCenter,
                            Qt.AlignmentFlag.AlignRight)[i])
            marks.addWidget(m, 1)
        ml.addLayout(marks)
        ml.addSpacing(8)

        self.codec_box = QWidget()
        cg = QGridLayout(self.codec_box)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setHorizontalSpacing(12)
        cg.addWidget(label(_("Codec")), 0, 0)
        cg.addWidget(label(_("Images / s")), 0, 1)
        self.codec = QComboBox()
        self.codec.currentIndexChanged.connect(self._update)
        self.fps = QComboBox()
        for f in sorted({*formats.FRAME_RATES, project.fps}):
            text = f"{f} ({_('projet')})" if f == project.fps else str(f)
            self.fps.addItem(text, f)
        self.fps.setCurrentIndex(self.fps.findData(project.fps))
        self.fps.currentIndexChanged.connect(self._update)
        for combo in (self.codec, self.fps):
            combo.setMinimumHeight(40)
        cg.addWidget(self.codec, 1, 0)
        cg.addWidget(self.fps, 1, 1)
        ml.addWidget(self.codec_box)
        ml.addSpacing(8)
        self.hardware = QCheckBox(_("Accélération matérielle (carte graphique, si disponible)"))
        self.hardware.setChecked(hardware)
        ml.addWidget(self.hardware)
        ml.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        self.export_button = button(_("Exporter"), "primary", "download")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._accept)
        for b in (cancel, self.export_button):
            b.setMinimumHeight(44)
            buttons.addWidget(b)
        ml.addLayout(buttons)
        outer.addWidget(main, 1)
        self._format_changed()

    # --- état --------------------------------------------------------------------

    @property
    def audio_only(self) -> bool:
        return self.tabs.current() == "audio"

    @property
    def still_image(self) -> bool:
        return self.tabs.current() == "image"

    def _chips(self) -> _Chips:
        return {"audio": self.audio_formats, "image": self.image_formats}.get(
            self.tabs.current(), self.video_formats)

    def _tab_changed(self, _key: str) -> None:
        for chips in (self.video_formats, self.audio_formats, self.image_formats):
            chips.setVisible(chips is self._chips())
        self.range_box.setVisible(not self.still_image)
        self.frame_hint.setVisible(self.still_image)
        self._format_changed()

    def _format(self) -> str:
        return self._chips().current()

    def _format_changed(self, *_args) -> None:
        fmt = self._format()
        video = not self.audio_only and not self.still_image
        self.video_box.setVisible(not self.audio_only)
        self.codec_box.setVisible(video)
        self.hardware.setVisible(video and fmt in ("mp4", "mov"))
        for w in (self.quality, self.recommended):
            w.setEnabled(not self.still_image)
        custom = self.extra.get(fmt)
        if video:
            gif = fmt == "gif"
            for key, b in self.resolutions.buttons.items():
                b.setEnabled(not gif or key in GIF_RESOLUTIONS)
            if gif and self.resolutions.current() not in GIF_RESOLUTIONS:
                self.resolutions.set_current("480p")
            self.codec.blockSignals(True)
            self.codec.clear()
            if custom is not None:
                self.codec.addItem(_("Défini par le module"), "")
            for codec in VIDEO_FORMATS.get(fmt, ("", ()))[1]:
                self.codec.addItem(CODEC_LABELS[codec], codec)
            self.codec.blockSignals(False)
            self.codec.setEnabled(self.codec.count() > 1)
        self._update()

    def choose_format(self, fmt: str) -> None:
        """Présélectionne un format (bouton d'un module dans le panneau Modules)."""
        audio = fmt in AUDIO_FORMATS or (fmt in self.extra and self.extra[fmt].audio_only)
        self.tabs.set_current("image" if fmt in IMAGE_FORMATS else "audio" if audio else "file")
        self._tab_changed("")
        chips = self._chips()
        if fmt in chips.buttons:
            chips.buttons[fmt].setChecked(True)
            self._format_changed()

    def _extension(self) -> str:
        fmt = self._format()
        if fmt in self.extra:
            return self.extra[fmt].extension
        if self.still_image:
            return IMAGE_FORMATS[fmt]
        return AUDIO_FORMATS[fmt] if self.audio_only else VIDEO_FORMATS[fmt][0]

    def _label(self, fmt: str) -> str:
        return _(self.extra[fmt].name) if fmt in self.extra else FORMAT_LABELS[fmt]

    def target(self) -> Path:
        return Path(self.folder_edit.text()) / (_safe_filename(self.name_edit.text())
                                                + self._extension())

    def _range(self) -> tuple[int, int]:
        if self.part.current() == "range" and self.selection is not None:
            return self.selection
        return 0, 0

    def settings(self) -> ExportSettings:
        fmt = self._format()
        quality = QUALITIES[self.quality.value()]
        start, end = self._range()
        if self.audio_only:
            return ExportSettings(str(self.target()), fmt, "", 0, 0, self.project.fps, quality,
                                  custom_audio_only=fmt in self.extra, range_start=start,
                                  range_end=end)
        w, h = export_size(self.project.canvas_size, self.resolutions.current())
        if self.still_image:
            return ExportSettings(str(self.target()), fmt, "", w, h, self.project.fps,
                                  range_start=self.playhead, range_end=self.playhead + 1)
        return ExportSettings(str(self.target()), fmt, self.codec.currentData() or "h264",
                              w, h, self.fps.currentData(), quality,
                              self.hardware.isVisible() and self.hardware.isChecked(),
                              range_start=start, range_end=end)

    def _update(self, *_args) -> None:
        s = self.settings()
        self.recommended.setVisible(s.quality == RECOMMENDED_QUALITY)
        if s.audio_only:
            output = self._label(s.format)
        else:
            output = f"{self._label(s.format)} · {self.resolutions.current()}"
        self.summary_output.setText(output)
        start, end = self._range()
        frames = (end - start) if end else self.frames
        self.summary_size.setText(human_size(estimated_bytes(s, frames, self.project.fps)))
        self.export_button.setEnabled(bool(self.name_edit.text().strip()) and self.frames > 0)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, _("Dossier d'export"),
                                                  self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def _accept(self) -> None:
        target = self.target()
        if target.exists():
            answer = QMessageBox.question(
                self, _("Exporter la vidéo"),
                _("{name} existe déjà dans ce dossier. Le remplacer ?").format(name=target.name))
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()
