# SPDX-License-Identifier: GPL-3.0-or-later
"""Opérations de montage sur la timeline d'un projet (sans Qt).

Règles :
- une piste vidéo accepte les vidéos et les images ; une piste audio les sons et la bande
  son des vidéos ; une piste texte les clips de texte ;
- deux clips d'une même piste ne se chevauchent jamais, sauf ceux reliés par une
  transition : le clip de droite recouvre alors les dernières images du clip de gauche ;
- un clip vidéo ou audio ne peut pas dépasser la longueur de son média (à sa vitesse).
"""
from __future__ import annotations

import copy

from montar.core import keyframes
from montar.core.project import (
    Clip,
    Marker,
    MediaItem,
    Project,
    TextStyle,
    Track,
    Transition,
    new_id,
)
from montar.i18n import _

IMAGE_DEFAULT_SECONDS = 5
TEXT_DEFAULT_SECONDS = 5
MIN_SPEED, MAX_SPEED = 0.1, 16.0
TRACK_KINDS = ("text", "video", "audio")
TRACK_NAMES = {"text": "Texte", "video": "Vidéo", "audio": "Audio"}
TRACK_PREFIX = {"text": "T", "video": "V", "audio": "A"}
VOICE_OVER_TRACK = "Voix off"
VIDEO_TRANSITIONS = ("dissolve", "dip_black", "dip_white", "wipe_right", "wipe_left",
                     "slide_left", "slide_right", "zoom")
AUDIO_TRANSITIONS = ("dissolve",)


def transition_allowed(kind: str, track_kind: str) -> bool:
    """Les transitions des modules (identifiant avec un point) sont des transitions vidéo."""
    if track_kind == "audio":
        return kind in AUDIO_TRANSITIONS
    return kind in VIDEO_TRANSITIONS or "." in kind


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

    def media_of(self, clip: Clip) -> MediaItem | None:
        """Média du clip (None pour un texte)."""
        if clip.is_text:
            return None
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

    def accepts(self, track: Track, media: MediaItem | None) -> bool:
        """La piste peut-elle recevoir ce média (None = clip de texte) ?"""
        if media is None:
            return track.kind == "text"
        if track.kind == "video":
            return media.kind in ("video", "image")
        if track.kind == "audio":
            return media.kind == "audio" or (media.kind == "video" and media.has_audio)
        return False

    @staticmethod
    def timing_locked(clip: Clip) -> bool:
        """Un module (ex. timelapse) peut figer la durée et le point d'entrée d'un clip."""
        return any(isinstance(v, dict) and v.get("locks_timing") for v in clip.modules.values())

    def accepts_clip(self, track: Track, clip: Clip) -> bool:
        """Un clip déjà placé ne change que pour une piste du même type."""
        return track.kind == self.track(clip.track_id).kind

    def first_track(self, kind: str) -> Track | None:
        """Piste la plus basse du type (V1, T1) ou première piste audio (A1)."""
        tracks = [t for t in self.project.tracks if t.kind == kind]
        if not tracks:
            return None
        return tracks[0] if kind == "audio" else tracks[-1]

    def track_labels(self) -> dict[str, str]:
        """Libellés courts : V1 et T1 = pistes les plus basses, A1 = première piste audio."""
        labels = {}
        for kind in TRACK_KINDS:
            tracks = [t for t in self.project.tracks if t.kind == kind]
            ordered = tracks if kind == "audio" else list(reversed(tracks))
            for i, t in enumerate(ordered, start=1):
                labels[t.id] = f"{TRACK_PREFIX[kind]}{i}"
        return labels

    def available_after(self, clip: Clip) -> int | None:
        """Images de timeline disponibles depuis le point d'entrée (None = illimité)."""
        media = self.media_of(clip)
        if media is None:
            return None
        length = media.length_frames(self.fps)
        if length is None:
            return None
        if clip.reverse:  # le haut de la plage est fixe : on peut descendre jusqu'à 0
            return max(1, int((clip.source_in + clip.duration * clip.speed) / clip.speed))
        return max(1, int((length - clip.source_in) / clip.speed))

    def available_before(self, clip: Clip) -> int | None:
        """Images de timeline dont le début du clip peut reculer (None = illimité)."""
        media = self.media_of(clip)
        if media is None or media.length_frames(self.fps) is None:
            return None
        if clip.reverse:  # reculer le début montre des images plus loin dans le média
            top = clip.source_in + clip.duration * clip.speed
            return max(0, int((media.length_frames(self.fps) - top) / clip.speed))
        return int(clip.source_in / clip.speed)

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

    # --- transitions (lecture) ---------------------------------------------------------

    def transition(self, transition_id: str) -> Transition:
        for t in self.project.transitions:
            if t.id == transition_id:
                return t
        raise TimelineError(f"transition inconnue : {transition_id}")

    def transitions_of(self, clip_id: str) -> list[Transition]:
        return [t for t in self.project.transitions if clip_id in (t.left_id, t.right_id)]

    def transition_after(self, clip_id: str) -> Transition | None:
        return next((t for t in self.project.transitions if t.left_id == clip_id), None)

    def transition_before(self, clip_id: str) -> Transition | None:
        return next((t for t in self.project.transitions if t.right_id == clip_id), None)

    def neighbour(self, clip_id: str, side: str) -> Clip | None:
        """Clip collé (ou relié par une transition) à droite ou à gauche."""
        clip = self.clip(clip_id)
        link = self.transition_after(clip_id) if side == "right" else \
            self.transition_before(clip_id)
        if link is not None:
            return self.clip(link.right_id if side == "right" else link.left_id)
        for c in self.clips_on(clip.track_id, ignore=clip.id):
            if side == "right" and c.start == clip.end:
                return c
            if side == "left" and c.end == clip.start:
                return c
        return None

    def max_transition(self, left: Clip, right: Clip) -> int:
        """Durée maximale d'une transition entre deux clips (les autres transitions déduites)."""
        before = self.transition_before(left.id)
        after = self.transition_after(right.id)
        room_left = left.duration - (before.duration if before else 0)
        room_right = right.duration - (after.duration if after else 0)
        return max(0, min(room_left, room_right) - 1)

    # --- modifications ------------------------------------------------------------

    def default_duration(self, media: MediaItem) -> int:
        length = media.length_frames(self.fps)
        return length if length is not None else IMAGE_DEFAULT_SECONDS * self.fps

    def add_clip(self, media: MediaItem, track_id: str | None = None,
                 start: int | None = None, duration: int | None = None) -> Clip:
        if media.kind not in ("video", "image", "audio"):
            raise TimelineError(f"type de média inconnu : {media.kind}")
        if track_id:
            track = self.track(track_id)
        else:
            kind = "audio" if media.kind == "audio" else "video"
            track = self.first_track(kind) or self.add_track(kind)
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

    def add_text(self, style: TextStyle, start: int, track_id: str | None = None,
                 duration: int | None = None) -> Clip:
        track = self.track(track_id) if track_id else (self.first_track("text")
                                                       or self.add_track("text"))
        if track.kind != "text":
            raise TimelineError("un texte se place sur une piste texte")
        clip = Clip("", track.id, 0, duration or TEXT_DEFAULT_SECONDS * self.fps,
                    text=copy.deepcopy(style))
        clip.start = self.free_start(track.id, start, clip.duration)
        self.project.clips.append(clip)
        return clip

    def move_clip(self, clip_id: str, track_id: str, start: int) -> Clip:
        clip = self.clip(clip_id)
        track = self.track(track_id)
        if not self.accepts_clip(track, clip):
            track = self.track(clip.track_id)
        self._drop_transitions(clip_id)
        clip.track_id = track.id
        clip.start = self.free_start(track.id, start, clip.duration, ignore=clip.id)
        return clip

    def trim_bounds(self, clip_id: str, edge: str) -> tuple[int, int]:
        """Positions possibles du bord `edge` ("start" ou "end") du clip."""
        clip = self.clip(clip_id)
        if self.timing_locked(clip):
            return (clip.start, clip.start) if edge == "start" else (clip.end, clip.end)
        if edge == "start" and self.transition_before(clip_id) is not None:
            return clip.start, clip.start  # bord occupé par une transition
        if edge == "end" and self.transition_after(clip_id) is not None:
            return clip.end, clip.end
        others = self.clips_on(clip.track_id, ignore=clip.id)
        other_transition = self.transition_after(clip_id) if edge == "start" else \
            self.transition_before(clip_id)
        reserved = other_transition.duration if other_transition else 0
        if edge == "start":
            prev_end = max((c.end for c in others if c.end <= clip.start), default=0)
            before = self.available_before(clip)
            low = prev_end if before is None else max(prev_end, clip.start - before)
            return low, clip.end - 1 - reserved
        next_start = min((c.start for c in others if c.start >= clip.end), default=None)
        after = self.available_after(clip)
        high = clip.start + after if after is not None else None
        limits = [x for x in (next_start, high) if x is not None]
        return clip.start + 1 + reserved, min(limits) if limits else 1 << 30

    def trim(self, clip_id: str, edge: str, frame: int) -> Clip:
        clip = self.clip(clip_id)
        low, high = self.trim_bounds(clip_id, edge)
        frame = max(low, min(high, frame))
        if edge == "start":
            delta = frame - clip.start
            clip.start, clip.duration = frame, clip.duration - delta
            keyframes.shift(clip, -delta)  # les clés restent au même instant de la vidéo
            if self.available_before(clip) is not None and not clip.reverse:
                clip.source_in = max(0, clip.source_in + round(delta * clip.speed))
        elif edge == "end":
            if clip.reverse and self.media_of(clip) is not None:  # la fin montre le bas
                removed = clip.duration - (frame - clip.start)
                clip.source_in = max(0, clip.source_in + round(removed * clip.speed))
            clip.duration = frame - clip.start
        else:
            raise TimelineError(f"bord inconnu : {edge}")
        return clip

    def split(self, clip_id: str, frame: int) -> Clip | None:
        """Coupe le clip à `frame` ; renvoie la seconde partie (None si hors du clip)."""
        clip = self.clip(clip_id)
        if self.timing_locked(clip):
            return None
        before = self.transition_before(clip_id)
        after = self.transition_after(clip_id)
        low = clip.start + (before.duration if before else 0)
        high = clip.end - (after.duration if after else 0)
        if not low < frame < high:
            return None
        offset = frame - clip.start
        second = copy.deepcopy(clip)
        second.id = new_id()
        second.start, second.duration = frame, clip.duration - offset
        keyframes.shift(second, -offset)
        if clip.reverse and self.media_of(clip) is not None:
            # à l'envers : la première partie montre le haut de la plage, la seconde le bas
            clip.source_in += round(second.duration * clip.speed)
        elif self.available_before(clip) is not None:
            second.source_in = clip.source_in + round(offset * clip.speed)
        clip.duration, clip.fade_out, second.fade_in = offset, 0, 0
        if after is not None:
            after.left_id = second.id
        self.project.clips.insert(self.project.clips.index(clip) + 1, second)
        return second

    def isolate(self, clip_id: str, start: int, end: int) -> Clip:
        """Coupe le clip aux deux bornes de la plage et renvoie la partie du milieu."""
        clip = self.clip(clip_id)
        start, end = max(clip.start, start), min(clip.end, end)
        if end <= start:
            raise TimelineError("plage vide")
        if self.timing_locked(clip) and (start, end) != (clip.start, clip.end):
            raise TimelineError("ce clip ne peut pas être coupé")
        middle = self.split(clip_id, start) if start > clip.start else clip
        if middle is None:
            raise TimelineError("impossible de couper ici (transition)")
        if end < middle.end and self.split(middle.id, end) is None:
            raise TimelineError("impossible de couper ici (transition)")
        return middle

    def split_at(self, frame: int, clip_id: str | None = None) -> list[Clip]:
        """Coupe le clip indiqué, ou à défaut tous les clips sous la tête de lecture."""
        targets = [clip_id] if clip_id else [c.id for c in self.clips_at(frame)]
        return [part for cid in targets if (part := self.split(cid, frame)) is not None]

    def delete(self, clip_id: str, ripple: bool = False) -> None:
        clip = self.clip(clip_id)
        overlap = sum(t.duration for t in self.transitions_of(clip_id))
        self._drop_transitions(clip_id)
        self.project.clips.remove(clip)
        if ripple:  # referme l'espace laissé sur la piste
            self._shift_from(clip.track_id, clip.end - overlap, -(clip.duration - overlap))

    def duplicate(self, clip_id: str) -> Clip:
        clip = self.clip(clip_id)
        copy_ = copy.deepcopy(clip)
        copy_.id = new_id()
        end = max(clip.end, self.neighbour(clip_id, "right").end
                  if self.transition_after(clip_id) else clip.end)
        copy_.start = self.free_start(clip.track_id, end, clip.duration)
        self.project.clips.append(copy_)
        return copy_

    def set_speed(self, clip_id: str, speed: float) -> Clip:
        """Change la vitesse ; la durée suit et les clips suivants de la piste se décalent."""
        clip = self.clip(clip_id)
        if self.media_of(clip) is None or self.media_of(clip).kind == "image":
            raise TimelineError("la vitesse ne s'applique qu'aux vidéos et aux sons")
        if self.timing_locked(clip):
            raise TimelineError("retirez d'abord l'effet qui fixe la vitesse de ce clip")
        speed = max(MIN_SPEED, min(MAX_SPEED, round(speed, 3)))
        if speed == clip.speed:
            return clip
        self._drop_transitions(clip_id)
        old_end = clip.end
        duration = max(1, round(clip.duration * clip.speed / speed))
        clip.speed = speed
        clip.duration = min(duration, self.available_after(clip) or duration)
        clip.fade_in = min(clip.fade_in, clip.duration)
        clip.fade_out = min(clip.fade_out, clip.duration)
        self._shift_from(clip.track_id, old_end, clip.end - old_end, ignore=clip.id)
        return clip

    def set_reverse(self, clip_id: str, reverse: bool) -> Clip:
        clip = self.clip(clip_id)
        media = self.media_of(clip)
        if media is None or media.kind == "image":
            raise TimelineError("la lecture inversée ne s'applique qu'aux vidéos et aux sons")
        if self.timing_locked(clip):
            raise TimelineError("retirez d'abord l'effet qui fixe la vitesse de ce clip")
        clip.reverse = reverse
        return clip

    def insert_freeze(self, clip_id: str, frame: int, image: MediaItem,
                      duration: int) -> Clip:
        """Image fixe : coupe le clip à `frame`, décale la suite de `duration` images et place
        l'image à cet endroit."""
        clip = self.clip(clip_id)
        if self.track(clip.track_id).kind != "video":
            raise TimelineError("une image fixe se place sur une piste vidéo")
        if not clip.start <= frame < clip.end:
            raise TimelineError("placez la tête de lecture sur le clip")
        if frame > clip.start and self.split(clip_id, frame) is None:
            raise TimelineError("impossible de couper ici (transition)")
        self._shift_from(clip.track_id, frame, duration)
        still = Clip(image.id, clip.track_id, frame, max(1, duration))
        still.transform = copy.deepcopy(clip.transform)
        self.project.clips.append(still)
        return still

    def detach_audio(self, clip_id: str) -> Clip:
        """Place le son d'un clip vidéo sur une piste audio et coupe le son du clip vidéo."""
        clip = self.clip(clip_id)
        media = self.media_of(clip)
        if media is None or media.kind != "video" or not media.has_audio:
            raise TimelineError("ce clip n'a pas de son à détacher")
        track = self.first_track("audio") or self.add_track("audio")
        audio = Clip(media.id, track.id, 0, clip.duration, source_in=clip.source_in,
                     speed=clip.speed, reverse=clip.reverse, volume=clip.volume,
                     fade_in=clip.fade_in, fade_out=clip.fade_out)
        if any(c.start < clip.end and clip.start < c.end for c in self.clips_on(track.id)):
            track = self.add_track("audio")
            audio.track_id = track.id
        audio.start = self.free_start(track.id, clip.start, clip.duration)
        clip.volume = 0.0
        self.project.clips.append(audio)
        return audio

    # --- marqueurs -------------------------------------------------------------------

    def markers(self) -> list[Marker]:
        return sorted(self.project.markers, key=lambda m: m.frame)

    def marker(self, marker_id: str) -> Marker:
        for m in self.project.markers:
            if m.id == marker_id:
                return m
        raise TimelineError(f"marqueur inconnu : {marker_id}")

    def toggle_marker(self, frame: int) -> Marker | None:
        """Ajoute un marqueur à `frame`, ou retire celui qui s'y trouve déjà."""
        existing = next((m for m in self.project.markers if m.frame == frame), None)
        if existing is not None:
            self.project.markers.remove(existing)
            return None
        number = len(self.project.markers) + 1
        marker = Marker(max(0, frame), _("Marqueur {n}").format(n=number))
        self.project.markers.append(marker)
        return marker

    def move_marker(self, marker_id: str, frame: int) -> None:
        self.marker(marker_id).frame = max(0, frame)

    def rename_marker(self, marker_id: str, name: str) -> None:
        self.marker(marker_id).name = name.strip()

    def remove_marker(self, marker_id: str) -> None:
        self.project.markers.remove(self.marker(marker_id))

    def adjacent_marker(self, frame: int, direction: int) -> Marker | None:
        """Marqueur suivant (direction 1) ou précédent (-1) de `frame`."""
        markers = self.markers()
        if direction > 0:
            return next((m for m in markers if m.frame > frame), None)
        return next((m for m in reversed(markers) if m.frame < frame), None)

    # --- graphismes ---------------------------------------------------------------------

    def add_overlay(self, media: MediaItem, start: int, below: bool = False) -> Clip:
        """Place une image à `start` exactement, sur une piste vidéo libre à cet endroit :
        au-dessus de la piste principale (élément, cadre…) ou, avec `below`, en dessous de
        toutes (arrière-plan). Une piste est ajoutée au besoin."""
        duration = max(1, self.default_duration(media))
        video = [t for t in self.project.tracks if t.kind == "video"]  # de haut en bas
        candidates = video[-1:] if below else video[:-1]
        track = next((t for t in candidates
                      if self.free_start(t.id, start, duration) == start), None)
        if track is None:
            low, high = self.track_block("video")
            track = self.insert_track("video", high if below else low)
        clip = Clip(media.id, track.id, max(0, start), duration)
        self.project.clips.append(clip)
        return clip

    # --- voix off ----------------------------------------------------------------------

    def add_voice_over(self, media: MediaItem, start: int, trim: int = 0) -> Clip:
        """Place un enregistrement à `start` exactement, sur une piste « Voix off » libre à cet
        endroit (créée au besoin) ; les `trim` premières images (son capté avant le début de
        la lecture) sont retirées."""
        trim = max(0, min(trim, self.default_duration(media) - 1))
        duration = max(1, self.default_duration(media) - trim)
        tracks = [t for t in self.project.tracks if t.kind == "audio"]
        tracks.sort(key=lambda t: t.name != _(VOICE_OVER_TRACK))  # les pistes « Voix off » d'abord
        track = next((t for t in tracks if t.name == _(VOICE_OVER_TRACK)
                      and self.free_start(t.id, start, duration) == start), None)
        if track is None:
            track = self.add_track("audio")
            track.name = _(VOICE_OVER_TRACK)
        clip = Clip(media.id, track.id, max(0, start), duration)
        clip.source_in = trim
        self.project.clips.append(clip)
        return clip

    def add_track(self, kind: str) -> Track:
        if kind not in TRACK_KINDS:
            raise TimelineError(f"type de piste inconnu : {kind}")
        track = Track(kind, _(TRACK_NAMES[kind]))
        tracks = self.project.tracks
        if kind == "text":  # au-dessus de tout
            tracks.insert(0, track)
        elif kind == "video":  # au-dessus des autres pistes vidéo, sous les textes
            tracks.insert(sum(1 for t in tracks if t.kind == "text"), track)
        else:
            tracks.append(track)
        return track

    def track_block(self, kind: str) -> tuple[int, int]:
        """Indices (début, fin) où une piste du type peut se placer : textes, vidéos, audio."""
        rank = TRACK_KINDS.index(kind)
        low = sum(1 for t in self.project.tracks if TRACK_KINDS.index(t.kind) < rank)
        return low, low + sum(1 for t in self.project.tracks if t.kind == kind)

    def insert_track(self, kind: str, index: int) -> Track:
        """Nouvelle piste à la position `index`, ramenée parmi les pistes du même type."""
        if kind not in TRACK_KINDS:
            raise TimelineError(f"type de piste inconnu : {kind}")
        low, high = self.track_block(kind)
        track = Track(kind, _(TRACK_NAMES[kind]))
        self.project.tracks.insert(max(low, min(high, index)), track)
        return track

    def move_track(self, track_id: str, index: int) -> None:
        """Déplace une piste vers la position `index` (comptée avant le déplacement)."""
        track = self.track(track_id)
        tracks = self.project.tracks
        old = tracks.index(track)
        tracks.remove(track)
        if index > old:
            index -= 1
        low, high = self.track_block(track.kind)
        tracks.insert(max(low, min(high, index)), track)

    def move_clip_to_new_track(self, clip_id: str, index: int, start: int) -> Clip:
        """Déplace un clip sur une nouvelle piste insérée à la position `index`."""
        clip = self.clip(clip_id)
        track = self.insert_track(self.track(clip.track_id).kind, index)
        return self.move_clip(clip_id, track.id, start)

    def remove_track(self, track_id: str) -> None:
        track = self.track(track_id)
        if track.kind != "text" and sum(1 for t in self.project.tracks
                                        if t.kind == track.kind) <= 1:
            raise TimelineError("il faut garder au moins une piste de ce type")
        self.project.tracks.remove(track)
        self.project.clips = [c for c in self.project.clips if c.track_id != track_id]
        self.sanitize()

    def remove_media(self, media_id: str) -> None:
        self.project.media = [m for m in self.project.media if m.id != media_id]
        self.project.clips = [c for c in self.project.clips if c.media_id != media_id
                              or c.is_text]
        self.sanitize()

    # --- transitions (modifications) -------------------------------------------------

    def add_transition(self, left_id: str, right_id: str, kind: str = "dissolve",
                       duration: int | None = None) -> Transition:
        left, right = self.clip(left_id), self.clip(right_id)
        track = self.track(left.track_id)
        if right.track_id != track.id or right.start != left.end:
            raise TimelineError("une transition relie deux clips qui se suivent sur une piste")
        if not transition_allowed(kind, track.kind):
            kind = "dissolve"
        if self.transition_after(left_id) or self.transition_before(right_id):
            raise TimelineError("ces clips sont déjà reliés par une transition")
        limit = self.max_transition(left, right)
        if limit < 2:
            raise TimelineError("les clips sont trop courts pour une transition")
        length = max(2, min(limit, duration or self.fps))
        self._shift_from(track.id, right.start, -length)
        transition = Transition(track.id, left_id, right_id, kind, length)
        self.project.transitions.append(transition)
        return transition

    def set_transition(self, transition_id: str, kind: str | None = None,
                       duration: int | None = None) -> Transition:
        t = self.transition(transition_id)
        if kind is not None:
            if transition_allowed(kind, self.track(t.track_id).kind):
                t.kind = kind
        if duration is not None:
            left, right = self.clip(t.left_id), self.clip(t.right_id)
            limit = self.max_transition(left, right) + t.duration
            limit = min(limit, left.duration - 1, right.duration - 1)
            length = max(2, min(limit, duration))
            self._shift_from(t.track_id, right.start, t.duration - length)
            t.duration = length
        return t

    def remove_transition(self, transition_id: str) -> None:
        t = self.transition(transition_id)
        right = self.clip(t.right_id)
        self.project.transitions.remove(t)
        self._shift_from(t.track_id, right.start, t.duration)

    def fit_to_media(self, clip_id: str) -> Clip:
        """Après remplacement du média (par une version modifiée, plus courte par exemple) :
        le clip garde sa place mais ne dépasse plus la fin du média."""
        clip = self.clip(clip_id)
        media = self.media_of(clip)
        length = media.length_frames(self.fps) if media is not None else None
        if length is None:
            return clip
        if clip.source_in >= length:
            clip.source_in = 0
        available = max(1, int((length - clip.source_in) / clip.speed))
        if clip.duration > available:
            clip.duration = available
            clip.fade_in = min(clip.fade_in, available)
            clip.fade_out = min(clip.fade_out, available)
            self.sanitize()
        return clip

    def sanitize(self) -> None:
        """Retire les transitions dont les clips ne sont plus en place."""
        ids = {c.id: c for c in self.project.clips}
        kept = []
        for t in self.project.transitions:
            left, right = ids.get(t.left_id), ids.get(t.right_id)
            if (left is not None and right is not None and left.track_id == t.track_id
                    and right.track_id == t.track_id and left.end - right.start == t.duration):
                kept.append(t)
        self.project.transitions = kept

    def shift_after(self, track_id: str, frame: int, delta: int,
                    ignore: str | None = None) -> None:
        """Décale de `delta` les clips de la piste commençant à `frame` ou après."""
        self._shift_from(track_id, frame, delta, ignore)

    def merge_contiguous(self, clip_id: str) -> Clip:
        """Réunit le clip avec ses voisins s'ils sont la suite exacte du même média
        (mêmes réglages, vitesse normale) : l'inverse d'une coupe."""
        clip = self.clip(clip_id)

        def same(a: Clip, b: Clip) -> bool:
            keep = ("id", "start", "duration", "source_in", "fade_in", "fade_out")
            fields_a = {k: v for k, v in a.__dict__.items() if k not in keep}
            fields_b = {k: v for k, v in b.__dict__.items() if k not in keep}
            return (fields_a == fields_b and a.speed == 1.0 and not a.is_text
                    and not a.modules and a.end == b.start
                    and a.source_in + a.duration == b.source_in
                    and self.transition_after(a.id) is None)

        for side in ("left", "right"):
            other = self.neighbour(clip.id, side)
            if other is None:
                continue
            left, right = (other, clip) if side == "left" else (clip, other)
            if not same(left, right):
                continue
            after = self.transition_after(right.id)
            left.duration += right.duration
            left.fade_out = right.fade_out
            if after is not None:
                after.left_id = left.id
            self.project.clips.remove(right)
            clip = left
        return clip

    def _drop_transitions(self, clip_id: str) -> None:
        self.project.transitions = [t for t in self.project.transitions
                                    if clip_id not in (t.left_id, t.right_id)]

    def _shift_from(self, track_id: str, frame: int, delta: int,
                    ignore: str | None = None) -> None:
        """Décale de `delta` les clips de la piste commençant à `frame` ou après."""
        if delta == 0:
            return
        for c in self.clips_on(track_id, ignore=ignore):
            if c.start >= frame:
                c.start = max(0, c.start + delta)


def snapshot(project: Project) -> tuple:
    """Copie de l'état modifiable du projet (pour annuler / rétablir)."""
    return copy.deepcopy((project.media, project.tracks, project.clips, project.transitions,
                          project.markers))


def restore(project: Project, state: tuple) -> None:
    (project.media, project.tracks, project.clips, project.transitions,
     project.markers) = copy.deepcopy(state)

