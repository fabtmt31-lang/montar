# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Timelapse » : accélère fortement une partie d'un clip vidéo.

Il sert aussi d'exemple complet de l'API des modules (outil + source de clip)."""
from __future__ import annotations

from montar.api import ClipSource, ModuleAPI, SourceOverride, Tool
from montar.i18n import _

from . import core


def _video_clip(editor, clip) -> bool:
    if clip is None or clip.is_text:
        return False
    media = editor.project.find_media(clip.media_id)
    track = editor.timeline.track(clip.track_id)
    return media is not None and media.kind == "video" and track.kind == "video"


class TimelapseTool(Tool):
    id = "timelapse.apply"
    name = "Timelapse…"
    icon = "gauge"
    section = "speed"

    def available(self, editor, clip) -> bool:
        return _video_clip(editor, clip) and (
            core.settings_of(clip) is not None or not editor.timeline.timing_locked(clip))

    def run(self, editor, clip) -> None:
        from .dialog import TimelapseDialog

        existing = core.settings_of(clip)
        fps = editor.project.fps
        if existing is not None:  # modification : la plage est le segment existant
            start, end = clip.start, clip.end
            source_frames, whole = int(existing["source_frames"]), True
        else:
            start, end = clip.start, clip.end
            marked = editor.selection_range
            if marked is not None and marked[0] == clip.id:
                start, end = max(clip.start, marked[1]), min(clip.end, marked[2])
            source_frames = max(1, round((end - start) * clip.speed))
            whole = (start, end) == (clip.start, clip.end)
        settings = core.Settings.from_dict(existing or {})
        dialog = TimelapseDialog(editor.parent, source_frames, fps, settings, whole)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        chosen = dialog.settings()
        clip_id = clip.id
        result = editor.edit(_("Timelapse"),
                             lambda timeline: core.apply(timeline, clip_id, start, end, chosen))
        if result is not None:
            editor.select(result.id)


class RemoveTimelapseTool(Tool):
    id = "timelapse.remove"
    name = "Retirer le timelapse"
    icon = "rotate-ccw"
    section = "speed"

    def available(self, editor, clip) -> bool:
        return clip is not None and core.settings_of(clip) is not None

    def run(self, editor, clip) -> None:
        clip_id = clip.id
        result = editor.edit(_("Retirer le timelapse"), lambda t: core.remove(t, clip_id))
        if result is not None:
            editor.select(result.id)


class TimelapseSource(ClipSource):
    """Rend le segment depuis le fichier pré-calculé, ou en attendant par saut d'images."""

    def resolve(self, context, clip, media):
        data = core.settings_of(clip)
        if data is None:
            return None
        path = core.cache_path(context.cache_dir, media.path, clip.source_in, data, context.fps)
        if path.exists():
            return SourceOverride(str(path), 0, 1.0)

        job = (media.path, clip.source_in, dict(data), context.fps, path)  # copie figée

        def work(progress, cancelled):
            media_path, source_in, settings, fps, target = job
            core.render(media_path, target, source_in, settings, fps, progress, cancelled)

        context.schedule_job(path.name, _("Timelapse"), work)
        return None  # aperçu provisoire : la vitesse du clip, rendue par saut d'images

    def badge(self, settings) -> str:
        return f"TL ×{float(settings.get('factor', 0)):g}"


def register(api: ModuleAPI) -> None:
    api.add_tool(TimelapseTool)
    api.add_tool(RemoveTimelapseTool)
    api.add_clip_source(TimelapseSource)
