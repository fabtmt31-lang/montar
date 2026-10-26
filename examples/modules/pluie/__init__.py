# SPDX-License-Identifier: GPL-3.0-or-later
"""Module « Pluie » : la vidéo semble filmée sous la pluie — gouttes sur l'objectif ou sur
une vitre, image assombrie d'un jour de pluie, pluie qui tombe, brume, éclairs.

L'effet est aussi une source de clip (`ClipSource`) : `resolve`, appelé juste avant
`filters` pour chaque clip, donne le contexte de rendu (taille de la toile, fréquence
d'images, dossier de cache, tâches de fond) et la durée du clip. La source rendue est celle
du clip, inchangée. Les gouttes sont calculées en tâche de fond ; en attendant, l'ambiance
seule est appliquée.

Pour que l'utilisation reste légère, les réglages montrent d'abord un aperçu immédiat
(gouttes figées, pluie qui tombe), sans calcul de fond. Le bouton « Appliquer la pluie »,
sous le titre de l'effet dans le panneau Effets (voir `bouton.py`), lance le calcul où les
gouttes ruissellent. La pluie ne couvre que l'image du clip, pas les bandes autour."""
from __future__ import annotations

from montar.api import ZOOM, ClipSource, Param, SourceOverride, VideoEffect
from montar.i18n import _

from . import core

MODULE_ID = "pluie"  # identifiant du module et de l'effet : `resolve` est alors appelé
APPLIED = "_gouttes"  # réglages des gouttes appliqués (bouton « Appliquer la pluie »)


def _placed(context, clip) -> bool:
    """Le moteur place-t-il le clip lui-même (filtre « affine ») ? C'est le cas s'il est
    transformé, s'il a des images clés, ou si un autre effet le zoome."""
    transform = getattr(clip, "transform", None)
    if transform is not None and not transform.is_identity():
        return True
    if any(points for points in (getattr(clip, "keyframes", None) or {}).values()):
        return True
    manager = getattr(context, "manager", None)
    if manager is None:
        return False
    for module_id, effect in manager.effects():
        values = (getattr(clip, "modules", None) or {}).get(effect.id) \
            if effect.id != MODULE_ID else None
        if isinstance(values, dict):
            filters = manager.guarded(
                module_id, lambda e=effect, v=values: list(e.filters({**e.defaults(), **v})),
                [])
            if any(name == ZOOM for name, _props in filters):
                return True
    return False


class Rain(VideoEffect, ClipSource):
    id = MODULE_ID
    name = "Pluie"
    description = ("Comme filmé sous la pluie : gouttes d'eau sur l'objectif ou une vitre, "
                   "image plus sombre et plus froide, pluie qui tombe, brume, éclairs. "
                   "Curseurs à 50 % : réglage normal du temps choisi. Réglez, puis cliquez "
                   "sur « Appliquer la pluie » pour que les gouttes ruissellent.")
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
        Param.bool("mouille", "Objectif mouillé (image adoucie)", True),
        Param("variante", "Variante des gouttes", "int", 1, 1, 20),
    ]

    APPLIED = APPLIED

    def __init__(self) -> None:
        from .bouton import ApplyButton

        self._current = None  # (contexte, clip) transmis par resolve au filters qui suit
        self._wanted: dict = {}  # clip → calques attendus (les autres calculs sont abandonnés)
        self.button = ApplyButton(self)

    def apply(self, context, clip_id: str) -> None:
        """Bouton « Appliquer la pluie » : les réglages actuels des gouttes sont retenus,
        et le calcul des gouttes qui ruissellent est lancé (modification annulable)."""
        def change(timeline):
            values = timeline.clip(clip_id).modules[MODULE_ID]
            values[APPLIED] = core.drop_state(
                core.Settings.from_values({**self.defaults(), **values}))

        context.edit(_("Appliquer la pluie"), change)

    def job_of(self, context, clip_id: str) -> float | None:
        """Avancement (0 … 1) du calcul des gouttes du clip, ou None."""
        folder = self._wanted.get(clip_id)
        jobs = getattr(getattr(context, "jobs", None), "jobs", {}) or {}
        job = jobs.get(f"pluie:{folder.name}") if folder is not None else None
        return float(job.get("progress", 0.0)) if job is not None else None

    # --- source de clip : contexte de rendu --------------------------------------------

    def resolve(self, context, clip, media):
        self._current = None
        if media is None or media.kind not in ("video", "image"):
            return None
        project = getattr(context, "project", None)
        cw, ch = project.canvas_size if project is not None else (1920, 1080)
        frame = core.clip_frame(cw, ch, getattr(media, "width", 0) or 0,
                                getattr(media, "height", 0) or 0,
                                getattr(clip, "transform", None), _placed(context, clip))
        self._current = (context, clip, frame)
        self.button.attach(context)
        manager = getattr(context, "manager", None)
        if manager is not None and any(mid != MODULE_ID and mid in clip.modules
                                       for mid, _s in manager.sources()):
            return None  # une autre source (timelapse…) fournit déjà le fichier du clip
        # la source du clip, telle quelle : le clip n'est jamais « en attente de calcul »
        if media.kind == "image":
            return SourceOverride(core.still_image(context.cache_dir, media.path), 0, 1.0,
                                  "image")
        return SourceOverride(media.path, clip.source_in, clip.speed, "video")

    def badge(self, settings):
        s = core.Settings.from_values({**self.defaults(), **settings})
        return _("Pluie") if core.is_applied(s, settings.get(APPLIED)) else _("Pluie · aperçu")

    # --- effet ---------------------------------------------------------------------------

    def filters(self, values):
        current, self._current = self._current, None
        s = core.Settings.from_values(values)
        result = core.ambiance_filters(s)
        if current is None:  # appelé hors du rendu d'un clip : l'ambiance seule
            return result
        context, clip, ((width, height), area, scale) = current
        fps = int(getattr(context, "fps", 25))
        cache = context.cache_dir
        # éclairs en dernier : ils illuminent aussi les gouttes ; puis la zone hors de
        # l'image du clip redevient transparente
        last = core.lightning_filters(s, int(clip.duration), fps) \
            + core.keep_outside_transparent(cache, area, width, height)
        if s.brume > 0.001:
            haze = core.haze_image(cache / "pluie", s.brume)
            result.append(("watermark", {"resource": str(haze), "producer.eof": "loop",
                                         "composite.geometry": core.geometry(area),
                                         "composite.distort": 1, "composite.fill": 1}))
        if not s.has_drops:
            return result + last
        result += core.softening_filters(s, height)
        folder = core.cache_folder(cache, s, width, height, fps, area, scale)
        applied = core.is_applied(s, values.get(APPLIED))
        if applied:
            self._wanted[clip.id] = folder
            if core.ready(folder):
                return result + core.drop_filters(folder, s, height) + last
        else:
            self._wanted.pop(clip.id, None)
        # réglages en cours, ou calcul pas encore fini : aperçu immédiat, gouttes figées
        preview = core.preview_layers(cache, s, width, height, area, scale)
        result += core.drop_filters(preview, s, height, preview=True) + last
        if not applied:
            return result

        def stale() -> bool:  # réglage déjà changé (curseur glissé) : calcul inutile
            return folder not in self._wanted.values()

        def work(progress, cancelled):
            try:
                core.render_layers(folder, s, width, height, fps, progress,
                                   lambda: cancelled() or stale(), area, scale)
            except core.Cancelled:
                if cancelled():
                    raise
                # abandon silencieux : l'aperçu rechargé demande les calques à jour

        context.schedule_job(f"pluie:{folder.name}", _("Gouttes de pluie"), work)
        return result


def register(api) -> None:
    rain = Rain()
    api.add_video_effect(rain)
    api.add_clip_source(rain)
