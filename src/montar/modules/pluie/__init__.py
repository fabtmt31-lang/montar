# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Pluie » : la vidéo semble filmée sous la pluie — gouttes sur l'objectif
ou sur une vitre, image assombrie d'un jour de pluie, pluie qui tombe, brume, éclairs.

Il utilise `VideoEffect.clip_filters` et `VideoEffect.adjust` (API 1.5) : les gouttes sont
calculées en tâche de fond, et un préréglage règle les autres curseurs."""
from __future__ import annotations

from montar.api import Param, VideoEffect
from montar.i18n import _

from . import core


class Rain(VideoEffect):
    id = "pluie.pluie"
    name = "Pluie"
    description = ("Comme filmé sous la pluie : gouttes d'eau sur l'objectif ou une vitre, "
                   "image plus sombre et plus froide, pluie qui tombe, brume, éclairs.")
    icon = "cloud-rain"
    params = [
        Param.choice("preset", "Temps", [("pluie", "Pluie"), ("bruine", "Bruine"),
                                         ("averse", "Averse"), ("orage", "Orage"),
                                         (core.CUSTOM, "Personnalisé")]),
        Param.choice("surface", "Gouttes sur", [("objectif", "L'objectif de la caméra"),
                                                ("vitre", "Une vitre")]),
        Param.float("volume", "Volume de gouttes", 0.0, 1.0, default=0.5),
        Param.float("taille", "Taille des gouttes", 0.0, 1.0, default=0.5),
        Param.float("ruissellement", "Ruissellement", 0.0, 1.0, default=0.5),
        Param.float("ambiance", "Ambiance (image assombrie)", 0.0, 1.0, default=0.7),
        Param.float("chute", "Pluie qui tombe", 0.0, 1.0, default=0.4),
        Param.float("brume", "Brume", 0.0, 1.0, default=0.3),
        Param.bool("eclairs", "Éclairs", False),
        Param.bool("anime", "Gouttes animées (apparaissent, glissent)", True),
        Param.bool("mouille", "Objectif mouillé (image adoucie)", True),
        Param("variante", "Variante des gouttes", "int", 1, 1, 20),
    ]

    def __init__(self) -> None:
        self._wanted: dict = {}  # clip → calques attendus (les autres calculs sont abandonnés)

    def adjust(self, values, key):
        return core.apply_preset(values, key)

    def filters(self, values):
        """Sans contexte de rendu (API antérieure à 1.5) : l'ambiance seule."""
        return core.ambiance_filters(core.Settings.from_values(values))

    def clip_filters(self, context, clip, values):
        s = core.Settings.from_values(values)
        width = int(getattr(context, "width", 1920))
        height = int(getattr(context, "height", 1080))
        fps = int(getattr(context, "fps", 25))
        result = core.ambiance_filters(s)
        # éclairs en dernier : ils illuminent aussi les gouttes
        flashes = core.lightning_filters(s, int(clip.duration), fps)
        cache = getattr(context, "cache_dir", None)
        if cache is None:
            return result + flashes
        if s.brume > 0.001:
            haze = core.haze_image(cache / "pluie", s.brume)
            result.append(("watermark", {"resource": str(haze), "distort": 1}))
        if not s.has_drops:
            return result + flashes
        result += core.softening_filters(s, height)
        folder = core.cache_folder(cache, s, width, height, fps)
        self._wanted[getattr(clip, "id", None)] = folder
        if core.ready(folder):
            return result + core.drop_filters(folder, s, height) + flashes

        def stale() -> bool:  # réglage déjà changé (curseur glissé) : calcul inutile
            return folder not in self._wanted.values()

        def work(progress, cancelled):
            try:
                core.render_layers(folder, s, width, height, fps, progress,
                                   lambda: cancelled() or stale())
            except core.Cancelled:
                if cancelled():
                    raise
                # abandon silencieux : l'aperçu rechargé demande les calques à jour

        context.schedule_job(f"pluie:{folder.name}", _("Gouttes de pluie"), work)
        return result + flashes  # en attendant les gouttes : l'ambiance seule


def register(api) -> None:
    api.add_video_effect(Rain)
