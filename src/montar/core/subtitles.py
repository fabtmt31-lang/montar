# SPDX-License-Identifier: GPL-3.0-or-later
"""Sous-titres (F-TXT-05) : édition dans le projet, import et export au format SRT."""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from montar.core.project import Clip, Project, Subtitle, TextStyle

DEFAULT_SECONDS = 3
_TIME = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})")
_LINE = re.compile(rf"{_TIME.pattern}\s*-->\s*{_TIME.pattern}")


class SrtError(ValueError):
    pass


def ordered(project: Project) -> list[Subtitle]:
    return sorted(project.subtitles, key=lambda s: (s.start, s.end))


def at(project: Project, frame: int) -> Subtitle | None:
    return next((s for s in ordered(project) if s.start <= frame < s.end), None)


def add(project: Project, frame: int, text: str = "") -> Subtitle:
    """Nouveau sous-titre à `frame`, raccourci s'il atteint le suivant."""
    end = frame + DEFAULT_SECONDS * project.fps
    following = [s.start for s in project.subtitles if s.start > frame]
    if following:
        end = min(end, min(following))
    sub = Subtitle(frame, max(frame + 1, end), text)
    project.subtitles.append(sub)
    return sub


def find(project: Project, subtitle_id: str) -> Subtitle:
    for s in project.subtitles:
        if s.id == subtitle_id:
            return s
    raise KeyError(subtitle_id)


def set_bounds(sub: Subtitle, start: int | None = None, end: int | None = None) -> None:
    if start is not None:
        sub.start = max(0, start)
    if end is not None:
        sub.end = end
    sub.end = max(sub.start + 1, sub.end)


def _ms(frame: int, fps: int) -> int:
    return round(frame * 1000 / fps)


def _stamp(ms: int) -> str:
    h, rest = divmod(max(0, ms), 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(subtitles: list[Subtitle], fps: int, start: int = 0, end: int = 0) -> str:
    """Texte SRT ; `start` / `end` limitent à une partie (temps relatifs à `start`)."""
    blocks = []
    for sub in sorted(subtitles, key=lambda s: s.start):
        a, b = sub.start, sub.end
        if end:
            b = min(b, end)
        a = max(a, start)
        if b <= a or not sub.text.strip():
            continue
        blocks.append(f"{len(blocks) + 1}\n{_stamp(_ms(a - start, fps))} --> "
                      f"{_stamp(_ms(b - start, fps))}\n{sub.text.strip()}\n")
    return "\n".join(blocks)


def _frames(groups: tuple[str, ...], fps: int) -> int:
    h, m, s, ms = groups
    seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
    return round(seconds * fps)


def parse_srt(text: str, fps: int) -> list[Subtitle]:
    """Sous-titres d'un fichier SRT (numéros facultatifs, balises HTML retirées)."""
    result = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        index = next((i for i, line in enumerate(lines) if _LINE.search(line)), None)
        if index is None:
            continue
        g = _LINE.search(lines[index]).groups()
        start, end = _frames(g[:4], fps), _frames(g[4:], fps)
        content = re.sub(r"</?[^>]+>", "", "\n".join(lines[index + 1:])).strip()
        if content:
            result.append(Subtitle(start, max(start + 1, end), content))
    if text.strip() and not result:
        raise SrtError("aucun sous-titre reconnu")
    return result


def read_srt(path: Path, fps: int) -> list[Subtitle]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return parse_srt(raw.decode(encoding), fps)
        except UnicodeDecodeError:
            continue
    raise SrtError("encodage inconnu")


def text_clip(sub: Subtitle, style: TextStyle) -> Clip:
    """Clip de texte (non enregistré) qui affiche le sous-titre."""
    return Clip("", "", sub.start, sub.end - sub.start,
                text=replace(style, content=sub.text, animation_in="none",
                             animation_out="none"))
