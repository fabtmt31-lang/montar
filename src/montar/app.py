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
        _enable_stack_dumps(log_dir / "traces.log")
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _enable_stack_dumps(file: Path) -> None:
    """Diagnostic des blocages : `pkill -USR1 -f montar` écrit la pile de chaque fil dans
    ~/.cache/montar/logs/traces.log ; les plantages y sont aussi consignés."""
    import faulthandler
    import signal

    stream = open(file, "a", encoding="utf-8")  # noqa: SIM115 - ouvert toute la session
    faulthandler.enable(stream)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, stream, all_threads=True)


def diagnostic() -> int:
    """Informations à joindre à un signalement de problème."""
    import platform

    print(f"montar {__version__}")
    print(f"Python {platform.python_version()}")
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        name = next((line.split("=", 1)[1].strip('"') for line in release.splitlines()
                     if line.startswith("PRETTY_NAME=")), "?")
        print(f"Système : {name}")
    except OSError:
        pass
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        print(f"Qt {QT_VERSION_STR}, PyQt {PYQT_VERSION_STR}")
    except ImportError as exc:
        print(f"PyQt6 absent : {exc}")
    import locale

    try:
        locale.setlocale(locale.LC_ALL, "")  # comme Qt au démarrage
    except locale.Error:
        pass
    print(f"Convention numérique du système : « {locale.localeconv()['decimal_point']} » "
          f"({locale.setlocale(locale.LC_NUMERIC)})")
    try:
        from montar.engine import get_engine
        from montar.engine.mlt_engine import preview_scaling_check

        engine = get_engine()
        print(f"MLT {engine.version()}")
        check = preview_scaling_check()
        print(f"Convention numérique du moteur : « {locale.localeconv()['decimal_point']} »")
        print(f"Placement dans l'aperçu : {'correct' if check['ok'] else 'INCORRECT'}")
        print(f"  attendu {check.get('expected')}")
        for size, box in check.get("sizes", {}).items():
            print(f"  {size} : {box}")
        if check.get("error"):
            print(f"  erreur : {check['error']}")
    except Exception as exc:
        print(f"Moteur indisponible : {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="montar", description="Montage vidéo simple et local")
    parser.add_argument("project", nargs="?", help="projet .montar à ouvrir")
    parser.add_argument("--version", action="version", version=f"montar {__version__}")
    parser.add_argument("--diagnostic", action="store_true",
                        help="affiche les versions et vérifie le moteur de rendu, puis quitte")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    if args.diagnostic:
        return diagnostic()

    _setup_logging()
    from PyQt6.QtWidgets import QApplication

    from montar.core.settings import Settings
    from montar.ui.main_window import MainWindow
    from montar.ui.theme import theme
    from montar.ui.theme.manager import app_icon, load_fonts

    app = QApplication([sys.argv[0], *qt_args])
    # QApplication adopte la convention numérique du système (virgule en français), que
    # MLT utiliserait pour lire ses nombres : le moteur exige le point décimal.
    from montar.engine.mlt_engine import use_c_numeric

    use_c_numeric()
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
        window.session.close()
        window.open_project(Path(args.project))
    else:
        window.check_interrupted()
    return app.exec()
