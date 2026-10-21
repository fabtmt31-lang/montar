#!/bin/sh
# Construit le paquet montar_<version>_all.deb dans dist/.
# Prérequis : sudo apt install build-essential debhelper dh-python python3
set -eu
cd "$(dirname "$0")/.."
dpkg-buildpackage -us -uc -b
mkdir -p dist
version=$(dpkg-parsechangelog -S Version)
mv "../montar_${version}_all.deb" dist/
rm -f "../montar_${version}_"*.buildinfo "../montar_${version}_"*.changes
echo "Paquet : dist/montar_${version}_all.deb"
