# SPDX-License-Identifier: GPL-3.0-or-later
"""Effet « Pluie » : réglages, filtres MLT de l'ambiance et calcul des calques de gouttes.

L'ambiance (image plus sombre, plus froide, brume, éclairs, objectif mouillé) est faite de
filtres MLT ordinaires : elle suit les curseurs sans délai. Les gouttes posées sur l'objectif
(ou la vitre) sont calculées une fois avec NumPy, en boucle de quelques secondes, dans deux
fichiers :

- un **masque** (niveaux de gris) : là où il y a de l'eau, l'image vue à travers la goutte
  (floue, plus claire) remplace l'image nette (filtres `mask_start` / `mask_apply`) ;
- un **calque** transparent superposé (`watermark`) : bord sombre et reflet des gouttes,
  ombrage intérieur, traits de la pluie qui tombe.

Ces calques ne dépendent pas de la vidéo : ils sont recalculés seulement quand un réglage
des gouttes change, et partagés par tous les clips aux mêmes réglages."""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MODULE_VERSION = 2  # change le nom des calques en cache si leur dessin évolue
LOOP_SECONDS = 5  # durée de la boucle des gouttes animées
MAX_SIDE = 1920  # calques limités à cette taille (le moteur les met à l'échelle)

# Le « temps » choisi donne le caractère de la pluie ; les curseurs l'ajustent : 50 % =
# valeur du temps choisi, 0 % = rien, 100 % = le double.
PRESETS = {
    # volume, taille, ruissellement, ambiance, pluie qui tombe, brume, éclairs
    "bruine": dict(volume=0.2, taille=0.3, ruissellement=0.15, ambiance=0.5, chute=0.2,
                   brume=0.2, eclairs=False),
    "pluie": dict(volume=0.5, taille=0.5, ruissellement=0.5, ambiance=0.7, chute=0.4,
                  brume=0.3, eclairs=False),
    "averse": dict(volume=0.9, taille=0.75, ruissellement=0.9, ambiance=0.85, chute=0.8,
                   brume=0.45, eclairs=False),
    "orage": dict(volume=0.8, taille=0.7, ruissellement=0.8, ambiance=1.0, chute=0.9,
                  brume=0.35, eclairs=True),
}
SLIDERS = ("volume", "taille", "ruissellement", "ambiance", "chute", "brume")
SURFACES = ("objectif", "vitre")

# réglages qui changent le dessin des gouttes (les autres sont des filtres instantanés)
DROP_KEYS = ("volume", "taille", "ruissellement", "chute", "surface", "anime", "variante")


@dataclass(frozen=True)
class Settings:
    """Réglages effectifs (0 … 1), une fois le temps et les curseurs combinés."""

    volume: float = 0.5
    taille: float = 0.5
    ruissellement: float = 0.5
    ambiance: float = 0.7
    chute: float = 0.4
    brume: float = 0.3
    eclairs: bool = False
    surface: str = "objectif"
    anime: bool = True
    mouille: bool = True
    variante: int = 1

    @classmethod
    def from_values(cls, values: dict) -> Settings:
        """Valeurs du clip (temps + curseurs à 50 % par défaut) → réglages effectifs."""
        preset = PRESETS.get(values.get("temps"), PRESETS["pluie"])

        def slider(key: str) -> float:
            try:
                k = max(0.0, min(1.0, float(values.get(key, 0.5))))
            except (TypeError, ValueError):
                k = 0.5
            return max(0.0, min(1.0, preset[key] * 2 * k))

        def step(key: str) -> float:
            """Réglage des gouttes arrondi à 5 % : le glisser d'un curseur ne lance pas un
            calcul par position, et la différence ne se voit pas."""
            return round(slider(key) * 20) / 20

        surface = values.get("surface", "objectif")
        try:
            variante = max(1, min(99, int(values.get("variante", 1))))
        except (TypeError, ValueError):
            variante = 1
        return cls(volume=step("volume"), taille=step("taille"),
                   ruissellement=step("ruissellement"), ambiance=slider("ambiance"),
                   chute=step("chute"), brume=slider("brume"),
                   eclairs=preset["eclairs"] or bool(values.get("eclairs", False)),
                   surface=surface if surface in SURFACES else "objectif",
                   anime=True,
                   mouille=bool(values.get("mouille", True)), variante=variante)

    @property
    def has_drops(self) -> bool:
        return self.volume > 0.001 or self.chute > 0.001


# --- filtres de l'ambiance (instantanés) ----------------------------------------------------


def ambiance_filters(s: Settings) -> list[tuple[str, dict]]:
    """Jour de pluie : image désaturée, plus sombre, tons moyens écrasés, contraste adouci,
    noirs voilés, dominante froide."""
    k = s.ambiance
    if k <= 0.001:
        return []
    tint = (1 - 0.07 * k, 1 - 0.01 * k, min(1.0, 1 + 0.06 * k))
    low = 0.06 * k
    high = low + (1 - 0.18 * k) * (1 - 0.32 * k)
    levels = {}
    for c, t in zip("rgb", tint, strict=True):
        levels[f"av.{c}omin"] = round(low * t, 4)
        levels[f"av.{c}omax"] = round(min(1.0, high * t), 4)
    return [("avfilter.eq", {"av.saturation": round(1 - 0.45 * k, 3),
                             "av.gamma": round(1 / (1 + 0.25 * k), 3)}),
            ("avfilter.colorlevels", levels)]


def softening_filters(s: Settings, height: int) -> list[tuple[str, dict]]:
    """Eau sur l'objectif : toute l'image est un peu adoucie (plus sur une vitre, où la
    mise au point est faite sur les gouttes)."""
    if not s.mouille or s.volume <= 0.001:
        return []
    sigma = (0.8 + 1.2 * s.volume) * (1.8 if s.surface == "vitre" else 1.0)
    return [("avfilter.gblur", {"av.sigma": round(sigma * height / 720, 2)})]


def flash_points(duration: int, fps: int, seed: int) -> list[tuple[int, float]]:
    """Éclairs d'orage : (image, niveau de luminosité), un éclair toutes les 4 à 9 s en
    moyenne, en double flash comme un vrai éclair."""
    rng = random.Random(seed)
    points = [(0, 1.0)]
    t = round(fps * rng.uniform(0.8, 3.0))
    while t + 8 < duration:
        peak = rng.uniform(1.7, 2.3)
        for dt, level in ((-1, 1.0), (0, peak), (2, 1.15), (3, peak * 0.85), (7, 1.0)):
            if t + dt > points[-1][0]:
                points.append((t + dt, round(level, 3)))
        t += round(fps * rng.uniform(4.0, 9.0))
    if points[-1][0] < duration - 1:
        points.append((duration - 1, 1.0))
    return points


def lightning_filters(s: Settings, duration: int, fps: int) -> list[tuple[str, dict]]:
    if not s.eclairs or duration < 2:
        return []
    points = flash_points(duration, fps, s.variante)
    if len(points) <= 2:
        return []
    level = ";".join(f"{f}={v:g}" for f, v in points)
    return [("brightness", {"level": level, "in": 0, "out": duration - 1})]


HAZE_ROWS = 540


def haze_image(folder: Path, amount: float) -> Path:
    """Brume : voile gris-bleu, plus dense en haut de l'image (petite image PNG étirée)."""
    level = round(amount * 20)
    path = folder / f"brume{MODULE_VERSION}_{level:02d}.png"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        for y in range(HAZE_ROWS):  # assez de lignes pour un dégradé sans bandes
            a = round(255 * 0.35 * (level / 20) * (1 - 0.7 * y / (HAZE_ROWS - 1)))
            rows.append(bytes([140, 153, 168, a]) * 4)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(_png(4, HAZE_ROWS, rows))
        tmp.replace(path)
    return path


def _png(width: int, height: int, rows, gray: bool = False, level: int = 9) -> bytes:
    """Image PNG (RVBA, ou niveaux de gris) à partir de ses lignes d'octets."""
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\0" + bytes(r) for r in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 0 if gray else 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b""))


# --- images fixes ----------------------------------------------------------------------------

# formats d'image que le moteur ouvre comme de vraies images fixes ; les autres (WebP, GIF,
# BMP, TIFF…) sont ouverts comme une vidéo d'une seule image, et l'image disparaît alors
# derrière les filtres de la pluie (fond gris) : le module en utilise une copie PNG
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
    key = json.dumps([str(source.resolve()), stat.st_mtime_ns, stat.st_size])
    target = cache_dir / "pluie" / "images" / f"{hashlib.sha1(key.encode()).hexdigest()}.png"
    if target.exists():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".part.png")
    done = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", path,
                           "-frames:v", "1", "-update", "1", str(tmp)],
                          capture_output=True, timeout=60)
    if done.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return path  # copie impossible : l'image d'origine, telle quelle
    tmp.replace(target)
    return str(target)


# --- zone couverte par l'image du clip ----------------------------------------------------

FULL = (0.0, 0.0, 1.0, 1.0)
MAX_CROP = 0.45


def clip_area(cw: int, ch: int, mw: int, mh: int, transform=None) -> tuple:
    """Zone (x, y, largeur, hauteur, en fractions de la toile) qu'occupe l'image du clip là
    où le moteur applique les filtres : l'image recadrée, ajustée à la toile en gardant ses
    proportions, le reste étant transparent. La pluie ne déborde pas de cette zone."""
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


def _box(area: tuple, w: int, h: int) -> tuple[int, int, int, int]:
    """Zone en pixels d'un calque w×h : (x, y, largeur, hauteur)."""
    x0, y0 = round(area[0] * w), round(area[1] * h)
    x1, y1 = round((area[0] + area[2]) * w), round((area[1] + area[3]) * h)
    return x0, y0, max(2, min(w, x1) - x0), max(2, min(h, y1) - y0)


def _padded(image, w: int, h: int, box: tuple):
    """Calque de la toile entière, transparent (ou sec) hors de la zone de l'image."""
    import numpy as np

    if image.shape[:2] == (h, w):
        return image
    out = np.zeros((h, w) + image.shape[2:], image.dtype)
    x, y, bw, bh = box
    out[y:y + bh, x:x + bw] = image[:h - y, :w - x]
    return out


def area_mask(cache_dir: Path, area: tuple, width: int, height: int) -> Path:
    """Masque de la zone de l'image (opaque dedans, transparent dehors), à la taille de la
    toile. Le canal alpha est exact ; la luminosité serait lue sur une échelle réduite
    (le noir laisserait passer 6 % de l'image)."""
    w, h = layer_size(width, height)
    x, y, bw, bh = _box(area, w, h)
    path = cache_dir / "pluie" / f"zone{MODULE_VERSION}_{w}x{h}_{x}_{y}_{bw}_{bh}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        inside, outside = b"\xff\xff\xff\xff", b"\0\0\0\0"
        row = outside * x + inside * bw + outside * max(0, w - x - bw)
        rows = [row if y <= j < y + bh else outside * w for j in range(h)]
        tmp = path.with_suffix(".part")
        tmp.write_bytes(_png(w, h, rows))
        tmp.replace(path)
    return path


def keep_outside_transparent(cache_dir: Path, area: tuple, width: int,
                             height: int) -> list[tuple[str, dict]]:
    """Les calques superposés rendent opaque tout le cadre du clip : hors de la zone de
    l'image, il redevient transparent (sinon une image incrustée sur une autre piste
    masquerait celle du dessous par des bandes noires)."""
    if area == FULL:
        return []
    return [("shape", {"resource": str(area_mask(cache_dir, area, width, height)),
                       "use_luminance": 0, "use_mix": 0, "audio_match": 0,
                       "alpha_operation": "minimum"})]


def geometry(area: tuple) -> str:
    """Rectangle MLT (en %) de la zone de l'image."""
    x, y, w, h = (100 * v for v in area)
    return f"{x:.3f}%/{y:.3f}%:{w:.3f}%x{h:.3f}%"


# --- calques des gouttes -------------------------------------------------------------------


def layer_size(width: int, height: int) -> tuple[int, int]:
    """Taille des calques : celle de la toile, réduite si elle dépasse MAX_SIDE (paire)."""
    k = min(1.0, MAX_SIDE / max(width, height, 1))
    return max(2, round(width * k / 2) * 2), max(2, round(height * k / 2) * 2)


def loop_frames(s: Settings, fps: int) -> tuple[int, int]:
    """Nombre d'images du masque et du calque (1 : image fixe)."""
    loop = max(2, round(LOOP_SECONDS * fps))
    mask = loop if s.anime and s.volume > 0.001 else 1
    overlay = loop if (mask > 1 or s.chute > 0.001) else 1
    return mask, overlay


def cache_folder(cache_dir: Path, s: Settings, width: int, height: int, fps: int,
                 area: tuple = FULL, scale: float = 1.0) -> Path:
    key = json.dumps([MODULE_VERSION, layer_size(width, height), fps, list(area), scale,
                      [getattr(s, k) for k in DROP_KEYS]])
    return cache_dir / "pluie" / hashlib.sha1(key.encode()).hexdigest()[:20]


MASK, OVERLAY = "masque.mp4", "calque.mov"
PREVIEW_MASK, PREVIEW_OVERLAY, PREVIEW_RAIN = "masque.png", "calque.png", "pluie.mov"
PREVIEW_SIDE = 960  # aperçu des réglages : gouttes figées, image réduite
RAIN_SIDE, RAIN_FRAMES, RAIN_FPS = 640, 50, 25  # aperçu : pluie qui tombe (boucle de 2 s)


def ready(folder: Path) -> bool:
    return (folder / MASK).exists() and (folder / OVERLAY).exists()


def preview_layers(cache_dir: Path, s: Settings, width: int, height: int,
                   area: tuple = FULL, scale: float = 1.0) -> Path:
    """Aperçu immédiat pendant les réglages (une fraction de seconde) : gouttes figées et
    pluie qui tombe ; le calcul complet, où les gouttes ruissellent, se fait quand on
    applique la pluie."""
    from dataclasses import replace

    k = min(1.0, PREVIEW_SIDE / max(width, height, 1))
    w, h = max(2, round(width * k)), max(2, round(height * k))
    key = json.dumps([MODULE_VERSION, "aperçu", w, h, list(area), scale,
                      [getattr(s, k) for k in DROP_KEYS if k != "anime"]])
    folder = cache_dir / "pluie" / ("apercu-" + hashlib.sha1(key.encode()).hexdigest()[:16])
    names = [PREVIEW_MASK, PREVIEW_OVERLAY] + ([PREVIEW_RAIN] if s.chute > 0.001 else [])
    if all((folder / n).exists() for n in names):
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    box = _box(area, w, h)
    still = _Scene(replace(s, anime=False, chute=0.0), box[2], box[3], 2, unit=h / 720 * scale)
    mask, over = still.frame(0, True, True)
    mask, over = _padded(mask, w, h, box), _padded(over, w, h, box)
    for name, data in ((PREVIEW_MASK, _png(w, h, mask, gray=True, level=1)),
                       (PREVIEW_OVERLAY, _png(w, h, over.reshape(h, -1), level=1))):
        tmp = folder / (name + ".part")
        tmp.write_bytes(data)
        tmp.replace(folder / name)
    if s.chute > 0.001:  # la pluie qui tombe, seule : rapide à dessiner
        k = min(1.0, RAIN_SIDE / max(width, height, 1))
        rw, rh = max(2, round(width * k / 2) * 2), max(2, round(height * k / 2) * 2)
        rbox = _box(area, rw, rh)
        rain = _Scene(replace(s, volume=0.0), rbox[2], rbox[3], RAIN_FRAMES,
                      unit=rh / 720 * scale)
        tmp = folder / ("part-" + PREVIEW_RAIN)
        proc, errors = _encoder(tmp, "rgba", rw, rh, RAIN_FPS,
                                ["-c:v", "qtrle", "-pix_fmt", "argb", "-f", "mov"])
        try:
            for i in range(RAIN_FRAMES):
                _m, over = rain.frame(i, False, True)
                proc.stdin.write(_padded(over, rw, rh, rbox).tobytes())
            _finish(proc, errors)
        except BaseException:
            _abort(proc)
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(folder / PREVIEW_RAIN)
    return folder


@dataclass
class _Drop:
    x: float
    y: float
    r: float
    aspect: float
    born: int  # image d'apparition dans la boucle
    life: int  # durée de vie (images)
    slide_at: int  # âge auquel elle se met à glisser (-1 : jamais)
    trail: float  # longueur du sillon laissé au-dessus (goutte fixe)
    walk: object = None  # écart du sillon à la verticale, tous les 2 px (tableau)


class _Layers:
    """Hauteur d'eau et ombrage, dessinés goutte par goutte : là où deux gouttes se
    touchent, la plus épaisse l'emporte."""

    def __init__(self, scene: _Scene, base: _Layers | None = None) -> None:
        import numpy as np

        self.scene = scene
        if base is None:
            shape = (scene.h, scene.w)
            self.hm, self.light, self.dark = (np.zeros(shape, np.float32) for _ in range(3))
        else:
            self.hm, self.light, self.dark = base.hm.copy(), base.light.copy(), \
                base.dark.copy()

    def _paint(self, x0: int, y0: int, v, sx, sy, radius: float) -> None:
        import numpy as np

        sc = self.scene
        y1, x1 = y0 + v.shape[0], x0 + v.shape[1]
        win = v > self.hm[y0:y1, x0:x1]
        if not win.any():
            return
        wet = np.clip(v * sc.gain, 0, 1)
        rim = np.where(v > 0.01, (1 - v) ** sc.rim_power, 0)
        rel = np.clip(sy / radius, -1, 1)
        # vue inversée à travers la goutte : le sol en haut (sombre), le ciel en bas (clair)
        dark = 0.6 * rim + 0.3 * np.clip(-rel, 0, 1) * wet
        light = 0.22 * np.clip(rel, 0, 1) * wet
        if radius > 2.5 * sc.unit:  # reflet : petit point clair en haut à gauche
            dist = np.hypot(sx + radius * 0.35, sy + radius * 0.4) / radius
            light = light + sc.spec * np.clip(1 - dist / 0.22, 0, 1) ** 1.5 * (v > 0.3)
        for layer, value in ((self.hm, v), (self.light, light), (self.dark, dark)):
            layer[y0:y1, x0:x1][win] = np.broadcast_to(value, v.shape)[win]

    def drop(self, x: float, y: float, rx: float, ry: float, top: float = 1.0) -> None:
        import numpy as np

        w, h = self.scene.w, self.scene.h
        x0, x1 = int(max(0, x - rx - 2)), int(min(w, x + rx + 3))
        y0, y1 = int(max(0, y - ry - 2)), int(min(h, y + ry + 3))
        if x1 <= x0 or y1 <= y0 or rx < 0.4:
            return
        sx = np.arange(x0, x1, dtype=np.float32)[None, :] - x
        sy = np.arange(y0, y1, dtype=np.float32)[:, None] - y
        if rx > 5:  # contour légèrement irrégulier (une goutte n'est pas un cercle)
            ang = np.arctan2(sy, sx)
            wob = 1 + 0.07 * np.sin(3 * ang + x) + 0.04 * np.sin(5 * ang + y)
        else:
            wob = 1.0
        r2 = (sx / (rx * wob)) ** 2 + (sy / (ry * wob)) ** 2
        v = np.sqrt(np.clip(1 - r2, 0, 1)) * top
        self._paint(x0, y0, v, sx, sy, max(rx, ry))

    def trail(self, d: _Drop, bottom: float, top: float, fade: float) -> None:
        """Sillon fin laissé par une goutte qui a glissé, avec quelques perles."""
        import numpy as np

        sc = self.scene
        w, h = sc.w, sc.h
        y0, y1 = int(max(0, top)), int(min(h, bottom + 1))
        if y1 <= y0:
            return
        rows = np.arange(y0, y1, dtype=np.float32)
        steps = (bottom - rows) / (2 * sc.unit)
        center = d.x + np.interp(steps, np.arange(len(d.walk)), d.walk)
        rr = max(0.5, d.r * 0.22 * fade)
        x0 = int(max(0, center.min() - rr - 2))
        x1 = int(min(w, center.max() + rr + 3))
        if x1 <= x0:
            return
        dx = np.arange(x0, x1, dtype=np.float32)[None, :] - center[:, None]
        v = np.sqrt(np.clip(1 - (dx / rr) ** 2, 0, 1)) * (0.85 * fade)
        self._paint(x0, y0, v, dx, np.zeros_like(dx), rr)
        length = max(1.0, bottom - top)
        for k in range(int(length / (50 * sc.unit))):  # perles : une tous les 50 px environ
            t = ((k * 0.618 + d.x * 0.01) % 1.0) * length
            i = min(len(d.walk) - 1, int(t / (2 * sc.unit)))
            self.drop(d.x + float(d.walk[i]), bottom - t, rr * 1.8, rr * 2.0, top=fade)


class _Scene:
    """Gouttes, gouttelettes et traits de pluie tirés au hasard (graine = variante)."""

    def __init__(self, s: Settings, w: int, h: int, loop: int,
                 unit: float | None = None) -> None:
        import numpy as np

        self.s, self.w, self.h, self.loop = s, w, h, loop
        rng = np.random.default_rng(1000 + s.variante)
        # tailles exprimées pour une toile de 720 lignes (la scène peut n'en couvrir qu'une
        # partie : la zone de l'image du clip)
        unit = unit or h / 720
        self.unit = unit
        soft = s.surface == "objectif"  # gouttes floues sur l'objectif, nettes sur une vitre
        self.gain, self.rim_power, self.spec = (2.5, 2.0, 0.45) if soft else (5.0, 3.0, 0.6)
        size = 0.5 + s.taille
        # surface couverte, en toiles de 1280×720 : même densité de gouttes quelle que soit
        # la résolution (aperçu réduit, export 4K)
        surface = (w * h) / (1280 * 720 * unit * unit)
        animated = s.anime and loop > 1
        self.drops: list[_Drop] = []
        self.drizzle = None
        if s.volume > 0.001:
            # gouttes animées : chacune n'est visible qu'une partie de la boucle
            more = 1.4 if animated else 1.0
            for _ in range(round((6 + 110 * s.volume) * more)):
                r = float(rng.uniform(4, 20)) * size * unit
                life = int(rng.integers(loop // 2, loop)) if animated else loop
                big = r > 11 * size * unit and rng.random() < 0.6 * s.ruissellement
                trail = float(rng.uniform(90, 340)) * s.ruissellement * unit \
                    if big and not animated else 0.0
                d = _Drop(float(rng.uniform(0, w)), float(rng.uniform(0, h)), r,
                          float(rng.uniform(1.0, 1.2)), int(rng.integers(0, loop)), life,
                          int(life * rng.uniform(0.25, 0.55)) if big and animated else -1,
                          trail)
                if big:
                    d.walk = np.cumsum(rng.normal(0, 0.3, round(h / unit / 2) + 2))
                self.drops.append(d)
            # gouttelettes très fines (bruine) : elles restent en place
            n = round((300 + 3500 * s.volume) * surface)
            self.drizzle = (rng.uniform(0, w, n), rng.uniform(0, h, n),
                            rng.uniform(0.8, 3.0, n) * (0.6 + 0.6 * s.taille) * unit)
        # traits de pluie : chacun parcourt un nombre entier de fois la hauteur pendant la
        # boucle, pour qu'elle se referme sans saut
        count = round(2200 * s.chute * surface)
        span = h + 120 * unit
        self.streaks = (rng.uniform(-0.2 * w, w, count), rng.uniform(0, span, count),
                        rng.uniform(18, 46, count) * unit, rng.uniform(0.16, 0.47, count),
                        rng.integers(3, 7, count) * span / max(1, loop))
        self.span = span
        self.slant = 0.18
        self._static: _Layers | None = None

    # dessin -----------------------------------------------------------------------------

    def layers(self, frame: int) -> _Layers:
        if self._static is None:
            self._static = _Layers(self)
            if self.drizzle is not None:
                for x, y, r in zip(*self.drizzle, strict=True):
                    self._static.drop(float(x), float(y), float(r), float(r))
        out = _Layers(self, self._static)
        for d in self.drops:
            age = (frame - d.born) % self.loop
            if age >= d.life:
                continue
            scale, fade = 1.0, 1.0
            if self.loop > 1 and d.life < self.loop:
                grow, end = 4, max(1, min(8, d.life // 3))
                scale = min(1.0, 0.4 + 0.6 * age / grow)
                if d.life - age < end:  # la goutte s'efface avant de disparaître
                    fade = (d.life - age) / end
                    scale *= 0.6 + 0.4 * fade
            r = d.r * scale
            y = d.y
            if d.slide_at >= 0 and age > d.slide_at:  # glisse en accélérant
                t = age - d.slide_at
                y = d.y + 0.35 * self.unit * t * t
                out.trail(d, y - r * 0.6, d.y - r * 0.3, fade)
            elif d.trail:
                out.trail(d, y - r * 0.6, y - d.trail, 1.0)
            out.drop(d.x, y, r, r * d.aspect, top=fade)
        return out

    def streak_layer(self, frame: int):
        """Traits de pluie qui tombent (flou de mouvement), en léger biais."""
        import numpy as np

        w, h = self.w, self.h
        layer = np.zeros((h, w), np.float32)
        x0, y0, length, alpha, speed = self.streaks
        if not len(x0):
            return layer
        y = (y0 + speed * frame) % self.span - 60 * self.unit
        steps = np.linspace(0, 1, 24, dtype=np.float32)
        px = x0[:, None] + length[:, None] * steps * self.slant
        py = y[:, None] + length[:, None] * steps
        # trait effilé aux deux bouts
        a = alpha[:, None] * np.clip(np.sin(np.pi * steps), 0, 1)[None, :] ** 0.7
        ix, iy = px.astype(np.int32).ravel(), py.astype(np.int32).ravel()
        keep = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        np.maximum.at(layer, (iy[keep], ix[keep]), a.ravel()[keep])
        # un pixel de flou horizontal : trait plus doux
        layer[:, 1:] = np.maximum(layer[:, 1:], layer[:, :-1] * 0.5)
        return layer

    def frame(self, frame: int, mask: bool, overlay: bool):
        """(masque uint8 h×w, calque RGBA uint8 h×w×4) de l'image `frame` de la boucle."""
        import numpy as np

        lay = self.layers(frame)
        out_mask = (np.clip(lay.hm * self.gain, 0, 1) * 255).astype(np.uint8) if mask else None
        if not overlay:
            return out_mask, None
        light, dark = lay.light, lay.dark
        if self.s.chute > 0.001:
            light = np.maximum(light, self.streak_layer(frame) * 0.42)
        total = light + dark
        alpha = np.clip(total, 0, 1)
        white = light / np.maximum(total, 1e-6)
        rgba = np.empty((self.h, self.w, 4), np.uint8)
        # bleu-gris très clair pour la lumière, presque noir pour les bords
        for c, (lo, hi) in enumerate(((12, 236), (16, 242), (22, 250))):
            rgba[..., c] = (lo + (hi - lo) * white).astype(np.uint8)
        rgba[..., 3] = (alpha * 255).astype(np.uint8)
        return out_mask, rgba


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


def render_layers(folder: Path, s: Settings, width: int, height: int, fps: int,
                  progress=lambda ratio: None, cancelled=lambda: False,
                  area: tuple = FULL, scale: float = 1.0) -> Path:
    """Calcule le masque et le calque des gouttes dans `folder` (écrit d'abord ailleurs) ;
    hors de la zone de l'image du clip, ils sont vides. `width` × `height` : cadre que
    reçoivent les filtres ; `scale` : hauteur de la toile / hauteur de ce cadre (les
    gouttes gardent leur taille par rapport à la toile)."""
    w, h = layer_size(width, height)
    n_mask, n_over = loop_frames(s, fps)
    box = _box(area, w, h)
    scene = _Scene(s, box[2], box[3], max(n_mask, n_over), unit=h / 720 * scale)
    folder.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=folder.name + ".", dir=folder.parent))
    gop = ["-g", str(max(1, fps))]
    mask_proc, mask_err = _encoder(work / MASK, "gray", w, h, fps,
                                   ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                                    "-pix_fmt", "yuv420p", *gop, "-f", "mp4"])
    over_proc, over_err = _encoder(work / OVERLAY, "rgba", w, h, fps,
                                   ["-c:v", "qtrle", "-pix_fmt", "argb", *gop, "-f", "mov"])
    try:
        total = max(n_mask, n_over)
        for i in range(total):
            if cancelled():
                raise Cancelled()
            mask, over = scene.frame(i, i < n_mask, i < n_over)
            try:
                if mask is not None:
                    mask_proc.stdin.write(_padded(mask, w, h, box).tobytes())
                if over is not None:
                    over_proc.stdin.write(_padded(over, w, h, box).tobytes())
            except BrokenPipeError:
                break  # l'erreur de ffmpeg est remontée par _finish
            progress((i + 1) / (total + 1))
        _finish(mask_proc, mask_err)
        _finish(over_proc, over_err)
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        work.replace(folder)
    except BaseException:
        _abort(mask_proc)
        _abort(over_proc)
        shutil.rmtree(work, ignore_errors=True)
        raise
    progress(1.0)
    return folder


def drop_filters(folder: Path, s: Settings, height: int,
                 preview: bool = False) -> list[tuple[str, dict]]:
    """Filtres qui posent les gouttes calculées (ou leur aperçu) sur l'image du clip."""
    mask, overlay = (PREVIEW_MASK, PREVIEW_OVERLAY) if preview else (MASK, OVERLAY)
    result = []
    if s.volume > 0.001:
        # dans les gouttes : l'image vue à travers l'eau, floue et un peu plus claire
        blur = (3.0 + 4.0 * s.taille) * (1.6 if s.surface == "objectif" else 1.0)
        result += [
            ("mask_start", {"filter": "shape", "filter.resource": str(folder / mask),
                            "filter.use_luminance": 1, "filter.use_mix": 0,
                            "filter.audio_match": 0, "filter.producer.eof": "loop"}),
            ("avfilter.gblur", {"av.sigma": round(blur * height / 720, 2)}),
            ("avfilter.eq", {"av.brightness": 0.04, "av.contrast": 0.9,
                             "av.saturation": 0.85}),
            ("mask_apply", {}),
        ]
    result.append(("watermark", {"resource": str(folder / overlay),
                                 "producer.eof": "loop", "distort": 1}))
    if preview and (folder / PREVIEW_RAIN).exists():  # la pluie tombe aussi dans l'aperçu
        result.append(("watermark", {"resource": str(folder / PREVIEW_RAIN),
                                     "producer.eof": "loop", "distort": 1}))
    return result
