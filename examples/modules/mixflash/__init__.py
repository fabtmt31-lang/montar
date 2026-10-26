# SPDX-License-Identifier: GPL-3.0-or-later
"""Module « Mix Flash » : une ou plusieurs vidéos d'une piste découpées en extraits de 0,5 à
5 s, mélangés au hasard sans perdre une image, avec des fondus au blanc ou au noir.

Clic droit sur un clip vidéo → « Mix Flash… ». Sur un extrait : « Remélanger le Mix
Flash… » ou « Défaire le Mix Flash »."""
from __future__ import annotations

from montar.api import ModuleAPI, Param, Tool, VideoEffect
from montar.i18n import _

from . import core


def _ramp(color: str, points: list[tuple[int, float]], length: int) -> tuple[str, dict]:
    """Filtre animé vers le blanc ou le noir ; `points` : (image, part de couleur de 0 à 1)."""
    clip = {"in": 0, "out": length - 1}  # positions relatives au début du clip (API 1.4)
    if color == "white":  # relève les ombres jusqu'au blanc
        lift = ";".join(f"{f}={a:g}" for f, a in points)
        return "lift_gamma_gain", {"lift_r": lift, "lift_g": lift, "lift_b": lift, **clip}
    level = ";".join(f"{f}={1 - a:g}" for f, a in points)
    return "brightness", {"level": level, "alpha": -1, **clip}


class Couleur(VideoEffect):
    """Fondus et flashs du Mix Flash, posés par l'outil sur les extraits."""

    id = core.MODULE_ID
    name = "Fondu Mix Flash"
    description = "Fondu au noir ou au blanc au début ou à la fin du clip, ou aplat de couleur."
    icon = "sun"
    params = [
        Param.choice("color", "Couleur (fin du clip)", [("black", "Noir"), ("white", "Blanc")]),
        Param("fade_out", "Images en fondu à la fin", "int", 0, 0, 50),
        Param.choice("fade_in_color", "Couleur (début du clip)",
                     [("black", "Noir"), ("white", "Blanc")]),
        Param("fade_in", "Images en fondu au début", "int", 0, 0, 50),
        Param("length", "Durée du clip (images)", "int", 0, 0, 100000),
        Param.bool("full", "Aplat de couleur", False),
    ]

    def filters(self, values):
        if values.get("full"):
            expr = "maxval" if values["color"] == "white" else "minval"
            return [("avfilter.lutrgb", {"av.r": expr, "av.g": expr, "av.b": expr})]
        length = int(values["length"])
        if length < 2:
            return []
        m = max(0, min(int(values["fade_out"]), length - 1))
        n = max(0, min(int(values["fade_in"]), length - 1 - m))
        ramps: dict[str, list[tuple[int, float]]] = {}
        if n:  # première image : toute la couleur, l'image revient en n images
            ramps.setdefault(values["fade_in_color"], []).extend([(0, 1.0), (n, 0.0)])
        if m:  # dernière image : toute la couleur
            ramps.setdefault(values["color"], []).extend(
                [(length - 1 - m, 0.0), (length - 1, 1.0)])
        result = []
        for color, points in ramps.items():
            merged = dict(sorted(points))  # une même image en fin de montée et début de descente
            result.append(_ramp(color, sorted(merged.items()), length))
        return result


def _settings_dialog(editor, clips, chosen, settings, remix):
    from .dialog import MixFlashDialog

    dialog = MixFlashDialog(editor.parent, clips, chosen, editor.project.fps, settings, remix,
                            names=lambda c: editor.timeline.media_of(c).name)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return None
    return dialog.chosen_ids(), dialog.settings()


def _select(editor, created) -> None:
    select = getattr(editor, "select", None)
    if created and callable(select):
        select(created[0].id)


class MixFlashTool(Tool):
    id = "fab.mixflash.apply"
    name = "Mix Flash…"
    icon = "square-split-horizontal"
    description = ("Découpe les vidéos choisies de la piste en extraits de 0,5 à 5 s et les "
                   "mélange au hasard, avec des fondus au blanc ou au noir.")

    def available(self, editor, clip) -> bool:
        return clip is not None and core.eligible(editor.timeline, clip)

    def run(self, editor, clip) -> None:
        clips = core.candidates(editor.timeline, clip)
        result = _settings_dialog(editor, clips, {clip.id}, core.Settings(), remix=False)
        if result is None:
            return
        ids, settings = result
        created = editor.edit(_("Mix Flash"), lambda t: core.apply(t, ids, settings))
        _select(editor, created)


class RemixTool(Tool):
    id = "fab.mixflash.remix"
    name = "Remélanger le Mix Flash…"
    icon = "square-split-horizontal"
    description = "Nouveau mélange des mêmes vidéos, avec d'autres réglages si besoin."

    def available(self, editor, clip) -> bool:
        return core.group_of(clip) is not None

    def run(self, editor, clip) -> None:
        data = core.group_of(clip)
        originals = [core._build(core.Clip, d) for d in data.get("originals", [])]
        settings = core.Settings.from_dict(data.get("settings", {}))
        settings.seed += 1
        result = _settings_dialog(editor, originals, {c.id for c in originals}, settings,
                                  remix=True)
        if result is None:
            return
        _ids, settings = result
        clip_id = clip.id
        created = editor.edit(_("Remélanger le Mix Flash"),
                              lambda t: core.remix(t, clip_id, settings))
        _select(editor, created)


class RestoreTool(Tool):
    id = "fab.mixflash.restore"
    name = "Défaire le Mix Flash"
    icon = "rotate-ccw"
    description = "Retire les extraits et remet les clips d'origine à leur place."

    def available(self, editor, clip) -> bool:
        return core.group_of(clip) is not None

    def run(self, editor, clip) -> None:
        clip_id = clip.id
        restored = editor.edit(_("Défaire le Mix Flash"), lambda t: core.restore(t, clip_id))
        _select(editor, restored)


def register(api: ModuleAPI) -> None:
    api.add_video_effect(Couleur)
    api.add_tool(MixFlashTool)
    api.add_tool(RemixTool)
    api.add_tool(RestoreTool)
