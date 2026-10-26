# SPDX-License-Identifier: GPL-3.0-or-later
"""Finition pro traduite pour le moteur : filtres appliqués à l'image composée et au son
mixé, équilibre voix / musique, harmonisation des plans et pistes séparées (stems).

Les égaliseurs biquad de FFmpeg restent sans effet quand MLT les applique : l'égaliseur et
le coupe-bas passent par le module « sox » de MLT."""
from __future__ import annotations

import dataclasses
import math

from montar.core.mastering import EQ_BANDS, AudioMaster, Mastering, VideoMaster
from montar.engine.base import MasterSpec, TimelineSpec
from montar.engine.grading import curve_string, grade_filters
from montar.engine.looks import color_filters

Filters = list[tuple[str, dict[str, object]]]

LEGAL_KNEE = 0.9  # début de l'adoucissement des hautes lumières
LEGAL_MAX = 0.98  # niveau le plus haut atteint (reste dans la plage TV après conversion)
LIMITER_MARGIN = 1.0  # dB sous la crête visée : le limiteur ne mesure pas la crête vraie
VOICE_BOOST = 2.0  # dB ajoutés aux voix quand « voix devant » est au maximum
MUSIC_CUT = 8.0  # dB retirés au reste
STEMS = ("dialog", "music")  # dialogues (voix ou son des vidéos), musique et effets


# --- image -------------------------------------------------------------------------------

def _mix_curve(target: list[tuple[float, float]], amount: float) -> str:
    """Courbe entre l'identité (amount = 0) et `target` (amount = 1)."""
    return curve_string([[x, x + (y - x) * amount] for x, y in target])


def _balance(amount: float, **values: float) -> tuple[str, dict]:
    return ("avfilter.colorbalance",
            {f"av.{k}": round(max(-1.0, min(1.0, v * amount)), 4) for k, v in values.items()})


def _eq(contrast: float = 1.0, saturation: float = 1.0) -> tuple[str, dict]:
    return ("avfilter.eq", {"av.contrast": round(contrast, 4),
                            "av.saturation": round(saturation, 4)})


def look_filters(look: str, amount: float, lut: str = "") -> Filters:
    a = max(0.0, min(1.0, amount))
    if look == "lut":
        return [("avfilter.lut3d", {"av.file": lut, "av.interp": "tetrahedral"})] if lut else []
    if a == 0:
        return []
    if look == "natural":
        return [("avfilter.curves", {"av.m": _mix_curve(
                    [(0, 0), (0.25, 0.22), (0.75, 0.78), (1, 1)], a)}),
                _eq(1 + 0.05 * a, 1 + 0.1 * a)]
    if look == "cinema":
        return [_balance(a, rs=-0.06, bs=0.08, rh=0.06, bh=-0.05),
                ("avfilter.curves", {"av.m": _mix_curve(
                    [(0, 0.05), (0.3, 0.27), (0.7, 0.74), (1, 0.96)], a)}),
                _eq(1.0, 1 - 0.12 * a)]
    if look == "warm":
        return [("avfilter.colortemperature", {"av.temperature": round(6500 - 2000 * a)}),
                _eq(1.0, 1 + 0.08 * a)]
    if look == "cool":
        return [("avfilter.colortemperature", {"av.temperature": round(6500 + 3500 * a)}),
                _eq(1.0, 1 - 0.05 * a)]
    if look == "teal_orange":
        return [_balance(a, rs=-0.14, gs=0.02, bs=0.14, rm=0.04, bm=-0.04, rh=0.12, gh=0.02,
                         bh=-0.14),
                _eq(1 + 0.1 * a, 1 + 0.12 * a)]
    if look == "film":
        return [("avfilter.curves", {"av.m": _mix_curve(
                    [(0, 0.07), (0.25, 0.25), (0.75, 0.76), (1, 0.93)], a)}),
                _balance(a, rm=0.04, bm=-0.05, bs=0.03),
                _eq(1.0, 1 - 0.22 * a)]
    if look == "bw":
        return [_eq(1 + 0.1 * a, 1 - a)]
    return []


def legal_filter() -> tuple[str, dict]:
    """Adoucit les hautes lumières au lieu de les écrêter (aucun blanc « brûlé »)."""
    k, m = LEGAL_KNEE, LEGAL_MAX
    x = "(val/maxval)"
    soft = f"({k}+{m - k:.4f}*(1-exp(-({x}-{k})/{m - k:.4f})))"
    expr = f"clip(if(gt({x},{k}),{soft},{x})*maxval,0,maxval)"
    return ("avfilter.lutrgb", {"av.r": expr, "av.g": expr, "av.b": expr})


def video_master_filters(v: VideoMaster, lut: str = "") -> Filters:
    """Ordre d'un étalonneur : correction primaire, roues et courbes, look, texture,
    puis conformité."""
    filters: Filters = list(color_filters(v.color))
    if v.tint:  # > 0 : magenta (moins de vert)
        filters.append(_balance(1.0, gs=-0.1 * v.tint, gm=-0.15 * v.tint, gh=-0.1 * v.tint))
    filters += grade_filters(dataclasses.replace(v.grade, lut=""), "")
    filters += look_filters(v.look, v.look_amount, lut)
    if v.vignette > 0:
        filters.append(("avfilter.vignette", {"av.angle": round(0.15 + 0.6 * v.vignette, 4)}))
    if v.grain > 0:
        filters.append(("avfilter.noise", {"av.alls": round(4 + 26 * v.grain),
                                           "av.allf": "t+u"}))
    if v.legal:
        filters.append(legal_filter())
    return filters


def match_filter(values: list[float], amount: float = 1.0) -> tuple[str, dict]:
    """Correction d'un plan : gain et décalage par canal (harmonisation)."""
    a = max(0.0, min(1.0, amount))
    props = {}
    for i, ch in enumerate("rgb"):
        gain = 1 + (float(values[i]) - 1) * a
        offset = float(values[3 + i]) * a
        props[f"av.{ch}"] = f"clip(val*{gain:.4f}+{offset:.4f}*maxval,0,maxval)"
    return ("avfilter.lutrgb", props)


def consumer_color(v: VideoMaster) -> dict:
    """Métadonnées de couleur du fichier exporté."""
    trc = "iec61966-2-1" if v.color_space == "srgb" else "bt709"
    return {"color_primaries": "bt709", "color_trc": trc}


# --- son ---------------------------------------------------------------------------------

def _sox(effect: str) -> tuple[str, dict]:
    return ("sox", {"effect": effect})


def eq_filters(gains: list[float]) -> Filters:
    filters: Filters = []
    for i, (freq, gain) in enumerate(zip(EQ_BANDS, gains, strict=False)):
        if abs(gain) < 0.05:
            continue
        g = round(max(-12.0, min(12.0, gain)), 2)
        if i == 0:
            filters.append(_sox(f"bass {g:g} {freq}"))
        elif i == len(EQ_BANDS) - 1:
            filters.append(_sox(f"treble {g:g} {freq}"))
        else:
            filters.append(_sox(f"equalizer {freq} 1.2q {g:g}"))
    return filters


def limiter_filter(true_peak: float) -> tuple[str, dict]:
    limit = 10 ** ((true_peak - LIMITER_MARGIN) / 20)
    return ("avfilter.alimiter", {"av.limit": round(max(0.0625, min(1.0, limit)), 5),
                                  "av.level": 0, "av.attack": 5, "av.release": 60})


def audio_master_filters(a: AudioMaster, gain_db: float = 0.0, limiter: bool = True) -> Filters:
    """Nettoyage, égalisation, dynamique, espace, niveau, puis limiteur de crête."""
    filters: Filters = []
    if a.cleanup:
        filters.append(_sox("highpass 70"))
        filters.append(("avfilter.deesser", {"av.i": 0.4, "av.f": 0.5}))
    filters += eq_filters(a.eq)
    if a.compress > 0:
        c = max(0.0, min(1.0, a.compress))
        filters.append(("avfilter.acompressor", {
            "av.threshold": round(10 ** ((-14 - 14 * c) / 20), 4),
            "av.ratio": round(1.5 + 3 * c, 2), "av.attack": 20, "av.release": 250,
            "av.makeup": round(10 ** ((3 + 6 * c) / 20), 3)}))
    if abs(a.width - 1.0) > 0.01:
        filters.append(("avfilter.extrastereo", {"av.m": round(max(0.0, min(2.0, a.width)), 3)}))
    if abs(gain_db) > 0.01:
        filters.append(("volume", {"level": round(gain_db, 2)}))
    if limiter and a.limiter:
        filters.append(limiter_filter(a.true_peak))
    return filters


# --- application à la timeline -----------------------------------------------------------

def dialog_tracks(spec: TimelineSpec) -> set[int]:
    """Pistes des dialogues : les pistes de voix si elles ont des clips, sinon le son des
    pistes vidéo (la voix prise à la caméra)."""
    voices = {i for i, t in enumerate(spec.tracks) if t.role == "voice" and t.clips}
    if voices:
        return voices
    return {i for i, t in enumerate(spec.tracks) if t.role == "video" and t.clips
            and any(c.kind == "video" for c in t.clips)}


def has_sound(spec: TimelineSpec, stem: str | None = None) -> bool:
    """La timeline (ou le stem) a-t-elle au moins un clip qui peut sonner ?"""
    dialog = dialog_tracks(spec)
    for i, t in enumerate(spec.tracks):
        if t.muted or (stem == "dialog" and i not in dialog) or (stem == "music" and i in dialog):
            continue
        if any(c.kind in ("video", "audio") and c.volume > 0 for c in t.clips):
            return True
    return False


def apply_master(spec: TimelineSpec, mastering: Mastering, *, gain_db: float = 0.0,
                 limiter: bool = True, stem: str | None = None, lut: str = "",
                 video: bool = True, audio: bool = True) -> TimelineSpec:
    """Timeline avec la finition : corrections des plans, équilibre des pistes, filtres de
    l'image et du son. `stem` ne garde que les dialogues (« dialog ») ou la musique et les
    effets (« music »). `gain_db` est le gain de loudness calculé par l'analyse."""
    v, a = mastering.video, mastering.audio
    dialog = dialog_tracks(spec)
    boost = 10 ** (VOICE_BOOST * a.voice_front / 20)
    cut = 10 ** (-MUSIC_CUT * a.voice_front / 20)
    tracks = []
    for i, track in enumerate(spec.tracks):
        changes: dict = {}
        if audio and a.voice_front > 0 and track.role in ("video", "voice", "music"):
            changes["volume"] = track.volume * (boost if i in dialog else cut)
        if (stem == "dialog" and i not in dialog) or (stem == "music" and i in dialog):
            changes["muted"] = True
        if video and v.match_shots and v.matches and track.kind == "video":
            clips = []
            for c in track.clips:
                values = v.matches.get(c.key)
                if values and len(values) == 6 and c.kind in ("video", "image"):
                    c = dataclasses.replace(c, extra_filters=c.extra_filters + (
                        match_filter(values, v.match_amount),))
                clips.append(c)
            changes["clips"] = tuple(clips)
        tracks.append(dataclasses.replace(track, **changes) if changes else track)
    master = MasterSpec(
        tuple(video_master_filters(v, lut)) if video else (),
        tuple(audio_master_filters(a, gain_db, limiter)) if audio else ())
    return dataclasses.replace(spec, tracks=tuple(tracks), master=master)


def loudness_gain(measured: float, target: float) -> float:
    """Gain (dB) qui amène la loudness mesurée sur la cible ; 0 pour un son muet."""
    if measured is None or measured <= -69 or not math.isfinite(measured):
        return 0.0
    return round(max(-30.0, min(30.0, target - measured)), 2)


# --- harmonisation des plans -------------------------------------------------------------

def frame_stats(rgba: bytes, width: int, height: int) -> list[float]:
    """Moyenne et écart type de chaque canal (0 à 1) d'une image RGBA."""
    import numpy as np

    pixels = np.frombuffer(rgba, dtype=np.uint8).reshape(height * width, 4)[:, :3] / 255.0
    return [*pixels.mean(axis=0).tolist(), *pixels.std(axis=0).tolist()]


def clipped_fraction(rgba: bytes, width: int, height: int) -> float:
    """Part des pixels écrêtés (un canal à 0 ou à 255 sur toute une zone)."""
    import numpy as np

    pixels = np.frombuffer(rgba, dtype=np.uint8).reshape(height * width, 4)[:, :3]
    high = (pixels >= 254).all(axis=1)
    low = (pixels <= 1).all(axis=1)
    return float((high | low).mean())


def match_values(reference: list[float], shot: list[float]) -> list[float]:
    """Gain et décalage par canal qui rapprochent les statistiques du plan de celles de la
    référence (transfert de moyenne et d'écart type, borné pour rester naturel)."""
    values_gain, values_offset = [], []
    for c in range(3):
        mean_r, std_r = reference[c], reference[3 + c]
        mean_s, std_s = shot[c], shot[3 + c]
        gain = std_r / std_s if std_s > 0.01 else 1.0
        gain = max(0.75, min(1.33, gain))
        offset = max(-0.2, min(0.2, mean_r - gain * mean_s))
        values_gain.append(round(gain, 4))
        values_offset.append(round(offset, 4))
    return values_gain + values_offset


def deviation(reference: list[float], shot: list[float]) -> float:
    """Écart de couleur entre un plan et la référence (0 = identique)."""
    return round(sum(abs(reference[i] - shot[i]) for i in range(3))
                 + 0.5 * sum(abs(reference[3 + i] - shot[3 + i]) for i in range(3)), 4)
