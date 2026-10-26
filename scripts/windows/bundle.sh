#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Dossier autonome de montar pour Windows, à partir de MSYS2 (UCRT64) : Python, PyQt6, NumPy,
# MLT et ses modules, frei0r, FFmpeg et toutes les DLL dont ils dépendent, plus montar.
# Même disposition que MSYS2 (bin/, lib/, share/) : Python, Qt et MLT s'y retrouvent seuls.
#   À lancer dans un shell MSYS2 UCRT64 :  bash scripts/windows/bundle.sh [SORTIE]
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:-build/windows/montar}
P=$MINGW_PREFIX
py=$(python -c 'import sys; print(f"python{sys.version_info[0]}.{sys.version_info[1]}")')

rm -rf "$out"
mkdir -p "$out/bin" "$out/lib" "$out/share/qt6"

echo "== Python ($py)"
cp "$P"/bin/python.exe "$P"/bin/pythonw.exe "$out/bin/"
# bibliothèque standard, sans ce qui ne sert pas à montar
mkdir -p "$out/lib/$py"
for item in "$P/lib/$py"/*; do
    case "$(basename "$item")" in
        site-packages|__pycache__|test|idlelib|tkinter|turtledemo|ensurepip|lib2to3|config-*\
        |unittest|pydoc_data|venv|sqlite3|dbm|curses|_pyrepl) ;;
        *) cp -r "$item" "$out/lib/$py/" ;;
    esac
done
site="$out/lib/$py/site-packages"
mkdir -p "$site"
for pkg in PyQt6 numpy mlt7.py; do
    cp -r "$P/lib/$py/site-packages/$pkg" "$site/"
done
cp "$P/lib/$py/site-packages"/_mlt7*.pyd "$site/"
cp -r "$P/lib/$py/site-packages"/PyQt6*.dist-info "$P/lib/$py/site-packages"/numpy*.dist-info \
      "$site/" 2>/dev/null || true
# modules de PyQt6 inutiles (et leurs DLL Qt) : ni QML, ni web, ni 3D
find "$site/PyQt6" -maxdepth 1 \( -name 'QtQml*' -o -name 'QtQuick*' -o -name 'QtWeb*' \
     -o -name 'Qt3D*' -o -name 'QtDesigner*' -o -name 'QtBluetooth*' -o -name 'QtNfc*' \
     -o -name 'QtSql*' -o -name 'QtTest*' -o -name 'QtRemoteObjects*' -o -name 'QtSensors*' \
     -o -name 'QtSerialPort*' -o -name 'QtPositioning*' -o -name 'QtHelp*' -o -name 'QtPdf*' \
     -o -name 'QtSpatialAudio*' -o -name 'QtTextToSpeech*' -o -name 'uic' -o -name 'lupdate' \
     -o -name 'QtMultimedia*' -o -name 'QtNetwork*' -o -name 'QtOpenGL*' -o -name 'QtDBus*' \
     -o -name 'QtXml*' -o -name 'QtPrintSupport*' -o -name 'QtCharts*' -o -name 'QtSerialBus*' \
     -o -name 'QtDataVisualization*' -o -name 'QtStateMachine*' -o -name 'QtShaderTools*' \
     -o -name 'QtGraphs*' -o -name 'QtHttpServer*' -o -name 'QtWebSockets*' \) \
     -exec rm -rf {} +

echo "== montar"
cp -r "$root/src/montar" "$site/"
find "$out" -name __pycache__ -prune -exec rm -rf {} +

echo "== Qt (modules d'extension, traductions)"
mkdir -p "$out/share/qt6/plugins" "$out/share/qt6/translations"
for d in platforms styles imageformats iconengines; do
    [ -d "$P/share/qt6/plugins/$d" ] && cp -r "$P/share/qt6/plugins/$d" "$out/share/qt6/plugins/"
done
cp "$P"/share/qt6/translations/qtbase_{fr,en}.qm "$out/share/qt6/translations/" 2>/dev/null || true
cat > "$out/bin/qt.conf" <<'EOF'
[Paths]
Prefix = ..
Plugins = share/qt6/plugins
Translations = share/qt6/translations
EOF

echo "== MLT, frei0r, FFmpeg"
# modules de MLT dont montar se sert (les autres, et leurs DLL, alourdiraient l'installateur
# d'autant : placebo et glaxnimate tirent Vulkan, shaderc, QML…)
mkdir -p "$out/lib/mlt"
for m in core avformat frei0r plus rubberband sox sdl2 gdk resample xml; do
    [ -e "$P/lib/mlt/libmlt$m.dll" ] && cp "$P/lib/mlt/libmlt$m.dll" "$out/lib/mlt/"
done
cp -r "$P/share/mlt" "$out/share/"
[ -d "$P/lib/frei0r-1" ] && cp -r "$P/lib/frei0r-1" "$out/lib/"
cp "$P"/bin/ffmpeg.exe "$P"/bin/ffprobe.exe "$out/bin/"
[ -d "$P/etc/fonts" ] && mkdir -p "$out/etc" && cp -r "$P/etc/fonts" "$out/etc/"

echo "== Lanceur montar.exe (Python chargé dans le processus de montar)"
python "$root/scripts/windows/make_icon.py" "$out/montar.ico"
version=$(PYTHONPATH="$root/src" python -c 'import montar; print(montar.__version__)')
work=$(mktemp -d)
cp "$out/montar.ico" "$work/"
printf '#define VERSION_DOTS "%s"\n#define VERSION_COMMAS %s,0\n' "$version" \
    "$(printf '%s' "$version" | tr . ,)" > "$work/version.h"
cp "$root/scripts/windows/launcher.rc" "$work/"
(cd "$work" && windres launcher.rc -O coff -o launcher.res)
pyinc=$(python -c 'import sysconfig; print(sysconfig.get_paths()["include"])')
gcc -municode -mwindows -O2 -I"$pyinc" "$root/scripts/windows/launcher.c" "$work/launcher.res" \
    -L"$P/lib" -l"$py" -o "$out/bin/montar.exe"
# à la racine (version portable) : relais vers bin\montar.exe
gcc -municode -mwindows -O2 "$root/scripts/windows/launcher_root.c" "$work/launcher.res" \
    -o "$out/montar.exe"
rm -rf "$work"

echo "== DLL nécessaires (dépendances de chaque exécutable et module)"
win_prefix=$(cygpath -w "$P" | tr '[:upper:]' '[:lower:]')

# chemins Windows des DLL de MSYS2 dont dépendent les fichiers donnés (récursivement) ;
# celles de Windows sont déjà sur chaque machine
msys_deps() {
    { xargs -0 ntldd -R 2>/dev/null || true; } \
        | sed -n 's/.*=> \(.*\.dll\).*/\1/Ip' | tr -d '\r' | sort -u \
        | while read -r dll; do
              lower=$(printf '%s' "$dll" | tr '[:upper:]' '[:lower:]')
              case "$lower" in "$win_prefix"\\bin\\*) printf '%s\n' "$dll" ;; esac
          done
}

copy_deps() {
    local added=0
    while read -r dll; do
        src=$(cygpath -u "$dll")
        if [ ! -e "$out/bin/$(basename "$src")" ]; then
            cp "$src" "$out/bin/"
            added=$((added + 1))
        fi
    done
    echo "$added"
}

find "$out" -type f \( -name '*.exe' -o -name '*.dll' -o -name '*.pyd' \) -print0 \
    | msys_deps | copy_deps | sed 's/^/DLL copiées : /'
# les DLL copiées ont parfois des dépendances chargées à l'exécution : une passe de plus
find "$out/bin" -name '*.dll' -print0 | msys_deps | copy_deps | sed 's/^/DLL copiées (2e passe) : /'

echo "== Précompilation"
"$out/bin/python.exe" -m compileall -q -j 0 "$out/lib/$py" >/dev/null || true

cp "$root/LICENSE" "$out/"
du -sh "$out"
echo "dossier prêt : $out"
