#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prototype du moteur de montar sous Windows (point ouvert n° 1 du cahier des charges).

Vérifie, avec le vrai moteur de montar, que la pile MSYS2 (Python, PyQt6, MLT, FFmpeg,
frei0r) suffit : filtres disponibles, rendu d'une image d'aperçu, export MP4. Écrit un
compte rendu (JSON et Markdown) et les fichiers produits dans le dossier donné.

    python scripts/windows/prototype.py SORTIE
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# filtres et services dont montar se sert (moteur, effets intégrés, son, étalonnage, suivi)
NEEDED = ["affine", "brightness", "volume", "obscure", "dynamictext", "rbpitch",
          "avfilter.eq", "avfilter.colortemperature", "avfilter.exposure", "avfilter.gblur",
          "avfilter.boxblur", "avfilter.chromashift", "avfilter.colorbalance",
          "avfilter.noise", "avfilter.drawbox", "avfilter.drawtext", "avfilter.vignette",
          "avfilter.colorkey", "avfilter.despill", "avfilter.lutrgb", "avfilter.curves",
          "avfilter.hue", "avfilter.vibrance", "avfilter.lut3d", "avfilter.median",
          "avfilter.bilateral", "avfilter.afftdn", "avfilter.dynaudnorm",
          "avfilter.acompressor", "avfilter.aecho", "avfilter.stereotools",
          "avfilter.highpass", "avfilter.lowpass", "avfilter.bass", "avfilter.treble",
          "avfilter.equalizer", "frei0r.cartoon", "frei0r.posterize", "frei0r.distort0r",
          "frei0r.glitch0r", "frei0r.scanline0r"]
NEEDED_TRANSITIONS = ["mix", "luma", "affine", "frei0r.cairoblend"]


class Report:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.steps: list[dict] = []

    def step(self, name: str, fn):
        start = time.monotonic()
        entry = {"étape": name}
        try:
            entry["résultat"] = fn()
            entry["ok"] = True
        except Exception as exc:  # le compte rendu continue : on veut tout voir d'un coup
            entry["ok"] = False
            entry["erreur"] = f"{type(exc).__name__} : {exc}"
            entry["trace"] = traceback.format_exc(limit=6)
        entry["durée_s"] = round(time.monotonic() - start, 2)
        self.steps.append(entry)
        mark = "OK " if entry["ok"] else "ÉCHEC"
        print(f"[{mark}] {name} ({entry['durée_s']} s)", flush=True)
        if not entry["ok"]:
            print(entry["trace"], flush=True)
        return entry.get("résultat")

    def write(self) -> bool:
        ok = all(s["ok"] for s in self.steps)
        (self.out / "rapport.json").write_text(
            json.dumps({"ok": ok, "étapes": self.steps}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        lines = ["# Prototype Windows du moteur de montar", "",
                 f"**Résultat : {'réussi' if ok else 'échec'}**", "",
                 "| Étape | | Durée | Détail |", "|---|---|---|---|"]
        for s in self.steps:
            detail = s.get("erreur") or json.dumps(s.get("résultat"), ensure_ascii=False)
            if len(detail) > 300:
                detail = detail[:300] + "…"
            lines.append(f"| {s['étape']} | {'✅' if s['ok'] else '❌'} | {s['durée_s']} s | "
                         f"{detail.replace('|', '/')} |")
        text = "\n".join(lines) + "\n"
        (self.out / "rapport.md").write_text(text, encoding="utf-8")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(text)
        return ok


def environment() -> dict:
    info = {"système": platform.platform(), "python": sys.version.split()[0],
            "exécutable": sys.executable}
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    info["pyqt6"], info["qt"] = PYQT_VERSION_STR, QT_VERSION_STR
    ffmpeg = shutil.which("ffmpeg")
    info["ffmpeg"] = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True,
                                    encoding="utf-8").stdout.splitlines()[0] if ffmpeg else None
    for var in ("MLT_REPOSITORY", "MLT_DATA", "MLT_PROFILES_PATH", "FREI0R_PATH"):
        info[var] = os.environ.get(var)
    return info


def mlt_services() -> dict:
    from montar.engine import mlt_engine

    mlt_engine._ensure_factory()
    mlt = mlt_engine.mlt
    repo = mlt.Factory().init()
    filters = repo.filters()
    names = {filters.get_name(i) for i in range(filters.count())}
    missing = [n for n in NEEDED if n not in names]
    transitions = repo.transitions()
    available = {transitions.get_name(i) for i in range(transitions.count())}
    missing += [n for n in NEEDED_TRANSITIONS if n not in available]
    return {"mlt": mlt.mlt_version_get_string(), "filtres": len(names),
            "manquants": missing, "rendu_natif": mlt_engine._native_get_image() is not None}


def make_media(out: Path) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    video, sound = out / "mire.mp4", out / "son.wav"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=25:duration=3", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=3", str(sound)], check=True)
    return {"vidéo": video.stat().st_size, "son": sound.stat().st_size}


def timeline(out: Path):
    from montar.core.project import AudioAdjust, ColorAdjust, Grade, Transform
    from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec

    video = ClipSpec(str(out / "mire.mp4"), "video", 0, 75, media_size=(640, 360),
                     transform=Transform(scale=0.8, rotation=5, opacity=0.9),
                     color=ColorAdjust(saturation=0.3), grade=Grade(gain=[0.4, 0.0]),
                     extra_filters=(("avfilter.noise", {"av.alls": 12, "av.allf": "t+u"}),))
    music = ClipSpec(str(out / "son.wav"), "audio", 0, 75, volume=0.7, fade_in=10,
                     audio=AudioAdjust(bass=3, pan=-0.3))
    return TimelineSpec(Canvas(1280, 720, 25), (TrackSpec("video", False, False, (video,)),
                                               TrackSpec("audio", False, False, (music,))))


def render_frame(out: Path) -> dict:
    from PyQt6.QtGui import QImage

    from montar.engine import get_engine

    source = get_engine().build(timeline(out))
    try:
        start = time.monotonic()
        data = source.render(30, 640, 360)
        elapsed = time.monotonic() - start
    finally:
        source.close()
    image = QImage(data, 640, 360, 640 * 4, QImage.Format.Format_RGBA8888)
    image.save(str(out / "apercu.png"))
    centre = image.pixelColor(320, 180)
    return {"octets": len(data), "rendu_ms": round(elapsed * 1000),
            "centre": centre.name(), "pas_noir": centre.value() > 20}


def export_mp4(out: Path) -> dict:
    from montar.engine import get_engine
    from montar.engine.export import ExportSettings

    target = out / "export.mp4"
    job = get_engine().export(timeline(out), ExportSettings(str(target), "mp4", "h264", 1280,
                                                            720, 25))
    job.start()
    if not job.wait(300):
        raise RuntimeError("export trop long")
    if job.error:
        raise RuntimeError(job.error)
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                            "stream=codec_name,width,height:format=duration", "-of", "json",
                            str(target)], capture_output=True, text=True, encoding="utf-8")
    data = json.loads(probe.stdout)
    return {"taille": target.stat().st_size, "durée": data["format"]["duration"],
            "flux": [s["codec_name"] for s in data["streams"]]}


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "prototype-windows").resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = Report(out)
    report.step("Environnement", environment)
    report.step("MLT et filtres", mlt_services)
    report.step("Médias de test", lambda: make_media(out))
    report.step("Image d'aperçu", lambda: render_frame(out))
    report.step("Export MP4", lambda: export_mp4(out))
    return 0 if report.write() else 1


if __name__ == "__main__":
    sys.exit(main())
