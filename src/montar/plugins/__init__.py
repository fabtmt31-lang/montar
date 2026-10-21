# SPDX-License-Identifier: GPL-3.0-or-later
"""Système de modules (extensions) de montar."""
from __future__ import annotations

from pathlib import Path

from montar.platform import paths
from montar.plugins.manager import ModuleError, ModuleInfo, ModuleManager


def builtin_modules_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "modules"


def user_modules_dir() -> Path:
    return paths.data_dir() / "modules"


def default_manager(disabled=()) -> ModuleManager:
    manager = ModuleManager(builtin_modules_dir(), user_modules_dir(), disabled)
    manager.load_all()
    return manager


__all__ = ["ModuleError", "ModuleInfo", "ModuleManager", "builtin_modules_dir",
           "default_manager", "user_modules_dir"]
