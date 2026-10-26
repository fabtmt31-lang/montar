# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre « Finition pro » : étalonnage (onglet Image) et mastering (onglet Son) de tout le
projet, avec comparaison avant / après, plans à harmoniser, scopes et mesures."""
from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from montar.core import mastering as cm
from montar.core.mastering import Mastering
from montar.core.timecode import frames_to_timecode
from montar.engine import mastering as mst
from montar.engine.base import Engine, Source, TimelineSpec
from montar.engine.master_job import Analysis, analyse
from montar.i18n import _
from montar.ui.editor.controls import SliderRow, section
from montar.ui.editor.finition_widgets import CompareView, EqEditor, LoudnessGraph, ShotStrip
from montar.ui.editor.grading import ColorWheel, CurvesEditor, import_lut
from montar.ui.editor.scopes import render_scope
from montar.ui.widgets import Segmented, Switch, button, label

log = logging.getLogger(__name__)

PREVIEW_WIDTH = 640
SCOPE_KINDS = (("waveform", "FORME D'ONDE"), ("vector", "VECTEURSCOPE"),
               ("parade", "PARADE RVB"))
LOOK_COLORS = {
    "natural": ("#B9C6BC", "#627A5F"), "cinema": ("#E3B678", "#2F4A36"),
    "warm": ("#F2B263", "#7A3F1D"), "cool": ("#9FC3D9", "#1E3A4F"),
    "teal_orange": ("#3F8C8A", "#C9773C"), "film": ("#D8C7A4", "#6B5A44"),
    "bw": ("#D6D6D6", "#2B2B2B"),
}


def _pct(v: float) -> str:
    return f"{round(v * 100)} %"


def _signed(v: float) -> str:
    return f"{round(v * 100):+d}".replace("-", "−") if round(v * 100) else "0"


def _db(v: float | None) -> str:
    if v is None or v <= -69:
        return "—"
    return f"{v:.1f}".replace("-", "−").replace(".", ",")


class _Tile(QFrame):
    """Mesure : titre, valeur actuelle, valeur après finition."""

    def __init__(self, title: str, unit: str) -> None:
        super().__init__()
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        layout.addWidget(label(title, "small"))
        self.value = label("—", "mono")
        self.value.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.unit = unit
        layout.addWidget(self.value)
        self.after = label("", "small")
        layout.addWidget(self.after)

    def set_values(self, value: str, after: str) -> None:
        self.value.setText(f"{value} {self.unit}" if value != "—" else "—")
        self.after.setText(after)


class _Choices(QWidget):
    """Choix exclusifs empilés (libellés trop longs pour un contrôle segmenté)."""

    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        group = QButtonGroup(self)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("variant", "choice")
            b.setMinimumHeight(36)
            b.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
            group.addButton(b)
            layout.addWidget(b)
            self._buttons[key] = b

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)


class FinitionDialog(QDialog):
    """Édite une copie des réglages ; `mastering` et `analysis` sont lus après `accept()`.

    `spec_factory` donne la timeline du projet sans finition, `lut_path` le chemin absolu
    d'une LUT du projet, `project_dir` le dossier où copier une LUT importée."""

    def __init__(self, project, spec_factory: Callable[[], TimelineSpec],
                 engine_factory: Callable[[], Engine], playhead: int = 0,
                 analysis: Analysis | None = None,
                 lut_path: Callable[[str], str] = lambda _p: "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.setWindowTitle(_("Finition pro"))
        self.setModal(True)
        self.resize(1280, 820)
        self.project = project
        self.mastering: Mastering = copy.deepcopy(project.mastering)
        self.analysis = analysis
        self._spec_factory, self._engine_factory = spec_factory, engine_factory
        self._lut_path = lut_path
        self._engine: Engine | None = None
        self._base: TimelineSpec | None = None
        self._before: Source | None = None
        self._after: Source | None = None
        self._length = 0
        self._frame = playhead
        self._loading = False
        self._analysis_thread: threading.Thread | None = None
        self._analysis_result: Analysis | Exception | None = None
        self._analysis_progress = 0.0
        self._cancel_analysis = threading.Event()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_image())
        self.pages.addWidget(self._build_sound())
        outer.addWidget(self.pages, 1)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._poll_analysis)

        self._load()
        self._show_analysis()
        QTimer.singleShot(0, self._prepare_preview)

    # --- construction ----------------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("EditorHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        title = QVBoxLayout()
        title.setSpacing(0)
        title.addWidget(label(_("Finition pro"), "h3"))
        title.addWidget(label(_("{name} · tout le projet").format(name=self.project.name),
                              "small"))
        layout.addLayout(title)
        layout.addSpacing(16)
        self.tabs = Segmented([("image", _("Image")), ("sound", _("Son"))], "image")
        self.tabs.changed.connect(lambda k: self.pages.setCurrentIndex(0 if k == "image" else 1))
        layout.addWidget(self.tabs)
        layout.addStretch(1)
        self.preset = QComboBox()
        self.preset.setMinimumHeight(36)
        self.preset.setToolTip(_("Préréglage de finition"))
        self._fill_presets()
        self.preset.activated.connect(self._preset_chosen)
        layout.addWidget(self.preset)
        save = button(_("Enregistrer le préréglage…"), "secondary")
        save.clicked.connect(self._save_preset)
        layout.addWidget(save)
        reset = button(_("Réinitialiser"), "secondary", "rotate-ccw")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)
        layout.addSpacing(8)
        self.preview_switch = Switch(self.mastering.preview)
        self.preview_switch.setToolTip(_("Voir et écouter la finition dans l'aperçu de "
                                         "l'éditeur"))
        self.preview_switch.toggled.connect(lambda on: setattr(self.mastering, "preview", on))
        layout.addWidget(self.preview_switch)
        layout.addWidget(label(_("Dans l'aperçu")))
        layout.addSpacing(8)
        cancel = button(_("Annuler"), "secondary")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        ok = button(_("Valider"), "primary", "check")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        layout.addWidget(ok)
        return header

    def _side(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(400)
        scroll.setWidget(content)
        return scroll

    def _slider(self, layout, title: str, minimum: float, maximum: float,
                apply: Callable[[float], None], fmt=_signed) -> SliderRow:
        row = SliderRow(title, minimum, maximum, fmt)
        row.moved.connect(lambda v: self._changed(lambda: apply(v)))
        layout.addWidget(row)
        return row

    def _switch_row(self, layout, title: str, apply: Callable[[bool], None]) -> Switch:
        row = QHBoxLayout()
        row.addWidget(label(title), 1)
        switch = Switch()
        switch.toggled.connect(lambda on: self._changed(lambda: apply(on)))
        row.addWidget(switch)
        layout.addLayout(row)
        return switch

    def _build_image(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.compare = CompareView()
        left.addWidget(self.compare, 1)
        controls = QHBoxLayout()
        self.compare_mode = Segmented([("curtain", _("Rideau")), ("side", _("Côte à côte"))],
                                      "curtain")
        self.compare_mode.changed.connect(self.compare.set_mode)
        controls.addWidget(self.compare_mode)
        self.zebras = QPushButton(_("Zébras hors gamme"))
        self.zebras.setCheckable(True)
        self.zebras.setProperty("variant", "choice")
        self.zebras.setToolTip(_("Rayures rouges sur les blancs brûlés et les noirs bouchés"))
        self.zebras.toggled.connect(self.compare.set_zebras)
        controls.addWidget(self.zebras)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setToolTip(_("Image comparée"))
        self.position.valueChanged.connect(self._seek)
        controls.addWidget(self.position, 1)
        self.timecode = label("", "mono")
        controls.addWidget(self.timecode)
        left.addLayout(controls)

        head = QHBoxLayout()
        head.addWidget(section(_("PLANS DU PROJET · HARMONISATION")))
        head.addStretch(1)
        self.reference_label = label("", "small")
        head.addWidget(self.reference_label)
        self.analyse_image = button(_("Analyser le projet"), "secondary", "activity")
        self.analyse_image.clicked.connect(self._start_analysis)
        head.addWidget(self.analyse_image)
        left.addLayout(head)
        self.shots = ShotStrip()
        self.shots.setToolTip(_("Cliquez sur un plan pour en faire la référence"))
        self.shots.picked.connect(self._pick_reference)
        strip = QScrollArea()
        strip.setWidgetResizable(True)
        strip.setFrameShape(QFrame.Shape.NoFrame)
        strip.setFixedHeight(ShotStrip.THUMB[1] + 26)
        strip.setWidget(self.shots)
        left.addWidget(strip)

        scopes = QHBoxLayout()
        self.scopes: dict[str, QLabel] = {}
        for key, title in SCOPE_KINDS:
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(label(_(title), "section"))
            view = QLabel()
            view.setFixedHeight(130)
            view.setMinimumWidth(160)
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            view.setStyleSheet("background: #0B120E; border-radius: 8px;")
            box.addWidget(view)
            scopes.addLayout(box, 1)
            self.scopes[key] = view
        left.addLayout(scopes)
        layout.addLayout(left, 1)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 12, 0)
        sl.setSpacing(6)
        sl.addWidget(section(_("1 · LOOK")))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.look_group = QButtonGroup(self)
        self.look_group.setExclusive(False)
        self.look_buttons: dict[str, QPushButton] = {}
        looks = [*cm.LOOKS.items(), ("lut", "LUT .cube…")]
        for i, (key, text) in enumerate(looks):
            b = QPushButton(_(text).replace("&", "&&"))  # « & » n'est pas un raccourci
            b.setCheckable(True)
            b.setMinimumHeight(52)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if key in LOOK_COLORS:
                top, bottom = LOOK_COLORS[key]
                b.setStyleSheet(
                    "QPushButton { color: #FFFFFF; font-weight: 700; font-size: 11px; "
                    "text-align: left; padding: 22px 6px 4px 6px; border-radius: 8px; "
                    f"border: 2px solid transparent; background: qlineargradient(x1:0, y1:0, "
                    f"x2:1, y2:1, stop:0 {top}, stop:1 {bottom}); }}"
                    "QPushButton:checked { border: 2px solid #4FA67A; }")
            else:
                b.setProperty("variant", "dashed")
            b.clicked.connect(lambda _c=False, k=key: self._pick_look(k))
            self.look_group.addButton(b)
            self.look_buttons[key] = b
            grid.addWidget(b, i // 4, i % 4)
        sl.addLayout(grid)
        self.lut_label = label("", "small")
        self.lut_label.setWordWrap(True)
        sl.addWidget(self.lut_label)
        v = lambda: self.mastering.video  # noqa: E731
        self.look_amount = self._slider(sl, _("Intensité"), 0, 1,
                                        lambda x: setattr(v(), "look_amount", x), _pct)

        sl.addWidget(section(_("2 · CORRECTION GLOBALE")))
        wheels = QGridLayout()
        wheels.setHorizontalSpacing(6)
        self.wheels: dict[str, tuple[ColorWheel, QSlider]] = {}
        for col, (key, title) in enumerate((("lift", _("Ombres")), ("gamma", _("Tons moyens")),
                                            ("gain", _("Hautes lumières")))):
            name = label(title, "small")
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wheel = ColorWheel(84)
            wheel.setToolTip(_("Glissez vers une couleur pour l'ajouter ; Maj : réglage fin ; "
                               "double-clic : neutre"))
            wheel.moved.connect(lambda x, y, k=key: self._changed(
                lambda: setattr(v().grade, k, [x, y])))
            level = QSlider(Qt.Orientation.Horizontal)
            level.setRange(-100, 100)
            level.setFixedWidth(84)
            level.setToolTip(_("Niveau : plus sombre ↔ plus clair"))
            level.valueChanged.connect(lambda n, k=key: self._changed(
                lambda: setattr(v().grade, f"{k}_level", n / 100)))
            wheels.addWidget(wheel, 0, col, Qt.AlignmentFlag.AlignHCenter)
            wheels.addWidget(name, 1, col)
            wheels.addWidget(level, 2, col, Qt.AlignmentFlag.AlignHCenter)
            self.wheels[key] = (wheel, level)
        sl.addLayout(wheels)
        self.color_rows: dict[str, SliderRow] = {}
        for key, title in (("exposure", _("Exposition")), ("contrast", _("Contraste")),
                           ("saturation", _("Saturation")), ("temperature", _("Température"))):
            self.color_rows[key] = self._slider(
                sl, title, -1, 1, lambda x, k=key: setattr(v().color, k, x))
        self.tint = self._slider(sl, _("Teinte (vert ↔ magenta)"), -1, 1,
                                 lambda x: setattr(v(), "tint", x))
        self.vibrance = self._slider(sl, _("Vibrance"), -1, 1,
                                     lambda x: setattr(v().grade, "vibrance", x))
        more = button(_("Courbes…"), "secondary")
        more.setCheckable(True)
        sl.addWidget(more)
        self.curves_box = QWidget()
        cb = QVBoxLayout(self.curves_box)
        cb.setContentsMargins(0, 0, 0, 0)
        self.curve_channel = Segmented([("master", _("Lum.")), ("red", _("Rouge")),
                                        ("green", _("Vert")), ("blue", _("Bleu"))],
                                       "master", compact=True)
        cb.addWidget(self.curve_channel)
        self.curves = CurvesEditor()
        self.curve_channel.changed.connect(self.curves.set_channel)
        self.curves.changed.connect(lambda ch, pts: self._changed(
            lambda: v().grade.curves.__setitem__(ch, [list(p) for p in pts])))
        cb.addWidget(self.curves)
        self.curves_box.setVisible(False)
        more.toggled.connect(self.curves_box.setVisible)
        sl.addWidget(self.curves_box)

        sl.addWidget(section(_("3 · CONFORMITÉ")))
        self.match = self._switch_row(sl, _("Harmoniser les plans sur la référence"),
                                      lambda on: setattr(v(), "match_shots", on))
        self.match_amount = self._slider(sl, _("Force de l'harmonisation"), 0, 1,
                                         lambda x: setattr(v(), "match_amount", x), _pct)
        self.legal = self._switch_row(sl, _("Niveaux légaux (16–235)"),
                                      lambda on: setattr(v(), "legal", on))
        row = QHBoxLayout()
        row.addWidget(label(_("Espace couleur de sortie")), 1)
        self.color_space = QComboBox()
        for key, text in cm.COLOR_SPACES.items():
            self.color_space.addItem(_(text), key)
        self.color_space.currentIndexChanged.connect(lambda _i: self._changed(
            lambda: setattr(v(), "color_space", self.color_space.currentData())))
        row.addWidget(self.color_space)
        sl.addLayout(row)
        self.grain = self._slider(sl, _("Grain"), 0, 1, lambda x: setattr(v(), "grain", x), _pct)
        self.vignette = self._slider(sl, _("Vignette"), 0, 1,
                                     lambda x: setattr(v(), "vignette", x), _pct)
        sl.addStretch(1)
        layout.addWidget(self._side(side))
        return page

    def _build_sound(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(12)
        tiles = QHBoxLayout()
        self.tile_lufs = _Tile(_("Loudness intégrée"), "LUFS")
        self.tile_peak = _Tile(_("Crête vraie"), "dBTP")
        self.tile_lra = _Tile(_("Plage dynamique (LRA)"), "LU")
        self.tile_balance = _Tile(_("Voix / musique"), "dB")
        for tile in (self.tile_lufs, self.tile_peak, self.tile_lra, self.tile_balance):
            tiles.addWidget(tile, 1)
        left.addLayout(tiles)
        head = QHBoxLayout()
        head.addWidget(section(_("LOUDNESS SUR TOUT LE PROJET (COURT TERME)")))
        head.addStretch(1)
        head.addWidget(label(_("orange : avant · vert : après · rouge : cible"), "small"))
        self.analyse_sound = button(_("Analyser le projet"), "secondary", "activity")
        self.analyse_sound.clicked.connect(self._start_analysis)
        head.addWidget(self.analyse_sound)
        left.addLayout(head)
        self.graph = LoudnessGraph()
        left.addWidget(self.graph, 1)
        left.addWidget(section(_("ÉGALISEUR DE MASTERING")))
        self.eq = EqEditor()
        self.eq.setToolTip(_("Glissez un point vers le haut ou le bas ; double-clic : 0 dB. "
                             "En fond : le spectre moyen du projet."))
        self.eq.changed.connect(self._eq_changed)
        left.addWidget(self.eq, 1)
        layout.addLayout(left, 1)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 12, 0)
        sl.setSpacing(6)
        a = lambda: self.mastering.audio  # noqa: E731
        sl.addWidget(section(_("1 · DESTINATION")))
        self.destinations: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, (text, lufs, _peak) in [*cm.DESTINATIONS.items(),
                                          ("custom", ("Personnalisé…", None, None))]:
            b = QPushButton(f"{_(text)}   {_db(lufs) + ' LUFS' if lufs is not None else ''}")
            b.setCheckable(True)
            b.setProperty("variant", "choice")
            b.setMinimumHeight(38)
            b.clicked.connect(lambda _c=False, k=key: self._pick_destination(k))
            group.addButton(b)
            sl.addWidget(b)
            self.destinations[key] = b
        grid = QGridLayout()
        grid.addWidget(label(_("Loudness visée (LUFS)")), 0, 0)
        self.lufs = QDoubleSpinBox()
        self.lufs.setRange(-31, -8)
        self.lufs.setDecimals(1)
        self.lufs.setSingleStep(0.5)
        self.lufs.valueChanged.connect(lambda x: self._custom_target("lufs", x))
        grid.addWidget(self.lufs, 0, 1)
        grid.addWidget(label(_("Crête maximale (dBTP)")), 1, 0)
        self.peak = QDoubleSpinBox()
        self.peak.setRange(-6, 0)
        self.peak.setDecimals(1)
        self.peak.setSingleStep(0.5)
        self.peak.valueChanged.connect(lambda x: self._custom_target("true_peak", x))
        grid.addWidget(self.peak, 1, 1)
        sl.addLayout(grid)

        sl.addWidget(section(_("2 · CHAÎNE DE MASTERING")))
        self.cleanup = self._switch_row(sl, _("Nettoyage (coupe-bas 70 Hz, dé-esseur)"),
                                        lambda on: setattr(a(), "cleanup", on))
        row = QHBoxLayout()
        row.addWidget(label(_("Tonalité")), 1)
        self.tone = QComboBox()
        for key, (text, _gains) in cm.TONES.items():
            self.tone.addItem(_(text), key)
        self.tone.addItem(_("Personnalisée"), "custom")
        self.tone.activated.connect(self._tone_chosen)
        row.addWidget(self.tone)
        sl.addLayout(row)
        self.compress = self._slider(sl, _("Compression"), 0, 1,
                                     lambda x: setattr(a(), "compress", x), _pct)
        self.voice_front = self._slider(sl, _("Voix devant"), 0, 1,
                                        lambda x: setattr(a(), "voice_front", x), _pct)
        self.stereo_width = self._slider(sl, _("Largeur stéréo"), 0, 2,
                                  lambda x: setattr(a(), "width", x), _pct)
        self.limiter = self._switch_row(sl, _("Limiteur de crête"),
                                        lambda on: setattr(a(), "limiter", on))

        sl.addWidget(section(_("3 · SORTIE DU SON")))
        self.layout_choice = _Choices([(k, _(t)) for k, t in cm.LAYOUTS.items()])
        self.layout_choice.changed.connect(lambda k: self._changed(
            lambda: setattr(a(), "layout", k), render=False))
        sl.addWidget(self.layout_choice)
        hint = label(_("5.1 : dialogues au centre, musique et effets autour, basses sur le "
                       "caisson. Pistes séparées : fichiers WAV « Dialogues » et « Musique et "
                       "effets » à côté de la vidéo."), "small")
        hint.setWordWrap(True)
        sl.addWidget(hint)
        note = label(_("Les réglages de chaque clip (onglet Audio de l'inspecteur) restent "
                       "appliqués avant : la finition agit sur le mixage final, comme un "
                       "ingénieur de mastering."), "small")
        note.setWordWrap(True)
        sl.addSpacing(8)
        sl.addWidget(note)
        sl.addStretch(1)
        layout.addWidget(self._side(side))
        return page

    # --- réglages ----------------------------------------------------------------------

    def _fill_presets(self) -> None:
        self.preset.clear()
        for key, text in cm.PRESETS.items():
            self.preset.addItem(_(text), f"builtin:{key}")
        users = cm.user_presets()
        if users:
            self.preset.insertSeparator(self.preset.count())
            for name in sorted(users):
                self.preset.addItem(name, f"user:{name}")

    def _load(self) -> None:
        """Contrôles ← réglages (sans déclencher de modification)."""
        self._loading = True
        m = self.mastering
        v, a = m.video, m.audio
        index = self.preset.findData(f"builtin:{m.preset}")
        if index < 0:
            index = self.preset.findData(f"user:{m.preset}")
        if index >= 0:
            self.preset.setCurrentIndex(index)
        self.preview_switch.setChecked(m.preview)
        for key, b in self.look_buttons.items():
            b.setChecked(key == v.look)
        self.lut_label.setText(_("LUT : {name}").format(name=Path(v.lut).name)
                               if v.look == "lut" and v.lut else "")
        self.look_amount.set_value(v.look_amount)
        self.look_amount.setEnabled(v.look in cm.LOOKS)
        for key, (wheel, level) in self.wheels.items():
            wheel.set_value(*getattr(v.grade, key))
            level.blockSignals(True)
            level.setValue(round(getattr(v.grade, f"{key}_level") * 100))
            level.blockSignals(False)
        for key, row in self.color_rows.items():
            row.set_value(getattr(v.color, key))
        self.tint.set_value(v.tint)
        self.vibrance.set_value(v.grade.vibrance)
        self.curves.set_curves(v.grade.curves)
        for switch, value in ((self.match, v.match_shots), (self.legal, v.legal),
                              (self.cleanup, a.cleanup), (self.limiter, a.limiter)):
            switch.blockSignals(True)
            switch.setChecked(value)
            switch.blockSignals(False)
        self.match_amount.set_value(v.match_amount)
        self.color_space.blockSignals(True)
        self.color_space.setCurrentIndex(max(0, self.color_space.findData(v.color_space)))
        self.color_space.blockSignals(False)
        self.grain.set_value(v.grain)
        self.vignette.set_value(v.vignette)
        for key, b in self.destinations.items():
            b.setChecked(key == a.destination)
        for spin, value in ((self.lufs, a.lufs), (self.peak, a.true_peak)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.tone.setCurrentIndex(max(0, self.tone.findData(a.tone)))
        self.eq.set_gains(a.eq)
        self.compress.set_value(a.compress)
        self.voice_front.set_value(a.voice_front)
        self.stereo_width.set_value(a.width)
        self.layout_choice.set_current(a.layout)
        self.shots.set_reference(v.match_reference or
                                 (self.analysis.reference if self.analysis else ""))
        self._loading = False

    def _changed(self, apply: Callable[[], None], render: bool = True) -> None:
        if self._loading:
            return
        apply()
        if render:
            self._render_timer.start()
        self._show_analysis()

    def _pick_look(self, key: str) -> None:
        v = self.mastering.video
        if key == "lut":
            path, _f = QFileDialog.getOpenFileName(self, _("Choisir une LUT"), str(Path.home()),
                                                   _("LUT 3D (*.cube)"))
            if not path:
                self._load()
                return
            try:
                folder = self.project.media_dir or Path(path).parent
                v.lut = import_lut(Path(path), folder) if self.project.media_dir else path
            except OSError as exc:
                QMessageBox.warning(self, _("Finition pro"), str(exc))
                self._load()
                return
            v.look = "lut"
        else:
            v.look = "" if v.look == key else key
        self._load()
        self._render_timer.start()

    def _pick_reference(self, key: str) -> None:
        self.mastering.video.match_reference = key
        self.shots.set_reference(key)
        shot = next((s for s in (self.analysis.shots if self.analysis else ()) if s.key == key),
                    None)
        if shot is not None and self.analysis is not None:
            from montar.engine.mastering import deviation, match_values

            for s in self.analysis.shots:
                s.deviation = deviation(shot.stats, s.stats)
            self.analysis.reference = key
            self.analysis.matches = {s.key: match_values(shot.stats, s.stats)
                                     for s in self.analysis.shots}
            self.mastering.video.matches = dict(self.analysis.matches)
            self.position.setValue(shot.start)
        self._show_analysis()
        self._render_timer.start()

    def _pick_destination(self, key: str) -> None:
        if key == "custom":
            self.mastering.audio.destination = "custom"
        else:
            cm.set_destination(self.mastering.audio, key)
        self._load()
        self._show_analysis()

    def _custom_target(self, attr: str, value: float) -> None:
        if self._loading:
            return
        setattr(self.mastering.audio, attr, value)
        self.mastering.audio.destination = "custom"
        self._load()
        self._show_analysis()

    def _tone_chosen(self, _index: int) -> None:
        cm.set_tone(self.mastering.audio, self.tone.currentData())
        self._load()

    def _eq_changed(self, gains: list) -> None:
        self.mastering.audio.eq = [float(g) for g in gains]
        self.mastering.audio.tone = "custom"
        self.tone.setCurrentIndex(self.tone.findData("custom"))

    def _preset_chosen(self, _index: int) -> None:
        kind, _sep, key = (self.preset.currentData() or "").partition(":")
        if kind == "builtin":
            self.mastering = cm.preset(key, self.mastering)
        else:
            found = cm.user_presets().get(key)
            if found is None:
                return
            current = self.mastering
            found.enabled, found.preview = current.enabled, current.preview
            found.video.match_reference = current.video.match_reference
            found.video.matches = current.video.matches
            self.mastering = found
        self._load()
        self._show_analysis()
        self._render_timer.start()

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, _("Enregistrer le préréglage"),
                                        _("Nom du préréglage :"))
        name = name.strip()
        if not ok or not name:
            return
        try:
            cm.save_user_preset(name, self.mastering)
        except OSError as exc:
            QMessageBox.warning(self, _("Finition pro"), str(exc))
            return
        self.mastering.preset = name
        self._fill_presets()
        self._load()

    def _reset(self) -> None:
        self.mastering = cm.preset(self.mastering.preset if self.mastering.preset in cm.PRESETS
                                   else cm.DEFAULT_PRESET, self.mastering)
        self._load()
        self._show_analysis()
        self._render_timer.start()

    # --- aperçu ------------------------------------------------------------------------

    def _preview_size(self) -> tuple[int, int]:
        w, h = self._base.canvas.width, self._base.canvas.height
        width = min(PREVIEW_WIDTH, w)
        return width, max(2, round(width * h / w / 2) * 2)

    def _prepare_preview(self) -> None:
        try:
            self._base = self._spec_factory()
            self._length = self._base.length
            if self._length == 0:
                self.compare.set_message(_("La timeline est vide."))
                return
            self._engine = self._engine_factory()
            self._before = self._engine.build(self._base)
            self._after = self._engine.build(self._master_spec())
        except Exception as exc:  # moteur absent, média illisible
            log.warning("aperçu de la finition impossible : %s", exc)
            self.compare.set_message(_("Aperçu indisponible : {error}").format(error=exc))
            return
        self.position.blockSignals(True)
        self.position.setRange(0, max(0, self._length - 1))
        self._frame = max(0, min(self._frame, self._length - 1))
        self.position.setValue(self._frame)
        self.position.blockSignals(False)
        self._render(before=True)

    def _master_spec(self) -> TimelineSpec:
        m = self.mastering
        return mst.apply_master(self._base, m, lut=self._lut_path(m.video.lut), audio=False)

    def _seek(self, frame: int) -> None:
        self._frame = frame
        self._render(before=True)

    def _image(self, source: Source) -> QImage:
        w, h = self._preview_size()
        data = source.render(self._frame, w, h)
        return QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()

    def _render(self, before: bool = False) -> None:
        if self._after is None or self._engine is None:
            return
        spec = self._master_spec()
        try:
            if not self._after.update(spec):
                self._after.close()
                self._after = self._engine.build(spec)
            after = self._image(self._after)
            previous = self.compare.before
            first = self._image(self._before) if before or previous is None else previous
        except Exception as exc:
            log.warning("rendu de la finition impossible : %s", exc)
            self.compare.set_message(_("Aperçu indisponible : {error}").format(error=exc))
            return
        self.compare.set_images(first, after)
        self.timecode.setText(frames_to_timecode(self._frame, self.project.fps))
        for key, view in self.scopes.items():
            try:
                scope = render_scope(after, key)
            except Exception as exc:  # NumPy absent
                view.setText(str(exc))
                continue
            view.setPixmap(QPixmap.fromImage(scope).scaled(
                view.width(), view.height(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    # --- analyse -----------------------------------------------------------------------

    def _start_analysis(self) -> None:
        if self._analysis_thread is not None or self._base is None:
            return
        base, mastering = self._base, copy.deepcopy(self.mastering)
        engine_factory = self._engine_factory
        lut = self._lut_path(mastering.video.lut)
        self._cancel_analysis.clear()
        self._analysis_progress = 0.0

        def run() -> None:
            try:
                self._analysis_result = analyse(
                    engine_factory(), base, mastering, lut=lut, full=True,
                    cancelled=self._cancel_analysis.is_set,
                    progress=lambda p: setattr(self, "_analysis_progress", p))
            except Exception as exc:  # annulation ou échec : affiché
                self._analysis_result = exc

        self._analysis_result = None
        self._analysis_thread = threading.Thread(target=run, name="montar-analyse", daemon=True)
        self._analysis_thread.start()
        self._poll.start()
        self._poll_analysis()

    def _poll_analysis(self) -> None:
        thread = self._analysis_thread
        if thread is None:
            self._poll.stop()
            return
        if thread.is_alive():
            text = _("Analyse… {p} %").format(p=round(self._analysis_progress * 100))
            for b in (self.analyse_image, self.analyse_sound):
                b.setText(text)
                b.setEnabled(False)
            return
        self._poll.stop()
        self._analysis_thread = None
        for b in (self.analyse_image, self.analyse_sound):
            b.setText(_("Analyser le projet"))
            b.setEnabled(True)
        result = self._analysis_result
        if isinstance(result, Exception):
            if not self._cancel_analysis.is_set():
                QMessageBox.warning(self, _("Finition pro"),
                                    _("L'analyse a échoué : {error}").format(error=result))
            return
        if result is None:
            return
        self.analysis = result
        v = self.mastering.video
        if result.matches:
            v.matches = dict(result.matches)
            v.match_reference = v.match_reference or result.reference
        self._load()
        self._show_analysis()
        self._render_timer.start()

    def wait_analysis(self, timeout: float = 120) -> None:
        """Attend la fin de l'analyse (tests)."""
        if self._analysis_thread is not None:
            self._analysis_thread.join(timeout)
        self._poll_analysis()

    def _show_analysis(self) -> None:
        a = self.analysis
        audio = self.mastering.audio
        if a is not None:
            self.shots.set_shots(a.shots, self.mastering.video.match_reference or a.reference)
        ref = self.shots.reference
        index = next((i for i, s in enumerate(self.shots.shots) if s.key == ref), None)
        self.reference_label.setText(_("Référence : plan {n} (étoile)").format(n=index + 1)
                                     if index is not None else "")
        loud = a.loudness if a is not None else None
        if loud is None:
            for tile in (self.tile_lufs, self.tile_peak, self.tile_lra):
                tile.set_values("—", _("Analysez le projet"))
            self.graph.set_data([], 0.0, audio.lufs, audio.true_peak)
        else:
            gain = mst.loudness_gain(loud.integrated, audio.lufs)
            self.tile_lufs.set_values(_db(loud.integrated),
                                      _("→ {v} après finition").format(v=_db(audio.lufs)))
            peak_after = min(loud.true_peak + gain, audio.true_peak) if audio.limiter \
                else loud.true_peak + gain
            self.tile_peak.set_values(_db(loud.true_peak),
                                      _("→ {v} (limiteur)").format(v=_db(peak_after))
                                      if audio.limiter else _("→ {v}").format(v=_db(peak_after)))
            self.tile_lra.set_values(_db(loud.lra), _("mesurée après la chaîne de mastering"))
            self.graph.set_data(loud.curve, gain, audio.lufs, audio.true_peak)
        if a is not None and a.dialog_lufs is not None and a.music_lufs is not None:
            diff = a.dialog_lufs - a.music_lufs
            self.tile_balance.set_values(f"{diff:+.0f}".replace("-", "−"),
                                         _("dialogues par rapport à la musique"))
        else:
            self.tile_balance.set_values("—", _("voix et musique nécessaires"))
        if a is not None:
            self.eq.set_spectrum(a.spectrum)

    # --- fermeture ---------------------------------------------------------------------

    def done(self, result: int) -> None:  # noqa: D401 - surcharge de QDialog
        self._cancel_analysis.set()
        if self._analysis_thread is not None:
            self._analysis_thread.join(30)
        self._poll.stop()
        self._render_timer.stop()
        for source in (self._before, self._after):
            if source is not None:
                source.close()
        self._before = self._after = None
        super().done(result)
