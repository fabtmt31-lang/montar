#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Icône Windows (.ico, plusieurs tailles en PNG) à partir de l'icône SVG de montar.

    python scripts/windows/make_icon.py SORTIE.ico
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png(size: int) -> bytes:
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(ROOT / "src/montar/assets/montar.svg")).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def ico(images: list[tuple[int, bytes]]) -> bytes:
    """Format ICO : en-tête, une entrée par taille, puis les images PNG."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        side = 0 if size >= 256 else size  # 0 signifie 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - nécessaire au rendu
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "montar.ico")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ico([(s, png(s)) for s in SIZES]))
    print(f"icône écrite : {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
