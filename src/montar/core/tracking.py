# SPDX-License-Identifier: GPL-3.0-or-later
"""Suivi de mouvement : un rectangle choisi sur la première image est retrouvé image après
image par corrélation croisée normalisée (calcul par FFT, NumPy), dans une fenêtre autour
de la position précédente. Le modèle s'adapte lentement (changements de lumière, de forme).

Les positions sont données en fractions de l'image (0 à 1), centre du rectangle."""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass

ANALYSIS_WIDTH = 480  # largeur des images analysées
LOST = 0.35  # en dessous de ce score, l'objet est considéré perdu (position gardée)
ADAPT = 0.12  # part de l'image courante intégrée au modèle à chaque image sûre


class TrackingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Point:
    frame: int  # image relative au début du suivi
    x: float  # centre, en fraction de la largeur
    y: float
    score: float  # confiance (corrélation, de -1 à 1)


def read_frames(source: str, start: float, duration: float, fps: float,
                width: int = ANALYSIS_WIDTH) -> Iterator:
    """Images en niveaux de gris (tableaux NumPy) du passage, à `fps` images par seconde."""
    import numpy as np

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TrackingError("ffmpeg est introuvable")
    probe = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-i", source,
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "rawvideo",
                            "-pix_fmt", "gray", "-"], capture_output=True, timeout=60)
    if probe.returncode != 0 or not probe.stdout:
        raise TrackingError("image illisible")
    height = len(probe.stdout) // width
    process = subprocess.Popen(
        [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", source,
         "-vf", f"fps={fps:.6f},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "gray",
         "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width * height
    try:
        assert process.stdout is not None
        while True:
            data = process.stdout.read(size)
            if len(data) < size:
                break
            yield np.frombuffer(data, dtype=np.uint8).reshape(height, width).astype(np.float32)
    finally:
        process.kill()
        process.wait()


def _local_sums(image, th: int, tw: int):
    """Sommes sur toutes les fenêtres th × tw (images intégrales)."""
    import numpy as np

    s = np.pad(image, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return s[th:, tw:] - s[:-th, tw:] - s[th:, :-tw] + s[:-th, :-tw]


def match(region, template):
    """Carte de corrélation normalisée (positions valides) et position du maximum."""
    import numpy as np

    th, tw = template.shape
    rh, rw = region.shape
    t = template - template.mean()
    t_norm = float(np.sqrt((t * t).sum())) or 1.0
    shape = (rh + th, rw + tw)
    corr = np.fft.irfft2(np.fft.rfft2(region, shape) * np.fft.rfft2(t[::-1, ::-1], shape),
                         shape)[th - 1:rh, tw - 1:rw]
    n = th * tw
    sums = _local_sums(region, th, tw)
    squares = _local_sums(region * region, th, tw)
    variance = np.maximum(squares - sums * sums / n, 1e-6)
    score = corr / (np.sqrt(variance) * t_norm)
    best = np.unravel_index(int(np.argmax(score)), score.shape)
    return score, (int(best[0]), int(best[1])), float(score[best])


def track(frames: Iterator, rect: tuple[float, float, float, float],
          progress: Callable[[float], None] = lambda r: None,
          cancelled: Callable[[], bool] = lambda: False, total: int = 0) -> list[Point]:
    """Suit `rect` (x, y, largeur, hauteur en fractions de l'image, sur la première image)."""
    points: list[Point] = []
    template = None
    for index, frame in enumerate(frames):
        if cancelled():
            raise TrackingError("annulé")
        h, w = frame.shape
        if template is None:
            tw = max(8, round(rect[2] * w))
            th = max(8, round(rect[3] * h))
            left = min(max(0, round(rect[0] * w)), w - tw)
            top = min(max(0, round(rect[1] * h)), h - th)
            cx0, cy0 = left + tw / 2, top + th / 2
            template = frame[top:top + th, left:left + tw].copy()
            # zone presque uniforme (rien à reconnaître) : agrandie pour prendre les bords
            while template.std() < 3 and tw < w // 2 and th < h // 2:
                tw, th = min(w, round(tw * 1.4)), min(h, round(th * 1.4))
                left = int(min(max(0, cx0 - tw / 2), w - tw))
                top = int(min(max(0, cy0 - th / 2), h - th))
                template = frame[top:top + th, left:left + tw].copy()
            points.append(Point(0, (left + tw / 2) / w, (top + th / 2) / h, 1.0))
            continue
        th, tw = template.shape
        radius = max(12, round(0.6 * max(th, tw)))
        cx, cy = points[-1].x * w, points[-1].y * h
        x0 = int(max(0, min(w - tw, cx - tw / 2 - radius)))
        y0 = int(max(0, min(h - th, cy - th / 2 - radius)))
        x1 = int(min(w, max(x0 + tw, cx + tw / 2 + radius)))
        y1 = int(min(h, max(y0 + th, cy + th / 2 + radius)))
        _score, (dy, dx), best = match(frame[y0:y1, x0:x1], template)
        if best < LOST:  # perdu : on garde la dernière position
            points.append(Point(index, points[-1].x, points[-1].y, best))
        else:
            top, left = y0 + dy, x0 + dx
            patch = frame[top:top + th, left:left + tw]
            template = (1 - ADAPT) * template + ADAPT * patch
            points.append(Point(index, (left + tw / 2) / w, (top + th / 2) / h, best))
        if total:
            progress(min(1.0, index / total))
    if not points:
        raise TrackingError("aucune image à analyser")
    return points


def smooth(points: list[Point], radius: int = 2) -> list[Point]:
    """Moyenne glissante des positions : moins de tremblement."""
    result = []
    for i, p in enumerate(points):
        window = points[max(0, i - radius):i + radius + 1]
        result.append(Point(p.frame, sum(q.x for q in window) / len(window),
                            sum(q.y for q in window) / len(window), p.score))
    return result


def simplify(points: list[Point], step: int = 2) -> list[Point]:
    """Une position toutes les `step` images (plus la dernière) : moins de clés."""
    if not points:
        return []
    kept = points[::step]
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept
