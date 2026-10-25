# montar sous Windows

montar tourne sous Windows 10 et 11 (64 bits) avec la pile de [MSYS2](https://www.msys2.org)
**UCRT64** : Python, PyQt6, MLT 7 (et son module Python `mlt7`), FFmpeg, frei0r, NumPy.

## Installateur

Le job « Windows » de l'intégration continue (`.github/workflows/windows.yml`) :

1. installe la pile MSYS2 et lance le prototype du moteur puis toute la suite de tests ;
2. prépare un dossier autonome avec `scripts/windows/bundle.sh` : Python, la bibliothèque
   standard, PyQt6, NumPy, `mlt7`, les modules de MLT, frei0r, FFmpeg, les modules d'extension
   de Qt et toutes les DLL de MSYS2 dont ils dépendent (relevées avec `ntldd`), plus montar ;
3. vérifie ce dossier sans MSYS2 dans le `PATH` (diagnostic, aperçu, export MP4) ;
4. construit l'installateur `montar-<version>-windows-x64.exe` avec Inno Setup
   (`scripts/windows/montar.iss`), l'installe en silence, démarre l'interface puis le
   désinstalle ; l'installateur est publié comme artefact du job.

L'installateur propose une installation pour soi seul (sans droits d'administrateur) ou pour
tous les utilisateurs, un raccourci dans le menu Démarrer (et sur le bureau), et l'ouverture
des projets `.montar` d'un double clic. montar est lancé par `pythonw.exe -X utf8 -I -m montar`.

## À savoir

- Au démarrage, `montar.platform.windows.prepare()` indique à MLT ses dossiers (profils,
  modules, frei0r), met `bin/` (ffmpeg) dans le `PATH` et lance les processus enfants sans
  fenêtre de console.
- La voix off enregistre le micro par DirectShow.
- L'enregistrement d'écran n'est pas encore disponible sous Windows.
- Paramètres : `%APPDATA%\montar` ; cache et journaux : `%LOCALAPPDATA%\montar\cache` ;
  projets : dossier « Vidéos » de l'utilisateur, sous `Montar`.
