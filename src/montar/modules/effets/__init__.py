# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Effets » : effets vidéo composés de filtres MLT / FFmpeg, et zooms
animés (pseudo-filtre `montar.zoom` de l'API 1.3)."""
from __future__ import annotations

from montar.api import ZOOM, Param, VideoEffect


def _amount(values, key="intensite") -> float:
    return max(0.0, min(1.0, float(values.get(key, 0.5))))


class VHS(VideoEffect):
    id = "effets.vhs"
    name = "VHS"
    description = "Image de cassette vidéo : couleurs baveuses, grain, lignes de balayage."
    icon = "monitor-play"
    params = [Param.float("intensite", "Intensité", 0.0, 1.0, default=0.6),
              Param.bool("lignes", "Lignes de balayage", True)]

    def filters(self, values):
        a = _amount(values)
        shift = max(1, round(6 * a))
        result = [
            ("avfilter.rgbashift", {"av.rh": shift, "av.bh": -shift}),  # couleurs baveuses
            ("avfilter.eq", {"av.saturation": round(1 - 0.35 * a, 3),
                             "av.contrast": round(1 + 0.15 * a, 3),
                             "av.brightness": round(0.03 * a, 3)}),
            ("avfilter.gblur", {"av.sigma": round(0.3 + 0.9 * a, 2)}),
            ("avfilter.noise", {"av.alls": round(4 + 22 * a), "av.allf": "t+u"}),
        ]
        if values.get("lignes", True):
            result.append(("frei0r.scanline0r", {}))
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
    description = "Contours encrés et aplats de couleurs, comme une case de BD."
    icon = "palette"
    params = [Param.float("intensite", "Contours", 0.0, 1.0, default=0.4),
              Param.float("couleurs", "Aplats", 0.0, 1.0, default=0.5)]

    def filters(self, values):
        edges = _amount(values)
        flat = _amount(values, "couleurs")
        # aplats (moins de niveaux de couleur) puis contours : l'ordre compte
        return [
            ("avfilter.eq", {"av.saturation": round(1.2 + 0.5 * flat, 3),
                             "av.contrast": round(1.05 + 0.15 * flat, 3)}),
            ("frei0r.posterize", {"levels": round(0.45 - 0.3 * flat, 3)}),
            ("frei0r.cartoon", {"triplevel": round(0.995 - 0.017 * edges, 4)}),
        ]


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
