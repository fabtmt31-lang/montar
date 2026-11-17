# SPDX-License-Identifier: GPL-3.0-or-later
"""Effet « Super 8 » : réglages, filtres MLT, calques dessinés, cadence et bruit de projecteur.

- Couleurs de la pellicule, douceur, grain, vignettage, scintillement et instabilité de
  l'image : filtres MLT ordinaires, instantanés.
- Poussières, cheveux et rayures, fuites de lumière, fenêtre de projection : petits calques
  dessinés avec NumPy en une fraction de seconde (boucles de quelques secondes), mis en
  cache et superposés par le filtre `watermark`.
- Cadence 18 images/s : copie de la vidéo préparée une fois par ffmpeg, en tâche de fond.
- Bruit de projecteur : fichier son synthétisé, posé sur une piste audio.

Comme le module « Pluie » : les images fixes sont des vidéos d'une image (sans le module
« gdk » de MLT, sous Windows, une image PNG superposée devient blanche) et la transition
« composite » est imposée (watermark utilise « affine » depuis MLT 7.24 environ)."""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MODULE_VERSION = 1  # change le nom des calques en cache si leur dessin évolue
COMPOSITE = "composite"
MAX_SIDE = 1280  # calques limités à cette taille (le moteur les met à l'échelle)
LEAK_SIDE = 320  # fuites de lumière : très floues, dessinées en petit
DUST_SIDE = 960  # poussières : dessinées un peu plus petit (calcul deux fois plus court)
DUST_SECONDS = 2  # boucle des poussières (tirées à chaque image : la boucle ne se voit pas)
LEAK_SECONDS = 12  # boucle des fuites de lumière
FILM_FPS = 18  # cadence des caméras Super 8

# Le style donne le caractère ; les curseurs l'ajustent : 50 % = valeur du style, 0 % = rien,
# 100 % = le double.
STYLES = {
    "vacances": dict(pellicule="kodachrome", usure=0.3, grain=0.45, poussieres=0.3,
                     fuites=0.2, scintillement=0.3, instabilite=0.3, vignettage=0.5,
                     douceur=0.35),
    "fane": dict(pellicule="fanee", usure=0.5, grain=0.55, poussieres=0.45, fuites=0.3,
                 scintillement=0.45, instabilite=0.4, vignettage=0.65, douceur=0.5),
    "abime": dict(pellicule="fanee", usure=0.9, grain=0.7, poussieres=0.85, fuites=0.55,
                  scintillement=0.7, instabilite=0.6, vignettage=0.8, douceur=0.6),
}
SLIDERS = ("usure", "grain", "poussieres", "fuites", "scintillement", "instabilite",
           "vignettage", "douceur")
WEAR = ("poussieres", "fuites", "scintillement", "instabilite")  # pilotés aussi par l'usure
STOCKS = ("kodachrome", "ektachrome", "fanee", "nb")
FRAMES = ("fenetre", "perfo", "entier")


@dataclass(frozen=True)
class Settings:
    """Réglages effectifs (0 … 1), une fois le style et les curseurs combinés."""

    pellicule: str = "kodachrome"
    cadre: str = "fenetre"
    grain: float = 0.45
    poussieres: float = 0.3
    fuites: float = 0.2
    scintillement: float = 0.3
    instabilite: float = 0.3
    vignettage: float = 0.5
    douceur: float = 0.35
    cadence: bool = False
    bobine: bool = False
    variante: int = 1

    @classmethod
    def from_values(cls, values: dict) -> Settings:
        style = STYLES.get(values.get("style"), STYLES["vacances"])

        def knob(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(values.get(key, 0.5))))
            except (TypeError, ValueError):
                return 0.5

        def level(key: str) -> float:
            v = style[key] * 2 * knob(key)
            if key in WEAR:
                v *= 2 * knob("usure")
            # arrondi à 5 % : le glisser d'un curseur ne redessine pas un calque par position
            return round(max(0.0, min(1.0, v)) * 20) / 20

        stock = values.get("pellicule", "auto")
        try:
            variante = max(1, min(99, int(values.get("variante", 1))))
        except (TypeError, ValueError):
            variante = 1
        frame = values.get("cadre", "fenetre")
        return cls(pellicule=stock if stock in STOCKS else style["pellicule"],
                   cadre=frame if frame in FRAMES else "fenetre",
                   **{k: level(k) for k in SLIDERS if k != "usure"},
                   cadence=bool(values.get("cadence", False)),
                   bobine=bool(values.get("bobine", False)), variante=variante)


# --- filtres instantanés ----------------------------------------------------------------------


def stock_filters(s: Settings) -> list[tuple[str, dict]]:
    """Couleurs de la pellicule."""
    if s.pellicule == "kodachrome":  # chaud, saturé, rouges profonds, noirs denses
        return [("avfilter.eq", {"av.saturation": 1.45, "av.contrast": 1.1,
                                 "av.gamma": 0.9}),
                ("avfilter.colorbalance", {"av.rm": 0.1, "av.gm": 0.02, "av.bm": -0.12,
                                           "av.rh": 0.06, "av.bh": -0.1})]
    if s.pellicule == "ektachrome":  # plus froid, ombres bleu-cyan, hautes lumières crème
        return [("avfilter.eq", {"av.saturation": 1.05, "av.contrast": 1.04}),
                ("avfilter.colorbalance", {"av.rs": -0.07, "av.gs": 0.03, "av.bs": 0.14,
                                           "av.rm": -0.04, "av.bm": 0.07,
                                           "av.rh": 0.04, "av.bh": -0.02})]
    if s.pellicule == "nb":  # Tri-X, contrasté, léger ton chaud du tirage
        return [("avfilter.eq", {"av.saturation": 0.0, "av.contrast": 1.25}),
                ("avfilter.colorbalance", {"av.rh": 0.03, "av.bh": -0.03})]
    # pellicule vieillie : le cyan a pâli, dominante magenta-orangée, noirs laiteux
    return [("avfilter.eq", {"av.saturation": 0.55, "av.contrast": 0.75}),
            ("avfilter.colorbalance", {"av.rm": 0.12, "av.gm": -0.08, "av.bm": -0.03,
                                       "av.rs": 0.06, "av.bs": 0.05, "av.gh": -0.03}),
            ("avfilter.colorlevels", {"av.romin": 0.14, "av.gomin": 0.08, "av.bomin": 0.12})]


def look_filters(s: Settings, height: int) -> list[tuple[str, dict]]:
    """Douceur de l'optique, scintillement et instabilité, grain, vignettage."""
    result = []
    if s.douceur > 0.001:
        result.append(("avfilter.gblur", {"av.sigma": round((0.5 + 2.6 * s.douceur)
                                                            * height / 720, 2)}))
    if s.scintillement > 0.001 or s.instabilite > 0.001:
        # filtre « oldfilm » de MLT : sauts verticaux de l'image et variations de lumière
        result.append(("oldfilm", {
            "delta": round(1 + 10 * s.instabilite * height / 720),
            "every": max(2, round(40 - 35 * s.instabilite)) if s.instabilite > 0.001 else 9999,
            "brightnessdelta_up": round(4 + 22 * s.scintillement),
            "brightnessdelta_down": round(4 + 26 * s.scintillement),
            "brightnessdelta_every": max(1, round(20 - 18 * s.scintillement))
            if s.scintillement > 0.001 else 9999,
            "unevendevelop_up": 0, "unevendevelop_down": 0}))
    if s.grain > 0.001:
        result.append(("avfilter.noise", {"av.alls": round(8 + 46 * s.grain),
                                          "av.allf": "t+u"}))
    if s.vignettage > 0.001:
        result.append(("avfilter.vignette", {"av.angle": round(0.25 + 0.7 * s.vignettage, 3)}))
    return result


def reel_filters(s: Settings, duration: int, fps: int) -> list[tuple[str, dict]]:
    """Début et fin de bobine : quelques images brûlées, orangées, surexposées."""
    if not s.bobine or duration < 6:
        return []
    n = max(3, min(round(0.6 * fps), duration // 3))
    last = duration - 1
    # (image, part de lumière orangée)
    points = [(0, 1.0), (max(1, n // 3), 0.6), (n, 0.0)]
    if last - n > n:
        points += [(last - n, 0.0), (last - max(1, n // 3), 0.6), (last, 1.0)]

    def anim(scale: float) -> str:
        return ";".join(f"{f}={a * scale:.3f}" for f, a in points)

    return [("lift_gamma_gain", {"lift_r": anim(0.9), "lift_g": anim(0.45),
                                 "lift_b": anim(0.12), "gain_r": anim(0.8),
                                 "gain_g": anim(0.3), "gain_b": anim(0.0),
                                 "in": 0, "out": last})]


# --- images fixes -----------------------------------------------------------------------------

# formats que le moteur ouvre comme de vraies images fixes ; les autres (WebP, GIF, BMP,
# TIFF…) sont ouverts comme une vidéo d'une image et disparaîtraient sous les calques
STILL_FORMATS = (".png", ".jpg", ".jpeg")


def still_image(cache_dir: Path, path: str) -> str:
    """Chemin d'une image que le moteur ouvre comme image fixe (copie PNG faite une fois)."""
    source = Path(path)
    if source.suffix.lower() in STILL_FORMATS:
        return path
    try:
        stat = source.stat()
    except OSError:
        return path
    target = cache_dir / "super8" / "images" / \
        f"{_key(str(source.resolve()), stat.st_mtime_ns, stat.st_size)}.png"
    if target.exists():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".part.png")
    done = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", path,
                           "-frames:v", "1", "-update", "1", str(tmp)],
                          capture_output=True, timeout=60)
    if done.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return path
    tmp.replace(target)
    return str(target)


# --- zone couverte par l'image du clip (comme le module « Pluie ») ---------------------------

FULL = (0.0, 0.0, 1.0, 1.0)
MAX_CROP = 0.45


def clip_area(cw: int, ch: int, mw: int, mh: int, transform=None) -> tuple:
    """Zone (x, y, largeur, hauteur, en fractions de la toile) qu'occupe l'image du clip là
    où le moteur applique les filtres : l'image recadrée, ajustée à la toile en gardant ses
    proportions, le reste étant transparent."""
    if not (cw and ch and mw and mh):
        return FULL

    def crop(name: str) -> float:
        try:
            return max(0.0, min(MAX_CROP, float(getattr(transform, name, 0.0) or 0.0)))
        except (TypeError, ValueError):
            return 0.0

    vw = mw * (1 - crop("crop_left") - crop("crop_right"))
    vh = mh * (1 - crop("crop_top") - crop("crop_bottom"))
    k = min(cw / vw, ch / vh)
    w, h = min(1.0, vw * k / cw), min(1.0, vh * k / ch)
    return (round((1 - w) / 2, 4), round((1 - h) / 2, 4), round(w, 4), round(h, 4))


def clip_frame(cw: int, ch: int, mw: int, mh: int, transform=None,
               placed: bool = False) -> tuple[tuple[int, int], tuple, float]:
    """Cadre que reçoivent les filtres du clip : (taille en pixels de la toile, zone de
    l'image dans ce cadre, hauteur de la toile / hauteur du cadre).

    Sans transformation, c'est la toile entière, l'image y étant ajustée entre des bandes
    transparentes. Si le clip est placé (déplacé, redimensionné, recadré, images clés,
    zoom…), le moteur donne aux filtres l'image seule, sans bandes."""
    area = clip_area(cw, ch, mw, mh, transform)
    if not placed or area == FULL:
        return (cw, ch), area, 1.0
    w, h = max(2, round(area[2] * cw)), max(2, round(area[3] * ch))
    return (w, h), FULL, round(ch / h, 4)


def layer_size(width: int, height: int, side: int = MAX_SIDE) -> tuple[int, int]:
    k = min(1.0, side / max(width, height, 1))
    return max(2, round(width * k / 2) * 2), max(2, round(height * k / 2) * 2)


def _box(area: tuple, w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0 = round(area[0] * w), round(area[1] * h)
    x1, y1 = round((area[0] + area[2]) * w), round((area[1] + area[3]) * h)
    return x0, y0, max(2, min(w, x1) - x0), max(2, min(h, y1) - y0)


def geometry(area: tuple) -> str:
    x, y, w, h = (100 * v for v in area)
    return f"{x:.3f}%/{y:.3f}%:{w:.3f}%x{h:.3f}%"


# --- écriture des calques -------------------------------------------------------------------


class Cancelled(Exception):
    pass


def _encoder(path: Path, fmt: str, w: int, h: int, fps: int, codec: list[str]):
    errors = tempfile.TemporaryFile()
    cmd = [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", fmt, "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", *codec, str(path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors), errors


def _finish(proc, errors) -> None:
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        code = proc.wait(timeout=120)
        if code != 0:
            errors.seek(0)
            lines = errors.read().decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else f"ffmpeg a échoué (code {code})")
    finally:
        errors.close()


def _abort(proc) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def write_video(path: Path, w: int, h: int, fps: int, frames) -> Path:
    """Calque transparent (RVBA) : une vidéo, même pour une image fixe (voir en tête)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("part-" + path.name)
    proc, errors = _encoder(tmp, "rgba", w, h, fps, ["-c:v", "qtrle", "-pix_fmt", "argb",
                                                    "-f", "mov"])
    try:
        for frame in frames:
            proc.stdin.write(frame.tobytes())
        _finish(proc, errors)
    except BaseException:
        _abort(proc)
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return path


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps([MODULE_VERSION, *parts]).encode()).hexdigest()[:16]


def _rgba(light, dark, w: int, h: int, color=(250, 244, 230)):
    """Calque RVBA : lumière (clair) et ombre (noir) ; alpha = somme des deux."""
    import numpy as np

    total = light + dark
    alpha = np.clip(total, 0, 1)
    white = light / np.maximum(total, 1e-6)
    out = np.empty((h, w, 4), np.uint8)
    for c in range(3):
        out[..., c] = (color[c] * white).astype(np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return out


# --- poussières, cheveux, rayures --------------------------------------------------------------


def _disc(layer, x: float, y: float, r: float, value: float) -> None:
    import numpy as np

    h, w = layer.shape
    x0, x1 = int(max(0, x - r - 1)), int(min(w, x + r + 2))
    y0, y1 = int(max(0, y - r - 1)), int(min(h, y + r + 2))
    if x1 <= x0 or y1 <= y0:
        return
    sx = np.arange(x0, x1)[None, :] - x
    sy = np.arange(y0, y1)[:, None] - y
    v = np.clip(r + 0.5 - np.hypot(sx, sy), 0, 1) * value  # bord lissé
    np.maximum(layer[y0:y1, x0:x1], v, out=layer[y0:y1, x0:x1])


def _stroke(layer, points, width: float, value: float) -> None:
    for (xa, ya), (xb, yb) in zip(points, points[1:], strict=False):
        n = max(2, int(abs(xb - xa) + abs(yb - ya)))
        for t in range(n + 1):
            f = t / n
            _disc(layer, xa + (xb - xa) * f, ya + (yb - ya) * f, width / 2, value)


def dust_layer(cache_dir: Path, s: Settings, width: int, height: int, area: tuple,
               fps: int) -> Path | None:
    """Poussières (une image sur l'autre), cheveux (quelques images), rayures (qui durent)."""
    if s.poussieres <= 0.001:
        return None
    w, h = layer_size(width, height, DUST_SIDE)
    bx, by, bw, bh = _box(area, w, h)
    key = _key(w, h, list(area), fps, s.poussieres, s.variante)
    path = cache_dir / "super8" / f"poussieres-{key}.mov"
    if path.exists():
        return path
    import numpy as np

    rng = random.Random(1000 + s.variante)
    n = max(2, DUST_SECONDS * fps)
    unit = h / 720
    k = s.poussieres
    scratches = [[rng.uniform(bx, bx + bw), rng.randrange(n), rng.randint(fps // 2, 3 * fps),
                  rng.uniform(0.25, 0.6)] for _ in range(round(1 + 4 * k))]

    def frames():
        for i in range(n):
            light = np.zeros((h, w), np.float32)
            dark = np.zeros((h, w), np.float32)
            for _ in range(round(4 + 40 * k)):  # poussières : claires ou sombres
                x, y = rng.uniform(bx, bx + bw), rng.uniform(by, by + bh)
                r = rng.uniform(0.8, 3.2) * unit
                _disc(light if rng.random() < 0.4 else dark, x, y, r, rng.uniform(0.5, 0.95))
            if rng.random() < 0.25 * k:  # cheveu ou fibre
                x, y = rng.uniform(bx, bx + bw), rng.uniform(by, by + bh)
                pts = [(x, y)]
                for _s in range(10):
                    x += rng.gauss(0, 7 * unit)
                    y += rng.gauss(0, 7 * unit)
                    pts.append((x, y))
                _stroke(dark, pts, 1.6 * unit, 0.85)
            for sc in scratches:  # rayures verticales qui durent et dérivent un peu
                age = (i - sc[1]) % n
                if age < sc[2]:
                    sc[0] += rng.gauss(0, 0.6 * unit)
                    x = sc[0]
                    x0, x1 = int(max(0, x - 3 * unit)), int(min(w, x + 3 * unit + 1))
                    if x1 > x0:  # seules les colonnes proches de la rayure
                        xs = np.arange(x0, x1)[None, :]
                        line = np.clip(1.2 * unit - np.abs(xs - x), 0, 1) * sc[3]
                        np.maximum(light[by:by + bh, x0:x1], line,
                                   out=light[by:by + bh, x0:x1])
            yield _rgba(light, dark, w, h)

    return write_video(path, w, h, fps, frames())


# --- fuites de lumière ------------------------------------------------------------------------


def leak_layer(cache_dir: Path, s: Settings, width: int, height: int, area: tuple,
               fps: int) -> Path | None:
    """Lueurs orangées qui passent de temps en temps sur un bord de l'image."""
    if s.fuites <= 0.001:
        return None
    w, h = layer_size(width, height, LEAK_SIDE)
    bx, by, bw, bh = _box(area, w, h)
    key = _key(w, h, list(area), fps, s.fuites, s.variante)
    path = cache_dir / "super8" / f"fuites-{key}.mov"
    if path.exists():
        return path
    import numpy as np

    rng = random.Random(2000 + s.variante)
    n = max(2, LEAK_SECONDS * fps)
    events = []
    for _ in range(1 + round(2 * s.fuites)):
        side = rng.choice((0, 1))
        events.append((rng.randrange(n), rng.randint(fps, 3 * fps), side,
                       rng.uniform(0.2, 0.8), rng.uniform(0.5, 1.0)))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    def frames():
        for i in range(n):
            glow = np.zeros((h, w), np.float32)
            for start, length, side, ypos, power in events:
                age = (i - start) % n
                if age >= length:
                    continue
                f = np.sin(np.pi * age / length)  # monte puis retombe
                cx = bx + (0.1 if side == 0 else 0.9) * bw
                cy = by + ypos * bh
                d = np.hypot((xx - cx) / (0.45 * bw), (yy - cy) / (0.8 * bh))
                glow = np.maximum(glow, np.clip(1 - d, 0, 1) ** 1.4 * f * power)
            a = np.clip(glow * (0.55 + 0.4 * s.fuites), 0, 0.92)
            out = np.empty((h, w, 4), np.uint8)
            out[..., 0] = 255
            out[..., 1] = (110 + 120 * glow).clip(0, 255).astype(np.uint8)  # orange → jaune
            out[..., 2] = (30 + 90 * glow ** 2).clip(0, 255).astype(np.uint8)
            out[..., 3] = (a * 255).astype(np.uint8)
            yield out

    return write_video(path, w, h, fps, frames())


# --- fenêtre de projection --------------------------------------------------------------------


def gate_layer(cache_dir: Path, s: Settings, width: int, height: int, area: tuple) -> Path | None:
    """Noir autour d'une image 4:3 aux coins arrondis (prise au centre de l'image du clip),
    avec, au choix, la perforation de la pellicule à gauche."""
    if s.cadre == "entier":
        return None
    w, h = layer_size(width, height)
    bx, by, bw, bh = _box(area, w, h)
    path = cache_dir / "super8" / f"fenetre-{_key(w, h, list(area), s.cadre)}.mov"
    if path.exists():
        return path
    import numpy as np

    gw = min(bw, round(bh * 4 / 3))
    gh = min(bh, round(gw * 3 / 4)) if gw < bw else bh
    cx, cy = bx + bw / 2, by + bh / 2
    inset = max(2.0, 0.01 * gh)
    hx, hy = gw / 2 - inset, gh / 2 - inset
    radius = 0.06 * gh
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) + 0.5
    qx = np.abs(xx - cx) - (hx - radius)
    qy = np.abs(yy - cy) - (hy - radius)
    dist = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) \
        - radius
    soft = max(1.5, 0.006 * gh)
    dark = np.clip(dist / soft + 0.5, 0, 1)  # 0 dans la fenêtre, 1 dehors (bord adouci)
    light = np.zeros_like(dark)
    if s.cadre == "perfo":
        # perforation de la pellicule, à gauche de la fenêtre, à mi-hauteur
        px, py = cx - gw / 2 - 0.05 * gh, cy
        phx, phy, pr = 0.03 * gh, 0.065 * gh, 0.02 * gh
        qx = np.abs(xx - px) - (phx - pr)
        qy = np.abs(yy - py) - (phy - pr)
        hole = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) \
            + np.minimum(np.maximum(qx, qy), 0) - pr
        light = np.clip(0.5 - hole / soft, 0, 1) * 0.95
        dark = np.maximum(dark - light, 0)
    inside = np.zeros_like(dark)
    inside[by:by + bh, bx:bx + bw] = 1  # rien hors de la zone de l'image (bandes)
    frame = _rgba(light * inside, dark * inside, w, h, (246, 238, 220))
    return write_video(path, w, h, 25, [frame])


def overlay(path: Path | None) -> list[tuple[str, dict]]:
    if path is None:
        return []
    return [("watermark", {"resource": str(path), "transition": COMPOSITE,
                           "producer.eof": "loop", "distort": 1})]


def area_mask(cache_dir: Path, area: tuple, width: int, height: int) -> Path:
    """Masque (canal alpha) de la zone de l'image, à la taille de la toile."""
    import numpy as np

    w, h = layer_size(width, height)
    x, y, bw, bh = _box(area, w, h)
    path = cache_dir / "super8" / f"zone{MODULE_VERSION}_{w}x{h}_{x}_{y}_{bw}_{bh}.mov"
    if not path.exists():
        frame = np.zeros((h, w, 4), np.uint8)
        frame[y:y + bh, x:x + bw] = 255
        write_video(path, w, h, 25, [frame])
    return path


def keep_outside_transparent(cache_dir: Path, area: tuple, width: int,
                             height: int) -> list[tuple[str, dict]]:
    """Les calques rendent opaque tout le cadre du clip : hors de la zone de l'image, il
    redevient transparent (une image incrustée ne masque pas la piste du dessous)."""
    if area == FULL:
        return []
    return [("shape", {"resource": str(area_mask(cache_dir, area, width, height)),
                       "use_luminance": 0, "use_mix": 0, "audio_match": 0,
                       "alpha_operation": "minimum", "producer.eof": "loop"})]


# --- cadence 18 images/s ----------------------------------------------------------------------


def cadence_path(cache_dir: Path, media_path: str) -> Path:
    p = Path(media_path)
    try:
        stamp = [p.stat().st_mtime_ns, p.stat().st_size]
    except OSError:
        stamp = None
    return cache_dir / "super8" / "cadence" / f"{_key(str(p.resolve()), stamp, FILM_FPS)}.mp4"


def cadence_command(source: str, output: Path, media_fps: float) -> list[str]:
    """Vidéo ramenée à 18 images/s puis à sa cadence d'origine : chaque image est répétée,
    les durées et le son ne changent pas."""
    fps = media_fps if media_fps and media_fps > 1 else 25
    return [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-nostats", "-progress",
            "pipe:1", "-y", "-i", source, "-vf", f"fps={FILM_FPS},fps={fps:g}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-f", "mp4", str(output)]


def render_cadence(source: str, output: Path, media_fps: float, duration: float,
                   progress=lambda r: None, cancelled=lambda: False) -> Path:
    from montar.media import ffmpeg_run

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name("part-" + output.name)
    total_us = max(1.0, duration * 1_000_000)

    def on_progress(key: str, value: str) -> None:
        if key == "out_time_us":
            try:
                progress(min(1.0, int(value) / total_us))
            except ValueError:
                pass

    try:
        ffmpeg_run.run(cadence_command(source, tmp, media_fps), on_progress, cancelled)
        tmp.replace(output)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    progress(1.0)
    return output


# --- bruit de projecteur ----------------------------------------------------------------------

SOUND_RATE = 22050
MAX_SOUND_SECONDS = 600


def projector_sound(path: Path, seconds: float, seed: int = 1) -> Path:
    """Ronronnement du moteur, claquement de l'obturateur 18 fois par seconde, souffle du
    ventilateur, léger pleurage : un fichier WAV mono."""
    import wave

    import numpy as np

    seconds = max(0.5, min(MAX_SOUND_SECONDS, seconds))
    n = int(seconds * SOUND_RATE)
    t = np.arange(n, dtype=np.float32) / SOUND_RATE
    rng = np.random.default_rng(seed)
    wobble = 1 + 0.01 * np.sin(2 * np.pi * 0.6 * t)  # pleurage du moteur
    phase = 2 * np.pi * 52 * np.cumsum(wobble) / SOUND_RATE
    hum = 0.10 * np.sin(phase) + 0.05 * np.sin(2 * phase) + 0.025 * np.sin(3 * phase)
    noise = rng.normal(0, 1, n).astype(np.float32)
    hiss = np.convolve(noise, np.ones(8, np.float32) / 8, mode="same") * 0.05  # souffle
    clicks = np.zeros(n, np.float32)
    burst = np.exp(-np.arange(int(0.012 * SOUND_RATE)) / (0.0025 * SOUND_RATE))
    period = SOUND_RATE / FILM_FPS
    k = 0.0
    while k < n:
        i = int(k + rng.normal(0, 0.004) * SOUND_RATE)
        if 0 <= i < n - len(burst):
            clicks[i:i + len(burst)] += burst * rng.uniform(0.18, 0.26) \
                * rng.normal(0, 1, len(burst))
        k += period
    mix = hum + hiss + clicks
    fade = min(n // 4, int(0.3 * SOUND_RATE))  # fondus d'entrée et de sortie
    ramp = np.linspace(0, 1, fade, dtype=np.float32)
    mix[:fade] *= ramp
    mix[n - fade:] *= ramp[::-1]
    pcm = (np.clip(mix, -1, 1) * 32000).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("part-" + path.name)
    with wave.open(str(tmp), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SOUND_RATE)
        out.writeframes(pcm.tobytes())
    tmp.replace(path)
    return path
