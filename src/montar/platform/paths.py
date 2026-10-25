# SPDX-License-Identifier: GPL-3.0-or-later
"""Emplacements des fichiers de montar (XDG sous Linux, %APPDATA% sous Windows)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_DIR_NAME = "montar"


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_DIR_NAME
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_DIR_NAME


def data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_DIR_NAME
    return _xdg("XDG_DATA_HOME", ".local/share") / APP_DIR_NAME


def cache_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_DIR_NAME / "cache"
    return _xdg("XDG_CACHE_HOME", ".cache") / APP_DIR_NAME


def videos_dir() -> Path:
    """Dossier « Vidéos » de l'utilisateur, localisé (ex. ~/Vidéos). XDG_VIDEOS_DIR, s'il
    est défini, l'emporte partout."""
    env = os.environ.get("XDG_VIDEOS_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return _known_folder_videos() or Path.home() / "Videos"
    try:
        out = subprocess.run(
            ["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=2
        ).stdout.strip()
        if out and Path(out) != Path.home():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Videos"


def _known_folder_videos() -> Path | None:
    """Dossier « Vidéos » de Windows (déplaçable par l'utilisateur, ex. vers OneDrive)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    # FOLDERID_Videos {18989B1D-99B5-455B-841C-AB7C74E4DDFC}
    folder = GUID(0x18989B1D, 0x99B5, 0x455B,
                  (ctypes.c_ubyte * 8)(0x84, 0x1C, 0xAB, 0x7C, 0x74, 0xE4, 0xDD, 0xFC))
    path = ctypes.c_wchar_p()
    try:
        shell32 = ctypes.WinDLL("shell32")
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None,
                                        ctypes.byref(path)) != 0:
            return None
        return Path(path.value) if path.value else None
    except OSError:
        return None
    finally:
        if path:
            ctypes.WinDLL("ole32").CoTaskMemFree(path)


def default_projects_dir() -> Path:
    return videos_dir() / "Montar"


def assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


def user_first_name() -> str:
    """Prénom de l'utilisateur système (champ GECOS), sinon son identifiant."""
    name = ""
    if sys.platform != "win32":
        try:
            import pwd

            gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
            name = gecos.split()[0] if gecos else ""
        except (ImportError, KeyError, IndexError):
            pass
    if not name:
        name = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    return name[:1].upper() + name[1:]
