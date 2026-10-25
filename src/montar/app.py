# SPDX-License-Identifier: GPL-3.0-or-later
"""Point d'entrée de l'application."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from montar import __version__
from montar.platform import paths, windows


def _setup_logging() -> None:
    log_dir = paths.cache_dir() / "logs"
    # pas de console sous Windows (pythonw.exe) : sys.stderr vaut None
    handlers: list[logging.Handler] = [logging.StreamHandler()] if sys.stderr else []
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
    if sys.platform == "win32":
        print(f"Système : {platform.platform()}")
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


def _install_language(app, setting: str) -> None:
    """Langue de montar et, si Qt fournit ses traductions, celle des boutons standard."""
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

    from montar.i18n import set_language

    language = set_language(setting)
    QLocale.setDefault(QLocale(language))
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for base in (folder, "/usr/share/qt6/translations"):
        if translator.load(f"qtbase_{language}", base):
            app.installTranslator(translator)
            break


def _module_tool(args) -> int:
    from montar.plugins.devtools import new_module, pack_module
    from montar.plugins.manager import ModuleError

    try:
        if args.new_module:
            kinds = [k.strip() for t in (args.type or []) for k in t.split(",") if k.strip()]
            folder = new_module(Path(args.new_module), kinds=kinds or None)
            print(f"Module créé : {folder}")
            print("Modifiez __init__.py, puis Préférences → Extensions → Installer un module "
                  "→ « Lier un dossier (développement) ».")
        else:
            print(f"Archive créée : {pack_module(Path(args.pack_module))}")
    except (ModuleError, OSError) as exc:
        print(f"montar : {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="montar", description="Montage vidéo simple et local")
    parser.add_argument("project", nargs="?", help="projet .montar à ouvrir")
    parser.add_argument("--version", action="version", version=f"montar {__version__}")
    parser.add_argument("--diagnostic", action="store_true",
                        help="affiche les versions et vérifie le moteur de rendu, puis quitte")
    dev = parser.add_argument_group("auteurs de modules (voir docs/MODULES.md)")
    dev.add_argument("--new-module", metavar="DOSSIER",
                     help="crée le squelette d'un module dans DOSSIER, puis quitte")
    dev.add_argument("--type", action="append", metavar="TYPE",
                     help="avec --new-module : effet-video, effet-audio, transition, "
                          "generateur, graphisme, format, outil (répétable)")
    dev.add_argument("--pack-module", metavar="DOSSIER",
                     help="crée l'archive .montar-module du module DOSSIER, puis quitte")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    windows.prepare()
    if args.diagnostic:
        return diagnostic()
    if args.new_module or args.pack_module:
        return _module_tool(args)

    _setup_logging()
    from PyQt6.QtWidgets import QApplication

    from montar.core.settings import Settings
    from montar.ui.main_window import MainWindow
    from montar.ui.theme import theme
    from montar.ui.theme.manager import app_icon, load_fonts

    windows.set_app_id()
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
    _install_language(app, settings.language)
    theme().apply(settings.theme, settings.accent)
    window = MainWindow(settings, settings_file)
    window.show()
    if args.project:
        window.session.close()
        window.open_project(Path(args.project))
    else:
        window.check_interrupted()
    return app.exec()
