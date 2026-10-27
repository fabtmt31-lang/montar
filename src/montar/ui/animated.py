# SPDX-License-Identifier: GPL-3.0-or-later
"""Effets animés du panneau Éléments (éclairs, explosion, confettis…).

Chaque effet est dessiné image par image avec QPainter sur un fond transparent, puis
encodé par ffmpeg en vidéo MOV avec couche alpha (QuickTime Animation) : placé sur une
piste au-dessus de la vidéo, il s'y superpose. Le tirage aléatoire est fixé pour que le
rendu soit toujours le même."""
from __future__ import annotations

import math
import random
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from montar.i18n import N_

Draw = Callable[[QPainter, float, float, float], None]  # (peintre, largeur, hauteur, t ∈ [0, 1])


@dataclass(frozen=True)
class AnimatedEffect:
    id: str
    name: str
    seconds: float
    draw: Draw
    thumb_at: float = 0.4  # instant montré dans la vignette


def _rng(seed: str) -> random.Random:
    return random.Random(seed)


def _glow(p: QPainter, path: QPainterPath, color: QColor, width: float) -> None:
    """Trait lumineux : halo large et transparent puis cœur blanc."""
    for k, alpha in ((6.0, 0.10), (3.2, 0.22), (1.6, 0.5)):
        c = QColor(color)
        c.setAlphaF(c.alphaF() * alpha)
        p.setPen(QPen(c, width * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    p.setPen(QPen(QColor(255, 255, 255, round(255 * color.alphaF())), width,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)


def _bolt(rng: random.Random, x0: float, y0: float, x1: float, y1: float,
          roughness: float) -> QPainterPath:
    points = [(x0, y0), (x1, y1)]
    offset = roughness
    for _ in range(6):  # milieux décalés au hasard : trajet en zigzag
        out = [points[0]]
        for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
            mx, my = (ax + bx) / 2, (ay + by) / 2
            nx, ny = -(by - ay), bx - ax
            n = math.hypot(nx, ny) or 1
            d = rng.uniform(-offset, offset)
            out += [(mx + nx / n * d, my + ny / n * d), (bx, by)]
        points, offset = out, offset / 2
    path = QPainterPath(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    return path


def _lightning(p: QPainter, w: float, h: float, t: float) -> None:
    flashes = (0.05, 0.32, 0.58)  # trois éclairs
    for i, start in enumerate(flashes):
        local = (t - start) / 0.16
        if not 0 <= local <= 1:
            continue
        rng = _rng(f"eclair{i}")
        alpha = 1.0 if local < 0.35 else max(0.0, 1 - (local - 0.35) / 0.65)
        if 0.2 < local < 0.3:
            alpha *= 0.35  # scintillement
        x0 = w * rng.uniform(0.25, 0.75)
        x1 = x0 + w * rng.uniform(-0.25, 0.25)
        color = QColor(150, 190, 255)
        color.setAlphaF(alpha)
        main = _bolt(rng, x0, -h * 0.05, x1, h * rng.uniform(0.7, 1.0), w * 0.06)
        _glow(p, main, color, max(2.0, w * 0.004))
        for _ in range(2):  # ramifications
            fx = x0 + (x1 - x0) * rng.uniform(0.3, 0.6)
            fy = h * rng.uniform(0.25, 0.5)
            branch = _bolt(rng, fx, fy, fx + w * rng.uniform(-0.18, 0.18),
                           fy + h * rng.uniform(0.15, 0.3), w * 0.03)
            _glow(p, branch, color, max(1.0, w * 0.002))
        if local < 0.3:  # lueur sur toute l'image
            p.fillRect(QRectF(0, 0, w, h), QColor(200, 220, 255, round(40 * alpha)))


def _explosion(p: QPainter, w: float, h: float, t: float) -> None:
    cx, cy, size = w / 2, h / 2, min(w, h)
    grow = 1 - (1 - min(1.0, t / 0.5)) ** 3
    fade = max(0.0, 1 - max(0.0, t - 0.35) / 0.65)
    # fumée
    smoke = QRadialGradient(cx, cy, size * 0.55 * grow + 1)
    smoke.setColorAt(0, QColor(60, 50, 45, round(150 * fade)))
    smoke.setColorAt(1, QColor(60, 50, 45, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(smoke))
    p.drawEllipse(QPointF(cx, cy), size * 0.55 * grow + 1, size * 0.55 * grow + 1)
    # boule de feu
    core = max(0.0, 1 - t / 0.55)
    radius = size * 0.35 * grow + 1
    fire = QRadialGradient(cx, cy, radius)
    fire.setColorAt(0, QColor(255, 250, 210, round(255 * core)))
    fire.setColorAt(0.35, QColor(255, 190, 60, round(240 * core)))
    fire.setColorAt(0.75, QColor(235, 80, 20, round(170 * core)))
    fire.setColorAt(1, QColor(180, 30, 10, 0))
    p.setBrush(QBrush(fire))
    p.drawEllipse(QPointF(cx, cy), radius, radius)
    # étincelles
    rng = _rng("explosion")
    for _ in range(70):
        angle = rng.uniform(0, 2 * math.pi)
        speed = rng.uniform(0.25, 0.75) * size
        life = rng.uniform(0.45, 1.0)
        if t > life:
            continue
        k = t / life
        d = speed * (1 - (1 - k) ** 2)
        x, y = cx + math.cos(angle) * d, cy + math.sin(angle) * d + size * 0.15 * k * k
        c = QColor(255, rng.randint(150, 230), 60, round(255 * (1 - k)))
        p.setBrush(c)
        r = max(1.0, size * 0.008 * (1 - k * 0.6))
        p.drawEllipse(QPointF(x, y), r, r)


def _energy(p: QPainter, w: float, h: float, t: float) -> None:
    cx, cy, size = w / 2, h / 2, min(w, h)
    for delay in (0.0, 0.18, 0.36):
        k = (t - delay) / 0.6
        if not 0 <= k <= 1:
            continue
        r = size * 0.05 + size * 0.6 * (1 - (1 - k) ** 2)
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), r, r)
        color = QColor(90, 230, 255)
        color.setAlphaF(1 - k)
        p.setBrush(Qt.BrushStyle.NoBrush)
        _glow(p, path, color, max(1.5, size * 0.006 * (1 - k)))


def _confetti(p: QPainter, w: float, h: float, t: float) -> None:
    rng = _rng("confettis")
    colors = ("#F7C948", "#E4572E", "#2F7A56", "#4FB3F6", "#FF7AB6", "#C8F560")
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(140):
        x = rng.uniform(0, w)
        delay = rng.uniform(0, 0.5)
        speed = rng.uniform(0.8, 1.5)
        k = (t - delay) * speed
        if k <= 0:
            continue
        y = -h * 0.05 + k * h * 1.1
        if y > h * 1.05:
            continue
        x += math.sin(k * 8 + x) * w * 0.015
        size = rng.uniform(0.012, 0.022) * w
        p.save()
        p.translate(x, y)
        p.rotate(rng.uniform(0, 360) + k * 540)
        p.scale(1.0, abs(math.cos(k * 10 + x)))  # papier qui tourne sur lui-même
        p.setBrush(QColor(rng.choice(colors)))
        p.drawRect(QRectF(-size / 2, -size / 4, size, size / 2))
        p.restore()


def _star(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(8):
        a = i * math.pi / 4 - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.22
        point = QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr)
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


def _sparkles(p: QPainter, w: float, h: float, t: float) -> None:
    rng = _rng("etincelles")
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(40):
        x, y = rng.uniform(0.05, 0.95) * w, rng.uniform(0.05, 0.95) * h
        phase, rate = rng.uniform(0, 1), rng.uniform(1.0, 2.5)
        k = math.sin(math.pi * ((t * rate + phase) % 1.0))
        r = min(w, h) * rng.uniform(0.018, 0.04) * k
        if r < 0.5:
            continue
        halo = QRadialGradient(x, y, r * 2.2)
        halo.setColorAt(0, QColor(255, 240, 180, round(140 * k)))
        halo.setColorAt(1, QColor(255, 240, 180, 0))
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(x, y), r * 2.2, r * 2.2)
        p.setBrush(QColor(255, 255, 240, round(255 * k)))
        p.drawPath(_star(x, y, r))


def _fireworks(p: QPainter, w: float, h: float, t: float) -> None:
    bursts = ((0.0, 0.3, 0.3, "#FF7AB6"), (0.2, 0.7, 0.25, "#F7C948"),
              (0.42, 0.5, 0.4, "#4FB3F6"))
    p.setPen(Qt.PenStyle.NoPen)
    size = min(w, h)
    for i, (start, bx, by, color) in enumerate(bursts):
        k = (t - start) / 0.55
        if not 0 <= k <= 1:
            continue
        rng = _rng(f"feu{i}")
        cx, cy = bx * w, by * h
        for j in range(48):
            angle = j * 2 * math.pi / 48 + rng.uniform(-0.05, 0.05)
            speed = size * rng.uniform(0.22, 0.3)
            d = speed * (1 - (1 - k) ** 2)
            x = cx + math.cos(angle) * d
            y = cy + math.sin(angle) * d + size * 0.12 * k * k  # pesanteur
            c = QColor(color)
            c.setAlphaF(max(0.0, 1 - k ** 1.5))
            p.setBrush(c)
            r = size * 0.011
            p.drawEllipse(QPointF(x, y), r, r)
            trail = QColor(c)
            trail.setAlphaF(c.alphaF() * 0.35)
            p.setBrush(trail)
            p.drawEllipse(QPointF(x - math.cos(angle) * r * 3, y - math.sin(angle) * r * 3),
                          r * 0.7, r * 0.7)


def _heart(cx: float, cy: float, s: float) -> QPainterPath:
    path = QPainterPath(QPointF(cx, cy + s * 0.35))
    path.cubicTo(cx - s * 0.9, cy - s * 0.25, cx - s * 0.45, cy - s * 0.9, cx, cy - s * 0.4)
    path.cubicTo(cx + s * 0.45, cy - s * 0.9, cx + s * 0.9, cy - s * 0.25, cx, cy + s * 0.35)
    return path


def _hearts(p: QPainter, w: float, h: float, t: float) -> None:
    rng = _rng("coeurs")
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(26):
        x = rng.uniform(0.05, 0.95) * w
        delay, speed = rng.uniform(0, 0.6), rng.uniform(0.7, 1.2)
        k = (t - delay) * speed / 0.8
        if not 0 < k < 1:
            continue
        y = h * (1.05 - k * 0.9)
        x += math.sin(k * 6 + x) * w * 0.02
        s = min(w, h) * rng.uniform(0.05, 0.09)
        c = QColor(rng.choice(("#FF4F7B", "#FF7AB6", "#E4572E")))
        c.setAlphaF(min(1.0, (1 - k) * 1.6))
        p.setBrush(c)
        p.drawPath(_heart(x, y, s))


def _snow(p: QPainter, w: float, h: float, t: float) -> None:
    rng = _rng("neige")
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(160):
        x0, y0 = rng.uniform(0, w), rng.uniform(-h, h)
        speed, r = rng.uniform(0.25, 0.6), min(w, h) * rng.uniform(0.003, 0.009)
        y = (y0 + t * speed * h * 2) % (h * 1.1) - h * 0.05
        x = x0 + math.sin(t * 6 + x0) * w * 0.01
        p.setBrush(QColor(255, 255, 255, round(rng.uniform(150, 240))))
        p.drawEllipse(QPointF(x, y), r, r)


def _brush(p: QPainter, w: float, h: float, t: float) -> None:
    """Coup de pinceau jaune qui se dessine de gauche à droite, puis s'efface."""
    rng = _rng("pinceau")
    reveal = min(1.0, t / 0.35)
    reveal = 1 - (1 - reveal) ** 3
    fade = max(0.0, 1 - max(0.0, t - 0.8) / 0.2)
    left, right = w * 0.12, w * 0.88
    top, bottom = h * 0.42, h * 0.58
    end = left + (right - left) * reveal
    path = QPainterPath(QPointF(left, top))
    steps = 40
    for i in range(steps + 1):  # bord du haut, irrégulier
        x = left + (end - left) * i / steps
        path.lineTo(x, top + rng.uniform(-1, 1) * h * 0.012)
    for i in range(steps + 1):  # bord du bas
        x = end - (end - left) * i / steps
        path.lineTo(x, bottom + rng.uniform(-1, 1) * h * 0.012)
    path.closeSubpath()
    c = QColor("#F7C948")
    c.setAlphaF(fade)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(path)
    for _ in range(14):  # traces de poils
        y = rng.uniform(top, bottom)
        streak = QColor(255, 255, 255, round(60 * fade))
        p.setPen(QPen(streak, h * 0.004))
        p.drawLine(QPointF(left, y), QPointF(left + (end - left) * rng.uniform(0.4, 1), y))


def _smoke(p: QPainter, w: float, h: float, t: float) -> None:
    rng = _rng("fumee")
    p.setPen(Qt.PenStyle.NoPen)
    size = min(w, h)
    for _ in range(22):
        x = w * rng.uniform(0.3, 0.7)
        delay = rng.uniform(0, 0.5)
        k = (t - delay) / 0.6
        if not 0 < k < 1:
            continue
        y = h * (0.85 - k * rng.uniform(0.4, 0.7))
        x += (k * rng.uniform(-0.2, 0.2)) * w
        r = size * (0.06 + 0.22 * k)
        g = QRadialGradient(x, y, r)
        shade = rng.randint(170, 220)
        g.setColorAt(0, QColor(shade, shade, shade, round(110 * (1 - k))))
        g.setColorAt(1, QColor(shade, shade, shade, 0))
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(x, y), r, r)


def _bubbles(p: QPainter, w: float, h: float, t: float) -> None:
    rng = _rng("bulles")
    size = min(w, h)
    for _ in range(36):
        x0 = rng.uniform(0.05, 0.95) * w
        delay, speed = rng.uniform(0, 0.5), rng.uniform(0.7, 1.3)
        k = (t - delay) * speed
        if not 0 < k < 1:
            continue
        y = h * (1.05 - k * 1.1)
        x = x0 + math.sin(k * 9 + x0) * w * 0.015
        r = size * rng.uniform(0.012, 0.035)
        p.setPen(QPen(QColor(255, 255, 255, 190), max(1.0, r * 0.12)))
        p.setBrush(QColor(170, 225, 255, 45))
        p.drawEllipse(QPointF(x, y), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawEllipse(QPointF(x - r * 0.35, y - r * 0.35), r * 0.2, r * 0.2)


def _light_leak(p: QPainter, w: float, h: float, t: float) -> None:
    """Lueur chaude qui traverse l'image (fuite de lumière de pellicule)."""
    x = -0.3 * w + t * 1.6 * w
    for cx, cy, r, color in ((x, h * 0.4, 0.55, (255, 150, 60)),
                             (x - 0.25 * w, h * 0.7, 0.4, (255, 90, 90)),
                             (x + 0.2 * w, h * 0.2, 0.35, (255, 220, 120))):
        g = QRadialGradient(cx, cy, r * w)
        g.setColorAt(0, QColor(*color, 150))
        g.setColorAt(1, QColor(*color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r * w, r * w)


EFFECTS: dict[str, AnimatedEffect] = {e.id: e for e in (
    AnimatedEffect("eclair", N_("Éclairs"), 2.5, _lightning, 0.08),
    AnimatedEffect("explosion", N_("Explosion"), 2.0, _explosion, 0.2),
    AnimatedEffect("onde", N_("Onde d'énergie"), 2.0, _energy, 0.3),
    AnimatedEffect("confettis", N_("Confettis"), 3.0, _confetti, 0.38),
    AnimatedEffect("etincelles", N_("Étincelles"), 3.0, _sparkles, 0.3),
    AnimatedEffect("feu_artifice", N_("Feu d'artifice"), 3.0, _fireworks, 0.28),
    AnimatedEffect("coeurs", N_("Cœurs"), 3.0, _hearts, 0.5),
    AnimatedEffect("neige", N_("Neige"), 4.0, _snow, 0.4),
    AnimatedEffect("pinceau", N_("Coup de pinceau"), 2.5, _brush, 0.5),
    AnimatedEffect("fumee", N_("Fumée"), 3.0, _smoke, 0.5),
    AnimatedEffect("bulles", N_("Bulles"), 3.0, _bubbles, 0.5),
    AnimatedEffect("lumiere", N_("Fuite de lumière"), 2.5, _light_leak, 0.35),
)}


def frame(effect: AnimatedEffect, width: int, height: int, t: float) -> QImage:
    """Image de l'effet à l'instant `t` (0 à 1), fond transparent."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    effect.draw(painter, float(width), float(height), max(0.0, min(1.0, t)))
    painter.end()
    return image


def thumbnail(effect: AnimatedEffect, size) -> QPixmap:
    """Vignette : l'effet sur un damier (la transparence se voit), comme dans les logiciels
    de montage."""
    w, h = size.width() * 2, size.height() * 2
    pm = QPixmap(w, h)
    pm.fill(QColor("#E9EDEA"))
    painter = QPainter(pm)
    step = 12
    for y in range(0, h, step):
        for x in range(0, w, step):
            if (x // step + y // step) % 2:
                painter.fillRect(x, y, step, step, QColor("#D5DBD7"))
    painter.fillRect(0, 0, w, h, QColor(23, 38, 30, 110))  # assombri : les effets clairs
    painter.drawImage(0, 0, frame(effect, w, h, effect.thumb_at))
    painter.end()
    return pm


class RenderJob:
    """Rendu d'un effet en vidéo MOV transparente, dans un fil (interface non bloquée).
    Mêmes attributs qu'un export : `progress`, `finished`, `error`, `cancelled`."""

    def __init__(self, effect: AnimatedEffect, size: tuple[int, int], fps: int,
                 target: Path) -> None:
        self.effect, self.size, self.fps, self.target = effect, size, fps, target
        self.total = max(2, round(effect.seconds * fps))
        self.done = 0
        self.finished = self.cancelled = False
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def progress(self) -> float:
        return 1.0 if self.finished and not self.error else self.done / self.total

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="montar-effet", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.finished

    def _run(self) -> None:
        w, h = self.size
        part = self.target.with_name(self.target.stem + ".part.mov")
        cmd = [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", "bgra", "-s", f"{w}x{h}", "-r", str(self.fps), "-i", "-",
               "-c:v", "qtrle", "-pix_fmt", "argb", str(part)]
        try:
            # erreurs dans un fichier : un tuyau plein bloquerait ffmpeg
            errors_file = tempfile.TemporaryFile()
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors_file)
            assert proc.stdin is not None
            try:
                for i in range(self.total):
                    if self._stop.is_set():
                        break
                    image = frame(self.effect, w, h, i / (self.total - 1)).convertToFormat(
                        QImage.Format.Format_ARGB32)  # BGRA en mémoire, alpha non prémultiplié
                    proc.stdin.write(image.constBits().asstring(image.sizeInBytes()))
                    self.done = i + 1
            finally:
                proc.stdin.close()
                proc.wait()
                errors_file.seek(0)
                errors = errors_file.read().decode(errors="replace")
                errors_file.close()
            if self._stop.is_set():
                self.cancelled, self.error = True, "annulé"
            elif proc.returncode != 0:
                self.error = errors.strip().splitlines()[-1] if errors.strip() else "ffmpeg"
            else:
                part.replace(self.target)
        except Exception as exc:  # jamais d'exception hors du fil
            self.error = str(exc)
        finally:
            if part.exists():
                part.unlink(missing_ok=True)
            self.finished = True
