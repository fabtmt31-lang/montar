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
    """Dossier « Vidéos » de l'utilisateur, localisé (ex. ~/Vidéos)."""
    if sys.platform != "win32":
        env = os.environ.get("XDG_VIDEOS_DIR")
        if env:
            return Path(env)
        try:
            out = subprocess.run(
                ["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if out and Path(out) != Path.home():
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Videos"


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
