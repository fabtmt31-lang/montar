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


class VHS(VideoEffect):
    id = "effets.vhs"
    name = "VHS"
    description = ("Cassette vidéo des années 80-90 : image douce, couleurs baveuses et "
                   "ternies, grain, défauts de bande, affichage « PLAY ».")
    icon = "monitor-play"
    params = [Param.float("intensite", "Intensité", 0.0, 1.0, default=0.6),
              Param.bool("defauts", "Défauts de bande (parasites, ondulation)", True),
              Param.choice("affichage", "Affichage du magnétoscope",
                           [("lecture", "PLAY ▶"), ("lecture_date", "PLAY ▶ et date"),
                            ("aucun", "Aucun")]),
              Param.bool("lignes", "Lignes de balayage", False)]

    def filters(self, values):
        a = _amount(values)
        result = [
            # bande passante réduite : image douce, couleur beaucoup plus floue que le noir
            # et blanc, puis décalée vers la droite (bavure)
            ("avfilter.boxblur", {"av.luma_radius": f"w/{round(1200 - 700 * a)}",
                                  "av.luma_power": 1,
                                  "av.chroma_radius": f"w/{round(420 - 260 * a)}",
                                  "av.chroma_power": 2}),
            ("avfilter.chromashift", {"av.cbh": max(1, round(4 * a)),
                                      "av.crh": max(1, round(5 * a)), "av.edge": 1}),
            # couleurs délavées, noirs relevés, dominante chaude dans les hautes lumières
            ("avfilter.eq", {"av.saturation": round(1 - 0.3 * a, 3),
                             "av.contrast": round(1 - 0.14 * a, 3),
                             "av.brightness": round(0.045 * a, 3),
                             "av.gamma": round(1 + 0.06 * a, 3)}),
            ("avfilter.colorbalance", {"av.rs": round(0.05 * a, 3), "av.bs": round(0.07 * a, 3),
                                       "av.rh": round(0.05 * a, 3),
                                       "av.bh": round(-0.06 * a, 3)}),
            ("avfilter.noise", {"av.alls": round(8 + 26 * a), "av.allf": "t+u",
                                "av.c0s": round(4 + 8 * a)}),
        ]
        if values.get("defauts", True):
            result[2:2] = [
                # ondulation des lignes et décrochages de la bande (aléatoires)
                ("frei0r.distort0r", {"0": round(0.002 + 0.006 * a, 4),
                                      "1": round(0.02 + 0.04 * a, 3), "2": 0, "3": 0.6}),
                ("frei0r.glitch0r", {"0": round(0.03 + 0.08 * a, 3), "1": 0.06,
                                     "2": round(0.01 + 0.03 * a, 3), "3": 0.15}),
            ]
            # bande de parasites en bas de l'image (changement de tête de lecture)
            result.append(("avfilter.drawbox", {"av.x": 0, "av.y": "ih*0.955", "av.w": "iw",
                                                "av.h": "ih*0.045",
                                                "av.color": f"white@{0.06 + 0.12 * a:.2f}",
                                                "av.t": "fill"}))
        if values.get("lignes", False):
            result.append(("frei0r.scanline0r", {}))
        result.append(("avfilter.vignette", {"av.angle": round(0.25 + 0.3 * a, 3)}))
        shown = values.get("affichage", "lecture")
        if shown in ("lecture", "lecture_date"):
            result.append(_vcr_text("PLAY ▶", "w*0.06", "h*0.07", "h/12"))
        if shown == "lecture_date":
            today = date.today()
            result.append(_vcr_text(f"{MONTHS[today.month - 1]} {today.day:02d} {today.year}",
                                    "w*0.06", "h*0.83", "h/14"))
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
