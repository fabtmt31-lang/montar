# SPDX-License-Identifier: GPL-3.0-or-later
"""Plantages : chaque session est marquée dans traces.log (début, fin normale), où
faulthandler écrit la pile des fils en cas d'arrêt brutal. Au démarrage suivant, une
session sans fin normale qui a laissé une trace devient un rapport à montrer.

Les erreurs Python non rattrapées dans l'interface fermaient montar (PyQt arrête le
programme quand aucun gestionnaire n'est installé), sans rien écrire sous Windows (pas de
console) : elles sont maintenant consignées et l'application continue."""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("montar")

START = "=== montar "
CLEAN_END = "=== fermeture normale"
UNCAUGHT = "Erreur non rattrapée"
# signes d'un plantage dans une session (faulthandler, erreur Python)
_SIGNS = ("Fatal Python error", "Windows fatal exception", "Traceback (most recent call last)",
          UNCAUGHT)
MAX_SIZE, KEEP = 1_000_000, 200_000  # traces.log raccourci au démarrage au-delà de MAX_SIZE


def previous_crash(file: Path) -> str:
    """Trace de la dernière session si elle s'est mal terminée (sinon chaîne vide)."""
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    start = text.rfind(START)
    if start < 0:
        return ""
    block = text[start:]
    if CLEAN_END in block or not any(sign in block for sign in _SIGNS):
        return ""
    return block.strip()


def trim(file: Path) -> None:
    """Garde la fin de traces.log s'il devient trop gros."""
    try:
        if file.stat().st_size > MAX_SIZE:
            data = file.read_bytes()[-KEEP:]
            file.write_bytes(data[data.find(b"\n") + 1:])
    except OSError:
        pass


def begin_session(stream, version: str) -> None:
    stream.write(f"\n{START}{version} — {time.strftime('%Y-%m-%d %H:%M:%S')} — "
                 f"{sys.platform} ===\n")
    stream.flush()


def end_session(stream) -> None:
    stream.write(f"{CLEAN_END} — {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    stream.flush()


def install_hooks(stream, notify: Callable[[str], None] | None = None) -> None:
    """Erreurs non rattrapées (fil de l'interface et autres fils) : consignées dans le
    journal et dans traces.log ; `notify(message)` prévient l'utilisateur."""

    def record(kind: str, exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("%s (%s) :\n%s", UNCAUGHT, kind, text)
        try:
            stream.write(f"{UNCAUGHT} ({kind}, {time.strftime('%H:%M:%S')}) :\n{text}\n")
            stream.flush()
        except (OSError, ValueError):
            pass
        if notify is not None:
            try:
                notify(f"{exc_type.__name__} : {exc}")
            except Exception:  # jamais d'erreur dans le gestionnaire d'erreurs
                pass

    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        record("interface", exc_type, exc, tb)

    def thread_hook(args) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        record(f"fil {name}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook


def report(block: str, log_file: Path, version: str, lines: int = 80) -> str:
    """Texte du rapport : versions, trace du plantage, fin du journal."""
    import platform

    parts = [f"montar {version} · Python {platform.python_version()} · {platform.platform()}",
             "", "--- trace ---", block]
    try:
        tail = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        parts += ["", "--- fin du journal ---", *tail]
    except OSError:
        pass
    return "\n".join(parts)
