# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran simplifié (F-MED-06) : écran, zone ou fenêtre (X11), micro et son
de l'ordinateur (PulseAudio / PipeWire), webcam en incrustation ; par ffmpeg."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

WEBCAM_WIDTH = 0.25  # largeur de l'incrustation, en fraction de la largeur de la vidéo


@dataclass
class RecordOptions:
    source: str = "screen"  # screen | region | window
    geometry: tuple[int, int, int, int] = (0, 0, 1920, 1080)  # x, y, largeur, hauteur
    window_id: str = ""  # identifiant X11 (source « window »)
    display: str = ""  # par défaut : $DISPLAY
    fps: int = 30
    microphone: bool = True
    system_audio: bool = False
    webcam: str = ""  # périphérique v4l2 (/dev/video0), vide = pas de webcam
    show_cursor: bool = True


def session_problem() -> str:
    """Raison pour laquelle l'enregistrement est impossible ici, ou chaîne vide."""
    if shutil.which("ffmpeg") is None:
        return "ffmpeg est introuvable"
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return ("l'enregistrement d'écran n'est pas encore possible dans une session Wayland ; "
                "ouvrez une session X11 (la session Cinnamon par défaut de Linux Mint)")
    if not os.environ.get("DISPLAY"):
        return "aucun affichage X11 (variable DISPLAY absente)"
    return ""


def webcams() -> list[str]:
    """Caméras v4l2 présentes (les nœuds de métadonnées ne sont pas filtrés ici)."""
    return sorted(glob.glob("/dev/video*"))


def can_pick_window() -> bool:
    return shutil.which("xwininfo") is not None


def pick_window(timeout: float = 60.0) -> str:
    """Laisse l'utilisateur cliquer sur une fenêtre ; renvoie son identifiant X11."""
    out = subprocess.run(["xwininfo"], capture_output=True, text=True, timeout=timeout)
    for line in out.stdout.splitlines():
        if "Window id:" in line:
            return line.split("Window id:")[1].split()[0]
    return ""


def command(options: RecordOptions, target: str) -> list[str]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    display = options.display or os.environ.get("DISPLAY", ":0")
    cmd = [ffmpeg, "-v", "error", "-y", "-thread_queue_size", "512", "-f", "x11grab",
           "-framerate", str(options.fps), "-draw_mouse", "1" if options.show_cursor else "0"]
    if options.source == "window" and options.window_id:
        cmd += ["-window_id", options.window_id, "-i", display]
    elif options.source == "region":
        cmd += ["-select_region", "1", "-i", display]
    else:
        x, y, w, h = options.geometry
        cmd += ["-video_size", f"{w - w % 2}x{h - h % 2}", "-i", f"{display}+{x},{y}"]
    inputs = 1
    audio = []
    for wanted, device in ((options.microphone, "default"),
                           (options.system_audio, "@DEFAULT_MONITOR@")):
        if wanted:
            cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", device]
            audio.append(inputs)
            inputs += 1
    webcam = None
    if options.webcam:
        cmd += ["-thread_queue_size", "512", "-f", "v4l2", "-i", options.webcam]
        webcam = inputs
        inputs += 1
    graph = ["[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[screen]"]
    video = "[screen]"
    if webcam is not None:
        graph.append(f"[{webcam}:v][screen]scale2ref=w=main_w*{WEBCAM_WIDTH}:h=ow/mdar"
                     "[cam][base]")
        graph.append("[base][cam]overlay=W-w-24:H-h-24,format=yuv420p[video]")
        video = "[video]"
    maps = ["-map", video]
    if len(audio) == 2:
        graph.append(f"[{audio[0]}:a][{audio[1]}:a]amix=inputs=2:duration=longest[audio]")
        maps += ["-map", "[audio]"]
    elif audio:
        maps += ["-map", f"{audio[0]}:a"]
    cmd += ["-filter_complex", ";".join(graph), *maps,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-r", str(options.fps)]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    return cmd + ["-movflags", "+faststart", target]


class Recorder:
    """Un enregistrement en cours : `stop()` termine proprement le fichier."""

    def __init__(self, options: RecordOptions, target: Path) -> None:
        self.options, self.target = options, target
        self._proc: subprocess.Popen | None = None
        self.started = 0.0
        self.error = ""

    def start(self) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.target.with_suffix(".log"), "w+b")  # noqa: SIM115
        self._proc = subprocess.Popen(self._command(),
                                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=self._log)
        self.started = time.monotonic()

    def _command(self) -> list[str]:
        return command(self.options, str(self.target))

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started if self.started else 0.0

    def stop(self, timeout: float = 15.0) -> bool:
        """Arrête l'enregistrement ; renvoie True si un fichier lisible a été écrit."""
        proc = self._proc
        if proc is None:
            return False
        if proc.poll() is None:
            try:
                proc.communicate(b"q", timeout=timeout)  # ffmpeg finalise le fichier
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(5)
        self._log.seek(0)
        lines = self._log.read().decode("utf-8", "replace").strip().splitlines()
        self._log.close()
        self.target.with_suffix(".log").unlink(missing_ok=True)
        ok = self.target.exists() and self.target.stat().st_size > 0
        if not ok:
            self.error = lines[-1] if lines else "aucune image enregistrée"
        return ok
