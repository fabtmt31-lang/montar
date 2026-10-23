# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Studio » : fond vert (F-EDT-11) et stabilisation (F-EDT-12)."""
from __future__ import annotations

from montar.api import ClipSource, ModuleAPI, Param, SourceOverride, Tool, VideoEffect
from montar.i18n import _

from . import core

KEY_COLORS = {"vert": "0x00FF00", "bleu": "0x0047BB"}


class GreenScreen(VideoEffect):
    id = "studio.fond_vert"
    name = "Fond vert"
    description = ("Rend transparente la couleur du fond (vert ou bleu) : la piste du dessous "
                   "apparaît derrière le sujet.")
    icon = "layers"
    params = [Param.choice("couleur", "Couleur du fond", [("vert", "Vert"), ("bleu", "Bleu")]),
              Param.float("tolerance", "Tolérance", 0.0, 1.0, default=0.4),
              Param.float("douceur", "Douceur des bords", 0.0, 1.0, default=0.3),
              Param.float("debordement", "Suppression du reflet coloré", 0.0, 1.0,
                          default=0.6)]

    def filters(self, values):
        color = values.get("couleur", "vert")
        tolerance = max(0.0, min(1.0, float(values.get("tolerance", 0.4))))
        soft = max(0.0, min(1.0, float(values.get("douceur", 0.3))))
        spill = max(0.0, min(1.0, float(values.get("debordement", 0.6))))
        result = [("avfilter.colorkey", {"av.color": KEY_COLORS.get(color, KEY_COLORS["vert"]),
                                         "av.similarity": round(0.08 + 0.42 * tolerance, 3),
                                         "av.blend": round(0.01 + 0.25 * soft, 3)})]
        if spill > 0:  # reflet vert (ou bleu) sur les bords du sujet
            result.append(("avfilter.despill", {"av.type": "blue" if color == "bleu" else "green",
                                                "av.mix": round(spill, 3), "av.expand": 0}))
        return result


def _video_clip(editor, clip) -> bool:
    if clip is None or clip.is_text:
        return False
    media = editor.project.find_media(clip.media_id)
    return media is not None and media.kind == "video"


class StabilizeTool(Tool):
    id = "studio.stabiliser"
    name = "Stabiliser…"
    icon = "crosshair"
    description = ("Corrige les tremblements d'une vidéo filmée à la main (analyse en "
                   "arrière-plan ; les bords sont légèrement rognés).")

    def available(self, editor, clip) -> bool:
        return _video_clip(editor, clip)

    def run(self, editor, clip) -> None:
        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        if not core.available():
            QMessageBox.information(editor.parent, _("Stabiliser"), _(
                "La stabilisation demande ffmpeg avec vid.stab (paquet ffmpeg de Debian ou "
                "d'Ubuntu)."))
            return
        current = core.settings_of(clip)
        levels = [_("Légère"), _("Moyenne"), _("Forte")]
        index = 1 if current is None else min(2, round(core.strength_of(current) * 2))
        choice, ok = QInputDialog.getItem(editor.parent, _("Stabiliser"),
                                          _("Force de la stabilisation :"), levels, index, False)
        if not ok:
            return
        strength = levels.index(choice) / 2
        clip_id = clip.id

        def apply(timeline):
            target = timeline.clip(clip_id)
            data = dict(target.modules.get(core.MODULE_ID) or {})
            data["stabilize"] = strength
            target.modules[core.MODULE_ID] = data
            return target

        editor.edit(_("Stabiliser"), apply)


class RemoveStabilizeTool(Tool):
    id = "studio.retirer_stabilisation"
    name = "Retirer la stabilisation"
    icon = "rotate-ccw"
    description = "Revient à la vidéo d'origine."

    def available(self, editor, clip) -> bool:
        return clip is not None and core.settings_of(clip) is not None

    def run(self, editor, clip) -> None:
        clip_id = clip.id

        def remove(timeline):
            target = timeline.clip(clip_id)
            data = dict(target.modules.get(core.MODULE_ID) or {})
            data.pop("stabilize", None)
            if data:
                target.modules[core.MODULE_ID] = data
            else:
                target.modules.pop(core.MODULE_ID, None)
            return target

        editor.edit(_("Retirer la stabilisation"), remove)


class StabilizedSource(ClipSource):
    """Lit la vidéo stabilisée une fois calculée ; en attendant, l'original."""

    def resolve(self, context, clip, media):
        data = core.settings_of(clip)
        if data is None:
            return None
        strength = core.strength_of(data)
        path = core.cache_path(context.cache_dir, media.path, strength)
        if path.exists():
            return SourceOverride(str(path), clip.source_in, clip.speed)
        job = (media.path, path, strength, float(media.duration or 0))

        def work(progress, cancelled):
            source, target, value, seconds = job
            core.stabilize(source, target, value, seconds, progress, cancelled)

        context.schedule_job(path.name, _("Stabilisation"), work)
        return None

    def badge(self, settings) -> str | None:
        return "STAB" if "stabilize" in settings else None


def register(api: ModuleAPI) -> None:
    api.add_video_effect(GreenScreen)
    api.add_tool(StabilizeTool)
    api.add_tool(RemoveStabilizeTool)
    api.add_clip_source(StabilizedSource)
