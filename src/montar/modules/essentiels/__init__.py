# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Essentiels » : un exemple de chaque type de l'API 1.2 (effets audio,
transitions, générateurs, formats d'export)."""
from __future__ import annotations

from montar.api import AudioEffect, ExportFormat, Generator, Param, Transition

from .images import write_luma, write_png

# --- effets audio ---------------------------------------------------------------------------


class Echo(AudioEffect):
    id = "essentiels.echo"
    name = "Écho"
    description = "Répète le son avec un retard, comme dans une grande salle."
    icon = "music"
    params = [Param.float("retard", "Retard", 50, 1000, default=300, unit="ms"),
              Param.float("force", "Force", 0.1, 0.9, default=0.4)]

    def filters(self, values):
        delay = round(float(values["retard"]))
        decay = max(0.05, min(0.95, float(values["force"])))
        return [("avfilter.aecho", {"av.in_gain": 0.8, "av.out_gain": 0.9,
                                    "av.delays": str(delay), "av.decays": f"{decay:.2f}"})]


class Equalizer(AudioEffect):
    id = "essentiels.egaliseur"
    name = "Graves et aigus"
    description = "Renforce ou atténue les sons graves et aigus."
    icon = "volume-2"
    params = [Param.float("graves", "Graves", -12, 12, default=0, unit="dB"),
              Param.float("aigus", "Aigus", -12, 12, default=0, unit="dB")]

    def filters(self, values):
        result = []
        bass, treble = float(values["graves"]), float(values["aigus"])
        if abs(bass) >= 0.1:
            result.append(("avfilter.bass", {"av.g": round(bass, 1)}))
        if abs(treble) >= 0.1:
            result.append(("avfilter.treble", {"av.g": round(treble, 1)}))
        return result


class Leveler(AudioEffect):
    id = "essentiels.niveleur"
    name = "Volume égalisé"
    description = "Rapproche le volume des passages faibles et forts (voix, interviews)."
    icon = "gauge"
    params = [Param.float("force", "Force", 0.0, 1.0, default=0.5)]

    def filters(self, values):
        amount = max(0.0, min(1.0, float(values["force"])))
        # fenêtre courte = égalisation plus marquée
        return [("avfilter.dynaudnorm", {"av.f": round(500 - 350 * amount),
                                         "av.m": round(3 + 12 * amount, 1)})]


# --- transitions ----------------------------------------------------------------------------


class _Luma(Transition):
    shape = ""

    def transition(self, context, duration):
        pattern = write_luma(context.cache_dir / "essentiels" / f"{self.shape}.pgm", self.shape)
        return "luma", {"resource": str(pattern), "softness": 0.12}


class Circle(_Luma):
    id = "essentiels.cercle"
    name = "Cercle"
    description = "La vidéo suivante apparaît dans un cercle qui s'agrandit."
    icon = "circle-dot"
    shape = "circle"


class WipeDown(_Luma):
    id = "essentiels.volet_bas"
    name = "Volet vers le bas"
    description = "La vidéo suivante descend comme un rideau."
    icon = "chevron-left"
    shape = "down"


class Diagonal(_Luma):
    id = "essentiels.diagonale"
    name = "Diagonale"
    description = "Balayage en diagonale, du coin haut gauche."
    icon = "arrow-left-right"
    shape = "diagonal"


# --- générateurs ----------------------------------------------------------------------------


class SolidColor(Generator):
    id = "essentiels.fond"
    name = "Fond uni"
    description = "Image d'une seule couleur, à la taille du projet (fond de titre, pause)."
    icon = "palette"
    params = [Param.color("couleur", "Couleur", "#2F7A56")]

    def generate(self, context, values, target):
        write_png(target, context.width, context.height, values["couleur"])


class Gradient(Generator):
    id = "essentiels.degrade"
    name = "Dégradé"
    description = "Dégradé de deux couleurs, vertical ou horizontal."
    icon = "droplets"
    params = [Param.color("debut", "Première couleur", "#2F7A56"),
              Param.color("fin", "Seconde couleur", "#0B120E"),
              Param.choice("sens", "Sens", [("vertical", "De haut en bas"),
                                            ("horizontal", "De gauche à droite")])]

    def generate(self, context, values, target):
        write_png(target, context.width, context.height, values["debut"], values["fin"],
                  values["sens"])


# --- formats d'export -----------------------------------------------------------------------

_CRF = (28, 23, 18)
_AUDIO = ("128k", "192k", "256k")


class Matroska(ExportFormat):
    id = "essentiels.mkv"
    name = "MKV"
    extension = ".mkv"
    description = "Matroska, H.264 et AAC : lu par VLC et la plupart des lecteurs."

    def properties(self, settings):
        level = settings.level
        return {"f": "matroska", "vcodec": "libx264", "crf": _CRF[level],
                "preset": ("veryfast", "medium", "slow")[level], "pix_fmt": "yuv420p",
                "acodec": "aac", "ab": _AUDIO[level], "g": max(1, settings.fps * 2)}


class ProRes(ExportFormat):
    id = "essentiels.prores"
    name = "ProRes"
    extension = ".mov"
    description = "Apple ProRes 422 : gros fichier de très haute qualité, pour retravailler."

    def properties(self, settings):
        return {"f": "mov", "vcodec": "prores_ks", "profile": (1, 2, 3)[settings.level],
                "pix_fmt": "yuv422p10le", "acodec": "pcm_s16le"}


def register(api):
    for effect in (Echo, Equalizer, Leveler):
        api.add_audio_effect(effect)
    for transition in (Circle, WipeDown, Diagonal):
        api.add_transition(transition)
    for generator in (SolidColor, Gradient):
        api.add_generator(generator)
    for fmt in (Matroska, ProRes):
        api.add_export_format(fmt)
