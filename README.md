# montar

Logiciel libre de montage vidéo de bureau, simple et 100 % local, extensible par modules Python.
Cible : Debian 12+, Ubuntu 24.04+ et Linux Mint 22+ (paquet `.deb`) dans un premier temps, puis Windows.

- Cahier des charges : [docs/CAHIER_DES_CHARGES.md](docs/CAHIER_DES_CHARGES.md)
- Maquettes d'interface : [docs/maquettes/](docs/maquettes/)

## État d'avancement

**Jalon J5 — compléments v1 Linux** (en cours, version 0.5.1) :

- les calculs longs (export, Timelapse) s'affichent dans une grande fenêtre d'avancement
  au centre, qui protège le projet pendant le calcul (annulation possible) ;
- panneau Médias : recherche par nom, filtre **Tous / Utilisés / Non utilisés**, pastille ✓
  sur les médias déjà dans le montage.

**Jalon J4 — export** (0.5.0) :

- bouton **Exporter** (Ctrl+E) : MP4 / MOV (H.264, H.265), WebM (VP9), GIF animé, ou
  **audio seul** (MP3, WAV, AAC) ; résolution 480p à 4K, images par seconde, qualité
  Légère / Équilibrée / Maximale, taille estimée ; accélération matérielle (NVENC, VA-API)
  avec repli logiciel automatique ;
- le fichier est écrit par défaut dans le dossier `exports/` du projet ; l'export se fait en
  tâche de fond (avancement et temps restant dans l'en-tête, bouton d'annulation), puis
  **Lire** ou **Ouvrir le dossier** ;
- préférences : accélération matérielle, ondes audio sur les clips vidéo, magnétisme par
  défaut ;
- les boutons Montage / Couleur / Audio / Sous-titres de l'en-tête sont retirés.

**Jalon J3 — modules et Timelapse** (0.4) :

- **Timelapse** (module intégré) : sélectionnez une partie d'un clip (**Maj + glisser**
  sur le clip, outil « plage » de la barre de la timeline, ou touches **I** / **O**), puis onglet **Vitesse → Timelapse…** (ou clic droit sur le
  clip). Facteur ×2 à ×1000 ou durée cible, échantillonnage (une image sur N) ou fusion
  d'images, rampes de vitesse, son coupé / supprimé / accéléré, stabilisation de
  l'exposition. Le segment est pré-calculé en arrière-plan (avancement dans l'en-tête) ;
  « Retirer le timelapse » rend au clip sa forme d'origine ;
- **modules** en Python : effets, outils, sources de clip — voir
  [docs/MODULES.md](docs/MODULES.md) et l'exemple `examples/modules/negatif/` ;
  **Préférences → Extensions** pour activer, installer (`.montar-module`) ou supprimer ;
- 0.4.1 : dans l'aperçu, redimensionnement par les coins avec le coin opposé fixe,
  aimantation au centre et aux bords (Ctrl la désactive), cadre qui suit la rotation ;
  **Isoler** coupe un clip aux bornes de la sélection ; déposer un clip entre deux pistes
  (ou sur une place occupée) crée une nouvelle piste ; l'ordre des pistes se change en
  glissant leur en-tête ; les modes **Couleur** et **Audio** de l'en-tête ouvrent les
  panneaux correspondants ;
- 0.4.3 : correction du placement des éléments déplacés ou redimensionnés sur un système
  en français (MLT lisait « 345.6 » avec la virgule décimale) ; `montar --diagnostic`
  affiche les versions, la convention numérique et vérifie le placement dans l'aperçu ;
- 0.4.4 : chaque projet a son dossier `~/Vidéos/Montar/<nom>/` (fichier `.montar` et
  sous-dossier `medias/`) ; **tous les médias importés y sont copiés**, vidéos comprises
  (avancement dans l'en-tête). Les projets plus anciens sont rangés dans leur dossier et
  leurs médias copiés à l'ouverture. Timelapse : calcul beaucoup plus rapide sur les longues
  vidéos (facteur non entier, rampes, fusion), bouton **Annuler** et **Relancer** après un
  échec ou une annulation, arrêt d'un ffmpeg qui ne progresse plus.

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
sudo apt install ./montar_0.5.1_all.deb
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
| `src/montar/engine/` | moteur de rendu : interface abstraite + implémentation MLT, réglages d'export |
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
