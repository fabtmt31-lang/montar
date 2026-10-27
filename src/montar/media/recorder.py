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
    """« ddagrab » s'il fonctionne sur cet ordinateur (Windows 8 et plus récents, carte
    graphique), sinon « gdigrab »."""
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
    """Test du micro : niveau sonore en direct (0 à 1), lu par ffmpeg dans un fil."""

    RATE = 8000

    def __init__(self, device: str) -> None:
        import threading

        self.level = 0.0
        self.error = ""
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
        while True:
            data = self._proc.stdout.read(chunk)
            if not data:
                break
            samples = array.array("h", data[:len(data) // 2 * 2])
            peak = max((abs(v) for v in samples), default=0) / 32768
            self.level = max(peak, self.level * 0.6)  # retombe doucement
        if self._proc.poll() not in (None, 0) and not self.error:
            self.error = _("le micro ne répond pas")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


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
    for wanted, device in ((options.microphone, options.microphone_device or "default"),
                           (options.system_audio, "@DEFAULT_MONITOR@")):
        if wanted:
            cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", device]
            audio.append(inputs)
            inputs += 1
    webcam = None
    if options.webcam:
        cmd += ["-thread_queue_size", "512", "-f", "v4l2", "-i", options.webcam]
        webcam = inputs
    return _encode(cmd, options, audio, webcam, target, size=options.capture_size())


def _command_windows(options: RecordOptions, target: str) -> list[str]:
    """Écran ou zone par ddagrab (ou gdigrab), fenêtre par gdigrab ; sons et webcam par
    DirectShow."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    mouse = "1" if options.show_cursor else "0"
    cmd = [ffmpeg, "-v", "error", "-y"]
    prefix = ""
    size = options.capture_size()
    area = window_rect(options.window_title) if options.source == "window" else None
    if area is not None:  # la zone de la fenêtre sur le bureau (jamais noire)
        x, y, w, h = area
        size = (w - w % 2, h - h % 2)
        cmd += ["-thread_queue_size", "512", "-f", "gdigrab", "-framerate", str(options.fps),
                "-draw_mouse", mouse, "-offset_x", str(x), "-offset_y", str(y),
                "-video_size", f"{size[0]}x{size[1]}", "-i", "desktop"]
    elif options.source == "window" and options.window_title:
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
    microphone = (options.microphone_device or next(iter(dshow_devices("audio")), "")) \
        if options.microphone else ""
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
    return _encode(cmd, options, audio, webcam, target, prefix, size)


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
    if options.webcam_shape == "round":  # carré recadré au centre, masque rond
        shaped = (f"{cam}crop='min(iw,ih)':'min(iw,ih)',format=yuva420p,"
                  "geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
                  "a='if(lte(hypot(X-W/2,Y-H/2),W/2-1),alpha(X,Y),0)'[shaped]")
        scale = f"[shaped]{screen}scale2ref=w=trunc(iw*{share:g}/2)*2:h=ow[cam][base]"
        return [shaped, scale, f"[base][cam]overlay={where},format=yuv420p{out}"]
    # scale2ref : iw / ih sont ceux de l'image de référence (l'écran), main_a les
    # proportions de la webcam
    return [f"{cam}{screen}scale2ref=w=trunc(iw*{share:g}/2)*2:h=trunc(ow/main_a/2)*2"
            "[cam][base]",
            f"[base][cam]overlay={where},format=yuv420p{out}"]


def parts(target: str) -> tuple[str, str]:
    """Fichiers intermédiaires (écran avec le son, webcam) d'un enregistrement traité."""
    base = str(Path(target).with_suffix(""))
    return base + ".ecran.mkv", base + ".webcam.mkv"


def _encode(cmd: list[str], options: RecordOptions, audio: list[int], webcam: int | None,
            target: str, prefix: str = "", size: tuple[int, int] | None = None) -> list[str]:
    """Montage des entrées (écran, webcam en incrustation, sons mélangés) et encodage."""
    graph = [f"[0:v]{prefix}scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[screen]"]
    video = "[screen]"
    if webcam is not None and options.processed:
        # deux fichiers : l'écran (avec le son) et la webcam, assemblés après coup
        screen_part, cam_part = parts(target)
        maps = ["-map", video]
        if len(audio) == 2:
            graph.append(f"[{audio[0]}:a][{audio[1]}:a]amix=inputs=2:duration=longest[audio]")
            maps += ["-map", "[audio]"]
        elif audio:
            maps += ["-map", f"{audio[0]}:a"]
        quality = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                   "-r", str(options.fps)]
        cmd += ["-filter_complex", ";".join(graph), *maps, *quality]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        return cmd + [screen_part, "-map", f"{webcam}:v", *quality, "-pix_fmt", "yuv420p",
                      cam_part]
    if webcam is not None:
        graph += webcam_graph("[screen]", f"[{webcam}:v]", options, size)
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


def compose_command(options: RecordOptions, screen_part: str, cam_part: str, mask: str,
                    target: str, size: tuple[int, int] | None) -> list[str]:
    """Assemblage final d'un enregistrement traité : fond de la webcam flouté ou effacé
    d'après les masques (`mask`, blanc = personne), webcam placée sur l'écran."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    graph = ["[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[screen]",
             # masques agrandis à la taille de la webcam, bords adoucis
             "[2:v][1:v]scale2ref=w=iw:h=ih[maskbig][cam]",
             "[maskbig]format=gray,gblur=sigma=2[mask]"]
    if options.webcam_background == "blur":
        graph += ["[cam]split[camback][camfront]",
                  "[camback]gblur=sigma=18[blurred]",
                  "[camfront][mask]alphamerge[person]",
                  "[blurred][person]overlay=format=auto,format=yuv420p[camfx]"]
    else:  # effacé : seule la personne reste, posée sur l'écran
        graph += ["[cam]format=yuva420p[camrgba]", "[camrgba][mask]alphamerge[camfx]"]
    graph += webcam_graph("[screen]", "[camfx]", options, size)
    return [ffmpeg, "-v", "error", "-y", "-nostats", "-progress", "pipe:1",
            "-i", screen_part, "-i", cam_part, "-i", mask,
            "-filter_complex", ";".join(graph), "-map", "[video]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
            "-movflags", "+faststart", target]


class Finisher:
    """Après un enregistrement traité : masques de la webcam (media/segment.py) puis
    assemblage, dans un fil. Mêmes attributs qu'un export : `progress`, `finished`,
    `error`, `cancelled`."""

    def __init__(self, options: RecordOptions, target: Path, seconds: float) -> None:
        self.options, self.target = options, target
        self.total = max(1, round(seconds * options.fps))
        self.done = 0
        self.phase = "masks"
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
        return 0.8 * ratio if self.phase == "masks" else 0.8 + 0.2 * ratio

    def start(self) -> None:
        import threading

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
        mask = str(self.target.with_suffix("")) + ".masques.mkv"
        try:
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
                                           str(self.target), self._size(screen_part)),
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
        written = Path(parts(str(self.target))[0]) if self.options.processed else self.target
        ok = written.exists() and written.stat().st_size > 0
        if not ok:
            self.error = lines[-1] if lines else _("aucune image enregistrée")
        return ok
