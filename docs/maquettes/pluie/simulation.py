"""Maquettes de l'effet « Pluie » : scène de test procédurale + simulation des gouttes."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1280, 720
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- scènes de test
def blur(a, r):
    img = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255


def scene_rue(seed=3):
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):  # ciel de fin de journée
        t = y / H
        c = (int(120 + 90 * t), int(140 + 60 * t), int(175 + 30 * t))
        d.line([(0, y), (W, y)], fill=c)
    horizon = int(H * 0.62)
    x = -20
    while x < W:  # immeubles
        bw = int(rng.integers(90, 190))
        bh = int(rng.integers(180, 380))
        shade = int(rng.integers(55, 95))
        col = (shade, shade - 6, shade - 10 + int(rng.integers(0, 12)))
        d.rectangle([x, horizon - bh, x + bw, horizon], fill=col)
        for wy in range(horizon - bh + 18, horizon - 20, 26):
            for wx in range(x + 12, x + bw - 18, 22):
                if rng.random() < 0.45:
                    warm = rng.random() < 0.8
                    c = (255, 205, 120) if warm else (190, 215, 255)
                    d.rectangle([wx, wy, wx + 10, wy + 14], fill=c)
        x += bw + int(rng.integers(0, 10))
    for y in range(horizon, H):  # chaussée
        t = (y - horizon) / (H - horizon)
        g = int(70 - 30 * t)
        d.line([(0, y), (W, y)], fill=(g, g + 2, g + 6))
    d.polygon([(W * 0.48, horizon), (W * 0.52, horizon), (W * 0.56, H), (W * 0.44, H)],
              fill=(95, 95, 98))
    a = np.asarray(img, dtype=np.float32) / 255
    # reflet des immeubles sur la chaussée mouillée
    band = a[horizon - (H - horizon):horizon][::-1]
    a[horizon:] = a[horizon:] * 0.55 + blur(band, 6) * 0.45
    # lampadaires et phares : halos lumineux
    glow = np.zeros_like(a)
    yy, xx = np.mgrid[0:H, 0:W]
    lights = [(x, horizon - 150, (1.0, 0.8, 0.45), 14) for x in range(80, W, 260)]
    lights += [(560, horizon + 40, (1.0, 0.95, 0.85), 10), (640, horizon + 40, (1.0, 0.95, 0.85), 10),
               (820, horizon + 25, (1.0, 0.2, 0.15), 7), (870, horizon + 25, (1.0, 0.2, 0.15), 7)]
    for lx, ly, col, r in lights:
        dist = np.hypot(xx - lx, yy - ly)
        g = np.exp(-(dist / (r * 4)) ** 2) + 0.9 * (dist < r)
        glow += g[..., None] * np.array(col)
    return np.clip(a + glow * 0.85, 0, 1)


def scene_lac():
    """Paysage dans l'esprit des maquettes (montagnes, lac)."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(150 + 80 * t), int(195 + 40 * t), int(235 - 10 * t)))
    d.ellipse([930, 90, 1030, 190], fill=(255, 248, 225))
    d.polygon([(0, 420), (220, 240), (420, 380), (640, 170), (900, 360), (1100, 250),
               (1280, 330), (1280, 470), (0, 470)], fill=(110, 160, 125))
    d.polygon([(0, 470), (300, 380), (560, 450), (820, 390), (1280, 460), (1280, 500),
               (0, 500)], fill=(70, 125, 92))
    for y in range(500, H):
        t = (y - 500) / (H - 500)
        d.line([(0, y), (W, y)], fill=(int(90 + 40 * t), int(150 + 30 * t), int(185 + 20 * t)))
    d.polygon([(0, 660), (400, 610), (900, 640), (1280, 600), (1280, 720), (0, 720)],
              fill=(60, 90, 55))
    a = np.asarray(img, dtype=np.float32) / 255
    a[500:610] = a[500:610] * 0.6 + a[390:500][::-1] * 0.4
    return blur(a, 1.2)


# ---------------------------------------------------------------- effet pluie
def grade(a, k):
    """Jour de pluie : image plus sombre, plus froide, désaturée, contraste adouci."""
    luma = (a * [0.299, 0.587, 0.114]).sum(-1, keepdims=True)
    a = a + (luma - a) * (0.45 * k)                    # désaturation
    a = a * (1 - 0.32 * k)                             # plus sombre
    a = a ** (1 + 0.25 * k)                            # tons moyens écrasés
    a = a * (1 - 0.18 * k) + 0.06 * k                  # contraste adouci, noirs voilés
    a = a * np.array([1 - 0.07 * k, 1 - 0.01 * k, 1 + 0.06 * k])  # dominante froide
    return np.clip(a, 0, 1)


def haze(a, k):
    """Brume : voile gris-bleu plus dense en haut de l'image."""
    yy = np.linspace(1, 0.3, H)[:, None, None]
    return a * (1 - 0.35 * k * yy) + np.array([0.55, 0.6, 0.66]) * 0.35 * k * yy


def falling_rain(a, k, rng, angle=0.18):
    """Traits de pluie qui tombent (flou de mouvement), en léger biais."""
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    for _ in range(int(2200 * k)):
        x, y = rng.uniform(-100, W), rng.uniform(-60, H)
        ln = rng.uniform(18, 46)
        d.line([(x, y), (x + ln * angle, y + ln)], fill=int(rng.uniform(40, 120)), width=1)
    m = np.asarray(layer.filter(ImageFilter.GaussianBlur(0.6)), dtype=np.float32)[..., None] / 255
    return np.clip(a + m * 0.55 * (0.85 - a * 0.4), 0, 1)


def drops_map(rng, volume, size, trails):
    """Gouttes posées sur l'objectif : hauteur (0 = sec, 1 = sommet), centre et rayon de la
    goutte à laquelle appartient chaque pixel."""
    h = np.zeros((H, W), np.float32)
    cxm = np.zeros((H, W), np.float32)
    cym = np.zeros((H, W), np.float32)
    rm = np.ones((H, W), np.float32)
    yy, xx = np.mgrid[0:H, 0:W]

    def put(cx, cy, rx, ry, top=1.0):
        x0, x1 = int(max(0, cx - rx - 2)), int(min(W, cx + rx + 3))
        y0, y1 = int(max(0, cy - ry - 2)), int(min(H, cy + ry + 3))
        if x1 <= x0 or y1 <= y0:
            return
        sx, sy = xx[y0:y1, x0:x1], yy[y0:y1, x0:x1]
        ang = np.arctan2(sy - cy, sx - cx)  # contour légèrement irrégulier
        wob = 1 + 0.07 * np.sin(3 * ang + cx) + 0.04 * np.sin(5 * ang + cy)
        r2 = ((sx - cx) / (rx * wob)) ** 2 + ((sy - cy) / (ry * wob)) ** 2
        v = np.sqrt(np.clip(1 - r2, 0, 1)) * top
        win = v > h[y0:y1, x0:x1]
        h[y0:y1, x0:x1][win] = v[win]
        cxm[y0:y1, x0:x1][win] = cx
        cym[y0:y1, x0:x1][win] = cy
        rm[y0:y1, x0:x1][win] = max(rx, ry)

    for _ in range(int(8 + 110 * volume)):
        r = rng.uniform(4, 20) * (0.5 + size)
        cx, cy = rng.uniform(0, W), rng.uniform(0, H)
        if trails and r > 11 * (0.5 + size) and rng.random() < 0.6 * trails:
            # goutte qui a glissé : sillon mouillé fin, perles éparses au-dessus d'elle
            length = rng.uniform(90, 340) * trails
            x = cx
            for t in np.arange(r * 0.6, length, 2.0):
                x += rng.normal(0, 0.35)
                rr = r * 0.22 * (1 - t / length * 0.5)
                put(x, cy - t, rr, rr * 1.6, top=0.55)
                if rng.random() < 0.04:
                    put(x, cy - t, rr * 1.8, rr * 2.0)
        put(cx, cy, r, r * rng.uniform(1.0, 1.2))
    for _ in range(int(300 + 3500 * volume)):  # gouttelettes très fines (bruine)
        r = rng.uniform(0.8, 3.0) * (0.6 + size * 0.6)
        put(rng.uniform(0, W), rng.uniform(0, H), r, r)
    return h, cxm, cym, rm


def apply_drops(a, drops, focus_blur=2.0):
    """Chaque goutte est une petite lentille : elle montre une vue réduite et inversée de
    l'image autour d'elle, assombrie au bord, avec un reflet clair en haut à gauche."""
    h, cxm, cym, rm = drops
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    zoom = 5.0  # la goutte « voit » une zone 5 fois plus large qu'elle
    sx = np.clip(cxm - (xx - cxm) * zoom, 0, W - 1)
    sy = np.clip(cym - (yy - cym) * zoom - rm * 2.0, 0, H - 1)
    src = blur(a, 2.5)
    refr = src[sy.astype(int), sx.astype(int)]
    refr = refr * 1.08 + 0.03  # l'eau concentre la lumière
    wet = np.clip(h * 5, 0, 1)[..., None]
    base = blur(a, focus_blur) if focus_blur else a  # l'eau sur l'objectif adoucit tout
    out = base * (1 - wet) + refr * wet
    # bord de la goutte plus sombre (là où la lumière est déviée hors de l'objectif)
    rim = (np.clip(1 - h, 0, 1) ** 3 * (h > 0.01))[..., None]
    out = out * (1 - 0.55 * rim)
    # reflet spéculaire : petit point clair en haut à gauche de la goutte
    d = np.hypot(xx - (cxm - rm * 0.35), yy - (cym - rm * 0.4)) / np.maximum(rm, 1)
    spec = np.clip(1 - d / 0.22, 0, 1) ** 1.5 * (h > 0.3) * (rm > 2.5)
    out = out + spec[..., None] * 0.6
    return np.clip(out, 0, 1)


def rain(a, *, volume=0.5, size=0.5, trails=0.5, mood=0.7, falling=0.4, fog=0.3,
         focus_blur=1.6, seed=7):
    rng = np.random.default_rng(seed)
    a = grade(a, mood)
    if fog:
        a = haze(a, fog)
    if falling:
        a = falling_rain(a, falling, rng)
    drops = drops_map(rng, volume, size, trails)
    return apply_drops(a, drops, focus_blur if volume > 0 else 0)


def save(a, name):
    Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).save(OUT / name)


if __name__ == "__main__":
    rue, lac = scene_rue(), scene_lac()
    save(rue, "rue_original.png")
    save(lac, "lac_original.png")
    save(rain(rue, volume=0.2, size=0.35, trails=0.2, mood=0.5, falling=0.25, fog=0.15),
         "rue_pluie_legere.png")
    save(rain(rue), "rue_pluie_moyenne.png")
    save(rain(rue, volume=0.95, size=0.75, trails=1.0, mood=0.9, falling=0.8, fog=0.45),
         "rue_averse.png")
    save(rain(rue, volume=0.0, mood=0.8, falling=0.6, fog=0.35), "rue_ambiance_seule.png")
    save(rain(lac), "lac_pluie_moyenne.png")
    save(rain(lac, volume=0.95, size=0.75, trails=1.0, mood=0.9, falling=0.8, fog=0.5),
         "lac_averse.png")
