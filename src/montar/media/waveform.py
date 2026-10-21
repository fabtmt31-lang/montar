# SPDX-License-Identifier: GPL-3.0-or-later
"""Formes d'onde des médias audio, calculées avec ffmpeg et NumPy, mises en cache."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

PEAKS_PER_SECOND = 100
_SAMPLE_RATE = 16000


def waveform_path(cache: Path, media_path: str) -> Path:
    p = Path(media_path)
    try:
        stamp = f"{p.stat().st_mtime_ns}:{p.stat().st_size}"
    except OSError:
        stamp = "missing"
    key = hashlib.sha1(f"{p.resolve()}|{stamp}|{PEAKS_PER_SECOND}".encode()).hexdigest()
    return cache / "waveforms" / f"{key}.peaks"


def compute_peaks(media_path: str) -> bytes | None:
    """Crêtes du signal (0 à 255), PEAKS_PER_SECOND valeurs par seconde ; None si pas de son."""
    try:
        import numpy as np
    except ImportError:
        return None
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    cmd = [ffmpeg, "-v", "error", "-i", media_path, "-vn", "-ac", "1",
           "-ar", str(_SAMPLE_RATE), "-f", "s16le", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=300, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    samples = np.frombuffer(raw, dtype="<i2")
    if samples.size == 0:
        return None
    window = _SAMPLE_RATE // PEAKS_PER_SECOND
    count = -(-samples.size // window)
    padded = np.zeros(count * window, dtype=np.int32)
    padded[:samples.size] = np.abs(samples.astype(np.int32))
    peaks = padded.reshape(count, window).max(axis=1)
    return (np.minimum(peaks, 32767) * 255 // 32767).astype(np.uint8).tobytes()


def load_or_compute(cache: Path, media_path: str) -> bytes | None:
    out = waveform_path(cache, media_path)
    if out.exists():
        return out.read_bytes()
    peaks = compute_peaks(media_path)
    if peaks is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(peaks)
        tmp.replace(out)
    return peaks
