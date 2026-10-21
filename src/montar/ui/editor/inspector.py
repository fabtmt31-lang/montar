# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspecteur (panneau de droite, maquettes 02 et 03) : réglages de l'élément sélectionné."""
from __future__ import annotations

import math
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from montar.core.project import Clip, ColorAdjust, MediaItem, Project, Transform, Transition
from montar.core.timecode import frames_to_timecode, seconds_to_short
from montar.core.timeline import AUDIO_TRANSITIONS, VIDEO_TRANSITIONS
from montar.i18n import _
from montar.ui.editor.controller import EditorController
from montar.ui.editor.controls import ColorSwatches, SliderRow, Tabs, page, section
from montar.ui.labels import TRANSITIONS
from montar.ui.text_render import FAMILIES
from montar.ui.widgets import Segmented, button, label, set_icon

_KIND = {"video": "Clip vidéo", "image": "Image", "audio": "Son"}
TEXT_COLORS = ("#17261E", "#FFFFFF", "#2F7A56", "#BFE3CF", "#D9EBB9")
BACKGROUNDS = ("#FFFFFF", "#17261E", "#2F7A56", "#D917261E")
WEIGHT_NAMES = {400: "Normal", 500: "Moyen", 600: "Semi-gras", 700: "Gras", 800: "Extra-gras"}
SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


def _pct(v: float) -> str:
    return f"{v:.0f} %"


def _signed(v: float) -> str:
    return f"{v:+.0f}" if round(v) else "0"


class Inspector(QFrame):
    def __init__(self, controller: EditorController) -> None:
        super().__init__()
        self.setObjectName("Inspector")
        self.setFixedWidth(320)
        self.controller = controller
        self.clip_id: str | None = None
        self._refreshing = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        body.setMaximumWidth(310)  # pas de défilement horizontal
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(4)
        self.title = label("", "h3")
        self.title.setWordWrap(True)
        self.subtitle = label("", "small")
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addSpacing(14)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        layout.addStretch()
        self._info = self._build_info()
        self._clip = self._build_clip_page()
        self._text = self._build_text_page()
        self._transition = self._build_transition_page()
        for w in (self._info, self._clip, self._text, self._transition):
            self.pages.addWidget(w)

    # --- édition ------------------------------------------------------------------

    def _clip_obj(self) -> Clip | None:
        return next((c for c in self.controller.project.clips if c.id == self.clip_id), None)

    def _edit(self, label_: str, key: str, change: Callable[[Clip], None]) -> None:
        if self._refreshing or self.clip_id is None:
            return
        self.controller.edit_clip(label_, self.clip_id, change, merge=(self.clip_id, key))

    def _slider(self, layout, title: str, minimum: float, maximum: float, key: str,
                getter: Callable[[Clip], float], setter: Callable[[Clip, float], None],
                fmt=_pct, **kwargs) -> SliderRow:
        row = SliderRow(title, minimum, maximum, fmt, **kwargs)
        row.moved.connect(lambda v: self._edit(title, key, lambda c: setter(c, v)))
        row.getter = getter  # type: ignore[attr-defined]
        layout.addWidget(row)
        self._sliders.append(row)
        return row

    # --- pages ------------------------------------------------------------------------

    def _build_info(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.section = label("", "section")
        layout.addWidget(self.section)
        layout.addSpacing(6)
        host = QWidget()
        self._grid = QGridLayout(host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(10)
        self._grid.setColumnStretch(1, 1)
        layout.addWidget(host)
        layout.addStretch(1)
        return w

    def _build_clip_page(self) -> QWidget:
        self._sliders: list[SliderRow] = []

        image, il = page()
        il.addWidget(section(_("TRANSFORMATION")))
        self._slider(il, _("Position horizontale"), -100, 100, "x",
                     lambda c: c.transform.x * 100,
                     lambda c, v: setattr(c.transform, "x", v / 100), _signed)
        self._slider(il, _("Position verticale"), -100, 100, "y",
                     lambda c: c.transform.y * 100,
                     lambda c, v: setattr(c.transform, "y", v / 100), _signed)
        self._slider(il, _("Échelle"), 10, 400, "scale", lambda c: c.transform.scale * 100,
                     lambda c, v: setattr(c.transform, "scale", v / 100))
        self._slider(il, _("Rotation"), -180, 180, "rotation", lambda c: c.transform.rotation,
                     lambda c, v: setattr(c.transform, "rotation", v), lambda v: f"{v:.0f}°")
        self._slider(il, _("Opacité"), 0, 100, "opacity", lambda c: c.transform.opacity * 100,
                     lambda c, v: setattr(c.transform, "opacity", v / 100))
        il.addWidget(section(_("AJUSTEMENTS")))
        self.fit = Segmented([("fit", _("Ajuster")), ("fill", _("Remplir")),
                              ("stretch", _("Étirer"))])
        self.fit.changed.connect(lambda k: self._edit(_("Ajustement"), "fit",
                                                      lambda c: setattr(c.transform, "fit", k)))
        il.addWidget(self.fit)
        tools = QHBoxLayout()
        for icon, tip, change in (
            ("rotate-cw", _("Pivoter de 90°"), lambda c: setattr(
                c.transform, "rotation", ((c.transform.rotation + 90 + 180) % 360) - 180)),
            ("flip-horizontal-2", _("Retourner horizontalement"),
             lambda c: setattr(c.transform, "flip_h", not c.transform.flip_h)),
            ("flip-vertical-2", _("Retourner verticalement"),
             lambda c: setattr(c.transform, "flip_v", not c.transform.flip_v)),
            ("rotate-ccw", _("Réinitialiser la transformation"),
             lambda c: setattr(c, "transform", Transform())),
        ):
            b = button("", "secondary", icon, tooltip=tip)
            set_icon(b, icon, "ink", 18)
            b.clicked.connect(lambda _=False, t=tip, ch=change: self._edit(t, f"tool:{t}", ch))
            tools.addWidget(b)
        il.addLayout(tools)
        il.addWidget(section(_("RECADRAGE")))
        for name, title in (("crop_left", _("Gauche")), ("crop_right", _("Droite")),
                            ("crop_top", _("Haut")), ("crop_bottom", _("Bas"))):
            self._slider(il, title, 0, 45, name, lambda c, n=name: getattr(c.transform, n) * 100,
                         lambda c, v, n=name: setattr(c.transform, n, v / 100))
        il.addWidget(section(_("FONDUS")))
        self._fade_rows(il, "image")

        audio, al = page()
        al.addWidget(section(_("SON")))
        self._slider(al, _("Volume"), 0, 200, "volume", lambda c: c.volume * 100,
                     lambda c, v: setattr(c, "volume", v / 100))
        self.mute_button = button(_("Couper le son du clip"), "secondary", "volume-x")
        self.mute_button.clicked.connect(lambda: self._edit(
            _("Son du clip"), "mute", lambda c: setattr(c, "volume", 1.0 if c.volume == 0
                                                         else 0.0)))
        al.addWidget(self.mute_button)
        self.detach_button = button(_("Détacher l'audio"), "secondary", "unlink",
                                    tooltip=_("Place le son sur une piste audio"))
        self.detach_button.clicked.connect(self._detach_audio)
        al.addWidget(self.detach_button)
        al.addWidget(section(_("FONDUS")))
        self._fade_rows(al, "audio")

        speed, sl = page()
        sl.addWidget(section(_("VITESSE")))
        presets = QGridLayout()
        self._speed_buttons = QButtonGroup(self)
        for i, value in enumerate(SPEEDS):
            b = QPushButton(f"×{value:g}")
            b.setCheckable(True)
            b.setProperty("variant", "chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self._set_speed(v))
            self._speed_buttons.addButton(b)
            presets.addWidget(b, i // 3, i % 3)
        sl.addLayout(presets)
        self.speed_row = SliderRow(_("Vitesse"), 0.1, 16, lambda v: f"×{v:.2f}",
                                   to_slider=math.log, from_slider=math.exp)
        self.speed_row.moved.connect(lambda v: self._set_speed(v, merge=True))
        sl.addWidget(self.speed_row)
        self.duration_label = label("", "small")
        sl.addWidget(self.duration_label)

        color, cl = page()
        cl.addWidget(section(_("COULEUR")))
        for name, title in (("brightness", _("Luminosité")), ("contrast", _("Contraste")),
                            ("saturation", _("Saturation")), ("temperature", _("Température")),
                            ("exposure", _("Exposition"))):
            self._slider(cl, title, -100, 100, name,
                         lambda c, n=name: getattr(c.color, n) * 100,
                         lambda c, v, n=name: setattr(c.color, n, v / 100), _signed)
        reset = button(_("Réinitialiser les couleurs"), "secondary", "rotate-ccw")
        reset.clicked.connect(lambda: self._edit(_("Couleurs"), "color-reset",
                                                 lambda c: setattr(c, "color", ColorAdjust())))
        cl.addWidget(reset)

        self.clip_tabs = Tabs([("image", _("Image"), image), ("audio", _("Audio"), audio),
                               ("speed", _("Vitesse"), speed), ("color", _("Couleur"), color)])
        return self.clip_tabs

    def _fade_rows(self, layout, key: str) -> None:
        fps = self.controller.project.fps
        for name, title in (("fade_in", _("Fondu d'entrée")), ("fade_out", _("Fondu de sortie"))):
            self._slider(layout, title, 0, 5, f"{name}:{key}",
                         lambda c, n=name: getattr(c, n) / fps,
                         lambda c, v, n=name: setattr(c, n, min(round(v * fps),
                                                                 c.duration // 2)),
                         lambda v: f"{v:.1f} s")

    def _build_text_page(self) -> QWidget:
        style, sl = page()
        sl.addWidget(label(_("Texte")))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(76)
        self.text_edit.textChanged.connect(lambda: self._edit_text(
            _("Texte"), "content", content=self.text_edit.toPlainText()))
        sl.addWidget(self.text_edit)
        sl.addSpacing(6)
        sl.addWidget(label(_("Police")))
        self.family = QComboBox()
        self.family.addItems(FAMILIES)
        self.family.currentTextChanged.connect(
            lambda f: self._edit_text(_("Police"), "family", family=f))
        sl.addWidget(self.family)
        row = QHBoxLayout()
        size_col, weight_col = QVBoxLayout(), QVBoxLayout()
        size_col.addWidget(label(_("Taille")))
        self.size = QSpinBox()
        self.size.setRange(12, 400)
        self.size.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.size.valueChanged.connect(lambda v: self._edit_text(_("Taille"), "size", size=v))
        size_col.addWidget(self.size)
        weight_col.addWidget(label(_("Graisse")))
        self.weight = QComboBox()
        for value, name in WEIGHT_NAMES.items():
            self.weight.addItem(_(name), value)
        self.weight.currentIndexChanged.connect(lambda _i: self._edit_text(
            _("Graisse"), "weight", weight=self.weight.currentData()))
        weight_col.addWidget(self.weight)
        row.addLayout(size_col)
        row.addLayout(weight_col)
        sl.addLayout(row)
        fmt = QHBoxLayout()
        self.align_group = QButtonGroup(self)
        self._align_buttons = {}
        for key, icon in (("left", "align-left"), ("center", "align-center"),
                          ("right", "align-right")):
            b = button("", "secondary", icon)
            b.setCheckable(True)
            set_icon(b, icon, "ink", 18)
            b.clicked.connect(lambda _=False, k=key: self._edit_text(_("Alignement"), "align",
                                                                     align=k))
            self.align_group.addButton(b)
            self._align_buttons[key] = b
            fmt.addWidget(b)
        self._toggles = {}
        for key, icon, tip in (("italic", "italic", _("Italique")),
                               ("underline", "underline", _("Souligné")),
                               ("uppercase", "case-upper", _("Majuscules"))):
            b = button("", "secondary", icon, tooltip=tip)
            b.setCheckable(True)
            set_icon(b, icon, "ink", 18)
            b.toggled.connect(lambda on, k=key, t=tip: self._edit_text(t, k, **{k: on}))
            self._toggles[key] = b
            fmt.addWidget(b)
        sl.addLayout(fmt)
        sl.addWidget(label(_("Couleur")))
        self.text_color = ColorSwatches(TEXT_COLORS)
        self.text_color.picked.connect(lambda c: self._edit_text(_("Couleur"), "color", color=c))
        sl.addWidget(self.text_color)
        self.spacing = SliderRow(_("Interlettrage"), 0, 40, lambda v: f"{v:.0f}")
        self.spacing.moved.connect(lambda v: self._edit_text(_("Interlettrage"), "spacing",
                                                             letter_spacing=v))
        sl.addWidget(self.spacing)
        self.outline = SliderRow(_("Contour"), 0, 12, lambda v: f"{v:.0f}")
        self.outline.moved.connect(lambda v: self._edit_text(_("Contour"), "outline",
                                                             outline_width=v))
        sl.addWidget(self.outline)
        self.outline_color = ColorSwatches(TEXT_COLORS)
        self.outline_color.picked.connect(lambda c: self._edit_text(
            _("Couleur du contour"), "outline-color", outline_color=c))
        sl.addWidget(self.outline_color)
        self.shadow = QCheckBox(_("Ombre portée"))
        self.shadow.toggled.connect(lambda on: self._edit_text(_("Ombre"), "shadow", shadow=on))
        sl.addWidget(self.shadow)
        sl.addWidget(label(_("Bandeau")))
        self.background = ColorSwatches(BACKGROUNDS, allow_none=True)
        self.background.picked.connect(lambda c: self._edit_text(_("Bandeau"), "background",
                                                                 background=c))
        sl.addWidget(self.background)
        self.pill = QCheckBox(_("Bords arrondis"))
        self.pill.toggled.connect(lambda on: self._edit_text(_("Bandeau"), "pill", pill=on))
        sl.addWidget(self.pill)

        anim, al = page()
        self._anims = {}
        for key, title in (("animation_in", _("Animation d'entrée")),
                           ("animation_out", _("Animation de sortie"))):
            al.addWidget(label(title))
            seg = Segmented([("none", _("Aucune")), ("fade", _("Fondu")),
                             ("slide", _("Glisser"))])
            seg.changed.connect(lambda v, k=key, t=title: self._edit_text(t, k, **{k: v}))
            self._anims[key] = seg
            al.addWidget(seg)
            al.addSpacing(10)

        position, pl = page()
        self.text_x = SliderRow(_("Position horizontale"), 0, 100, _pct)
        self.text_x.moved.connect(lambda v: self._edit_text(_("Position"), "tx", x=v / 100))
        self.text_y = SliderRow(_("Position verticale"), 0, 100, _pct)
        self.text_y.moved.connect(lambda v: self._edit_text(_("Position"), "ty", y=v / 100))
        pl.addWidget(self.text_x)
        pl.addWidget(self.text_y)
        quick = QHBoxLayout()
        for title, y in ((_("Haut"), 0.15), (_("Centre"), 0.5), (_("Bas"), 0.85)):
            b = button(title, "secondary")
            b.clicked.connect(lambda _=False, yy=y: self._edit_text(
                _("Position"), f"quick{yy}", x=0.5, y=yy))
            quick.addWidget(b)
        pl.addLayout(quick)
        hint = label(_("Astuce : faites glisser le texte directement dans l'aperçu."), "small")
        hint.setWordWrap(True)
        pl.addWidget(hint)

        self.text_tabs = Tabs([("style", _("Style"), style), ("animation", _("Animation"), anim),
                               ("position", _("Position"), position)])
        return self.text_tabs

    def _build_transition_page(self) -> QWidget:
        w, layout = page()
        layout.addWidget(label(_("Type")))
        self.transition_kind = QComboBox()
        self.transition_kind.currentIndexChanged.connect(self._transition_kind_changed)
        layout.addWidget(self.transition_kind)
        layout.addSpacing(8)
        self.transition_duration = SliderRow(_("Durée"), 0.1, 5, lambda v: f"{v:.1f} s")
        self.transition_duration.moved.connect(self._transition_duration_changed)
        layout.addWidget(self.transition_duration)
        remove = button(_("Supprimer la transition"), "secondary", "trash-2")
        remove.clicked.connect(self._remove_transition)
        layout.addWidget(remove)
        layout.addStretch(1)
        return w

    # --- affichage --------------------------------------------------------------------

    def _show_page(self, widget: QWidget) -> None:
        """Affiche une page ; la pile prend sa hauteur et non celle de la plus grande page."""
        self.pages.setCurrentWidget(widget)
        for i in range(self.pages.count()):
            w = self.pages.widget(i)
            policy = w.sizePolicy()
            policy.setVerticalPolicy(policy.Policy.Preferred if w is widget
                                     else policy.Policy.Ignored)
            w.setSizePolicy(policy)
        self.pages.adjustSize()

    def _set_rows(self, rows: list[tuple[str, str]]) -> None:
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, (key, value) in enumerate(rows):
            k = label(key, "muted")
            v = QLabel(value)
            v.setProperty("role", "mono")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(k, i, 0, Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(v, i, 1)

    def show_project(self, project: Project) -> None:
        self.clip_id = None
        w, h = project.canvas_size
        self.title.setText(project.name)
        self.subtitle.setText(_("Projet"))
        self.section.setText(_("PROJET"))
        self._set_rows([
            (_("Format"), project.aspect),
            (_("Toile"), f"{w} × {h}"),
            (_("Images/s"), str(project.fps)),
            (_("Médias"), str(len(project.media))),
            (_("Fichier"), str(project.path or "—")),
        ])
        self._show_page(self._info)

    def show_media(self, media: MediaItem) -> None:
        self.clip_id = None
        self.title.setText(media.name)
        kind = _(_KIND.get(media.kind, media.kind))
        self.subtitle.setText(kind if media.kind == "image"
                              else f"{kind} · {seconds_to_short(media.duration)}")
        self.section.setText(_("PROPRIÉTÉS DU MÉDIA"))
        rows: list[tuple[str, str]] = []
        if media.kind != "audio":
            rows.append((_("Résolution"), f"{media.width} × {media.height}"))
        if media.kind == "video":
            rows.append((_("Images/s"), f"{media.fps:.3g}"))
        if media.kind != "image":
            rows.append((_("Durée"), f"{media.duration:.2f} s"))
        if media.video_codec and media.kind != "audio":
            rows.append((_("Codec vidéo"), media.video_codec))
        if media.has_audio:
            rows.append((_("Codec audio"), media.audio_codec or "—"))
        rows.append((_("Fichier"), media.path))
        if not media.exists:
            rows.append((_("État"), _("introuvable")))
        self._set_rows(rows)
        self._show_page(self._info)

    def show_clip(self, clip: Clip, media: MediaItem | None, track_label: str,
                  fps: int) -> None:
        same = self.clip_id == clip.id
        self.clip_id = clip.id
        timing = f"{frames_to_timecode(clip.start, fps)} · {frames_to_timecode(clip.duration, fps)}"
        if clip.is_text:
            first_line = clip.text.content.split("\n")[0] or _("Texte")
            self.title.setText(first_line)
            self.subtitle.setText(f"{_('Texte')} · {_('piste')} {track_label} · {timing}")
            self._show_page(self._text)
            self._refresh_text(clip, keep_cursor=same)
            return
        kind = _(_KIND.get(media.kind, media.kind)) if media else ""
        self.title.setText(media.name if media else "")
        self.subtitle.setText(f"{kind} · {_('piste')} {track_label} · {timing}")
        self._show_page(self._clip)
        audio_track = self.controller.timeline.track(clip.track_id).kind == "audio"
        if audio_track or (media and media.kind == "audio"):
            tabs = ["audio", "speed"]
        elif media and media.kind == "image":
            tabs = ["image", "color"]
        elif media and media.has_audio:
            tabs = ["image", "audio", "speed", "color"]
        else:
            tabs = ["image", "speed", "color"]
        self.clip_tabs.set_visible_tabs(tabs)
        self._refresh_clip(clip, media)

    def _refresh_clip(self, clip: Clip, media: MediaItem | None) -> None:
        self._refreshing = True
        for row in self._sliders:
            row.set_value(row.getter(clip))
        self.fit.set_current(clip.transform.fit)
        for b in self._speed_buttons.buttons():
            b.setChecked(b.text() == f"×{clip.speed:g}")
        self.speed_row.set_value(clip.speed)
        self.duration_label.setText(_("Durée du clip : {d}").format(
            d=frames_to_timecode(clip.duration, self.controller.project.fps)))
        self.mute_button.setText(_("Rétablir le son du clip") if clip.volume == 0
                                 else _("Couper le son du clip"))
        self.detach_button.setVisible(
            bool(media and media.kind == "video" and media.has_audio
                 and self.controller.timeline.track(clip.track_id).kind == "video"
                 and clip.volume > 0))
        self._refreshing = False

    def _refresh_text(self, clip: Clip, keep_cursor: bool) -> None:
        t = clip.text
        self._refreshing = True
        if self.text_edit.toPlainText() != t.content:
            cursor = self.text_edit.textCursor().position()
            self.text_edit.setPlainText(t.content)
            if keep_cursor:
                c = self.text_edit.textCursor()
                c.setPosition(min(cursor, len(t.content)))
                self.text_edit.setTextCursor(c)
        self.family.setCurrentText(t.family)
        self.size.setValue(round(t.size))
        index = self.weight.findData(t.weight)
        self.weight.setCurrentIndex(max(0, index))
        for key, b in self._align_buttons.items():
            b.setChecked(key == t.align)
        for key, b in self._toggles.items():
            b.setChecked(getattr(t, key))
        self.text_color.set_current(t.color)
        self.spacing.set_value(t.letter_spacing)
        self.outline.set_value(t.outline_width)
        self.outline_color.set_current(t.outline_color)
        self.shadow.setChecked(t.shadow)
        self.background.set_current(t.background)
        self.pill.setChecked(t.pill)
        for key, seg in self._anims.items():
            seg.set_current(getattr(t, key))
        self.text_x.set_value(t.x * 100)
        self.text_y.set_value(t.y * 100)
        self._refreshing = False

    def show_transition(self, transition: Transition) -> None:
        self.clip_id = None
        self._transition_id = transition.id
        name = _(TRANSITIONS.get(transition.kind, (transition.kind, ""))[0])
        self.title.setText(name)
        self.subtitle.setText(_("Transition"))
        self._refreshing = True
        kinds = AUDIO_TRANSITIONS if self.controller.timeline.track(
            transition.track_id).kind == "audio" else VIDEO_TRANSITIONS
        self.transition_kind.clear()
        for k in kinds:
            self.transition_kind.addItem(_(TRANSITIONS[k][0]), k)
        self.transition_kind.setCurrentIndex(kinds.index(transition.kind)
                                             if transition.kind in kinds else 0)
        fps = self.controller.project.fps
        self.transition_duration.set_value(transition.duration / fps)
        self._refreshing = False
        self._show_page(self._transition)

    # --- actions ---------------------------------------------------------------------

    def _edit_text(self, label_: str, key: str, **changes) -> None:
        def apply(c: Clip) -> None:
            for name, value in changes.items():
                setattr(c.text, name, value)

        self._edit(label_, f"text:{key}", apply)

    def _set_speed(self, speed: float, merge: bool = False) -> None:
        if self._refreshing or self.clip_id is None:
            return
        clip_id = self.clip_id
        self.controller.edit(_("Vitesse"), lambda t: t.set_speed(clip_id, speed),
                             merge=(clip_id, "speed") if merge else None)

    def _detach_audio(self) -> None:
        clip_id = self.clip_id
        if clip_id is not None:
            self.controller.edit(_("Détacher l'audio"), lambda t: t.detach_audio(clip_id))

    def _transition_kind_changed(self) -> None:
        kind = self.transition_kind.currentData()
        tid = getattr(self, "_transition_id", None)
        if self._refreshing or tid is None or kind is None:
            return
        self.controller.edit(_("Type de transition"), lambda t: t.set_transition(tid, kind=kind))

    def _transition_duration_changed(self, seconds: float) -> None:
        tid = getattr(self, "_transition_id", None)
        if self._refreshing or tid is None:
            return
        frames = round(seconds * self.controller.project.fps)
        self.controller.edit(_("Durée de la transition"),
                             lambda t: t.set_transition(tid, duration=frames),
                             merge=(tid, "duration"))

    def _remove_transition(self) -> None:
        tid = getattr(self, "_transition_id", None)
        if tid is not None:
            self.controller.edit(_("Supprimer la transition"), lambda t: t.remove_transition(tid))
