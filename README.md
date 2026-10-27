# montar

Logiciel libre de montage vidéo de bureau, simple et 100 % local, extensible par modules Python.
Cible : Debian 12+, Ubuntu 24.04+ et Linux Mint 22+ (paquet `.deb`) dans un premier temps, puis Windows.

- Cahier des charges : [docs/CAHIER_DES_CHARGES.md](docs/CAHIER_DES_CHARGES.md)
- Maquettes d'interface : [docs/maquettes/](docs/maquettes/)

## État d'avancement

**En développement** : **finition pro** à l'export, étalonnage et mastering de tout le
projet.

- dans le dialogue d'export, bloc **Finition pro** (interrupteur, résumé, préréglages : Vlog
  YouTube, Podcast vidéo, Diffusion TV EBU R128, Réseaux sociaux, Cinéma / festival) et
  bouton **Finition** dans l'en-tête de l'éditeur ;
- **image** : comparaison avant / après (rideau ou côte à côte, zébras hors gamme), 7 looks
  ou une LUT `.cube` avec intensité, roues, exposition, contraste, saturation, température,
  teinte, vibrance, courbes, **harmonisation des plans** sur un plan de référence, niveaux
  légaux, espace couleur Rec.709 ou sRGB, grain et vignette, scopes ;
- **son** : destination (−14, −16, −23, −24 LUFS ou personnalisée), crête vraie maximale,
  nettoyage, tonalité et égaliseur 5 bandes sur le spectre du projet, compression, « voix
  devant », largeur stéréo, limiteur ; sortie **stéréo**, **5.1** (dialogues au centre) ou
  **stéréo + pistes séparées** (« Dialogues » et « Musique et effets » en WAV) ;
- l'export se fait en **trois passes** (analyse, rendu, vérification) et se termine par un
  **rapport de conformité**, aussi enregistré à côté de la vidéo (`.rapport.txt`) ;
- la finition peut être **vue et écoutée dans l'aperçu** de l'éditeur ; les préréglages
  personnels sont enregistrés dans `~/.config/montar/finition.json`.

**Version 1.9** (1.9.0) : enregistrements en deux calques, format libre, lecteur.

- **webcam prête dès la première seconde** : elle s'ouvre pendant le compte à rebours
  (l'enregistrement l'attend si elle tarde) ; plus de webcam qui arrive après 5 s ni de
  saccade au moment où elle apparaît ;
- **l'écran et la webcam restent séparés** : dans la timeline, deux clips liés (ils se
  sélectionnent, se déplacent et se coupent ensemble) ; la webcam se **retire sur un
  passage** (Maj + glisser, puis clic droit « Supprimer la webcam sur la sélection »,
  avec un fondu ; en écran partagé l'écran reprend toute l'image) ou passe **en plein
  écran** sur un passage ; elle reste déplaçable et redimensionnable après coup ;
- **forme ronde** réglée sur le clip (plus incrustée dans l'image) ; fond effacé : vidéo
  transparente (VP9, sinon FFV1) ; plus d'étape d'assemblage à la fin ;
- **format libre** : « Ajuster le cadre à ce média » (clic droit dans Médias), bandeau
  « Adapter le projet » quand le premier média n'a pas le format du projet, format
  « Libre » à la création et « Changer le format… » dans l'inspecteur du projet ;
- **« Modifier le média »** : un grand lecteur avec le son (Espace, J / K / L), réglages
  appliqués pendant la lecture, original au même instant (bascule ou touche C maintenue),
  partie gardée en boucle.

**Version 1.8** (1.8.0) : enregistreur d'écran plus fluide et synchrone.

- **son et image synchrones** : chaque source (écran, micro, webcam) est datée avec
  l'horloge de l'ordinateur puis ramenée au même départ ;
- **plus fluide** : encodeur matériel de la carte graphique s'il est présent (NVIDIA,
  Intel, AMD), fenêtre filmée par Desktop Duplication comme l'écran, tampons plus grands
  pour la webcam, incrustation ronde calculée en petit ;
- **démarrage immédiat** : périphériques et méthode de capture découverts en tâche de fond ;
- **la zone filmée clignote** pendant le compte à rebours (écran, zone ou fenêtre) ;
- **détourage pendant l'enregistrement** : à la fin, il ne reste que l'assemblage (quelques
  secondes) ;
- **tester la webcam** (image en direct) et **réécouter** le test du micro ;
- correction : une transition à motif (balayage, stores…) faisait planter la timeline.

**Version 1.7** (1.7.0) : enregistreur d'écran.

- **webcam** : dans un coin (taille réglable, rectangle ou rond) ou en **écran partagé**
  (à gauche ou à droite), avec un aperçu de la disposition ; **fond flouté ou effacé** : la
  personne est détourée sur l'ordinateur après l'enregistrement (modèle « selfie
  segmenter » de MediaPipe, exécuté par montar lui-même, sans rien à installer) ;
- **micro au choix** et bouton **Tester** (niveau sonore en direct) ;
- Windows : la capture d'une **fenêtre** n'est plus noire (navigateurs, applications
  modernes) ; réglages gardés d'un enregistrement à l'autre.

**Version 1.6** (1.6.0) : montage plus rapide, textes, transitions et éléments.

- timeline : **sélection multiple** (Ctrl + clic, rectangle tracé dans un espace vide,
  Ctrl+A) pour déplacer, supprimer ou dupliquer plusieurs clips ; bouton **Unifier**
  (Ctrl+J) : des clips qui se suivent deviennent un seul clip (morceaux d'un même média
  recollés, sinon rendu avec leurs effets et transitions) ;
- **textes** : animations par le bas, le haut, la gauche, la droite, zoom et rebond, durées
  d'entrée et de sortie réglables, vitesse de la machine à écrire, interligne, opacité du
  bandeau, lignes secondaires (nom puis fonction) et barre d'accent ; **20 nouveaux
  modèles** de titres, tiers inférieurs, citations, génériques ;
- **transitions** : 15 nouvelles (balayages directionnels et doux, stores, ouvertures,
  fermeture, balayage circulaire, cercle, losange, tiers), avec vignettes ;
- rail **Éléments** (ex-Graphiques) en accordéon : deux exemples par catégorie, « Tout
  voir » ; les **filtres** y sont rangés ; nouveaux **effets animés** (éclairs, explosion,
  onde d'énergie, confettis, étincelles, feu d'artifice, cœurs, neige, coup de pinceau,
  fumée, bulles, fuite de lumière), en vidéo transparente au-dessus de l'image ;
- aperçu **plein écran** avec barre de lecture ; le double-clic pour en sortir ne fait plus
  planter montar ;
- Windows : enregistreur d'écran complet (zone, fenêtre, son de l'ordinateur) ;
  inspecteur : valeurs à saisir au clavier, réglages fluides ; interface en **occitan**
  (en cours).

**Version 1.3** (1.3.0) : exigences P3, étalonnage et suivi de mouvement.

- **son** : réduction de bruit, volume régulier, « s'efface sous les voix » (clic droit sur
  une piste → Piste de voix), et dans l'onglet Audio des **options avancées** : égaliseur,
  coupe-bas / coupe-haut, compresseur, hauteur, panoramique, écho, réverbération ;
- **fond vert** (effet du module Studio) et **stabilisation** (outil « Stabiliser… ») ;
- **kit de marque** (Accueil) : logos dans le panneau Éléments, couleurs et polices dans
  les textes ;
- **sous-titres automatiques**, transcrits sur l'ordinateur par Whisper (installez par
  exemple `pip install --user faster-whisper`) ;
- **catalogue de modules** en ligne, à activer dans les Préférences ;
- **étalonnage** (onglet Couleur) : roues ombres / tons moyens / hautes lumières, courbes,
  teinte, vibrance, LUT `.cube`, fenêtre **Scopes** ;
- **suivi de mouvement** (« Suivre un objet… ») : un graphisme ou un logo suit l'objet, ou
  l'objet est pixelisé.

**Version 1.2.1** : corrections et retours — opacité appliquée, déplacement fluide dans
l'aperçu, effets **VHS** et **bande dessinée** refaits (option « Trait vivant »), timeline
**agrandie** ou dans une **fenêtre séparée** (boutons à droite de sa barre d'outils).

**Version 1.2** (1.2.0) : exigences P2 du cahier des charges.

- **images clés** : dans l'inspecteur (onglet Image), « Ajouter une image clé », déplacez la
  tête de lecture puis changez la position, l'échelle, la rotation ou l'opacité — le clip
  s'anime entre les clés (losanges sur le clip dans la timeline) ;
- **sous-titres** (rail Sous-titres) : ajout à la tête de lecture, début / fin, import et
  export **SRT**, taille et position ; à l'export, incrustés dans l'image ou fichier `.srt`
  à côté de la vidéo ;
- **modèles de projet** (Accueil → Modèles) : intro, fin de vidéo, story verticale, ou vos
  projets enregistrés comme modèles (menu « ⋯ ») ;
- **raccourcis clavier personnalisables** (Préférences), **proxys** des vidéos 4K pour un
  aperçu fluide, **notifications** (cloche), aperçu des vidéos **au survol** ;
- texte animé **« machine à écrire »**, **verrouillage** des pistes, **zone de sécurité**,
  **lecture inversée**, **image fixe**, export d'une **plage** (I / O) ou d'une **image**,
  **couleur d'accent**, durée de la corbeille.

**Version 1.1** (1.1.0) : modules, effets et graphismes.

- rail **Modules** : tout ce qu'apportent les modules actifs, avec recherche ; un clic
  applique l'effet ou l'outil au clip sélectionné ; **Gérer les modules…** ;
- nouveau module intégré **Effets** : VHS, zoom lent / rapide, dézoom lent / rapide,
  bande dessinée, flou (doux, mouvement, carrés) ; le panneau **Effets** montre les effets
  appliqués au clip, avec leurs réglages ;
- rail **Graphiques** (devenu **Éléments** en 1.6) : annotations, figures, formes,
  arrière-plans, superpositions, cadres et stickers, placés à la tête de lecture (les
  arrière-plans sous la vidéo) ;
- **écrire ses modules** : guide complet [docs/MODULES.md](docs/MODULES.md),
  `montar --new-module DOSSIER --type effet-video` (squelette) et
  `montar --pack-module DOSSIER` (archive) ; **accueil → Modules → Installer un
  module** depuis un fichier `.montar-module` ou `.zip`, un dossier, ou un dossier lié pour
  le développement (**Recharger** relit le code).

**Version 1.0 — Linux** (1.0.0) : fin du jalon J5, toutes les exigences P1 sont en place.

- projets : **Enregistrer sous** / **Dupliquer**, copies de sauvegarde datées dans le
  dossier `sauvegardes/` du projet, **récupération** après un arrêt brutal, **reliaison**
  des médias manquants (les autres fichiers du même dossier sont retrouvés) ;
- accueil : **Médiathèque** (médias de tous les projets, réutilisables) et **Corbeille**
  (restauration, suppression définitive après 30 jours) ;
- aperçu : **volume**, **plein écran** (F), raccourcis **J / K / L** (arrière, pause,
  avant ; appuyer plusieurs fois accélère jusqu'à ×8), zoom **Ajuster / 50 / 100 / 200 %** ;
- timeline : **marqueurs** (M, Ctrl+← / Ctrl+→, glisser le fanion, double-clic pour le
  renommer) et **voix off** (bouton micro : la timeline est lue pendant que vous parlez,
  l'enregistrement est placé sur une piste « Voix off ») ;
- préférences : sauvegarde automatique activable (sinon Ctrl+S et proposition à la
  fermeture), intervalle des copies de sauvegarde, **Stockage & cache** (taille, « Vider le
  cache », espace libre), **langue** : français, anglais, occitan (traduction en cours) ou langue du système ;
- modules (API 1.2) : **effets audio**, **transitions**, **générateurs** (bouton
  **Créer…** du panneau Médias) et **formats d'export** ; nouveau module intégré
  **Essentiels** : écho, graves et aigus, volume égalisé, transitions cercle / volet /
  diagonale, fond uni et dégradé, exports MKV et ProRes.

**Jalon J5 — compléments v1 Linux** (0.5.1 à 0.5.4) :

- les calculs longs (export, Timelapse) s'affichent dans une grande fenêtre d'avancement
  au centre, qui protège le projet pendant le calcul (annulation possible) ;
- panneau Médias : recherche par nom, filtre **Tous / Utilisés / Non utilisés**, pastille ✓
  sur les médias déjà dans le montage ;
- **Modifier le média…** (clic droit dans le panneau Médias) : aperçu avant / après côte à
  côte ; rogner début / fin, recadrer, pivoter, retourner, couleur et filtres, vitesse,
  volume ou suppression du son, Timelapse sur tout le média ; puis **Remplacer
  l'original** (les clips qui l'utilisent sont adaptés, annulable) ou **Créer une copie** ;
- **Enregistrer** (rail de gauche) : enregistrement de l'écran entier, d'une zone dessinée à
  la souris ou d'une fenêtre, avec le micro et / ou le son de l'ordinateur et la webcam en
  incrustation ; montar se réduit et laisse une petite fenêtre « Arrêter » ;
  l'enregistrement est ajouté aux médias du projet. Session X11 nécessaire (session
  Cinnamon par défaut de Linux Mint) ; pas encore sous Wayland ;
- clic droit sur un clip (ou une plage sélectionnée) → **Appliquer un effet ou un module…** :
  une fenêtre avec recherche regroupe les outils des modules (Timelapse…), les effets des
  modules, les filtres et les effets ; sur une plage, le clip est d'abord coupé à ses bornes.

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
  **accueil → Modules** pour activer, installer (`.montar-module`) ou supprimer ;
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

## Installer le paquet

```sh
sudo apt install ./montar_1.1.0_all.deb
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
