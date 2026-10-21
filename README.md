# montar

Logiciel libre de montage vidéo de bureau, simple et 100 % local, extensible par modules Python.
Cible : Debian 12+, Ubuntu 24.04+ et Linux Mint 22+ (paquet `.deb`) dans un premier temps, puis Windows.

- Cahier des charges : [docs/CAHIER_DES_CHARGES.md](docs/CAHIER_DES_CHARGES.md)
- Maquettes d'interface : [docs/maquettes/](docs/maquettes/)

## État d'avancement

**Jalon J3 — modules et Timelapse** (version 0.4.0) :

- **Timelapse** (module intégré) : marquez une partie d'un clip avec **I** (début) et
  **O** (fin) dans la timeline, puis onglet **Vitesse → Timelapse…** (ou clic droit sur le
  clip). Facteur ×2 à ×1000 ou durée cible, échantillonnage (une image sur N) ou fusion
  d'images, rampes de vitesse, son coupé / supprimé / accéléré, stabilisation de
  l'exposition. Le segment est pré-calculé en arrière-plan (avancement dans l'en-tête) ;
  « Retirer le timelapse » rend au clip sa forme d'origine ;
- **modules** en Python : effets, outils, sources de clip — voir
  [docs/MODULES.md](docs/MODULES.md) et l'exemple `examples/modules/negatif/` ;
  **Préférences → Extensions** pour activer, installer (`.montar-module`) ou supprimer.

**Jalon J2 — édition de base** (0.3) :

- inspecteur du clip, onglets **Image** (position, échelle, rotation, opacité,
  ajuster / remplir / étirer, retournement, recadrage, fondus), **Audio** (volume, couper le
  son, détacher l'audio), **Vitesse** (×0,1 à ×16), **Couleur** (luminosité, contraste,
  saturation, température, exposition) ;
- panneau **Filtres** : noir et blanc, noir intense, sépia, vintage, chaud, froid, éclatant,
  délavé, avec intensité ; panneau **Effets** : flou, netteté, vignettage ;
- panneau **Transitions** : fondu enchaîné, fondu au noir, fondu au blanc, balayages,
  glissements, zoom, à glisser sur la jonction entre deux clips ; durée réglable dans
  l'inspecteur ;
- panneau **Texte** : 4 styles de titres et 4 bandeaux (maquette 03), police, taille, graisse,
  alignement, couleur, interlettrage, contour, ombre, bandeau, animations d'entrée et de
  sortie ; le texte se déplace et se redimensionne directement dans l'aperçu ;
- volume par piste (clic droit sur l'en-tête de la piste).

**Jalon J1 — timeline** (version 0.2.0) :

- timeline multipiste : pistes vidéo superposées (V1, V2…, la plus haute passe devant),
  pistes audio (A1, A2…) mixées avec le son des vidéos ; ajout de pistes ;
- ajout d'un média par glisser-déposer depuis « Médias du projet » ou double-clic ;
- déplacer un clip (y compris vers une autre piste), rogner ses bords, couper (S),
  supprimer (Suppr), supprimer en refermant l'espace (Maj+Suppr), dupliquer (Ctrl+D) ;
- aimantation aux bords des clips et à la tête de lecture, zoom (Ctrl + molette) ;
- annuler / rétablir (Ctrl+Z, Ctrl+Maj+Z) ;
- couper le son d'une piste, masquer une piste vidéo ;
- lecture de la timeline **avec le son** ; formes d'onde et vignettes sur les clips.

**Jalon J0 — socle** (0.1.0) : accueil, nouveau projet, import de médias, aperçu,
préférences, thèmes, paquet `.deb`.

Pas encore disponible : export (J4).

## Installer le paquet

```sh
sudo apt install ./montar_0.4.0_all.deb
```

Le paquet est produit par l'intégration continue (onglet *Actions* de GitHub, artefacts
`montar-deb-*`) ou localement avec `./scripts/build-deb.sh`.

## Développement

Dépendances (paquets système) :

```sh
sudo apt install python3 python3-pyqt6 python3-pyqt6.qtsvg python3-mlt libmlt-data \
  python3-numpy frei0r-plugins ffmpeg python3-pytest
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
| `src/montar/core/` | modèle sans Qt : projet, timeline (opérations de montage), historique, formats |
| `src/montar/engine/` | moteur de rendu : interface abstraite + implémentation MLT |
| `src/montar/api.py`, `src/montar/plugins/` | API publique et gestionnaire des modules |
| `src/montar/modules/` | modules intégrés (Timelapse) |
| `src/montar/media/` | analyse des médias (ffprobe), vignettes, formes d'onde |
| `src/montar/ui/` | interface PyQt6 : thème, accueil, montage, timeline (`ui/timeline/`), dialogues |
| `src/montar/assets/` | polices (OFL) et icônes Lucide (ISC) embarquées |
| `data/` | lanceur, entrée de menu, type MIME, métadonnées AppStream, page de manuel |
| `debian/` | empaquetage Debian |
| `tests/` | tests `pytest` |

## Licence

montar est distribué sous licence GNU GPL v3 ou ultérieure — voir [LICENSE](LICENSE).
Les polices Manrope, JetBrains Mono, Fraunces et Caveat sont sous licence SIL OFL 1.1, les icônes Lucide sous
licence ISC (voir `debian/copyright`).
