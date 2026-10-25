# SPDX-License-Identifier: GPL-3.0-or-later
"""Stabilisation (F-EDT-12) : analyse puis correction du mouvement avec vid.stab (FFmpeg),
en deux passes sur le fichier entier ; le résultat est mis en cache."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

MODULE_ID = "studio"


class StabilizeError(RuntimeError):
    pass


def settings_of(clip) -> dict | None:
    data = clip.modules.get(MODULE_ID)
    return data if isinstance(data, dict) and "stabilize" in data else None


def strength_of(data: dict) -> float:
    return max(0.0, min(1.0, float(data.get("stabilize", 0.5))))


def cache_path(cache_dir: Path, media_path: str, strength: float) -> Path:
    p = Path(media_path)
    try:
        stamp = f"{p.stat().st_mtime_ns}:{p.stat().st_size}"
    except OSError:
        stamp = "missing"
    key = hashlib.sha1(f"{p.resolve()}|{stamp}|{strength:.2f}".encode()).hexdigest()[:20]
    return cache_dir / "stabilisation" / f"{key}.mp4"


def available() -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "vidstabdetect" in out and "vidstabtransform" in out


def _run(cmd: list[str], duration: float, progress: Callable[[float], None], low: float,
         high: float, cancelled: Callable[[], bool], cwd: str | None = None) -> None:
    """Lance ffmpeg ; l'avancement (`-progress`) est ramené dans [low, high]."""
    process = subprocess.Popen([cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, cwd=cwd)
    try:
        assert process.stdout is not None
        for line in process.stdout:
            if cancelled():
                process.kill()
                raise StabilizeError("annulé")
            if line.startswith("out_time_us=") and duration > 0:
                try:
                    done = int(line.split("=", 1)[1]) / 1e6 / duration
                except ValueError:
                    continue
                progress(low + (high - low) * max(0.0, min(1.0, done)))
        process.wait()
        if process.returncode != 0:
            error = (process.stderr.read() if process.stderr else "").strip()
            raise StabilizeError(error.splitlines()[-1] if error else "échec de ffmpeg")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def stabilize(source: str, target: Path, strength: float, duration: float,
              progress: Callable[[float], None], cancelled: Callable[[], bool]) -> None:
    """Analyse (passe 1) puis corrige (passe 2) ; le son est copié tel quel."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise StabilizeError("ffmpeg est introuvable")
    target.parent.mkdir(parents=True, exist_ok=True)
    shakiness = round(4 + 6 * strength)
    smoothing = round(8 + 40 * strength)
    source = str(Path(source).resolve())
    target = target.resolve()
    with tempfile.TemporaryDirectory(prefix="montar-stab-") as tmp:
        # fichier d'analyse nommé sans chemin (ffmpeg lancé dans le dossier temporaire) : un
        # chemin Windows (« C:\… ») casserait la syntaxe des filtres
        trf = "transforms.trf"
        _run([ffmpeg, "-y", "-v", "error", "-i", source, "-vf",
              f"vidstabdetect=shakiness={shakiness}:accuracy=12:result={trf}", "-f", "null",
              "-"], duration, progress, 0.0, 0.4, cancelled, tmp)
        partial = target.with_suffix(".tmp.mp4")
        # zoom optimal : les bords noirs laissés par la correction sont rognés
        _run([ffmpeg, "-y", "-v", "error", "-i", source, "-map", "0:v:0", "-map", "0:a?",
              "-vf", f"vidstabtransform=input={trf}:smoothing={smoothing}:optzoom=1:"
                     f"interpol=bicubic,unsharp=5:5:0.6:3:3:0.3",
              "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p",
              "-c:a", "copy", str(partial)], duration, progress, 0.4, 1.0, cancelled, tmp)
        partial.replace(target)
    progress(1.0)
