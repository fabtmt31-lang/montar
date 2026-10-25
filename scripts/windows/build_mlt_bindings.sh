#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Bindings Python « mlt7 » pour le MLT de MSYS2 (Windows), s'ils manquent : SWIG est lancé
# sur l'interface de la même version de MLT, puis le module est compilé contre la
# bibliothèque installée et copié dans le site-packages de Python.
#   À lancer dans un shell MSYS2 (UCRT64 ou MINGW64).
set -euo pipefail

if python -c "import mlt7" 2>/dev/null; then
    echo "mlt7 déjà importable : rien à construire"
    python -c "import mlt7; print('MLT', mlt7.mlt_version_get_string())"
    exit 0
fi

version=$(pkg-config --modversion mlt-framework-7)
echo "MLT installé : $version — construction des bindings Python"
work=$(mktemp -d)
git clone --quiet --depth 1 --branch "v$version" https://github.com/mltframework/mlt.git "$work/mlt"
cd "$work/mlt/src/swig/python"

# l'interface inclut les en-têtes du dépôt ; on compile contre ceux qui sont installés
swig -c++ -python -module mlt7 $(pkg-config --cflags-only-I mlt++-7 mlt-framework-7) \
    -o mlt_wrap.cxx ../mlt.i
python_inc=$(python -c "import sysconfig; print(sysconfig.get_paths()['include'])")
python_lib=$(python -c "import sysconfig; print(sysconfig.get_config_var('LDLIBRARY') or '')")
site=$(python -c "import sysconfig; print(sysconfig.get_paths()['platlib'])")
ext=$(python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.pyd')")
echo "Python : en-têtes $python_inc, bibliothèque ${python_lib:-?}, extension $ext"
g++ -shared -O2 -fPIC -w mlt_wrap.cxx -o "_mlt7$ext" \
    $(pkg-config --cflags mlt++-7 mlt-framework-7) -I"$python_inc" \
    $(pkg-config --libs mlt++-7 mlt-framework-7) \
    $(pkg-config --libs python3-embed 2>/dev/null || pkg-config --libs python3)
cp mlt7.py "_mlt7$ext" "$site/"
cd /
python -c "import mlt7; print('mlt7 construit pour MLT', mlt7.mlt_version_get_string())"
