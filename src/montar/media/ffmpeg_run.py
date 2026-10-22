# SPDX-License-Identifier: GPL-3.0-or-later
"""Exécution de ffmpeg en tâche de fond : avancement (`-progress pipe:1`), annulation
vérifiée plusieurs fois par seconde, arrêt d'un ffmpeg qui n'avance plus."""
from __future__ import annotations

import os
import select
import subprocess
import tempfile
import time
from collections.abc import Callable

STALL_SECONDS = 120


class Cancelled(Exception):
    pass


class Stalled(RuntimeError):
    pass


def run(cmd: list[str], on_progress: Callable[[str, str], None] = lambda k, v: None,
        cancelled: Callable[[], bool] = lambda: False,
        stall_seconds: float | None = None) -> None:
    """Lance `cmd` (qui doit contenir `-progress pipe:1`) et transmet chaque couple
    clé=valeur d'avancement. Lève Cancelled, Stalled ou RuntimeError (message de ffmpeg)."""
    stall = STALL_SECONDS if stall_seconds is None else stall_seconds
    # messages d'erreur dans un fichier : un tuyau plein bloquerait ffmpeg
    errors = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors)
    try:
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        pending, last_change, last_state = b"", time.monotonic(), None
        while True:
            if cancelled():
                raise Cancelled()
            ready, _w, _x = select.select([fd], [], [], 0.25)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break  # ffmpeg a terminé
                pending += chunk
                *lines, pending = pending.split(b"\n")
                for line in lines:
                    key, _sep, value = line.decode("ascii", "replace").strip().partition("=")
                    if key in ("frame", "out_time_us") and (key, value) != last_state:
                        last_state, last_change = (key, value), time.monotonic()
                    on_progress(key, value)
            if time.monotonic() - last_change > stall:
                raise Stalled(f"ffmpeg n'avance plus depuis {round(stall / 60)} minutes ; "
                              "le calcul a été arrêté")
        code = proc.wait()
        if code != 0:
            errors.seek(0)
            lines = errors.read().decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else f"ffmpeg a échoué (code {code})")
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc.wait()
        raise
    finally:
        errors.close()
