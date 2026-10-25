# SPDX-License-Identifier: GPL-3.0-or-later
"""Module « Pluie » : la vidéo semble filmée sous la pluie — gouttes sur l'objectif ou sur
une vitre, image assombrie d'un jour de pluie, pluie qui tombe, brume, éclairs.

L'effet est aussi une source de clip (`ClipSource`) : `resolve`, appelé juste avant
`filters` pour chaque clip, donne le contexte de rendu (taille de la toile, fréquence
d'images, dossier de cache, tâches de fond) et la durée du clip. La source rendue est celle
du clip, inchangée. Les gouttes sont calculées en tâche de fond ; en attendant, l'ambiance
seule est appliquée."""
from __future__ import annotations

from montar.api import ClipSource, Param, SourceOverride, VideoEffect
from montar.i18n import _

from . import core

MODULE_ID = "pluie"  # identifiant du module et de l'effet : `resolve` est alors appelé


class Rain(VideoEffect, ClipSource):
    id = MODULE_ID
    name = "Pluie"
    description = ("Comme filmé sous la pluie : gouttes d'eau sur l'objectif ou une vitre, "
                   "image plus sombre et plus froide, pluie qui tombe, brume, éclairs. "
                   "Curseurs à 50 % : réglage normal du temps choisi.")
    icon = "droplets"
    params = [
        Param.choice("temps", "Temps", [("pluie", "Pluie"), ("bruine", "Bruine"),
                                        ("averse", "Averse"), ("orage", "Orage")]),
        Param.choice("surface", "Gouttes sur", [("objectif", "L'objectif de la caméra"),
                                                ("vitre", "Une vitre")]),
        Param.float("volume", "Volume de gouttes", 0.0, 1.0, default=0.5),
        Param.float("taille", "Taille des gouttes", 0.0, 1.0, default=0.5),
        Param.float("ruissellement", "Ruissellement", 0.0, 1.0, default=0.5),
        Param.float("ambiance", "Ambiance (image assombrie)", 0.0, 1.0, default=0.5),
        Param.float("chute", "Pluie qui tombe", 0.0, 1.0, default=0.5),
        Param.float("brume", "Brume", 0.0, 1.0, default=0.5),
        Param.bool("eclairs", "Éclairs (toujours avec « Orage »)", False),
        Param.bool("anime", "Gouttes animées (apparaissent, glissent)", True),
        Param.bool("mouille", "Objectif mouillé (image adoucie)", True),
        Param("variante", "Variante des gouttes", "int", 1, 1, 20),
    ]

    def __init__(self) -> None:
        self._current = None  # (contexte, clip) transmis par resolve au filters qui suit
        self._wanted: dict = {}  # clip → calques attendus (les autres calculs sont abandonnés)

    # --- source de clip : contexte de rendu --------------------------------------------

    def resolve(self, context, clip, media):
        self._current = (context, clip)
        if media is None or media.kind not in ("video", "image"):
            return None
        # la source du clip, telle quelle : le clip n'est jamais « en attente de calcul »
        return SourceOverride(media.path, clip.source_in, clip.speed,
                              "image" if media.kind == "image" else "video")

    def badge(self, settings):
        return _("Pluie")

    # --- effet ---------------------------------------------------------------------------

    def filters(self, values):
        current, self._current = self._current, None
        s = core.Settings.from_values(values)
        result = core.ambiance_filters(s)
        if current is None:  # appelé hors du rendu d'un clip : l'ambiance seule
            return result
        context, clip = current
        project = getattr(context, "project", None)
        width, height = project.canvas_size if project is not None else (1920, 1080)
        fps = int(getattr(context, "fps", 25))
        # éclairs en dernier : ils illuminent aussi les gouttes
        flashes = core.lightning_filters(s, int(clip.duration), fps)
        cache = context.cache_dir
        if s.brume > 0.001:
            haze = core.haze_image(cache / "pluie", s.brume)
            result.append(("watermark", {"resource": str(haze), "distort": 1}))
        if not s.has_drops:
            return result + flashes
        result += core.softening_filters(s, height)
        folder = core.cache_folder(cache, s, width, height, fps)
        self._wanted[clip.id] = folder
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
    rain = Rain()
    api.add_video_effect(rain)
    api.add_clip_source(rain)
