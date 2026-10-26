# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistrement d'une voix off (F-TL-03) : le micro est enregistré par ffmpeg
(PulseAudio / PipeWire sous Linux, DirectShow sous Windows) pendant que la timeline est lue."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from montar.i18n import N_
from montar.media.recorder import Recorder, dshow_devices

ON_WINDOWS = sys.platform == "win32"

RATE = 48000
WAV_HEADER = 44  # octets de l'en-tête d'un fichier WAV PCM


def microphones() -> list[tuple[str, str]]:
    """(périphérique, description) des entrées son ; « default » en premier."""
    found = [("default", N_("Micro par défaut"))]
    if ON_WINDOWS:
        return found + [(name, name) for name in dshow_microphones()]
    if shutil.which("pactl") is None:
        return found
    try:
        out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return found
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not parts[1].endswith(".monitor"):  # pas le son de sortie
            found.append((parts[1], parts[1]))
    return found


def dshow_microphones() -> list[str]:
    """Entrées son DirectShow (Windows), dans l'ordre donné par ffmpeg."""
    return dshow_devices("audio")


def command(device: str, target: str) -> list[str]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    if ON_WINDOWS:
        if device in ("", "default"):  # DirectShow n'a pas d'entrée « par défaut »
            device = next(iter(dshow_microphones()), "")
        source = ["-f", "dshow", "-audio_buffer_size", "50", "-i", f"audio={device}"]
    else:
        source = ["-f", "pulse", "-fragment_size", "1024", "-i", device or "default"]
    return [ffmpeg, "-v", "error", "-y", *source, "-ac", "1", "-ar", str(RATE),
            "-c:a", "pcm_s16le", "-flush_packets", "1", target]


class VoiceRecorder(Recorder):
    """Enregistrement du micro dans un fichier WAV (lisible même après un arrêt brutal)."""

    def __init__(self, device: str, target: Path) -> None:
        super().__init__(None, target)  # type: ignore[arg-type]
        self.device = device

    def _command(self) -> list[str]:
        return command(self.device, str(self.target))

    def captured(self) -> float:
        """Secondes de son déjà écrites dans le fichier."""
        try:
            size = self.target.stat().st_size
        except OSError:
            return 0.0
        return max(0, size - WAV_HEADER) / (RATE * 2)
