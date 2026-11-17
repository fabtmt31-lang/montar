# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Effets » : effets vidéo composés de filtres MLT / FFmpeg, et zooms
animés (pseudo-filtre `montar.zoom` de l'API 1.3)."""
from __future__ import annotations

from datetime import date

from montar.api import ZOOM, Param, VideoEffect
from montar.platform.paths import assets_dir


def _amount(values, key="intensite") -> float:
    return max(0.0, min(1.0, float(values.get(key, 0.5))))


# mois à l'anglaise, comme sur les caméscopes (pas une chaîne d'interface)
MONTHS = "JAN. FEB. MAR. APR. MAY JUN. JUL. AUG. SEP. OCT. NOV. DEC.".split()


def _vcr_text(text: str, x: str, y: str, size: str) -> tuple[str, dict]:
    """Texte d'affichage de magnétoscope ; taille relative à la hauteur de l'image."""
    font = assets_dir() / "fonts" / "JetBrainsMono_500Medium.ttf"
    return ("avfilter.drawtext", {
        "av.text": text, "av.fontfile": str(font), "av.fontsize": size, "av.x": x, "av.y": y,
        "av.fontcolor": "0xF4F4F0", "av.shadowcolor": "black@0.45", "av.shadowx": 2,
        "av.shadowy": 2})


def _vhs_levels(values) -> tuple[float, float, float]:
    """(couleur, grain, défauts) de 0 à 1. Les clips réglés avant la 1.15 n'avaient qu'une
    intensité et une case « défauts » : ils gardent un rendu proche, sans socle fixe."""
    if isinstance(values.get("defauts"), bool) or (
            "intensite" in values and "couleur" not in values):
        a = _amount(values)
        return a, a * 0.8, a if values.get("defauts", True) else 0.0
    return (_amount(values, "couleur"), _amount(values, "grain"),
            _amount(values, "defauts"))


def _vhs_date(values) -> str:
    """Date du magnétoscope : celle saisie (« 24 DEC 1994 »), sinon celle du jour."""
    text = str(values.get("date") or "").strip().upper()
    if text:
        return text
    today = date.today()
    return f"{MONTHS[today.month - 1]} {today.day:02d} {today.year}"


class VHS(VideoEffect):
    id = "effets.vhs"
    name = "VHS"
    description = ("Cassette vidéo des années 80-90 : couleurs baveuses et ternies, grain, "
                   "défauts de bande, affichage « PLAY » ou « REC ». À zéro, l'image reste "
                   "propre.")
    icon = "monitor-play"
    params = [Param.float("couleur", "Couleur de cassette", 0.0, 1.0, default=0.5),
              Param.float("grain", "Grain", 0.0, 1.0, default=0.3),
              Param.float("defauts", "Défauts de bande", 0.0, 1.0, default=0.25),
              Param.choice("affichage", "Affichage",
                           [("lecture", "PLAY ▶"), ("lecture_date", "PLAY ▶ et date"),
                            ("rec", "● REC"), ("rec_date", "● REC, date et compteur"),
                            ("aucun", "Aucun")]),
              Param.text("date", "Date affichée", placeholder="Date du jour (ex. 24 DEC 1994)"),
              Param.bool("lignes", "Lignes de balayage", False)]
    presets = {"leger": ("Léger", {"couleur": 0.3, "grain": 0.12, "defauts": 0.0}),
               "cassette": ("Cassette", {"couleur": 0.55, "grain": 0.35, "defauts": 0.3}),
               "vieille": ("Vieille cassette", {"couleur": 0.9, "grain": 0.65,
                                                "defauts": 0.8})}

    def filters(self, values):
        color, grain, faults = _vhs_levels(values)
        result = []
        if color > 0.01:
            # bande passante réduite : couleur plus floue que le noir et blanc, décalée
            result.append(("avfilter.boxblur", {
                "av.luma_radius": f"w/{round(1600 - 900 * color)}", "av.luma_power": 1,
                "av.chroma_radius": f"w/{round(700 - 450 * color)}", "av.chroma_power": 2}))
            shift_b, shift_r = round(4 * color), round(5 * color)
            if shift_b or shift_r:
                result.append(("avfilter.chromashift", {"av.cbh": shift_b, "av.crh": shift_r,
                                                        "av.edge": 1}))
            # couleurs délavées, noirs relevés, dominante chaude dans les hautes lumières
            result += [
                ("avfilter.eq", {"av.saturation": round(1 - 0.3 * color, 3),
                                 "av.contrast": round(1 - 0.14 * color, 3),
                                 "av.brightness": round(0.045 * color, 3),
                                 "av.gamma": round(1 + 0.06 * color, 3)}),
                ("avfilter.colorbalance", {"av.rs": round(0.05 * color, 3),
                                           "av.bs": round(0.07 * color, 3),
                                           "av.rh": round(0.05 * color, 3),
                                           "av.bh": round(-0.06 * color, 3)}),
            ]
        if faults > 0.01:
            # ondulation des lignes ; décrochages seulement sur une bande bien usée
            result.append(("frei0r.distort0r", {"0": round(0.008 * faults, 4),
                                                "1": round(0.06 * faults, 3), "2": 0,
                                                "3": 0.6}))
            if faults > 0.4:
                f = (faults - 0.4) / 0.6
                result.append(("frei0r.glitch0r", {"0": round(0.01 + 0.1 * f, 3), "1": 0.06,
                                                   "2": round(0.01 + 0.03 * f, 3),
                                                   "3": 0.15}))
            # bande de parasites en bas de l'image (changement de tête de lecture)
            result.append(("avfilter.drawbox", {"av.x": 0, "av.y": "ih*0.955", "av.w": "iw",
                                                "av.h": "ih*0.045",
                                                "av.color": f"white@{0.2 * faults:.2f}",
                                                "av.t": "fill"}))
        if grain > 0.01:
            result.append(("avfilter.noise", {"av.alls": max(1, round(32 * grain)),
                                              "av.allf": "t+u",
                                              "av.c0s": max(1, round(10 * grain))}))
        if values.get("lignes", False):
            result.append(("frei0r.scanline0r", {}))
        if color > 0.01:
            result.append(("avfilter.vignette", {"av.angle": round(0.5 * color, 3)}))
        shown = values.get("affichage", "lecture")
        if shown in ("lecture", "lecture_date"):
            result.append(_vcr_text("PLAY ▶", "w*0.06", "h*0.07", "h/12"))
        if shown in ("rec", "rec_date"):
            # point rouge qui clignote (une demi-seconde sur deux), comme un caméscope
            dot = _vcr_text("●", "w*0.94-text_w-h/12*2.2", "h*0.07", "h/12")
            dot[1].update({"av.fontcolor": "0xE0332B", "av.alpha": "lt(mod(t,1),0.5)"})
            result += [dot, _vcr_text("REC", "w*0.94-text_w", "h*0.07", "h/12")]
        if shown in ("lecture_date", "rec_date"):
            result.append(_vcr_text(_vhs_date(values), "w*0.06", "h*0.83", "h/14"))
        if shown == "rec_date":  # compteur qui défile depuis le début du clip
            result.append(_vcr_text("%{pts:gmtime:0:%H\\:%M\\:%S}", "w*0.94-text_w",
                                    "h*0.83", "h/14"))
        return result


class _Zoom(VideoEffect):
    """Zoom (ou dézoom) du cadre du clip autour de son centre."""

    icon = "zoom-in"
    inward = True
    fast = False

    @property
    def params(self):
        params = [Param.float("intensite", "Intensité", 0.05, 1.0, default=0.25)]
        if self.fast:
            params.append(Param.float("duree", "Durée", 0.2, 3.0, default=0.6, unit="s"))
        return params

    def filters(self, values):
        big = 1.0 + _amount(values)
        start, end = (1.0, big) if self.inward else (big, 1.0)
        seconds = float(values.get("duree", 0.6)) if self.fast else 0
        return [(ZOOM, {"start": start, "end": end, "seconds": seconds,
                        "ease": "smooth" if self.fast else "linear"})]


class SlowZoom(_Zoom):
    id = "effets.zoom_lent"
    name = "Zoom lent"
    description = "Avance doucement dans l'image pendant toute la durée du clip (Ken Burns)."


class FastZoom(_Zoom):
    id = "effets.zoom_rapide"
    name = "Zoom rapide"
    description = "Zoom avant marqué au début du clip, puis l'image reste agrandie."
    fast = True


class SlowZoomOut(_Zoom):
    id = "effets.dezoom_lent"
    name = "Dézoom lent"
    description = "Part d'un cadrage serré et recule doucement jusqu'à l'image entière."
    icon = "zoom-out"
    inward = False


class FastZoomOut(_Zoom):
    id = "effets.dezoom_rapide"
    name = "Dézoom rapide"
    description = "Recul rapide au début du clip, du cadrage serré à l'image entière."
    icon = "zoom-out"
    inward = False
    fast = True


class Comic(VideoEffect):
    id = "effets.bd"
    name = "Bande dessinée"
    description = ("Contours encrés et aplats de couleurs, comme une case de BD ; le trait "
                   "peut vibrer comme dans un vieux dessin animé.")
    icon = "palette"
    params = [Param.float("intensite", "Contours", 0.0, 1.0, default=0.5),
              Param.float("couleurs", "Aplats", 0.0, 1.0, default=0.5),
              Param.bool("vivant", "Trait vivant (vieux dessin animé)", False)]

    def filters(self, values):
        edges = _amount(values)
        flat = _amount(values, "couleurs")
        result = [
            # textures lissées d'abord : les contours ne gardent que les vraies formes
            ("avfilter.median", {"av.radius": 4}),
            ("avfilter.bilateral", {"av.sigmaS": 12, "av.sigmaR": 0.15}),
            ("frei0r.cartoon", {"triplevel": round(0.9985 - 0.007 * edges, 4),
                                "diffspace": 0.004}),
            ("avfilter.eq", {"av.saturation": round(1.1 + 0.4 * flat, 3),
                             "av.contrast": round(1.02 + 0.1 * flat, 3)}),
            ("frei0r.posterize", {"levels": round(0.5 - 0.3 * flat, 3)}),
        ]
        if values.get("vivant", False):
            # un grain différent à chaque image déplace un peu les contours détectés, et
            # l'image ondule légèrement : le trait « bouillonne » comme s'il était redessiné
            result.insert(0, ("avfilter.noise", {"av.alls": 22, "av.allf": "t"}))
            result.append(("frei0r.distort0r", {"0": 0.003, "1": 0.02, "2": 0, "3": 0.6}))
        return result


class Blur(VideoEffect):
    id = "effets.flou"
    name = "Flou"
    description = "Flou réglable : doux, de mouvement (horizontal ou vertical) ou en carrés."
    icon = "droplets"
    params = [Param.choice("style", "Style", [("doux", "Doux"),
                                              ("horizontal", "Mouvement horizontal"),
                                              ("vertical", "Mouvement vertical"),
                                              ("carres", "En carrés")]),
              Param.float("intensite", "Intensité", 0.0, 1.0, default=0.5)]

    def filters(self, values):
        a = _amount(values)
        style = values.get("style", "doux")
        if style in ("horizontal", "vertical"):
            return [("avfilter.dblur", {"av.angle": 0 if style == "horizontal" else 90,
                                        "av.radius": round(2 + 40 * a)})]
        if style == "carres":
            return [("frei0r.squareblur", {"Kernel size": round(0.02 + 0.3 * a, 3)})]
        return [("avfilter.gblur", {"av.sigma": round(0.5 + 20 * a, 2)})]


def register(api):
    for effect in (VHS, SlowZoom, FastZoom, SlowZoomOut, FastZoomOut, Comic, Blur):
        api.add_video_effect(effect)
