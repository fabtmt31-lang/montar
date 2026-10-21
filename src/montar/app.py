# SPDX-License-Identifier: GPL-3.0-or-later
"""Point d'entrée de l'application."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from montar import __version__
from montar.platform import paths


def _setup_logging() -> None:
    log_dir = paths.cache_dir() / "logs"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_dir / "montar.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="montar", description="Montage vidéo simple et local")
    parser.add_argument("project", nargs="?", help="projet .montar à ouvrir")
    parser.add_argument("--version", action="version", version=f"montar {__version__}")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    _setup_logging()
    from PyQt6.QtWidgets import QApplication

    from montar.core.settings import Settings
    from montar.ui.main_window import MainWindow
    from montar.ui.theme import theme
    from montar.ui.theme.manager import app_icon, load_fonts

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("montar")
    app.setApplicationDisplayName("montar")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("montar")
    load_fonts()
    app.setWindowIcon(app_icon())

    settings_file = paths.config_dir() / "settings.json"
    settings = Settings.load(settings_file)
    theme().apply(settings.theme)
    window = MainWindow(settings, settings_file)
    window.show()
    if args.project:
        window.open_project(Path(args.project))
    return app.exec()
