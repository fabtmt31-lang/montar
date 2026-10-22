# SPDX-License-Identifier: GPL-3.0-or-later
"""Petites images écrites sans dépendance : PNG (fonds) et PGM (motifs de transition)."""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) == 8:  # #AARRGGBB : la transparence est ignorée
        value = value[2:]
    if len(value) != 6:
        raise ValueError(f"couleur invalide : {color}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> bytes:
    return bytes(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def write_png(path: Path, width: int, height: int, top: str, bottom: str | None = None,
              direction: str = "vertical") -> None:
    """Fond uni (`bottom` absent) ou dégradé linéaire vertical / horizontal."""
    a = rgb(top)
    b = rgb(bottom) if bottom else a
    if direction == "horizontal":
        row = b"".join(_mix(a, b, x / max(1, width - 1)) for x in range(width))
        rows = [row] * height
    else:
        rows = [_mix(a, b, y / max(1, height - 1)) * width for y in range(height)]
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(png)
    tmp.replace(path)


def write_luma(path: Path, shape: str, width: int = 320, height: int = 180) -> Path:
    """Motif de la transition MLT « luma » : les zones sombres passent en premier."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    radius = math.hypot(cx, cy)
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            if shape == "circle":
                v = math.hypot(x - cx, y - cy) / radius
            elif shape == "down":
                v = y / (height - 1)
            elif shape == "up":
                v = 1 - y / (height - 1)
            else:  # diagonale, du coin haut gauche
                v = (x / (width - 1) + y / (height - 1)) / 2
            pixels.append(round(255 * v))
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(f"P5 {width} {height} 255\n".encode() + bytes(pixels))
    tmp.replace(path)
    return path
