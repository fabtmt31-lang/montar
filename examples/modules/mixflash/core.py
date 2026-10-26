# SPDX-License-Identifier: GPL-3.0-or-later
"""Mix Flash : découpe, mélange et application à la timeline (sans Qt, testable).

Les clips choisis d'une piste sont découpés en extraits de durée aléatoire, mélangés puis
replacés bout à bout à l'emplacement du premier. Chaque image des clips d'origine se
retrouve dans exactement un extrait (vérifié avant d'appliquer). Entre deux extraits, un
fondu au noir ou au blanc est possible après les extraits de 3 à 5 s : soit par-dessus les
images (durée inchangée), soit sous forme d'un flash de couleur inséré (rien n'est masqué).

Les réglages du groupe et les clips d'origine sont gardés dans `clip.modules["fab.mixflash"]`
de chaque extrait, pour remélanger ou revenir aux clips d'origine."""
from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, fields

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
FADE_ELIGIBLE = (3.0, 5.0)  # secondes : seuls les extraits de cette durée ont un fondu après eux
LIMITS = (0.5, 5.0)  # bornes des réglages de durée des extraits, en secondes
COLORS = {"none": "Aucun", "black": "Noir", "white": "Blanc", "mix": "Noir et blanc"}
MODES = {"insert": "Flash inséré", "over": "Par-dessus les images"}
SOUND = {"detach": "Détacher le son d'abord", "remove": "Supprimer le son"}


@dataclass
class Settings:
    min_seconds: float = 0.5
    max_seconds: float = 5.0
    fade_color: str = "mix"
    fade_mode: str = "insert"
    probability: float = 0.6  # chance d'un fondu après un extrait de 3 à 5 s
    fade_seconds: float = 0.4
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
        s.fade_color = s.fade_color if s.fade_color in COLORS else "mix"
        s.fade_mode = s.fade_mode if s.fade_mode in MODES else "insert"
        s.sound = s.sound if s.sound in SOUND else "detach"
        s.probability = max(0.0, min(1.0, s.probability))
        s.fade_seconds = max(0.1, min(1.0, s.fade_seconds))
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
    """Élément du résultat : un extrait, ou un flash de couleur (`piece` vaut alors None)."""

    piece: Piece | None
    length: int
    color: str = ""  # couleur du fondu (extrait) ou du flash
    fade_in: int = 0  # images en fondu « par-dessus » au début / à la fin de l'extrait
    fade_out: int = 0
    fade_in_color: str = ""


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
    if total <= high:
        return [total]  # clip plus court que le maximum : un seul extrait
    parts: list[int] = []
    rest = total
    while rest > high:
        n = rng.randint(low, high)
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


def plan(lengths: list[int], fps: int, settings: Settings) -> list[Item]:
    """Résultat du mélange pour des clips de `lengths` images (même tirage → même résultat)."""
    rng = random.Random(settings.seed)
    low = max(1, round(settings.min_seconds * fps))
    high = max(low, round(settings.max_seconds * fps))
    pieces = []
    for source, total in enumerate(lengths):
        offset = 0
        for index, length in enumerate(split_lengths(total, low, high, rng)):
            pieces.append(Piece(source, index, offset, length))
            offset += length
    order = shuffle(pieces, rng, settings.no_adjacent)
    lo, hi = (round(s * fps) for s in FADE_ELIGIBLE)
    fade = max(1, round(settings.fade_seconds * fps))
    items: list[Item] = []
    for i, piece in enumerate(order):
        item = Item(piece, piece.length)
        if items and items[-1].piece is not None and items[-1].color \
                and settings.fade_mode == "over":
            item.fade_in = min(fade, piece.length // 2)
            item.fade_in_color = items[-1].color
        items.append(item)
        last = i == len(order) - 1
        if last or settings.fade_color == "none" or not lo <= piece.length <= hi:
            continue
        if rng.random() >= settings.probability:
            continue
        color = settings.fade_color
        if color == "mix":
            color = rng.choice(("black", "white"))
        item.color = color
        if settings.fade_mode == "over":
            item.fade_out = min(fade, piece.length // 2)
        else:
            items.append(Item(None, fade, color))
    return items


def covers(lengths: list[int], items: list[Item]) -> bool:
    """Chaque image de chaque source est dans exactement un extrait."""
    for source, total in enumerate(lengths):
        spans = sorted((i.piece.offset, i.piece.length) for i in items
                       if i.piece is not None and i.piece.source == source)
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
    """Clip vidéo d'une piste vidéo, que le Mix Flash peut découper."""
    if clip.is_text or group_of(clip) is not None or timeline.timing_locked(clip):
        return False
    media = timeline.media_of(clip)
    return (media is not None and media.kind == "video"
            and timeline.track(clip.track_id).kind == "video")


def candidates(timeline, clip: Clip) -> list[Clip]:
    """Clips de la piste de `clip` que l'on peut mélanger, dans l'ordre de la piste."""
    return [c for c in timeline.clips_on(clip.track_id) if eligible(timeline, c)]


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
                               "length": item.length, "full": False}
    return clip


def _flash_clip(previous: Clip, item: Item, start: int, record: dict) -> Clip:
    """Aplat de couleur : quelques images de l'extrait précédent, recouvertes par la couleur."""
    return Clip(previous.media_id, previous.track_id, start, item.length,
                source_in=previous.source_in, speed=previous.speed, volume=0.0,
                transform=Transform(fit="stretch"),
                modules={MODULE_ID: {**record, "role": "flash", "color": item.color,
                                     "fade_in_color": item.color, "full": True,
                                     "fade_in": 0, "fade_out": 0, "length": item.length}})


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
            if media.has_audio and c.volume > 0:  # son déjà détaché : volume nul
                timeline.detach_audio(c.id)
    sources = [copy.deepcopy(c) for c in clips]
    lengths = [c.duration for c in sources]
    items = plan(lengths, timeline.fps, settings)
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
        if item.piece is not None:
            clip = _piece_clip(sources[item.piece.source], item, position, record)
        else:
            clip = _flash_clip(created[-1], item, position, record)
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
