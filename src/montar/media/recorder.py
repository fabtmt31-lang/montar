# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran simplifié (F-MED-06) : écran, zone ou fenêtre (X11), micro et son
de l'ordinateur (PulseAudio / PipeWire), webcam en incrustation ; par ffmpeg.

Sous Windows : écran ou zone par ddagrab (Desktop Duplication : pixels réels, quelle que
soit la mise à l'échelle de Windows ; repli sur gdigrab), fenêtre par gdigrab, micro,
webcam et son de l'ordinateur (entrée « Mixage stéréo » si Windows la propose) par
DirectShow."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from montar.i18n import N_, _

ON_WINDOWS = sys.platform == "win32"

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
    webcam: str = ""  # v4l2 (/dev/video0) ou nom DirectShow ; vide = pas de webcam
    show_cursor: bool = True
    # Windows
    screen_index: int = 0  # écran filmé (ordre des écrans de Windows)
    region: tuple[int, int, int, int] | None = None  # zone dans cet écran, pixels réels
    window_title: str = ""  # titre de la fenêtre filmée (source « window »)


def session_problem() -> str:
    """Raison pour laquelle l'enregistrement est impossible ici, ou chaîne vide."""
    if shutil.which("ffmpeg") is None:
        return N_("ffmpeg est introuvable")
    if ON_WINDOWS:
        return ""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return N_("l'enregistrement d'écran n'est pas encore possible dans une session Wayland ; "
                  "ouvrez une session X11 (la session Cinnamon par défaut de Linux Mint)")
    if not os.environ.get("DISPLAY"):
        return N_("aucun affichage X11 (variable DISPLAY absente)")
    return ""


def webcams() -> list[str]:
    """Caméras v4l2 présentes (les nœuds de métadonnées ne sont pas filtrés ici), ou
    caméras DirectShow sous Windows."""
    if ON_WINDOWS:
        return dshow_devices("video")
    return sorted(glob.glob("/dev/video*"))


def dshow_devices(kind: str) -> list[str]:
    """Périphériques DirectShow (Windows) d'un type (« audio » ou « video »)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow",
                              "-i", "dummy"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10).stderr
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_dshow(out, kind)


def parse_dshow(listing: str, kind: str = "audio") -> list[str]:
    """Noms des périphériques d'un type dans la liste de ffmpeg (`-list_devices true`)."""
    names = []
    for line in listing.splitlines():
        found = re.search(r'"([^"]+)"\s*\((audio|video)\)', line)
        if found and found.group(2) == kind and found.group(1) not in names:
            names.append(found.group(1))
    return names


def can_pick_window() -> bool:
    """Sous Windows, la fenêtre se choisit dans une liste (titres des fenêtres ouvertes)."""
    return ON_WINDOWS or shutil.which("xwininfo") is not None


def can_select_region() -> bool:
    return True  # X11 : ffmpeg ; Windows : sélection à la souris dans montar


def can_record_system_audio() -> bool:
    return not ON_WINDOWS or bool(loopback_device())


# entrées DirectShow qui renvoient le son de l'ordinateur (selon la carte son, la langue
# de Windows ou un câble audio virtuel)
_LOOPBACK = tuple(  # (noms de périphériques, pas des textes à traduire)
    "stereo mix|mixage stéréo|mezcla estéreo|stereomix|what u hear|wave out|cable output|"
    "virtual-audio-capturer".split("|"))


def loopback_device() -> str:
    """Entrée DirectShow du son de l'ordinateur, ou chaîne vide."""
    return next((d for d in dshow_devices("audio")
                 if any(k in d.lower() for k in _LOOPBACK)), "")


_GRABBER: str | None = None


def windows_grabber() -> str:
    """« ddagrab » si ffmpeg le propose (Windows 8 et plus récents), sinon « gdigrab »."""
    global _GRABBER
    if _GRABBER is None:
        _GRABBER = "gdigrab"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is not None:
            try:
                out = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                                     text=True, errors="replace", timeout=15).stdout
                if " ddagrab " in out:
                    _GRABBER = "ddagrab"
            except (OSError, subprocess.SubprocessError):
                pass
    return _GRABBER


def window_titles() -> list[str]:
    """Titres des fenêtres visibles (Windows), pour filmer l'une d'elles."""
    if not ON_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titles: list[str] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value.strip()
                if title and title not in titles and title != "Program Manager":
                    titles.append(title)
        return True

    user32.EnumWindows(proc(visit), 0)
    return titles


def pick_window(timeout: float = 60.0) -> str:
    """Laisse l'utilisateur cliquer sur une fenêtre ; renvoie son identifiant X11."""
    out = subprocess.run(["xwininfo"], capture_output=True, text=True, timeout=timeout)
    for line in out.stdout.splitlines():
        if "Window id:" in line:
            return line.split("Window id:")[1].split()[0]
    return ""


def command(options: RecordOptions, target: str) -> list[str]:
    if ON_WINDOWS:
        return _command_windows(options, target)
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
    return _encode(cmd, options, audio, webcam, target)


def _command_windows(options: RecordOptions, target: str) -> list[str]:
    """Écran ou zone par ddagrab (ou gdigrab), fenêtre par gdigrab ; sons et webcam par
    DirectShow."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    mouse = "1" if options.show_cursor else "0"
    cmd = [ffmpeg, "-v", "error", "-y"]
    prefix = ""
    if options.source == "window" and options.window_title:
        cmd += ["-thread_queue_size", "512", "-f", "gdigrab", "-framerate", str(options.fps),
                "-draw_mouse", mouse, "-i", f"title={options.window_title}"]
    elif windows_grabber() == "ddagrab":
        grab = (f"ddagrab=output_idx={options.screen_index}:framerate={options.fps}"
                f":draw_mouse={mouse}")
        if options.source == "region" and options.region:
            rx, ry, rw, rh = options.region
            grab += f":offset_x={rx}:offset_y={ry}:video_size={rw - rw % 2}x{rh - rh % 2}"
        cmd += ["-f", "lavfi", "-i", grab]
        prefix = "hwdownload,format=bgra,"  # images rendues par la carte graphique
    else:
        x, y, w, h = options.geometry
        if options.source == "region" and options.region:
            rx, ry, w, h = options.region
            x, y = x + rx, y + ry
        cmd += ["-thread_queue_size", "512", "-f", "gdigrab", "-framerate", str(options.fps),
                "-draw_mouse", mouse, "-offset_x", str(x), "-offset_y", str(y),
                "-video_size", f"{w - w % 2}x{h - h % 2}", "-i", "desktop"]
    inputs, audio, webcam = 1, [], None
    microphone = next(iter(dshow_devices("audio")), "") if options.microphone else ""
    loopback = loopback_device() if options.system_audio else ""
    if microphone == loopback:  # seule entrée disponible : le son de l'ordinateur
        microphone = ""
    for device in (microphone, loopback):
        if device:
            cmd += ["-thread_queue_size", "1024", "-f", "dshow", "-audio_buffer_size", "50",
                    "-i", f"audio={device}"]
            audio.append(inputs)
            inputs += 1
    if options.webcam:
        cmd += ["-thread_queue_size", "512", "-f", "dshow", "-i", f"video={options.webcam}"]
        webcam = inputs
    return _encode(cmd, options, audio, webcam, target, prefix)


def _encode(cmd: list[str], options: RecordOptions, audio: list[int], webcam: int | None,
            target: str, prefix: str = "") -> list[str]:
    """Montage des entrées (écran, webcam en incrustation, sons mélangés) et encodage."""
    graph = [f"[0:v]{prefix}scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[screen]"]
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
            self.error = lines[-1] if lines else _("aucune image enregistrée")
        return ok
