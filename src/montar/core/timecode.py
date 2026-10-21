# SPDX-License-Identifier: GPL-3.0-or-later
"""Conversion entre numéros d'image et timecodes."""
from __future__ import annotations


def frames_to_timecode(frame: int, fps: float) -> str:
    """Timecode « hh:mm:ss:ii » (ii = image dans la seconde)."""
    fps_i = max(1, round(fps))
    frame = max(0, int(frame))
    seconds, ff = divmod(frame, fps_i)
    hh, rem = divmod(seconds, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def seconds_to_short(seconds: float) -> str:
    """Durée courte pour les vignettes : « 0:48 », « 12:35 », « 1:02:03 »."""
    total = max(0, int(round(seconds)))
    hh, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    if hh:
        return f"{hh}:{mm:02d}:{ss:02d}"
    return f"{mm}:{ss:02d}"
