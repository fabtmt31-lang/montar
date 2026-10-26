# SPDX-License-Identifier: GPL-3.0-or-later
"""Mix Flash : découpe, mélange et application à la timeline (sans Qt, testable).

Les clips choisis d'une piste sont découpés en extraits de durée aléatoire, mélangés puis
replacés bout à bout à l'emplacement du premier. Chaque image des clips d'origine se
retrouve dans exactement un extrait (vérifié avant d'appliquer). Entre deux extraits, une
transition est possible, posée par-dessus les images (la durée ne change pas) : un fondu au
noir ou au blanc après les extraits d'au moins 1 s, ou un éclat lumineux (l'image se
surexpose jusqu'au blanc à la coupe, puis retombe) après les extraits d'au moins 0,5 s.

Les réglages du groupe et les clips d'origine sont gardés dans `clip.modules["fab.mixflash"]`
de chaque extrait, pour remélanger ou revenir aux clips d'origine."""
from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, fields
from itertools import pairwise

from montar.core.project import (
    AudioAdjust,
    Clip,
    ColorAdjust,
    Effects,
    Grade,
    TextStyle,
    Transform,
    new_id,
)
from montar.core.timeline import TimelineError

MODULE_ID = "fab.mixflash"
FADE_MIN = 1.0  # secondes : durée minimale d'un extrait suivi d'un fondu
BURST_MIN = 0.5  # secondes : durée minimale d'un extrait suivi d'un éclat
BURST_ATTACK = 0.4  # part de l'éclat avant la coupe (montée) ; le reste est la retombée
LIMITS = (0.5, 5.0)  # bornes des réglages de durée des extraits, en secondes
TRANSITIONS = {"none": "Aucune", "fade": "Fondus", "burst": "Éclats lumineux",
               "mix": "Fondus et éclats"}
COLORS = {"black": "Noir", "white": "Blanc", "mix": "Noir et blanc"}
SOUND = {"detach": "Détacher le son d'abord", "remove": "Supprimer le son"}


@dataclass
class Settings:
    min_seconds: float = 0.5
    max_seconds: float = 5.0
    transition: str = "mix"
    fade_color: str = "mix"
    probability: float = 0.6  # chance d'une transition après un extrait assez long
    fade_seconds: float = 0.4
    burst_seconds: float = 0.3
    sound: str = "detach"
    no_adjacent: bool = True  # deux extraits qui se suivaient ne restent pas côte à côte
    seed: int = 1

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        s = cls()
        for key in asdict(s):
            if key in data:
                setattr(s, key, type(getattr(s, key))(data[key]))
        s.min_seconds = max(LIMITS[0], min(LIMITS[1], s.min_seconds))
        s.max_seconds = max(s.min_seconds, min(LIMITS[1], s.max_seconds))
        s.transition = s.transition if s.transition in TRANSITIONS else "mix"
        s.fade_color = s.fade_color if s.fade_color in COLORS else "mix"
        s.sound = s.sound if s.sound in SOUND else "detach"
        s.probability = max(0.0, min(1.0, s.probability))
        s.fade_seconds = max(0.1, min(1.0, s.fade_seconds))
        s.burst_seconds = max(0.1, min(1.0, s.burst_seconds))
        return s


@dataclass
class Piece:
    """Extrait : `length` images de la source n° `source`, à partir de `offset`."""

    source: int
    index: int  # rang de l'extrait dans sa source
    offset: int
    length: int


@dataclass
class Item:
    """Extrait du résultat, avec ses transitions posées par-dessus ses images."""

    piece: Piece
    length: int
    after: str = ""  # transition vers l'extrait suivant : "", "fade" ou "burst"
    color: str = ""  # couleur du fondu de fin
    fade_in: int = 0  # images en fondu au début / à la fin de l'extrait
    fade_out: int = 0
    fade_in_color: str = ""
    burst_in: int = 0  # images de retombée d'un éclat (début) / de montée (fin)
    burst_out: int = 0


# --- découpe et mélange ------------------------------------------------------------------

def _feasible(total: int, low: int, high: int) -> int | None:
    """Plus petit nombre de parts de `low` à `high` images dont la somme vaut `total`."""
    k = -(-total // high)
    return k if k * low <= total else None


def _distribute(total: int, k: int, low: int, high: int, rng: random.Random) -> list[int]:
    """`k` parts aléatoires entre `low` et `high` (si possible), de somme exactement `total`."""
    parts = [low] * k
    extra = total - low * k
    if extra < 0:  # impossible de respecter le minimum : parts égales
        parts = [total // k] * k
        extra = total - sum(parts)
    weights = [rng.random() + 0.05 for _ in range(k)]
    scale = sum(weights)
    room = [max(0, high - p) for p in parts]
    for i in range(k):
        add = min(room[i], int(extra * weights[i] / scale))
        parts[i] += add
        room[i] -= add
    rest = total - sum(parts)
    i = 0
    while rest > 0:  # reliquat des arrondis, sans dépasser le maximum si possible
        slot = i % k
        if room[slot] > 0 or all(r <= 0 for r in room):
            parts[slot] += 1
            room[slot] -= 1
            rest -= 1
        i += 1
    rng.shuffle(parts)
    return parts


def split_lengths(total: int, low: int, high: int, rng: random.Random) -> list[int]:
    """Découpe `total` images en extraits de `low` à `high` images, de somme exacte."""
    if total <= 0:
        return []
    low, high = max(1, low), max(1, low, high)
    if total < 2 * low:
        return [total]  # trop court pour deux extraits d'au moins la durée minimale
    parts = [rng.randint(low, min(high, total - low))]  # au moins deux extraits
    rest = total - parts[0]
    while True:
        n = rng.randint(low, high)
        if n >= rest:
            break
        parts.append(n)
        rest -= n
    if rest >= low:
        return [*parts, rest]
    pool = rest  # reste trop court : on le fond avec les derniers extraits puis on redécoupe
    while parts:
        pool += parts.pop()
        k = _feasible(pool, low, high)
        if k is not None:
            return parts + _distribute(pool, k, low, high, rng)
    k = max(1, round(total / ((low + high) / 2)))  # bornes trop serrées : au plus près
    return _distribute(total, k, low, high, rng)


def _adjacent(a: Piece, b: Piece) -> bool:
    return a.source == b.source and abs(a.index - b.index) == 1


def _conflicts(order: list[Piece]) -> int:
    return sum(_adjacent(order[i - 1], order[i]) for i in range(1, len(order)))


def shuffle(pieces: list[Piece], rng: random.Random, no_adjacent: bool) -> list[Piece]:
    """Ordre aléatoire ; avec `no_adjacent`, évite deux extraits voisins dans leur source."""
    best = list(pieces)
    rng.shuffle(best)
    if not no_adjacent:
        return best
    for _attempt in range(50):
        if _conflicts(best) == 0:
            break
        rest = list(pieces)
        rng.shuffle(rest)
        order: list[Piece] = []
        while rest:  # tirage pas à pas parmi les extraits qui ne touchent pas le précédent
            fits = [p for p in rest if not order or not _adjacent(order[-1], p)]
            chosen = rng.choice(fits or rest)
            rest.remove(chosen)
            order.append(chosen)
        if _conflicts(order) < _conflicts(best):
            best = order
    return best  # sans ordre parfait (une seule source très courte), le moins de voisins


def plan(lengths: list[int], fps: int, settings: Settings,
         whole: list[bool] | None = None) -> list[Item]:
    """Résultat du mélange pour des clips de `lengths` images (même tirage → même résultat).

    Les sources marquées dans `whole` (timelapses) restent d'un seul tenant."""
    rng = random.Random(settings.seed)
    low = max(1, round(settings.min_seconds * fps))
    high = max(low, round(settings.max_seconds * fps))
    pieces = []
    for source, total in enumerate(lengths):
        offset = 0
        parts = [total] if whole and whole[source] else split_lengths(total, low, high, rng)
        for index, length in enumerate(parts):
            pieces.append(Piece(source, index, offset, length))
            offset += length
    order = shuffle(pieces, rng, settings.no_adjacent)
    fade = max(1, round(settings.fade_seconds * fps))
    burst = max(2, round(settings.burst_seconds * fps))
    kinds = {"fade": ("fade",), "burst": ("burst",), "mix": ("fade", "burst")}.get(
        settings.transition, ())
    items = [Item(piece, piece.length) for piece in order]
    for item, following in pairwise(items):
        allowed = [k for k in kinds
                   if item.length >= round((FADE_MIN if k == "fade" else BURST_MIN) * fps)]
        if not allowed or rng.random() >= settings.probability:
            continue
        item.after = rng.choice(allowed)
        if item.after == "fade":
            color = settings.fade_color
            item.color = rng.choice(("black", "white")) if color == "mix" else color
            item.fade_out = min(fade, item.length // 2)
            following.fade_in = min(fade, following.length // 2)
            following.fade_in_color = item.color
        else:  # montée courte avant la coupe, retombée plus longue après
            attack = max(1, round(burst * BURST_ATTACK))
            item.burst_out = min(attack, item.length // 2)
            following.burst_in = min(max(1, burst - attack), following.length // 2)
    return items


def covers(lengths: list[int], items: list[Item]) -> bool:
    """Chaque image de chaque source est dans exactement un extrait."""
    for source, total in enumerate(lengths):
        spans = sorted((i.piece.offset, i.piece.length) for i in items
                       if i.piece.source == source)
        position = 0
        for offset, length in spans:
            if offset != position or length <= 0:
                return False
            position += length
        if position != total:
            return False
    return True


# --- timeline -------------------------------------------------------------------------------

def group_of(clip: Clip | None) -> dict | None:
    """Réglages du groupe Mix Flash du clip, ou None si le clip n'en fait pas partie."""
    data = clip.modules.get(MODULE_ID) if clip is not None else None
    return data if isinstance(data, dict) and data.get("group") else None


def eligible(timeline, clip: Clip) -> bool:
    """Clip d'image (vidéo ou photo) d'une piste vidéo, que le Mix Flash peut mélanger."""
    if clip.is_text:
        return False
    media = timeline.media_of(clip)
    return (media is not None and media.kind in ("video", "image")
            and timeline.track(clip.track_id).kind == "video")


def kept_whole(timeline, clip: Clip) -> bool:
    """Clip dont un module fige la durée (timelapse) : déplacé d'un bloc, jamais découpé."""
    return timeline.timing_locked(clip)


def candidates(timeline, clip: Clip) -> list[Clip]:
    """Clips de la piste de `clip` que l'on peut mélanger, dans l'ordre de la piste."""
    return [c for c in timeline.clips_on(clip.track_id) if eligible(timeline, c)]


def kind_of(timeline, clip: Clip) -> str:
    """Nature du clip, affichée dans la fenêtre : "video", "image", "timelapse", "mixed"."""
    if kept_whole(timeline, clip):
        return "timelapse"
    if group_of(clip) is not None:
        return "mixed"
    return timeline.media_of(clip).kind


_NESTED = {"transform": Transform, "color": ColorAdjust, "effects": Effects,
           "audio": AudioAdjust, "grade": Grade, "text": TextStyle}


def _build(cls, data: dict):
    known = {f.name for f in fields(cls)}
    values = {}
    for key, value in data.items():
        if key in known:
            nested = _NESTED.get(key) if cls is Clip else None
            values[key] = _build(nested, value) if nested and isinstance(value, dict) else value
    return cls(**copy.deepcopy(values))


def _source_in(clip: Clip, offset: int, length: int) -> int:
    if clip.reverse:  # la plage est lue à l'envers : la fin du clip est le début du média
        return clip.source_in + round((clip.duration - offset - length) * clip.speed)
    return clip.source_in + round(offset * clip.speed)


def _piece_clip(src: Clip, item: Item, start: int, record: dict) -> Clip:
    piece = item.piece
    clip = copy.deepcopy(src)
    clip.id = new_id()
    clip.start, clip.duration = start, item.length
    clip.source_in = _source_in(src, piece.offset, piece.length)
    clip.volume, clip.fade_in, clip.fade_out = 0.0, 0, 0
    clip.keyframes = {}
    clip.modules.pop(MODULE_ID, None)
    clip.modules[MODULE_ID] = {**record, "role": "piece", "color": item.color or "black",
                               "fade_in_color": item.fade_in_color or "black",
                               "fade_in": item.fade_in, "fade_out": item.fade_out,
                               "burst_in": item.burst_in, "burst_out": item.burst_out,
                               "length": item.length, "full": False}
    return clip


def apply(timeline, clip_ids: list[str], settings: Settings) -> list[Clip]:
    """Remplace les clips par leurs extraits mélangés (à utiliser dans `editor.edit`)."""
    clips = sorted((timeline.clip(i) for i in clip_ids), key=lambda c: c.start)
    if not clips:
        raise TimelineError("aucun clip à mélanger")
    track_id = clips[0].track_id
    for c in clips:
        if c.track_id != track_id or not eligible(timeline, c):
            raise TimelineError("les clips doivent être des vidéos de la même piste")
    if settings.sound == "detach":
        for c in clips:
            media = timeline.media_of(c)
            # son déjà détaché : volume nul ; un timelapse garde son propre réglage du son
            if media.has_audio and c.volume > 0 and not kept_whole(timeline, c):
                timeline.detach_audio(c.id)
    sources = [copy.deepcopy(c) for c in clips]
    for source in sources:  # un extrait d'un mélange précédent redevient un clip ordinaire
        source.modules.pop(MODULE_ID, None)
    lengths = [c.duration for c in sources]
    items = plan(lengths, timeline.fps, settings, [kept_whole(timeline, c) for c in clips])
    if not covers(lengths, items):
        raise TimelineError("le découpage ne couvre pas toutes les images")
    anchor = clips[0].start
    for c in reversed(clips):  # retire les clips et referme leur place
        timeline.delete(c.id, ripple=True)
    total = sum(i.length for i in items)
    timeline.shift_after(track_id, anchor, total)
    record = {"group": new_id(), "settings": asdict(settings),
              "originals": [asdict(c) for c in sources]}
    created: list[Clip] = []
    position = anchor
    for item in items:
        clip = _piece_clip(sources[item.piece.source], item, position, record)
        timeline.project.clips.append(clip)
        created.append(clip)
        position += item.length
    return created


def members(timeline, clip: Clip) -> list[Clip]:
    data = group_of(clip)
    if data is None:
        return []
    return sorted((c for c in timeline.project.clips
                   if (group_of(c) or {}).get("group") == data["group"]),
                  key=lambda c: c.start)


def restore(timeline, clip_id: str) -> list[Clip]:
    """Retire les extraits du groupe et remet les clips d'origine à leur place."""
    clip = timeline.clip(clip_id)
    data = group_of(clip)
    if data is None:
        raise TimelineError("ce clip ne fait pas partie d'un Mix Flash")
    group = members(timeline, clip)
    track_id = group[0].track_id
    anchor = group[0].start
    end = max(c.end for c in group if c.track_id == track_id)
    for c in group:
        timeline.delete(c.id)
    originals = [_build(Clip, d) for d in data.get("originals", [])]
    length = sum(c.duration for c in originals)
    timeline.shift_after(track_id, end, length - (end - anchor))
    position = anchor
    for original in originals:
        original.track_id, original.start = track_id, position
        if any(c.id == original.id for c in timeline.project.clips):
            original.id = new_id()
        timeline.project.clips.append(original)
        position += original.duration
    return originals


def remix(timeline, clip_id: str, settings: Settings) -> list[Clip]:
    """Nouveau mélange du groupe, à partir des clips d'origine."""
    originals = restore(timeline, clip_id)
    return apply(timeline, [c.id for c in originals], settings)
