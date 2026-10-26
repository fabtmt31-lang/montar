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
   (`scripts/windows/montar.iss`) et la version portable
   `montar-<version>-windows-x64-portable.zip` (le même dossier, à décompresser n'importe où),
   installe en silence, démarre l'interface par `montar.exe` puis désinstalle ; les deux
   fichiers sont publiés comme artefact du job (« montar-windows »).

L'installateur propose une installation pour soi seul (sans droits d'administrateur) ou pour
tous les utilisateurs, un raccourci dans le menu Démarrer (et sur le bureau), et l'ouverture
des projets `.montar` d'un double clic.

## Lanceur

`bin\montar.exe` (`scripts/windows/launcher.c`) charge Python dans son propre processus et
équivaut à `pythonw.exe -X utf8 -I -m montar` : montar apparaît sous son nom et son icône
dans la barre et le gestionnaire des tâches. Le `montar.exe` à la racine du dossier
(`launcher_root.c`) relaie vers `bin\montar.exe`, pour la version portable.

## À savoir

- Au démarrage, `montar.platform.windows.prepare()` indique à MLT ses dossiers (profils,
  modules, frei0r), met `bin/` (ffmpeg) dans le `PATH` et lance les processus enfants sans
  fenêtre de console.
- La voix off enregistre le micro par DirectShow.
- Enregistrement d'écran : écran entier (gdigrab), micro et webcam par DirectShow ; la zone
  dessinée à la souris, la fenêtre choisie et le son de l'ordinateur restent propres à Linux.
- Police : rendu lissé et graisse un cran au-dessus sous Windows (`ui_font`).
- La version portable garde ses réglages dans `%APPDATA%\montar`, comme la version installée.
- Paramètres : `%APPDATA%\montar` ; cache et journaux : `%LOCALAPPDATA%\montar\cache` ;
  projets : dossier « Vidéos » de l'utilisateur, sous `Montar`.
