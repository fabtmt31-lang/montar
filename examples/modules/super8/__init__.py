# SPDX-License-Identifier: GPL-3.0-or-later
"""Module « Super 8 » : la vidéo semble tournée en Super 8 — couleurs de pellicule, grain,
poussières et rayures, scintillement et instabilité, fuites de lumière, fenêtre de
projection, cadence 18 images/s, bruit de projecteur.

Comme le module « Pluie », l'effet est aussi une source de clip (`ClipSource`) : `resolve`,
appelé juste avant `filters` pour chaque clip, donne le contexte de rendu (taille de la
toile, cache, tâches de fond) et sert la copie à 18 images/s quand elle est demandée. Le
bouton « Ajouter le bruit de projecteur » est ajouté sous le titre de l'effet (voir
`bouton.py`), et l'outil du même nom est dans le clic droit sur le clip."""
from __future__ import annotations

from montar.api import ZOOM, ClipSource, Param, SourceOverride, Tool, VideoEffect
from montar.i18n import _

from . import core

MODULE_ID = "super8"  # identifiant du module et de l'effet : `resolve` est alors appelé
SOUND_PREFIX = "Bruit de projecteur"


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


class Super8(VideoEffect, ClipSource):
    id = MODULE_ID
    name = "Super 8"
    description = ("Comme tourné en Super 8 : couleurs de pellicule, grain, poussières et "
                   "rayures, scintillement, fuites de lumière, fenêtre de projection. "
                   "Curseurs à 50 % : réglage normal du style choisi.")
    icon = "film"
    params = [
        Param.choice("style", "Style", [("vacances", "Vacances"),
                                        ("fane", "Souvenir fané"),
                                        ("abime", "Bobine abîmée")]),
        Param.choice("pellicule", "Pellicule", [("auto", "Selon le style"),
                                                ("kodachrome", "Kodachrome (chaud, saturé)"),
                                                ("ektachrome", "Ektachrome (plus froid)"),
                                                ("fanee", "Fanée"),
                                                ("nb", "Noir et blanc")]),
        Param.choice("cadre", "Cadre", [("fenetre", "Fenêtre 4:3, coins arrondis"),
                                        ("perfo", "Fenêtre 4:3 et perforation"),
                                        ("entier", "Image entière")]),
        Param.float("usure", "Usure de la pellicule", 0.0, 1.0, default=0.5),
        Param.float("grain", "Grain", 0.0, 1.0, default=0.5),
        Param.float("poussieres", "Poussières et rayures", 0.0, 1.0, default=0.5),
        Param.float("fuites", "Fuites de lumière", 0.0, 1.0, default=0.5),
        Param.float("scintillement", "Scintillement", 0.0, 1.0, default=0.5),
        Param.float("instabilite", "Instabilité de l'image", 0.0, 1.0, default=0.5),
        Param.float("vignettage", "Vignettage", 0.0, 1.0, default=0.5),
        Param.float("douceur", "Douceur de l'optique", 0.0, 1.0, default=0.5),
        Param.bool("bobine", "Début et fin de bobine (images brûlées)", False),
        Param.bool("cadence", "Cadence 18 images/s (préparée en arrière-plan)", False),
        Param("variante", "Variante des poussières", "int", 1, 1, 20),
    ]

    def __init__(self) -> None:
        from .bouton import SoundButton

        self._current = None  # (contexte, clip, cadre) transmis par resolve au filters suivant
        self.button = SoundButton(self)

    # --- source de clip : contexte de rendu, cadence 18 images/s ------------------------

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
        if media.kind == "image":
            return SourceOverride(core.still_image(context.cache_dir, media.path), 0, 1.0,
                                  "image")
        values = clip.modules.get(MODULE_ID)
        path = media.path
        if isinstance(values, dict) and values.get("cadence"):
            target = core.cadence_path(context.cache_dir, media.path)
            if target.exists():
                path = str(target)
            else:
                job = (media.path, float(getattr(media, "fps", 0) or 0),
                       float(getattr(media, "duration", 0) or 0), target)

                def work(progress, cancelled):
                    source, fps, seconds, output = job
                    core.render_cadence(source, output, fps, seconds, progress, cancelled)

                context.schedule_job(f"super8:{target.name}", _("Cadence 18 images/s"), work)
        # la source du clip (ou sa copie à 18 images/s) : jamais « en attente de calcul »
        return SourceOverride(path, clip.source_in, clip.speed, "video")

    def badge(self, settings):
        return _("Super 8")

    # --- effet ---------------------------------------------------------------------------

    def filters(self, values):
        current, self._current = self._current, None
        s = core.Settings.from_values(values)
        result = core.stock_filters(s)
        if current is None:  # appelé hors du rendu d'un clip : les couleurs seules
            return result
        context, clip, ((width, height), area, scale) = current
        fps = int(getattr(context, "fps", 25))
        cache = context.cache_dir
        result += core.look_filters(s, round(height * scale))
        result += core.reel_filters(s, int(clip.duration), fps)
        result += core.overlay(core.leak_layer(cache, s, width, height, area, fps))
        result += core.overlay(core.dust_layer(cache, s, width, height, area, fps))
        result += core.overlay(core.gate_layer(cache, s, width, height, area))
        return result + core.keep_outside_transparent(cache, area, width, height)


def add_projector_sound(editor, clip_id: str):
    """Bruit de projecteur sous le clip : fichier son créé dans les médias du projet, posé
    sur une piste audio libre à cet endroit (ou une nouvelle), volume bas."""
    from montar.media.probe import probe

    timeline = editor.timeline
    clip = timeline.clip(clip_id)
    project = editor.project
    folder = project.media_dir or (editor.cache_dir / "super8" / "sons")
    n = 1
    while (folder / f"{SOUND_PREFIX} {n}.wav").exists():
        n += 1
    path = core.projector_sound(folder / f"{SOUND_PREFIX} {n}.wav",
                                clip.duration / project.fps, seed=n)
    media = probe(path)
    start, end = clip.start, clip.start + clip.duration

    def place(t):
        t.project.media.append(media)
        track = next((tr for tr in t.project.tracks if tr.kind == "audio"
                      and not any(c.start < end and start < c.start + c.duration
                                  for c in t.clips_on(tr.id))), None)
        if track is None:
            track = t.add_track("audio")
        added = t.add_clip(media, track.id, start, clip.duration)
        added.volume = 0.35
        return added

    return editor.edit(_("Ajouter le bruit de projecteur"), place)


def has_projector_sound(project, clip) -> bool:
    """Un bruit de projecteur est-il déjà posé sous ce clip ?"""
    from pathlib import Path

    end = clip.start + clip.duration
    for c in project.clips:
        media = project.find_media(c.media_id) if c.media_id else None
        if media is None or media.kind != "audio":
            continue
        if Path(media.path).name.startswith(SOUND_PREFIX) and c.start < end \
                and clip.start < c.start + c.duration:
            return True
    return False


class ProjectorSoundTool(Tool):
    id = "super8.bruit"
    name = "Ajouter le bruit de projecteur"
    icon = "film"
    description = ("Pose sous le clip le ronronnement et le claquement d'un projecteur "
                   "Super 8, sur une piste audio.")

    def available(self, editor, clip) -> bool:
        return clip is not None and MODULE_ID in clip.modules

    def run(self, editor, clip) -> None:
        add_projector_sound(editor, clip.id)


def register(api) -> None:
    effect = Super8()
    api.add_video_effect(effect)
    api.add_clip_source(effect)
    api.add_tool(ProjectorSoundTool)
