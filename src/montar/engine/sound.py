# SPDX-License-Identifier: GPL-3.0-or-later
"""Réglages du son d'un clip traduits en filtres MLT / FFmpeg, et atténuation sous la voix
(« ducking ») calculée à partir des pistes de voix."""
from __future__ import annotations

from montar.core.project import AudioAdjust

DUCK_RAMP_SECONDS = 0.3  # descente et remontée du volume autour d'une voix


def audio_filters(a: AudioAdjust) -> list[tuple[str, dict]]:
    """Chaîne dans l'ordre d'un studio : nettoyage, égalisation, dynamique, hauteur, espace."""
    result: list[tuple[str, dict]] = []
    if a.highpass > 0:
        result.append(("avfilter.highpass", {"av.f": round(a.highpass)}))
    if a.lowpass > 0:
        result.append(("avfilter.lowpass", {"av.f": round(a.lowpass)}))
    if a.denoise > 0:
        result.append(("avfilter.afftdn", {"av.nr": round(6 + 34 * a.denoise, 1),
                                           "av.nf": round(-50 + 15 * a.denoise, 1),
                                           "av.tn": 1}))
    if a.bass:
        result.append(("avfilter.bass", {"av.f": 120, "av.g": round(a.bass, 1)}))
    if a.mid:
        result.append(("avfilter.equalizer", {"av.f": 1200, "av.t": "o", "av.w": 1.2,
                                              "av.g": round(a.mid, 1)}))
    if a.treble:
        result.append(("avfilter.treble", {"av.f": 6000, "av.g": round(a.treble, 1)}))
    if a.compress > 0:
        result.append(("avfilter.acompressor", {
            "av.threshold": round(10 ** ((-12 - 18 * a.compress) / 20), 4),
            "av.ratio": round(2 + 6 * a.compress, 2), "av.attack": 15, "av.release": 200,
            "av.makeup": round(1 + 2 * a.compress, 2)}))
    if a.normalize:
        result.append(("avfilter.dynaudnorm", {"av.f": 250, "av.g": 15, "av.p": 0.9}))
    if a.pitch:
        result.append(("rbpitch", {"octaveshift": round(a.pitch / 12, 4)}))
    if a.echo > 0:
        result.append(("avfilter.aecho", {"av.in_gain": 0.9, "av.out_gain": 0.85,
                                          "av.delays": "320|640",
                                          "av.decays": f"{0.25 + 0.3 * a.echo:.2f}|"
                                                       f"{0.1 + 0.2 * a.echo:.2f}"}))
    if a.reverb > 0:  # petite salle : échos très rapprochés
        d = 0.15 + 0.35 * a.reverb
        result.append(("avfilter.aecho", {
            "av.in_gain": 0.8, "av.out_gain": 0.8, "av.delays": "23|37|53|71|97",
            "av.decays": "|".join(f"{d * k:.2f}" for k in (1.0, 0.85, 0.7, 0.55, 0.4))}))
    if a.pan:
        result.append(("avfilter.stereotools", {"av.balance_out": round(a.pan, 3)}))
    return result


def voice_spans(project) -> list[tuple[int, int]]:
    """Intervalles (début, fin) où une piste de voix non coupée a un clip qui sonne."""
    voices = {t.id for t in project.tracks if t.kind == "audio" and t.voice and not t.muted}
    spans = sorted((c.start, c.start + c.duration) for c in project.clips
                   if c.track_id in voices and c.volume > 0)
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def duck_points(spans: list[tuple[int, int]], clip_start: int, duration: int, depth: float,
                fps: int) -> list[tuple[int, float]] | None:
    """Points (image relative au clip, gain en dB) de l'atténuation sous la voix ; None si
    aucune voix ne recouvre le clip."""
    ramp = max(1, round(DUCK_RAMP_SECONDS * fps))
    near: list[tuple[int, int]] = []
    for start, end in spans:  # deux voix rapprochées : le volume ne remonte pas entre elles
        if near and start - near[-1][1] < 2 * ramp:
            near[-1] = (near[-1][0], max(near[-1][1], end))
        else:
            near.append((start, end))
    points: list[tuple[int, float]] = []
    for start, end in near:
        a, b = start - clip_start, end - clip_start
        if b + ramp <= 0 or a - ramp >= duration:
            continue
        points += [(a - ramp, 0.0), (a, -depth), (b, -depth), (b + ramp, 0.0)]
    if not points:
        return None

    def gain_at(f: int) -> float:
        for (x0, g0), (x1, g1) in zip(points, points[1:], strict=False):
            if x0 <= f <= x1:
                return g0 if x1 == x0 else g0 + (g1 - g0) * (f - x0) / (x1 - x0)
        return 0.0

    last = max(0, duration - 1)
    inside = [(x, g) for x, g in points if 0 < x < last]
    return [(0, round(gain_at(0), 2)), *inside, (last, round(gain_at(last), 2))]
