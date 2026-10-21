# montar

Logiciel libre de montage vidéo de bureau, simple et 100 % local, extensible par modules Python.
Cible : Debian, Ubuntu et Linux Mint (paquet `.deb`) dans un premier temps, puis Windows.

- Cahier des charges : [docs/CAHIER_DES_CHARGES.md](docs/CAHIER_DES_CHARGES.md)
- Maquettes d'interface : [docs/maquettes/](docs/maquettes/)

## État d'avancement

**Jalon J0 — socle** (version 0.1.0) :

- écran d'accueil : création rapide (16:9, 9:16, 1:1), projets récents en grille ou en liste, recherche ;
- dialogue « Nouveau projet » : format, résolution, images par seconde ;
- projet enregistré automatiquement dans un fichier `.montar` (JSON, écriture atomique,
  chemins des médias relatifs au projet quand c'est possible) ;
- import de vidéos, images et sons (bouton ou glisser-déposer), analyse et vignettes en tâche de fond ;
- aperçu dans la toile du projet via le moteur MLT : lecture, curseur, image par image (← →),
  début / fin, qualité d'aperçu ;
- préférences : thème clair / sombre / système, dossier des projets, qualité de l'aperçu ;
- paquet `.deb` pour Debian 12+, Ubuntu 22.04+ et Linux Mint 21+.

Pas encore disponible : timeline, lecture du son, édition, export (voir le planning du cahier
des charges, §9).

## Installer le paquet

```sh
sudo apt install ./montar_0.1.0_all.deb
```

Le paquet est produit par l'intégration continue (onglet *Actions* de GitHub, artefacts
`montar-deb-*`) ou localement avec `./scripts/build-deb.sh`.

## Développement

Dépendances (paquets système) :

```sh
sudo apt install python3 python3-pyqt6 python3-pyqt6.qtsvg python3-mlt ffmpeg python3-pytest
# pour construire le paquet :
sudo apt install build-essential debhelper dh-python lintian
```

Lancer l'application depuis les sources :

```sh
PYTHONPATH=src python3 -m montar
```

Tests et vérification du style :

```sh
QT_QPA_PLATFORM=offscreen python3 -m pytest
pipx run ruff check src tests
```

Organisation du code :

| Dossier | Rôle |
|---------|------|
| `src/montar/core/` | modèle (projet, formats, timecodes, préférences), sans dépendance à Qt |
| `src/montar/engine/` | moteur de rendu : interface abstraite + implémentation MLT |
| `src/montar/media/` | analyse des médias (ffprobe) et vignettes |
| `src/montar/ui/` | interface PyQt6 : thème issu de la charte, accueil, montage, dialogues |
| `src/montar/assets/` | polices (OFL) et icônes Lucide (ISC) embarquées |
| `data/` | lanceur, entrée de menu, type MIME, métadonnées AppStream, page de manuel |
| `debian/` | empaquetage Debian |
| `tests/` | tests `pytest` |

## Licence

montar est distribué sous licence GNU GPL v3 ou ultérieure — voir [LICENSE](LICENSE).
Les polices Manrope et JetBrains Mono sont sous licence SIL OFL 1.1, les icônes Lucide sous
licence ISC (voir `debian/copyright`).
