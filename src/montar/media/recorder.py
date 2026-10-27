# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran simplifié (F-MED-06) : écran, zone ou fenêtre (X11), micro et son
de l'ordinateur (PulseAudio / PipeWire), webcam en incrustation ; par ffmpeg.

Sous Windows : écran ou zone par ddagrab (Desktop Duplication : pixels réels, quelle que
soit la mise à l'échelle de Windows ; repli sur gdigrab), fenêtre par la zone qu'elle
occupe à l'écran (filmée seule, une fenêtre dessinée par la carte graphique — navigateur,
applications modernes — sortirait noire), micro, webcam et son de l'ordinateur (entrée
« Mixage stéréo » si Windows la propose) par DirectShow.

La webcam s'incruste dans un coin (taille et forme réglables) ou partage l'écran ; son
fond peut être flouté ou effacé (voir media/segment.py : calcul après l'enregistrement)."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from montar.i18n import N_, _

ON_WINDOWS = sys.platform == "win32"

WEBCAM_WIDTH = 0.25  # largeur de l'incrustation, en fraction de la largeur de la vidéo
WEBCAM_POSITIONS = ("bottom_right", "bottom_left", "top_right", "top_left",
                    "split_right", "split_left")
MARGIN = 24  # écart entre l'incrustation et le bord de l'image (pixels)
SPLIT_BACKGROUND = "0x17261E"  # fond de l'écran partagé (autour de l'écran réduit)


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
    microphone_device: str = ""  # micro choisi (source PulseAudio, nom DirectShow) ; vide :
    # celui par défaut
    # webcam : coin (taille = part de la largeur) ou écran partagé (part pour la webcam)
    webcam_position: str = "bottom_right"
    webcam_size: float = WEBCAM_WIDTH
    webcam_shape: str = "rect"  # rect | round
    webcam_background: str = "none"  # none | blur | remove (après l'enregistrement)

    @property
    def split(self) -> bool:
        return self.webcam_position.startswith("split")

    @property
    def processed(self) -> bool:
        """Fond de la webcam flouté ou effacé : la webcam est enregistrée à part puis
        assemblée avec l'écran une fois l'enregistrement fini."""
        return bool(self.webcam) and self.webcam_background in ("blur", "remove")

    def capture_size(self) -> tuple[int, int] | None:
        """Taille de l'image filmée, si elle est connue avant l'enregistrement."""
        if self.source == "region" and self.region:
            return self.region[2], self.region[3]
        if self.source == "screen":
            return self.geometry[2], self.geometry[3]
        return None


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


_DSHOW: tuple[float, str] | None = None  # (instant, liste de ffmpeg)
_DSHOW_LOCK = threading.Lock()
DSHOW_TTL = 120.0  # secondes avant de relire la liste des périphériques


def dshow_listing(refresh: bool = False) -> str:
    """Liste DirectShow de ffmpeg, gardée en mémoire : la relire lance ffmpeg (une à
    plusieurs secondes), ce qui bloquait la fenêtre d'enregistrement."""
    global _DSHOW
    with _DSHOW_LOCK:
        if not refresh and _DSHOW is not None and time.monotonic() - _DSHOW[0] < DSHOW_TTL:
            return _DSHOW[1]
        ffmpeg = shutil.which("ffmpeg")
        out = ""
        if ffmpeg is not None:
            try:
                out = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f",
                                      "dshow", "-i", "dummy"], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=10).stderr
            except (OSError, subprocess.SubprocessError):
                out = ""
        _DSHOW = (time.monotonic(), out)
        return out


def dshow_devices(kind: str) -> list[str]:
    """Périphériques DirectShow (Windows) d'un type (« audio » ou « video »)."""
    return parse_dshow(dshow_listing(), kind)


_WARMED = False


def warm_up() -> None:
    """Prépare en tâche de fond ce qui est long à découvrir (périphériques, méthode de
    capture, encodeur) : la fenêtre d'enregistrement s'ouvre et démarre aussitôt."""
    global _WARMED
    if _WARMED:
        return
    _WARMED = True

    def run() -> None:
        if ON_WINDOWS:
            dshow_listing()
            windows_grabber()
        recording_encoder()

    threading.Thread(target=run, name="montar-preparation", daemon=True).start()


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
_GRABBER_LOCK = threading.Lock()


def windows_grabber() -> str:
    """« ddagrab » s'il fonctionne sur cet ordinateur (Windows 8 et plus récents, carte
    graphique), sinon « gdigrab »."""
    global _GRABBER
    with _GRABBER_LOCK:
        return _grabber()


def _grabber() -> str:
    global _GRABBER
    if _GRABBER is None:
        _GRABBER = "gdigrab"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is not None:
            # essai réel d'une image : ddagrab demande une carte graphique et une session
            # de bureau (il échoue, par exemple, dans une machine virtuelle sans GPU)
            try:
                done = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                                       "ddagrab=framerate=5", "-frames:v", "1", "-f", "null",
                                       "-"], capture_output=True, timeout=15)
                if done.returncode == 0:
                    _GRABBER = "ddagrab"
            except (OSError, subprocess.SubprocessError):
                pass
    return _GRABBER


_ENCODER: list[str] | None = None
_ENCODER_LOCK = threading.Lock()
SOFTWARE_ENCODER = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                    "-crf", "23"]
# encodeurs matériels essayés sous Windows (carte NVIDIA, Intel, AMD) : l'enregistrement ne
# prend presque plus de processeur, l'image ne saccade plus
_HARDWARE_ENCODERS = (
    ["-c:v", "h264_nvenc", "-preset", "p2", "-tune", "ll", "-rc", "vbr", "-cq", "23",
     "-b:v", "0"],
    ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"],
    ["-c:v", "h264_amf", "-usage", "lowlatency", "-quality", "speed", "-rc", "cqp",
     "-qp_i", "22", "-qp_p", "24"],
)


def recording_encoder() -> list[str]:
    """Arguments de l'encodeur vidéo de l'enregistrement : matériel s'il marche vraiment
    (essai d'encodage), sinon x264 au plus rapide."""
    global _ENCODER
    with _ENCODER_LOCK:
        if _ENCODER is None:
            _ENCODER = SOFTWARE_ENCODER
            ffmpeg = shutil.which("ffmpeg")
            for args in _HARDWARE_ENCODERS if ON_WINDOWS and ffmpeg else ():
                try:
                    done = subprocess.run(
                        [ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                         "color=c=black:s=640x360:r=30:d=0.3", *args, "-f", "null", "-"],
                        capture_output=True, timeout=15)
                except (OSError, subprocess.SubprocessError):
                    continue
                if done.returncode == 0:
                    _ENCODER = args
                    break
        return list(_ENCODER)


def monitors() -> list[tuple[int, int, int, int]]:
    """Windows : rectangles (x, y, largeur, hauteur) des écrans, en pixels réels, dans
    l'ordre de Windows (celui de ddagrab)."""
    if not ON_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    found: list[tuple[int, int, int, int]] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def visit(_monitor, _dc, rect, _lparam):
        r = rect.contents
        found.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(visit), 0)
    return found


def on_monitor(area: tuple[int, int, int, int],
               screens: list[tuple[int, int, int, int]]
               ) -> tuple[int, tuple[int, int, int, int]] | None:
    """Écran qui contient le centre de `area` et la partie de `area` visible sur cet écran,
    relative à son coin (pour ddagrab)."""
    x, y, w, h = area
    cx, cy = x + w / 2, y + h / 2
    for index, (sx, sy, sw, sh) in enumerate(screens):
        if sx <= cx < sx + sw and sy <= cy < sy + sh:
            left, top = max(x, sx), max(y, sy)
            right, bottom = min(x + w, sx + sw), min(y + h, sy + sh)
            cw, ch = right - left, bottom - top
            if cw > 16 and ch > 16:
                return index, (left - sx, top - sy, cw - cw % 2, ch - ch % 2)
    return None


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


def window_rect(title: str) -> tuple[int, int, int, int] | None:
    """Windows : rectangle (x, y, largeur, hauteur) de la fenêtre à l'écran, en pixels réels
    et sans son ombre ; elle est d'abord remise au premier plan."""
    if not ON_WINDOWS or not title:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    rect = wintypes.RECT()
    try:  # DWMWA_EXTENDED_FRAME_BOUNDS : cadre visible, sans l'ombre de Windows 10 / 11
        ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0
    except (AttributeError, OSError):
        ok = False
    if not ok and not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    return (rect.left, rect.top, w, h) if w > 16 and h > 16 else None


def microphones() -> list[tuple[str, str]]:
    """Micros : (identifiant, nom affiché). Linux : sources PulseAudio / PipeWire (sauf les
    « moniteurs », qui renvoient le son de l'ordinateur) ; Windows : entrées DirectShow."""
    if ON_WINDOWS:
        loop = loopback_device()
        return [(d, d) for d in dshow_devices("audio") if d != loop]
    if shutil.which("pactl") is None:
        return []
    try:
        out = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_pactl_sources(out)


def parse_pactl_sources(listing: str) -> list[tuple[str, str]]:
    found, name = [], ""
    for line in listing.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Description:") and name:
            if not name.endswith(".monitor"):
                found.append((name, line.split(":", 1)[1].strip() or name))
            name = ""
    return found


def microphone_input(device: str) -> list[str]:
    """Arguments ffmpeg d'entrée du micro `device` (vide : celui par défaut)."""
    if ON_WINDOWS:
        name = device or next(iter(d for d, _n in microphones()), "")
        return ["-f", "dshow", "-audio_buffer_size", "50", "-i", f"audio={name}"] if name \
            else []
    return ["-f", "pulse", "-i", device or "default"]


class LevelMeter:
    """Test du micro : niveau sonore en direct (0 à 1), lu par ffmpeg dans un fil ; les
    dernières secondes sont gardées pour être réécoutées (`save_wav`)."""

    RATE = 16000
    KEEP_SECONDS = 8

    def __init__(self, device: str) -> None:
        self.level = 0.0
        self.error = ""
        self._samples = bytearray()
        self._proc: subprocess.Popen | None = None
        args = microphone_input(device)
        if not args or shutil.which("ffmpeg") is None:
            self.error = _("aucun micro")
            return
        cmd = [shutil.which("ffmpeg"), "-v", "error", *args, "-ac", "1", "-ar",
               str(self.RATE), "-f", "s16le", "-"]
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError as exc:
            self.error = str(exc)
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        import array

        assert self._proc is not None and self._proc.stdout is not None
        chunk = self.RATE // 10 * 2  # 0,1 s
        keep = self.RATE * 2 * self.KEEP_SECONDS
        while True:
            data = self._proc.stdout.read(chunk)
            if not data:
                break
            data = data[:len(data) // 2 * 2]
            self._samples += data
            if len(self._samples) > keep:
                del self._samples[:len(self._samples) - keep]
            samples = array.array("h", data)
            peak = max((abs(v) for v in samples), default=0) / 32768
            self.level = max(peak, self.level * 0.6)  # retombe doucement
        if self._proc.poll() not in (None, 0) and not self.error:
            self.error = _("le micro ne répond pas")

    @property
    def seconds(self) -> float:
        return len(self._samples) / 2 / self.RATE

    def save_wav(self, path: Path) -> bool:
        """Écrit les dernières secondes entendues ; False s'il n'y a rien."""
        import wave

        if not self._samples:
            return False
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(self.RATE)
            out.writeframes(bytes(self._samples))
        return True

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def webcam_input(device: str) -> list[str]:
    if ON_WINDOWS:
        return ["-f", "dshow", "-rtbufsize", "256M", "-i", f"video={device}"]
    return ["-f", "v4l2", "-i", device]


class CameraPreview:
    """Test de la webcam : petites images en direct (RGB, `size`), lues par ffmpeg."""

    def __init__(self, device: str, size: tuple[int, int] = (320, 180), fps: int = 15) -> None:
        self.size = size
        self.frame: bytes | None = None  # dernière image reçue
        self.error = ""
        self._proc: subprocess.Popen | None = None
        if not device or shutil.which("ffmpeg") is None:
            self.error = _("aucune webcam")
            return
        w, h = size
        cmd = [shutil.which("ffmpeg"), "-v", "error", *webcam_input(device), "-vf",
               f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=rgb24",
               "-f", "rawvideo", "-"]
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError as exc:
            self.error = str(exc)
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        size = self.size[0] * self.size[1] * 3
        while True:
            data = self._proc.stdout.read(size)
            if len(data) < size:
                break
            self.frame = data
        if self.frame is None and not self.error:
            self.error = _("la webcam ne répond pas (déjà utilisée par une autre application ?)")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def pick_window(timeout: float = 60.0) -> tuple[str, tuple[int, int, int, int] | None]:
    """Laisse l'utilisateur cliquer sur une fenêtre (X11) ; renvoie son identifiant et son
    rectangle à l'écran."""
    try:
        out = subprocess.run(["xwininfo"], capture_output=True, text=True,
                             timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return "", None
    return parse_xwininfo(out)


def parse_xwininfo(listing: str) -> tuple[str, tuple[int, int, int, int] | None]:
    window, values = "", {}
    for line in listing.splitlines():
        if "Window id:" in line:
            window = line.split("Window id:")[1].split()[0]
        key, _sep, value = line.strip().partition(":")
        if key in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
            try:
                values[key] = int(value.strip())
            except ValueError:
                pass
    if len(values) == 4:
        return window, (values["Absolute upper-left X"], values["Absolute upper-left Y"],
                        values["Width"], values["Height"])
    return window, None


# toutes les sources sont datées avec l'horloge de l'ordinateur au moment où elles sont lues,
# puis ramenées à un même instant de départ : le son, la webcam et l'écran restent
# synchrones même si une source démarre plus tard que les autres (webcam lente à s'ouvrir)
WALLCLOCK = ["-use_wallclock_as_timestamps", "1"]


def command(options: RecordOptions, target: str, t0: float | None = None,
            live_masks: bool = False) -> list[str]:
    """Commande ffmpeg de l'enregistrement ; `t0` : instant de départ commun (secondes,
    horloge de l'ordinateur) ; `live_masks` : images réduites de la webcam envoyées sur la
    sortie standard (détourage pendant l'enregistrement)."""
    t0 = time.time() if t0 is None else t0
    if ON_WINDOWS:
        return _command_windows(options, target, t0, live_masks)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    display = options.display or os.environ.get("DISPLAY", ":0")
    cmd = [ffmpeg, "-v", "error", "-y", "-copyts", *WALLCLOCK, "-thread_queue_size", "1024",
           "-f", "x11grab", "-framerate", str(options.fps),
           "-draw_mouse", "1" if options.show_cursor else "0"]
    size = options.capture_size()
    if options.source == "window" and options.window_id:
        cmd += ["-window_id", options.window_id, "-i", display]
    else:
        x, y, w, h = options.geometry
        if options.source == "region" and options.region:
            rx, ry, w, h = options.region
            x, y = x + rx, y + ry
        cmd += ["-video_size", f"{w - w % 2}x{h - h % 2}", "-i", f"{display}+{x},{y}"]
    inputs = 1
    audio = []
    for wanted, device in ((options.microphone, options.microphone_device or "default"),
                           (options.system_audio, "@DEFAULT_MONITOR@")):
        if wanted:
            cmd += [*WALLCLOCK, "-thread_queue_size", "4096", "-f", "pulse", "-i", device]
            audio.append(inputs)
            inputs += 1
    webcam = None
    if options.webcam:
        cmd += [*WALLCLOCK, "-thread_queue_size", "1024", *webcam_input(options.webcam)]
        webcam = inputs
    return _encode(cmd, options, audio, webcam, target, "", size, t0, live_masks)


def _command_windows(options: RecordOptions, target: str, t0: float,
                     live_masks: bool) -> list[str]:
    """Écran, zone ou fenêtre par ddagrab (ou gdigrab) ; sons et webcam par DirectShow."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    mouse = "1" if options.show_cursor else "0"
    cmd = [ffmpeg, "-v", "error", "-y", "-copyts"]
    prefix = ""
    size = options.capture_size()
    ddagrab = windows_grabber() == "ddagrab"
    output, part = options.screen_index, None  # écran et zone filmés par ddagrab
    if options.source == "region" and options.region:
        part = options.region
    area = window_rect(options.window_title) if options.source == "window" else None
    if area is not None and ddagrab:
        # fenêtre : la zone qu'elle occupe sur son écran (jamais noire)
        found = on_monitor(area, monitors())
        if found is not None:
            output, part = found
        else:
            ddagrab = False
    if options.source == "window" and area is None:  # fenêtre introuvable : par son titre
        cmd += [*WALLCLOCK, "-thread_queue_size", "1024", "-f", "gdigrab", "-framerate",
                str(options.fps), "-draw_mouse", mouse, "-i", f"title={options.window_title}"]
        size = None
    elif ddagrab:
        grab = f"ddagrab=output_idx={output}:framerate={options.fps}:draw_mouse={mouse}"
        if part is not None:
            px, py, pw, ph = part
            grab += f":offset_x={px}:offset_y={py}:video_size={pw - pw % 2}x{ph - ph % 2}"
            size = (pw - pw % 2, ph - ph % 2)
        cmd += [*WALLCLOCK, "-f", "lavfi", "-i", grab]
        prefix = "hwdownload,format=bgra,"  # images rendues par la carte graphique
    else:
        if area is not None:
            x, y, w, h = area
        else:
            x, y, w, h = options.geometry
            if part is not None:
                rx, ry, w, h = part
                x, y = x + rx, y + ry
        size = (w - w % 2, h - h % 2)
        cmd += [*WALLCLOCK, "-thread_queue_size", "1024", "-f", "gdigrab", "-framerate",
                str(options.fps), "-draw_mouse", mouse, "-offset_x", str(x), "-offset_y",
                str(y), "-video_size", f"{size[0]}x{size[1]}", "-i", "desktop"]
    inputs, audio, webcam = 1, [], None
    microphone = (options.microphone_device or next(iter(dshow_devices("audio")), "")) \
        if options.microphone else ""
    loopback = loopback_device() if options.system_audio else ""
    if microphone == loopback:  # seule entrée disponible : le son de l'ordinateur
        microphone = ""
    for device in (microphone, loopback):
        if device:
            cmd += [*WALLCLOCK, "-thread_queue_size", "4096", "-f", "dshow", "-rtbufsize",
                    "64M", "-audio_buffer_size", "50", "-i", f"audio={device}"]
            audio.append(inputs)
            inputs += 1
    if options.webcam:
        # grand tampon : une webcam en MJPEG ne perd plus d'images quand l'ordinateur force
        cmd += [*WALLCLOCK, "-thread_queue_size", "1024", *webcam_input(options.webcam)]
        webcam = inputs
    return _encode(cmd, options, audio, webcam, target, prefix, size, t0, live_masks)


def webcam_graph(screen: str, cam: str, options: RecordOptions,
                 size: tuple[int, int] | None, out: str = "[video]") -> list[str]:
    """Filtres ffmpeg qui posent la webcam `cam` sur l'image `screen` : dans un coin (taille
    `webcam_size` de la largeur, rectangle ou rond) ou en écran partagé (l'écran réduit d'un
    côté, la webcam recadrée de l'autre). `size` : taille de l'écran filmé si connue."""
    share = max(0.1, min(0.6, options.webcam_size))
    if options.split:
        w, h = size or (16, 9)
        aspect = share * w / h  # proportions de la bande de la webcam
        # écran réduit puis complété jusqu'à sa taille d'origine (la bande de la webcam)
        x = "0" if options.webcam_position == "split_right" else "ow-iw"
        cam_x = "W-w" if options.webcam_position == "split_right" else "0"
        return [
            f"{screen}scale=trunc(iw*{1 - share:g}/2)*2:-2,"
            f"pad=w=trunc(iw/{1 - share:g}/2)*2:h=trunc(ih/{1 - share:g}/2)*2:x={x}"
            f":y=(oh-ih)/2:color={SPLIT_BACKGROUND}[canvas]",
            f"{cam}crop='min(iw,ih*{aspect:.4f})':'min(ih,iw/{aspect:.4f})'[camcrop]",
            f"[camcrop][canvas]scale2ref=w=trunc(iw*{share:g}/2)*2:h=ih[cam][base]",
            f"[base][cam]overlay={cam_x}:0,format=yuv420p{out}",
        ]
    where = {"bottom_right": f"W-w-{MARGIN}:H-h-{MARGIN}",
             "bottom_left": f"{MARGIN}:H-h-{MARGIN}",
             "top_right": f"W-w-{MARGIN}:{MARGIN}",
             "top_left": f"{MARGIN}:{MARGIN}"}.get(options.webcam_position,
                                                   f"W-w-{MARGIN}:H-h-{MARGIN}")
    if options.webcam_shape == "round":
        # carré recadré au centre, réduit d'abord : le masque rond (geq, lent) ne porte
        # que sur les points de l'incrustation
        return [f"{cam}crop='min(iw,ih)':'min(iw,ih)'[square]",
                f"[square]{screen}scale2ref=w=trunc(iw*{share:g}/2)*2:h=ow[camsmall][base]",
                "[camsmall]format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
                "a='if(lte(hypot(X-W/2,Y-H/2),W/2-1),alpha(X,Y),0)'[cam]",
                f"[base][cam]overlay={where},format=yuv420p{out}"]
    # scale2ref : iw / ih sont ceux de l'image de référence (l'écran), main_a les
    # proportions de la webcam
    return [f"{cam}{screen}scale2ref=w=trunc(iw*{share:g}/2)*2:h=trunc(ow/main_a/2)*2"
            "[cam][base]",
            f"[base][cam]overlay={where},format=yuv420p{out}"]


def parts(target: str) -> tuple[str, str]:
    """Fichiers intermédiaires (écran avec le son, webcam) d'un enregistrement traité."""
    base = str(Path(target).with_suffix(""))
    return base + ".ecran.mkv", base + ".webcam.mkv"


def mask_part(target: str) -> str:
    """Vidéo des masques de la webcam (blanc = personne)."""
    return str(Path(target).with_suffix("")) + ".masques.mkv"


def start_time(path: str) -> float:
    """Instant de la première image (les fichiers de l'enregistrement gardent l'heure
    commune de départ : la webcam peut commencer après l'écran)."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return 0.0
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=start_time",
                              "-of", "csv=p=0", path], capture_output=True, text=True,
                             timeout=30).stdout.strip()
        return max(0.0, float(out or 0))
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


MASK_SIZE = (256, 144)  # images envoyées au détourage (taille du modèle)


def _encode(cmd: list[str], options: RecordOptions, audio: list[int], webcam: int | None,
            target: str, prefix: str = "", size: tuple[int, int] | None = None,
            t0: float = 0.0, live_masks: bool = False) -> list[str]:
    """Montage des entrées (écran, webcam, sons mélangés), ramenées à l'instant `t0`, et
    encodage."""
    shift = f"setpts=PTS-{t0:.6f}/TB"
    graph = [f"[0:v]{prefix}{shift},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[screen]"]
    for k, index in enumerate(audio):
        graph.append(f"[{index}:a]asetpts=PTS-{t0:.6f}/TB,aresample=async=1000[a{k}]")
    if len(audio) == 2:
        graph.append("[a0][a1]amix=inputs=2:duration=longest[audio]")
    elif audio:
        graph.append("[a0]anull[audio]")
    sound = ["-map", "[audio]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"] if audio \
        else []
    video = [*recording_encoder(), "-r", str(options.fps)]
    if webcam is not None:
        graph.append(f"[{webcam}:v]{shift}[cam0]")
    if webcam is not None and options.processed:
        # deux fichiers (l'écran avec le son, la webcam), assemblés après coup ; avec le
        # détourage en direct, images réduites de la webcam sur la sortie standard
        screen_part, cam_part = parts(target)
        outputs = ["-map", "[screen]", *video, *sound, screen_part,
                   "-map", "[camfile]", *video, "-pix_fmt", "yuv420p", cam_part]
        if live_masks:
            w, h = MASK_SIZE
            graph.append("[cam0]split=2[camfile][campipe]")
            graph.append(f"[campipe]scale={w}:{h},format=rgb24[campix]")
            outputs += ["-map", "[campix]", "-r", str(options.fps), "-f", "rawvideo",
                        "pipe:1"]
        else:
            graph.append("[cam0]null[camfile]")
        return cmd + ["-filter_complex", ";".join(graph), *outputs]
    label = "[screen]"
    if webcam is not None:
        graph += webcam_graph("[screen]", "[cam0]", options, size)
        label = "[video]"
    return cmd + ["-filter_complex", ";".join(graph), "-map", label, *video, *sound,
                  "-movflags", "+faststart", target]


def compose_command(options: RecordOptions, screen_part: str, cam_part: str, mask: str,
                    target: str, size: tuple[int, int] | None,
                    cam_start: float = 0.0) -> list[str]:
    """Assemblage final d'un enregistrement traité : fond de la webcam flouté ou effacé
    d'après les masques (`mask`, blanc = personne, une image par image de la webcam, à
    partir de `cam_start`), webcam placée sur l'écran. Les heures des fichiers sont
    gardées (-copyts) : le son, l'écran et la webcam restent alignés."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    graph = ["[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[screen]",
             f"[2:v]setpts=PTS-STARTPTS+{cam_start:.6f}/TB[maskat]",
             # masques agrandis à la taille de la webcam, bords adoucis
             "[maskat][1:v]scale2ref=w=iw:h=ih[maskbig][cam]",
             "[maskbig]format=gray,gblur=sigma=2[mask]"]
    if options.webcam_background == "blur":
        graph += ["[cam]split[camback][camfront]",
                  "[camback]gblur=sigma=18[blurred]",
                  "[camfront][mask]alphamerge[person]",
                  "[blurred][person]overlay=format=auto,format=yuv420p[camfx]"]
    else:  # effacé : seule la personne reste, posée sur l'écran
        graph += ["[cam]format=yuva420p[camrgba]", "[camrgba][mask]alphamerge[camfx]"]
    graph += webcam_graph("[screen]", "[camfx]", options, size)
    return [ffmpeg, "-v", "error", "-y", "-nostats", "-progress", "pipe:1", "-copyts",
            "-i", screen_part, "-i", cam_part, "-i", mask,
            "-filter_complex", ";".join(graph), "-map", "[video]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
            "-movflags", "+faststart", target]


class Finisher:
    """Après un enregistrement traité : masques de la webcam (media/segment.py) puis
    assemblage, dans un fil. Mêmes attributs qu'un export : `progress`, `finished`,
    `error`, `cancelled`."""

    def __init__(self, options: RecordOptions, target: Path, seconds: float,
                 masks_ready: bool = False) -> None:
        self.options, self.target = options, target
        self.total = max(1, round(seconds * options.fps))
        self.done = 0
        # masques déjà calculés pendant l'enregistrement : seul l'assemblage reste
        self.masks_ready = masks_ready
        self.phase = "compose" if masks_ready else "masks"
        self.finished = self.cancelled = False
        self.error = ""
        self.fallback: Path | None = None  # écran seul, si l'assemblage n'a pas pu se faire
        self._stop = False
        self._thread = None

    @property
    def progress(self) -> float:
        if self.finished and not self.error:
            return 1.0
        ratio = min(1.0, self.done / self.total)
        if self.masks_ready:
            return ratio
        return 0.8 * ratio if self.phase == "masks" else 0.8 + 0.2 * ratio

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="montar-webcam", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop = True

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.finished

    def _run(self) -> None:
        from montar.media import ffmpeg_run
        from montar.media.segment import webcam_masks

        screen_part, cam_part = parts(str(self.target))
        mask = mask_part(str(self.target))
        try:
            if not self.masks_ready:
                webcam_masks(Path(cam_part), Path(mask), self.options.fps,
                             progress=lambda n: setattr(self, "done", n),
                             cancelled=lambda: self._stop)
            if self._stop:
                raise ffmpeg_run.Cancelled()
            self.phase, self.done = "compose", 0
            us_per_frame = 1_000_000 / self.options.fps

            def on_progress(key: str, value: str) -> None:
                if key == "out_time_us" and value.isdigit():
                    self.done = int(int(value) / us_per_frame)

            ffmpeg_run.run(compose_command(self.options, screen_part, cam_part, mask,
                                           str(self.target), self._size(screen_part),
                                           start_time(cam_part)),
                           on_progress, cancelled=lambda: self._stop)
        except ffmpeg_run.Cancelled:
            self.cancelled, self.error = True, "annulé"
        except Exception as exc:  # jamais d'exception hors du fil
            self.error = str(exc)
        finally:
            if self.error and Path(screen_part).exists():
                # échec ou annulation : l'écran (avec le son) est gardé, sans la webcam
                self.fallback = self.target.with_suffix(".mkv")
                Path(screen_part).replace(self.fallback)
            for leftover in (screen_part, cam_part, mask):
                Path(leftover).unlink(missing_ok=True)
            self.finished = True

    def _size(self, screen_part: str) -> tuple[int, int] | None:
        from montar.media.probe import probe

        try:
            info = probe(screen_part)
            return (info.width, info.height) if info.width and info.height else None
        except Exception:  # taille inconnue : proportions 16:9 supposées
            return None


class Recorder:
    """Un enregistrement en cours : `stop()` termine proprement le fichier."""

    def __init__(self, options: RecordOptions, target: Path) -> None:
        self.options, self.target = options, target
        self._proc: subprocess.Popen | None = None
        self._masker = None
        self.masks_ready = False  # détourage fait pendant l'enregistrement
        self.started = 0.0
        self.error = ""

    def start(self) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.target.with_suffix(".log"), "w+b")  # noqa: SIM115
        live = self.options.processed and self._can_segment()
        self._proc = subprocess.Popen(self._command(live),
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE if live else subprocess.DEVNULL,
                                      stderr=self._log)
        self.started = time.monotonic()
        if live:
            from montar.media.segment import LiveMasker

            self._masker = LiveMasker(self._proc.stdout, Path(mask_part(str(self.target))),
                                      self.options.fps)

    @staticmethod
    def _can_segment() -> bool:
        try:
            from montar.media.segment import model_path
        except ImportError:  # NumPy absent : détourage impossible
            return False
        return model_path().exists()

    def _command(self, live_masks: bool = False) -> list[str]:
        return command(self.options, str(self.target), time.time(), live_masks)

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
                proc.stdin.write(b"q")  # ffmpeg finalise le fichier
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(5)
        if self._masker is not None:
            self.masks_ready = self._masker.close()
            if not self.masks_ready:  # masques incomplets : recalculés après coup
                Path(mask_part(str(self.target))).unlink(missing_ok=True)
        self._log.seek(0)
        lines = self._log.read().decode("utf-8", "replace").strip().splitlines()
        self._log.close()
        self.target.with_suffix(".log").unlink(missing_ok=True)
        written = Path(parts(str(self.target))[0]) if self.options.processed else self.target
        ok = written.exists() and written.stat().st_size > 0
        if not ok:
            self.error = lines[-1] if lines else _("aucune image enregistrée")
        return ok
