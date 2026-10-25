# SPDX-License-Identifier: GPL-3.0-or-later
"""Préparation de l'environnement sous Windows, avant Qt et MLT.

montar y tourne avec un Python « relogeable » (MSYS2, ou la copie embarquée par
l'installateur) : bin/ contient python.exe, ffmpeg et les DLL, lib/ et share/ les modules de
MLT, frei0r et Qt. Les dossiers sont déduits de ce préfixe."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "appsdoc.montar"  # identifiant de l'application pour la barre des tâches


def prefix() -> Path:
    return Path(sys.base_prefix)


def prepare() -> None:
    """Sans effet hors de Windows ; ne remplace jamais une variable déjà définie."""
    if sys.platform != "win32":
        return
    root = prefix()
    bin_dir = root / "bin"
    if bin_dir.is_dir() and str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        # ffmpeg, ffprobe et les DLL de MLT
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    # MLT déduit ses dossiers de l'exécutable (ici python.exe) et ne trouve pas ses profils
    data = root / "share" / "mlt"
    if (data / "profiles").is_dir():
        os.environ.setdefault("MLT_DATA", str(data))
        os.environ.setdefault("MLT_PROFILES_PATH", str(data / "profiles"))
    if (root / "lib" / "mlt").is_dir():
        os.environ.setdefault("MLT_REPOSITORY", str(root / "lib" / "mlt"))
    if (root / "lib" / "frei0r-1").is_dir():
        os.environ.setdefault("FREI0R_PATH", str(root / "lib" / "frei0r-1"))
    _hide_consoles()


def _hide_consoles() -> None:
    """Lancé sans console (pythonw.exe), chaque ffmpeg ouvrirait une fenêtre noire : les
    processus enfants sont créés sans fenêtre, sauf demande contraire."""
    import subprocess

    original = subprocess.Popen.__init__
    if getattr(original, "_montar", False):
        return

    def init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    init._montar = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = init  # type: ignore[method-assign]


def set_app_id() -> None:
    """Fenêtres de montar regroupées sous son icône (et non celle de Python)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
