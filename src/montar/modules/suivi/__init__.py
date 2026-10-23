# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Suivi de mouvement » : un objet est suivi dans un clip vidéo (calcul en
arrière-plan, NumPy) ; un graphisme, une image ou un logo placé au-dessus le suit (images
clés de position), ou l'objet est pixelisé tout au long de son déplacement."""
from __future__ import annotations

import tempfile
from pathlib import Path

from montar.api import ModuleAPI, Param, Tool, VideoEffect
from montar.i18n import _

PIXELATE_ID = "suivi.pixeliser"
KEY_STEP = 2  # une clé de position toutes les 2 images


def _video_clip(editor, clip) -> bool:
    if clip is None or clip.is_text or clip.reverse:
        return False
    media = editor.project.find_media(clip.media_id)
    track = editor.timeline.track(clip.track_id)
    return media is not None and media.kind == "video" and track.kind == "video"


def followers(editor, clip) -> list[tuple[str, str]]:
    """Images et graphismes d'autres pistes qui chevauchent le clip : (id, nom)."""
    result = []
    for c in editor.project.clips:
        if c.id == clip.id or c.is_text or c.track_id == clip.track_id:
            continue
        media = editor.project.find_media(c.media_id)
        if media is None or media.kind not in ("image", "video"):
            continue
        if c.start < clip.start + clip.duration and clip.start < c.start + c.duration:
            result.append((c.id, media.name))
    return result


def follow_keys(project, video_clip, follower, points, start_rel: int) -> dict[str, list]:
    """Clés x / y du suiveur : il garde son écart de départ avec l'objet suivi."""
    from montar.core.keyframes import transform_at
    from montar.engine.geometry import offset_for_center, placement

    cw, ch = project.canvas_size
    vm = project.find_media(video_clip.media_id)
    fm = project.find_media(follower.media_id)
    p = placement(cw, ch, vm.width, vm.height, video_clip.transform)

    def obj(point):
        return p.left + point.x * p.width, p.top + point.y * p.height

    def rel(point) -> int:  # image du suiveur
        return video_clip.start + start_rel + point.frame - follower.start

    inside = [pt for pt in points if 0 <= rel(pt) < follower.duration]
    if not inside:
        return {}
    first = inside[0]
    t0 = transform_at(follower, rel(first))
    start = placement(cw, ch, fm.width, fm.height, t0)
    ox, oy = obj(first)
    dx, dy = start.left + start.width / 2 - ox, start.top + start.height / 2 - oy
    xs, ys = [], []
    for pt in inside:
        cx, cy = obj(pt)
        t = transform_at(follower, rel(pt))
        x, y = offset_for_center(cw, ch, fm.width, fm.height, t, cx + dx, cy + dy)
        xs.append([rel(pt), round(x, 4)])
        ys.append([rel(pt), round(y, 4)])
    return {"x": xs, "y": ys}


class TrackTool(Tool):
    id = "suivi.suivre"
    name = "Suivre un objet…"
    icon = "crosshair"
    description = ("Suit un objet dans la vidéo : un graphisme ou une image le suit, ou "
                   "l'objet est pixelisé (calcul en arrière-plan).")

    def available(self, editor, clip) -> bool:
        return _video_clip(editor, clip)

    def run(self, editor, clip) -> None:
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QMessageBox

        from montar.core import tracking
        from montar.media.frames import FrameError, extract_frame

        try:
            import numpy  # noqa: F401
        except ImportError:
            QMessageBox.information(editor.parent, _("Suivre un objet"), _(
                "Le suivi demande NumPy (paquet python3-numpy)."))
            return
        media = editor.project.find_media(clip.media_id)
        fps = editor.fps
        start_rel = min(max(0, editor.playhead - clip.start), clip.duration - 1)
        seconds = (clip.source_in + start_rel * clip.speed) / fps
        with tempfile.TemporaryDirectory(prefix="montar-suivi-") as tmp:
            try:
                still = extract_frame(media.path, seconds, Path(tmp) / "image.png")
            except FrameError as exc:
                editor.error(str(exc))
                return
            image = QImage(str(still))
        from .dialog import TrackDialog

        dialog = TrackDialog(editor.parent, image, followers(editor, clip))
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        choice = dialog.choice()
        job = (media.path, seconds, (clip.duration - start_rel) * clip.speed / fps,
               fps / clip.speed, choice["rect"], clip.duration - start_rel)
        clip_id = clip.id

        def work(progress, cancelled):
            path, start, duration, rate, rect, total = job
            frames = tracking.read_frames(path, start, duration, rate)
            points = tracking.track(frames, rect, progress, cancelled, total)
            return tracking.simplify(tracking.smooth(points), KEY_STEP)

        def done(points):
            if not points:
                editor.error(_("Le suivi n'a rien donné."))
                return
            if choice["mode"] == "follow":
                target_id = choice["target"]

                def attach(timeline):
                    video = timeline.clip(clip_id)
                    follower = timeline.clip(target_id)
                    keys = follow_keys(timeline.project, video, follower, points, start_rel)
                    follower.keyframes.update(keys)
                    return follower

                result = editor.edit(_("Suivre un objet"), attach)
                if result is not None:
                    editor.select(result.id)
            else:
                w, h = choice["rect"][2], choice["rect"][3]
                track = [[start_rel + p.frame, round(p.x, 4), round(p.y, 4)] for p in points]

                def pixelate(timeline):
                    target = timeline.clip(clip_id)
                    target.modules[PIXELATE_ID] = {"bloc": choice["block"], "piste": track,
                                                   "taille": [round(w, 4), round(h, 4)]}
                    return target

                editor.edit(_("Pixeliser l'objet suivi"), pixelate)

        editor.schedule_job(f"suivi:{clip.id}:{start_rel}", _("Suivi de mouvement"), work,
                            done)


class TrackedPixelate(VideoEffect):
    """Pixelisation qui suit l'objet : un filtre « obscure » par intervalle entre deux
    positions (le cadre glisse de l'une à l'autre)."""

    id = PIXELATE_ID
    name = "Pixelisation suivie"
    description = "Masque un objet suivi (créé par « Suivre un objet… »)."
    icon = "crosshair"
    params = [Param.float("bloc", "Taille des pavés", 4, 48, default=16),
              Param.float("marge", "Marge autour de l'objet", 0.0, 1.0, default=0.15)]

    def filters(self, values):
        points = values.get("piste") or []
        if len(points) < 1:
            return []
        w, h = values.get("taille", [0.1, 0.1])
        grow = 1 + max(0.0, float(values.get("marge", 0.15)))
        w, h = min(1.0, w * grow), min(1.0, h * grow)
        block = max(2, round(float(values.get("bloc", 16))))

        def geometry(x, y):
            left = min(max(0.0, x - w / 2), 1 - w)
            top = min(max(0.0, y - h / 2), 1 - h)
            return f"{left * 100:.2f}%/{top * 100:.2f}%:{w * 100:.2f}%x{h * 100:.2f}%:" \
                   f"{block}x{block}"

        result = []
        pairs = list(zip(points, points[1:], strict=False)) or [(points[0], points[0])]
        for (f0, x0, y0), (f1, x1, y1) in pairs:
            last = f1 - 1 if f1 > f0 else f0
            result.append(("obscure", {"start": geometry(x0, y0), "end": geometry(x1, y1),
                                       "in": int(f0), "out": int(last)}))
        f, x, y = points[-1]  # la dernière position tient une image
        result.append(("obscure", {"start": geometry(x, y), "end": geometry(x, y),
                                   "in": int(f), "out": int(f)}))
        return result


def register(api: ModuleAPI) -> None:
    api.add_tool(TrackTool)
    api.add_video_effect(TrackedPixelate)
