# SPDX-License-Identifier: GPL-3.0-or-later
"""Opérations de montage sur la timeline d'un projet (sans Qt).

Règles :
- une piste vidéo accepte les vidéos et les images, une piste audio les sons ;
- deux clips d'une même piste ne se chevauchent jamais : un clip déposé ou déplacé sur
  une zone occupée est placé dans l'espace libre le plus proche ;
- un clip vidéo ou audio ne peut pas dépasser la longueur de son média.
"""
from __future__ import annotations

import copy

from montar.core.project import Clip, MediaItem, Project, Track

IMAGE_DEFAULT_SECONDS = 5
TRACK_KIND_FOR_MEDIA = {"video": "video", "image": "video", "audio": "audio"}


class TimelineError(ValueError):
    pass


class Timeline:
    def __init__(self, project: Project) -> None:
        self.project = project

    # --- lecture -----------------------------------------------------------------

    @property
    def fps(self) -> int:
        return self.project.fps

    def track(self, track_id: str) -> Track:
        for t in self.project.tracks:
            if t.id == track_id:
                return t
        raise TimelineError(f"piste inconnue : {track_id}")

    def clip(self, clip_id: str) -> Clip:
        for c in self.project.clips:
            if c.id == clip_id:
                return c
        raise TimelineError(f"clip inconnu : {clip_id}")

    def media_of(self, clip: Clip) -> MediaItem:
        media = self.project.find_media(clip.media_id)
        if media is None:
            raise TimelineError(f"média inconnu : {clip.media_id}")
        return media

    def clips_on(self, track_id: str, ignore: str | None = None) -> list[Clip]:
        return sorted((c for c in self.project.clips
                       if c.track_id == track_id and c.id != ignore), key=lambda c: c.start)

    def length(self) -> int:
        return max((c.end for c in self.project.clips), default=0)

    def clips_at(self, frame: int) -> list[Clip]:
        return [c for c in self.project.clips if c.start <= frame < c.end]

    def accepts(self, track: Track, media: MediaItem) -> bool:
        return TRACK_KIND_FOR_MEDIA.get(media.kind) == track.kind

    def first_track(self, kind: str) -> Track | None:
        """Piste du type demandé la plus basse (V1 pour la vidéo, A1 pour l'audio)."""
        tracks = [t for t in self.project.tracks if t.kind == kind]
        if not tracks:
            return None
        return tracks[-1] if kind == "video" else tracks[0]

    def track_labels(self) -> dict[str, str]:
        """Libellés courts : V1 = piste vidéo la plus basse, A1 = première piste audio."""
        labels = {}
        videos = [t for t in self.project.tracks if t.kind == "video"]
        for i, t in enumerate(reversed(videos), start=1):
            labels[t.id] = f"V{i}"
        audios = [t for t in self.project.tracks if t.kind == "audio"]
        for i, t in enumerate(audios, start=1):
            labels[t.id] = f"A{i}"
        return labels

    def source_length(self, clip: Clip) -> int | None:
        return self.media_of(clip).length_frames(self.fps)

    def free_start(self, track_id: str, start: int, duration: int,
                   ignore: str | None = None) -> int:
        """Début le plus proche de `start` où `duration` images tiennent sans chevauchement."""
        start = max(0, start)
        gaps: list[tuple[int, int | None]] = []
        cursor = 0
        for c in self.clips_on(track_id, ignore):
            if c.start - cursor >= duration:
                gaps.append((cursor, c.start))
            cursor = max(cursor, c.end)
        gaps.append((cursor, None))
        best: int | None = None
        for gap_start, gap_end in gaps:
            latest = None if gap_end is None else gap_end - duration
            candidate = max(gap_start, start if latest is None else min(start, latest))
            if best is None or abs(candidate - start) < abs(best - start):
                best = candidate
        assert best is not None
        return best

    # --- modifications ------------------------------------------------------------

    def default_duration(self, media: MediaItem) -> int:
        length = media.length_frames(self.fps)
        return length if length is not None else IMAGE_DEFAULT_SECONDS * self.fps

    def add_clip(self, media: MediaItem, track_id: str | None = None,
                 start: int | None = None, duration: int | None = None) -> Clip:
        kind = TRACK_KIND_FOR_MEDIA.get(media.kind)
        if kind is None:
            raise TimelineError(f"type de média inconnu : {media.kind}")
        track = self.track(track_id) if track_id else (self.first_track(kind)
                                                       or self.add_track(kind))
        if not self.accepts(track, media):
            raise TimelineError("ce média ne peut pas être placé sur cette piste")
        if duration is None:
            duration = self.default_duration(media)
        if start is None:  # à la suite des clips de la piste
            start = max((c.end for c in self.clips_on(track.id)), default=0)
        clip = Clip(media.id, track.id, 0, max(1, duration))
        clip.start = self.free_start(track.id, start, clip.duration)
        self.project.clips.append(clip)
        return clip

    def move_clip(self, clip_id: str, track_id: str, start: int) -> Clip:
        clip = self.clip(clip_id)
        track = self.track(track_id)
        if not self.accepts(track, self.media_of(clip)):
            track = self.track(clip.track_id)
        clip.track_id = track.id
        clip.start = self.free_start(track.id, start, clip.duration, ignore=clip.id)
        return clip

    def trim_bounds(self, clip_id: str, edge: str) -> tuple[int, int]:
        """Positions possibles du bord `edge` ("start" ou "end") du clip."""
        clip = self.clip(clip_id)
        others = self.clips_on(clip.track_id, ignore=clip.id)
        source_len = self.source_length(clip)
        if edge == "start":
            prev_end = max((c.end for c in others if c.end <= clip.start), default=0)
            if source_len is None:  # image fixe : aucune limite côté source
                return prev_end, clip.end - 1
            low = max(prev_end, clip.start - clip.source_in)
            return low, clip.end - 1
        next_start = min((c.start for c in others if c.start >= clip.end), default=None)
        high = clip.start + (source_len - clip.source_in) if source_len is not None else None
        limits = [x for x in (next_start, high) if x is not None]
        return clip.start + 1, min(limits) if limits else 1 << 30

    def trim(self, clip_id: str, edge: str, frame: int) -> Clip:
        clip = self.clip(clip_id)
        low, high = self.trim_bounds(clip_id, edge)
        frame = max(low, min(high, frame))
        if edge == "start":
            delta = frame - clip.start
            still = self.source_length(clip) is None
            clip.start, clip.duration = frame, clip.duration - delta
            clip.source_in = 0 if still else clip.source_in + delta
        elif edge == "end":
            clip.duration = frame - clip.start
        else:
            raise TimelineError(f"bord inconnu : {edge}")
        return clip

    def split(self, clip_id: str, frame: int) -> Clip | None:
        """Coupe le clip à `frame` ; renvoie la seconde partie (None si hors du clip)."""
        clip = self.clip(clip_id)
        if not clip.start < frame < clip.end:
            return None
        offset = frame - clip.start
        second = Clip(clip.media_id, clip.track_id, frame, clip.duration - offset,
                      clip.source_in + offset)
        clip.duration = offset
        self.project.clips.insert(self.project.clips.index(clip) + 1, second)
        return second

    def split_at(self, frame: int, clip_id: str | None = None) -> list[Clip]:
        """Coupe le clip indiqué, ou à défaut tous les clips sous la tête de lecture."""
        targets = [clip_id] if clip_id else [c.id for c in self.clips_at(frame)]
        return [part for cid in targets if (part := self.split(cid, frame)) is not None]

    def delete(self, clip_id: str, ripple: bool = False) -> None:
        clip = self.clip(clip_id)
        self.project.clips.remove(clip)
        if ripple:  # referme l'espace laissé sur la piste
            for c in self.clips_on(clip.track_id):
                if c.start >= clip.end:
                    c.start -= clip.duration

    def duplicate(self, clip_id: str) -> Clip:
        clip = self.clip(clip_id)
        copy_ = Clip(clip.media_id, clip.track_id, 0, clip.duration, clip.source_in)
        copy_.start = self.free_start(clip.track_id, clip.end, clip.duration)
        self.project.clips.append(copy_)
        return copy_

    def add_track(self, kind: str) -> Track:
        if kind not in ("video", "audio"):
            raise TimelineError(f"type de piste inconnu : {kind}")
        track = Track(kind, "Vidéo" if kind == "video" else "Audio")
        if kind == "video":  # nouvelle piste vidéo au-dessus des autres
            self.project.tracks.insert(0, track)
        else:
            self.project.tracks.append(track)
        return track

    def remove_track(self, track_id: str) -> None:
        track = self.track(track_id)
        if sum(1 for t in self.project.tracks if t.kind == track.kind) <= 1:
            raise TimelineError("il faut garder au moins une piste de ce type")
        self.project.tracks.remove(track)
        self.project.clips = [c for c in self.project.clips if c.track_id != track_id]

    def remove_media(self, media_id: str) -> None:
        self.project.media = [m for m in self.project.media if m.id != media_id]
        self.project.clips = [c for c in self.project.clips if c.media_id != media_id]


def snapshot(project: Project) -> tuple:
    """Copie de l'état modifiable du projet (pour annuler / rétablir)."""
    return copy.deepcopy((project.media, project.tracks, project.clips))


def restore(project: Project, state: tuple) -> None:
    project.media, project.tracks, project.clips = copy.deepcopy(state)
