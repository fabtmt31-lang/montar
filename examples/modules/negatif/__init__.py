# SPDX-License-Identifier: GPL-3.0-or-later
"""Module d'exemple : effet « Négatif » réglable. Voir docs/MODULES.md."""
from montar.api import Param, VideoEffect


class Negatif(VideoEffect):
    id = "exemple.negatif"
    name = "Négatif"
    description = "Inverse les couleurs de l'image, plus ou moins fortement."
    params = [Param.float("intensite", "Intensité", 0.0, 1.0, default=1.0)]

    def filters(self, values):
        a = float(values["intensite"])
        # chaque composante : (1 - a) × valeur + a × (255 - valeur)
        expr = f"(1-{a:.3f})*val+{a:.3f}*(maxval-val)"
        return [("avfilter.lutrgb", {"av.r": expr, "av.g": expr, "av.b": expr})]


def register(api):
    api.add_video_effect(Negatif)
