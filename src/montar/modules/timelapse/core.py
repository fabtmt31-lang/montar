# SPDX-License-Identifier: GPL-3.0-or-later
"""Timelapse : calculs (sans Qt), application à la timeline et pré-calcul avec ffmpeg.

Le segment accéléré est un clip ordinaire dont la vitesse vaut images source / images
produites. Il est rendu à partir d'un fichier pré-calculé (une image sur N, ou la moyenne
de N images), ce qui donne un aperçu fluide et un export identique."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from montar.core.timeline import TimelineError

MODULE_ID = "timelapse"
MIN_FACTOR, MAX_FACTOR = 2.0, 1000.0
PRESETS = (4, 8, 16, 32, 60)
METHODS = {"sample": "Échantillonnage", "blend": "Fusion d'images"}
RAMPS = {"none": "Aucune", "in": "Douce en entrée", "out": "Douce en sortie",
         "both": "Les deux"}
AUDIO = {"mute": "Couper", "remove": "Supprimer", "speed": "Accélérer"}


class Cancelled(Exception):
    pass


@dataclass
class Settings:
    factor: float = 16.0
    method: str = "sample"
    ramp: str = "none"
    ramp_seconds: float = 1.0
    audio: str = "mute"
    deflicker: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        s = cls()
        for key in asdict(s):
            if key in data:
                setattr(s, key, type(getattr(s, key))(data[key]))
        s.factor = max(MIN_FACTOR, min(MAX_FACTOR, s.factor))
        s.method = s.method if s.method in METHODS else "sample"
        s.ramp = s.ramp if s.ramp in RAMPS else "none"
        s.audio = s.audio if s.audio in AUDIO else "mute"
        s.ramp_seconds = max(0.0, min(3.0, s.ramp_seconds))
        return s

    def ramp_frames(self, fps: int) -> tuple[int, int]:
        r = round(self.ramp_seconds * fps)
        return (r if self.ramp in ("in", "both") else 0,
                r if self.ramp in ("out", "both") else 0)


def frame_indices(source_frames: int, factor: float, ramp_in: int = 0,
                  ramp_out: int = 0) -> list[int]:
    """Images source retenues (relatives au début du segment), dans l'ordre.

    Sans rampe : 0, N, 2N… (exactement une image sur N). Avec rampe, la vitesse passe
    progressivement de ×1 à ×N au début et/ou de ×N à ×1 à la fin."""
    s = max(1, int(source_frames))
    n = max(1.0, float(factor))
    if ramp_in == ramp_out == 0:
        return [min(s - 1, round(j * n)) for j in range(max(1, math.ceil(s / n)))]
    while (ramp_in + ramp_out) * (1 + n) / 2 > s and (ramp_in or ramp_out):
        ramp_in, ramp_out = ramp_in // 2, ramp_out // 2  # segment trop court pour les rampes
    steady = max(0, math.ceil((s - (ramp_in + ramp_out) * (1 + n) / 2) / n))
    total = ramp_in + steady + ramp_out
    positions, p = [], 0.0
    for j in range(total):
        positions.append(p)
        if j < ramp_in:
            p += 1 + (n - 1) * (j + 0.5) / ramp_in
        elif j >= total - ramp_out:
            p += 1 + (n - 1) * (total - 1 - j + 0.5) / ramp_out
        else:
            p += n
    scale = (s - 1) / positions[-1] if positions and positions[-1] > s - 1 else 1.0
    result, last = [], -1
    for x in positions:
        i = min(s - 1, max(last + 1, round(x * scale)))
        if i > s - 1:
            break
        result.append(i)
        last = i
    return result or [0]


def output_frames(source_frames: int, settings: Settings, fps: int) -> int:
    return len(frame_indices(source_frames, settings.factor, *settings.ramp_frames(fps)))


def factor_for_duration(source_frames: int, target_frames: int) -> float:
    """Facteur donnant la durée voulue (mode « durée cible »)."""
    return max(MIN_FACTOR, min(MAX_FACTOR, source_frames / max(1, target_frames)))


# --- application à la timeline ---------------------------------------------------------


def settings_of(clip) -> dict | None:
    return clip.modules.get(MODULE_ID)


def apply(timeline, clip_id: str, start: int, end: int, settings: Settings):
    """Accélère la partie [start, end[ du clip ; renvoie le clip du segment accéléré.

    Sur un segment déjà accéléré, la plage [start, end[ désigne ce segment : il est d'abord
    rendu à sa durée d'origine, puis accéléré avec les nouveaux réglages."""
    clip = timeline.clip(clip_id)
    existing = settings_of(clip)
    if existing is not None:
        original = round(int(existing["source_frames"])
                         / (float(existing.get("previous_speed", 1.0)) or 1.0))
        segment_start = clip.start
        clip = remove(timeline, clip_id)
        start, end = segment_start, segment_start + original
    start, end = max(clip.start, start), min(clip.end, end)
    if end - start < 2:
        raise TimelineError("la plage choisie est trop courte")
    if end < clip.end:
        timeline.split(clip.id, end)
    if start > clip.start:
        clip = timeline.split(clip.id, start)
    source_frames = max(1, round(clip.duration * clip.speed))
    produced = output_frames(source_frames, settings, timeline.fps)
    old_end = clip.end
    data = asdict(settings)
    data.update(locks_timing=True, source_frames=source_frames,
                previous_speed=clip.speed, previous_volume=clip.volume)
    for t in timeline.transitions_of(clip.id):
        timeline.remove_transition(t.id)
    clip.modules[MODULE_ID] = data
    clip.speed = source_frames / produced
    clip.duration = produced
    clip.fade_in, clip.fade_out = min(clip.fade_in, produced), min(clip.fade_out, produced)
    if settings.audio != "speed":
        clip.volume = 0.0
    timeline.shift_after(clip.track_id, old_end, clip.end - old_end, ignore=clip.id)
    return clip


def remove(timeline, clip_id: str):
    """Rend au segment sa vitesse et sa durée d'origine, puis le réunit à ses voisins."""
    clip = timeline.clip(clip_id)
    data = settings_of(clip)
    if data is None:
        return clip
    for t in timeline.transitions_of(clip.id):
        timeline.remove_transition(t.id)
    old_end = clip.end
    speed = float(data.get("previous_speed", 1.0)) or 1.0
    clip.speed = speed
    clip.duration = max(1, round(int(data.get("source_frames", clip.duration)) / speed))
    clip.volume = float(data.get("previous_volume", 1.0))
    del clip.modules[MODULE_ID]
    timeline.shift_after(clip.track_id, old_end, clip.end - old_end, ignore=clip.id)
    return timeline.merge_contiguous(clip.id)


# --- pré-calcul ----------------------------------------------------------------------------


def cache_path(cache_dir: Path, media_path: str, source_in: int, data: dict, fps: int) -> Path:
    p = Path(media_path)
    try:
        stamp = [p.stat().st_mtime_ns, p.stat().st_size]
    except OSError:
        stamp = None
    settings = asdict(Settings.from_dict(data))
    key = json.dumps([str(p.resolve()), stamp, source_in, data.get("source_frames"), fps,
                      settings], sort_keys=True)
    return cache_dir / "timelapse" / f"{hashlib.sha1(key.encode()).hexdigest()}.mp4"


def _atempo(ratio: float) -> str:
    """Chaîne atempo (chaque étage accepte au plus ×100 avec FFmpeg ≥ 5)."""
    parts = []
    while ratio > 100:
        parts.append("atempo=100")
        ratio /= 100
    parts.append(f"atempo={max(0.5, ratio):.6f}")
    return ",".join(parts)


def ffmpeg_command(source: str, output: Path, source_in: int, data: dict,
                   fps: int) -> tuple[list[str], int]:
    """Commande ffmpeg produisant le segment accéléré, et son nombre d'images."""
    settings = Settings.from_dict(data)
    source_frames = int(data["source_frames"])
    indices = frame_indices(source_frames, settings.factor, *settings.ramp_frames(fps))
    produced = len(indices)
    chain = [f"fps={fps}"]
    if settings.deflicker:
        chain.append("deflicker=size=5")
    shift = 0
    if settings.method == "blend":
        window = max(2, min(1024, round(settings.factor)))
        chain.append(f"tmix=frames={window}")
        shift = window - 1  # l'image n mélange les images n-window+1 … n
    n = settings.factor
    if settings.ramp == "none" and float(n).is_integer() and shift == 0:
        chain.append(f"select='not(mod(n\\,{int(n)}))'")
    else:
        terms = "+".join(f"eq(n\\,{min(source_frames - 1, i + shift)})" for i in indices)
        chain.append(f"select='{terms}'")
    chain.append(f"setpts=N/({fps}*TB)")
    cmd = [shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1",
           "-y", "-ss", f"{source_in / fps:.6f}", "-i", source, "-t",
           f"{source_frames / fps:.6f}", "-vf", ",".join(chain), "-fps_mode", "cfr",
           "-r", str(fps), "-frames:v", str(produced), "-c:v", "libx264", "-preset",
           "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-g", str(fps)]
    if settings.audio == "speed":
        cmd += ["-af", _atempo(source_frames / produced), "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-an"]
    cmd += ["-f", "mp4", str(output)]
    return cmd, produced


def render(source: str, output: Path, source_in: int, data: dict, fps: int,
           progress=lambda ratio: None, cancelled=lambda: False) -> Path:
    """Pré-calcule le segment ; écrit d'abord un fichier temporaire."""
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.stem + ".part.mp4")
    cmd, produced = ffmpeg_command(source, tmp, source_in, data, fps)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancelled():
                proc.terminate()
                raise Cancelled()
            if line.startswith("frame="):
                try:
                    progress(min(1.0, int(line[6:]) / produced))
                except ValueError:
                    pass
        code = proc.wait()
        if code != 0:
            error = (proc.stderr.read() if proc.stderr else "").strip().splitlines()
            raise RuntimeError(error[-1] if error else f"ffmpeg a échoué (code {code})")
        tmp.replace(output)
        progress(1.0)
        return output
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        tmp.unlink(missing_ok=True)
        raise
