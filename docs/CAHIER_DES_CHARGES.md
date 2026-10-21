# Cahier des charges — Montar

> Logiciel de montage vidéo de bureau, simple et local, extensible par modules.
> Version du document : 0.1 (brouillon initial) — 21/10/2026

---

## 1. Contexte et objectifs

### 1.1 Contexte
Les éditeurs vidéo « grand public » comme Microsoft Clipchamp offrent une prise en main rapide,
mais imposent souvent un compte en ligne, un stockage cloud ou un fonctionnement dans le navigateur,
et ne sont pas disponibles nativement sous Linux.

### 1.2 Objectifs
| # | Objectif |
|---|----------|
| O1 | Proposer un éditeur vidéo **simple**, au niveau fonctionnel de Clipchamp (fonctions de base). |
| O2 | Fonctionner **100 % en local** : aucun compte, aucune connexion obligatoire, aucun envoi de média vers un drive. |
| O3 | Cibler **Linux en premier** (paquet `.deb`), puis **Windows** (installeur `.exe`/`.msi`). |
| O4 | Être **extensible par modules** (effets, transitions, formats d'export, outils) sans recompiler l'application. |
| O5 | Fournir dès la v1 un **effet Timelapse** applicable à une **portion** d'une vidéo. |

### 1.3 Hors périmètre (v1)
- Montage collaboratif / temps réel à plusieurs.
- Stockage cloud intégré (l'utilisateur reste libre de travailler dans un dossier synchronisé, mais l'application ne l'exige pas).
- Fonctions IA nécessitant un service en ligne.
- Compositing avancé (keying 3D, suivi de mouvement, étalonnage professionnel).
- Version macOS (envisageable plus tard, l'architecture ne doit pas l'empêcher).

---

## 2. Utilisateurs cibles

- **Utilisateur occasionnel** : monte des vidéos de vacances, tutoriels, vidéos pour réseaux sociaux.
- **Créateur de contenu débutant** : besoin de titres, musique, sous-titres, export vertical (9:16).
- **Développeur / contributeur** : souhaite ajouter un module (effet, export) via une API documentée.

Hypothèses : aucune compétence technique requise pour l'utilisateur final ; interface en français et en anglais dès la v1.

---

## 3. Exigences fonctionnelles

Priorités : **P1** = indispensable v1 · **P2** = souhaitable v1 · **P3** = versions ultérieures.

### 3.1 Gestion de projet
| ID | Exigence | Prio |
|----|----------|------|
| F-PRJ-01 | Créer, ouvrir, enregistrer, « enregistrer sous » un projet dans un fichier local (`.montar`). | P1 |
| F-PRJ-02 | Choisir le format du projet : 16:9, 9:16, 1:1, 4:5, 21:9 ; résolution et fréquence d'images (24/25/30/50/60 i/s). | P1 |
| F-PRJ-03 | Sauvegarde automatique périodique + récupération après plantage. | P1 |
| F-PRJ-04 | Liste des projets récents sur l'écran d'accueil (avec vignette). | P1 |
| F-PRJ-05 | Les médias sont **référencés** (non copiés) ; option « Rassembler le projet » pour copier tous les médias dans un dossier (archivage / transfert). | P2 |
| F-PRJ-06 | Détection des médias manquants et outil de reliaison. | P1 |
| F-PRJ-07 | Annuler / Rétablir illimité (dans la limite de la session). | P1 |

### 3.2 Bibliothèque de médias
| ID | Exigence | Prio |
|----|----------|------|
| F-MED-01 | Import par glisser-déposer ou sélecteur de fichiers : vidéo, audio, image. | P1 |
| F-MED-02 | Formats d'entrée minimaux : MP4 (H.264/H.265), MOV, MKV, WebM, AVI ; MP3, WAV, AAC, FLAC, OGG ; JPG, PNG, WebP, GIF. | P1 |
| F-MED-03 | Vignettes, durée, résolution affichées ; aperçu au survol. | P1 |
| F-MED-04 | Génération de **proxys** (copies basse résolution) pour les fichiers lourds (4K), en tâche de fond. | P2 |
| F-MED-05 | Enregistrement webcam / micro / écran local. | P3 |

### 3.3 Timeline (frise chronologique)
| ID | Exigence | Prio |
|----|----------|------|
| F-TL-01 | Pistes multiples : vidéo/image, texte, audio (nombre non limité arbitrairement). | P1 |
| F-TL-02 | Ajout de clips par glisser-déposer depuis la bibliothèque. | P1 |
| F-TL-03 | Déplacer, rogner (début/fin), **scinder** au curseur (raccourci `S`), supprimer, dupliquer. | P1 |
| F-TL-04 | Suppression avec fermeture automatique de l'espace (« ripple delete »). | P1 |
| F-TL-05 | Magnétisme (aimantation aux bords des clips et au curseur), activable/désactivable. | P1 |
| F-TL-06 | Zoom de la timeline, défilement, « ajuster à la fenêtre ». | P1 |
| F-TL-07 | Sélection d'une **plage** (point d'entrée / point de sortie) sur un clip — utilisée notamment par le Timelapse. | P1 |
| F-TL-08 | Verrouiller / masquer / couper le son d'une piste. | P2 |
| F-TL-09 | Affichage des formes d'onde audio. | P1 |
| F-TL-10 | Marqueurs nommés. | P2 |

### 3.4 Lecteur / prévisualisation
| ID | Exigence | Prio |
|----|----------|------|
| F-PRV-01 | Lecture temps réel de la timeline avec son, en résolution réduite si nécessaire. | P1 |
| F-PRV-02 | Navigation image par image, raccourcis J/K/L, espace = lecture/pause. | P1 |
| F-PRV-03 | Choix de la qualité d'aperçu (Complète, 1/2, 1/4). | P1 |
| F-PRV-04 | Manipulation directe dans l'aperçu : déplacer / redimensionner / pivoter un clip, un texte, une image. | P1 |
| F-PRV-05 | Mode plein écran. | P2 |

### 3.5 Édition de base des clips (équivalent Clipchamp)
| ID | Exigence | Prio |
|----|----------|------|
| F-EDT-01 | Recadrage (crop), rotation, retournement horizontal/vertical. | P1 |
| F-EDT-02 | Redimensionnement : ajuster / remplir / étirer ; position libre. | P1 |
| F-EDT-03 | Vitesse de clip constante (0,1× à 16×). | P1 |
| F-EDT-04 | Réglages de couleur simples : luminosité, contraste, saturation, température, exposition. | P1 |
| F-EDT-05 | Filtres prédéfinis (noir et blanc, sépia, vintage, froid, chaud…). | P1 |
| F-EDT-06 | Opacité et fondu d'entrée / de sortie (vidéo et audio). | P1 |
| F-EDT-07 | Effets simples : flou, vignettage, netteté, zoom lent (« Ken Burns ») sur image. | P2 |
| F-EDT-08 | Incrustation d'image (picture-in-picture) via pistes superposées. | P1 |
| F-EDT-09 | Image fixe (« freeze frame ») à la position du curseur. | P2 |
| F-EDT-10 | Lecture inversée. | P2 |
| F-EDT-11 | Images clés (keyframes) sur position, échelle, opacité. | P3 |
| F-EDT-12 | Fond vert (chroma key) basique. | P3 |
| F-EDT-13 | Stabilisation vidéo (traitement local). | P3 |

### 3.6 Transitions
| ID | Exigence | Prio |
|----|----------|------|
| F-TRN-01 | Transitions entre deux clips adjacents : fondu enchaîné, fondu au noir/blanc, glissement, balayage, zoom. | P1 |
| F-TRN-02 | Durée réglable par glisser ou saisie. | P1 |

### 3.7 Texte et titres
| ID | Exigence | Prio |
|----|----------|------|
| F-TXT-01 | Ajout de textes sur une piste dédiée ; police, taille, couleur, contour, ombre, fond, alignement. | P1 |
| F-TXT-02 | Modèles de titres (titre, sous-titre, bas de vignette / « lower third »). | P1 |
| F-TXT-03 | Animations d'entrée/sortie simples (fondu, glissement, machine à écrire). | P2 |
| F-TXT-04 | Import / export de sous-titres SRT ; sous-titres incrustés ou piste séparée à l'export. | P2 |
| F-TXT-05 | Transcription automatique **locale** (module optionnel, modèle de reconnaissance vocale hors ligne). | P3 |

### 3.8 Audio
| ID | Exigence | Prio |
|----|----------|------|
| F-AUD-01 | Volume par clip et par piste ; couper le son. | P1 |
| F-AUD-02 | Détacher l'audio d'un clip vidéo. | P1 |
| F-AUD-03 | Fondu audio d'entrée / de sortie. | P1 |
| F-AUD-04 | Enregistrement de voix off depuis le micro. | P2 |
| F-AUD-05 | Normalisation du volume ; atténuation automatique de la musique sous la voix (« ducking »). | P3 |
| F-AUD-06 | Réduction de bruit basique. | P3 |

### 3.9 Effet Timelapse (fonction par défaut, P1)

L'effet Timelapse doit permettre d'**accélérer fortement une partie seulement d'un clip**, le reste du clip conservant sa vitesse normale.

#### 3.9.1 Parcours utilisateur
1. L'utilisateur sélectionne un clip dans la timeline.
2. Il définit une plage : points d'entrée/sortie (`I` / `O`) ou glisser sur le clip, ou bien sélectionne directement un clip déjà scindé.
3. Il choisit **Effets → Timelapse** (ou clic droit → « Timelapse sur la sélection »).
4. Un panneau propose les réglages ci-dessous, avec aperçu immédiat.
5. Validation : le clip est découpé en 3 segments (avant / timelapse / après) ; le segment accéléré est visuellement repéré dans la timeline (badge « TL ×N »).

#### 3.9.2 Réglages
| Réglage | Valeurs | Défaut |
|---------|---------|--------|
| Mode de saisie | Facteur d'accélération **ou** durée cible du segment | Facteur |
| Facteur | ×2 à ×1000 (pas libre) ; préréglages ×4, ×8, ×16, ×32, ×60 | ×16 |
| Durée cible | ex. « 10 min → 15 s » ; le facteur est calculé | — |
| Méthode | **Échantillonnage** (une image sur N, rendu net et saccadé type timelapse classique) / **Fusion d'images** (moyenne de N images, rendu fluide avec traînées de mouvement) | Échantillonnage |
| Rampe de vitesse | Aucune / Douce en entrée / Douce en sortie / Les deux ; durée de rampe réglable (0–3 s) | Aucune |
| Audio du segment | Couper / Supprimer / Accélérer (hauteur préservée, utile seulement pour faibles facteurs) | Couper |
| Stabilisation de l'exposition | Lissage du scintillement de luminosité (« deflicker ») | Désactivé (P2) |

#### 3.9.3 Règles et contraintes
- L'effet est **non destructif** : il peut être modifié ou retiré à tout moment, le fichier source n'est jamais altéré.
- Plusieurs segments Timelapse peuvent coexister sur un même clip.
- La durée affichée dans la timeline est mise à jour en temps réel.
- Prévisualisation fluide jusqu'à ×64 en mode Échantillonnage sur la machine de référence ; au-delà, ou en mode Fusion, un **pré-calcul en tâche de fond** (cache) est autorisé avec barre de progression.
- Les transitions et le texte placés sur le segment s'appliquent normalement.
- Retirer l'effet propose de « fusionner » les segments pour retrouver le clip d'origine.

#### 3.9.4 Critères d'acceptation
- Une vidéo de 10 min en 1080p30, timelapse ×40 sur les minutes 2 à 8 → durée finale = 2 + 9 s + 2 = **4 min 9 s** (± 1 image).
- L'export du segment en mode Échantillonnage contient exactement une image source sur 40 (vérifiable par test automatisé sur une mire numérotée).
- Les parties avant/après sont strictement identiques à la source (même nombre d'images, synchro audio conservée).

### 3.10 Export
| ID | Exigence | Prio |
|----|----------|------|
| F-EXP-01 | Export MP4 (H.264 + AAC) en 480p, 720p, 1080p, 4K. | P1 |
| F-EXP-02 | Préréglages : « Web », « Réseaux sociaux vertical », « Haute qualité », « Brouillon rapide ». | P1 |
| F-EXP-03 | Export WebM (VP9/AV1), MOV, GIF animé, audio seul (MP3/WAV). | P2 |
| F-EXP-04 | Export d'une plage seulement de la timeline. | P2 |
| F-EXP-05 | Encodage matériel si disponible (VA-API sous Linux, NVENC, QSV, AMF sous Windows), repli logiciel automatique. | P2 |
| F-EXP-06 | Export en tâche de fond avec progression, temps restant estimé, annulation ; l'interface reste utilisable. | P1 |
| F-EXP-07 | Le fichier est écrit localement dans le dossier choisi ; **aucun téléversement automatique**. | P1 |
| F-EXP-08 | Exporter une image fixe (capture) au curseur. | P2 |

### 3.11 Modules (extensibilité)
| ID | Exigence | Prio |
|----|----------|------|
| F-MOD-01 | Gestionnaire de modules : liste, activer/désactiver, version, auteur, description. | P1 |
| F-MOD-02 | Installation d'un module depuis un fichier local (archive `.montar-module`) ; aucun dépôt en ligne requis. | P1 |
| F-MOD-03 | Types de modules supportés : **effet vidéo**, **effet audio**, **transition**, **générateur** (titre, fond, forme), **format d'export**, **outil** (action sur la timeline / panneau). | P1 (effet, transition) / P2 (autres) |
| F-MOD-04 | Le Timelapse est lui-même implémenté comme un **module intégré**, servant de référence pour l'API. | P1 |
| F-MOD-05 | Un module défectueux ne doit pas empêcher le démarrage (isolation, désactivation automatique après plantage). | P1 |
| F-MOD-06 | Un projet utilisant un module absent s'ouvre quand même ; l'effet manquant est signalé et ignoré au rendu. | P1 |
| F-MOD-07 | Dépôt / catalogue de modules en ligne (optionnel, désactivable). | P3 |

### 3.12 Préférences et ergonomie
| ID | Exigence | Prio |
|----|----------|------|
| F-UX-01 | Interface en français et anglais (fichiers de traduction, ajout d'autres langues possible). | P1 |
| F-UX-02 | Thème sombre et clair. | P1 |
| F-UX-03 | Raccourcis clavier documentés et personnalisables. | P2 |
| F-UX-04 | Choix des dossiers : cache, proxys, sauvegardes automatiques, export par défaut. | P1 |
| F-UX-05 | Vider le cache depuis les préférences, avec affichage de la taille occupée. | P1 |
| F-UX-06 | Aucune télémétrie par défaut ; rapport de plantage uniquement sur action explicite de l'utilisateur. | P1 |

---

## 4. Exigences non fonctionnelles

### 4.1 Plateformes
| Phase | Plateforme | Livrable |
|-------|------------|----------|
| 1 | Linux x86_64 — Debian 12+, Ubuntu 22.04 LTS+ (et dérivées : Mint, Pop!_OS) | Paquet **`.deb`** (+ AppImage en option) |
| 2 | Windows 10 (22H2) / 11 x64 | Installeur `.exe` (NSIS ou Inno Setup) ou `.msi`, + version portable `.zip` |
| Ultérieur | Linux arm64, Flatpak, macOS | — |

Le code doit être **multiplateforme dès le départ** : pas d'appel système spécifique à Linux hors d'une couche d'abstraction.

### 4.2 Configuration de référence
- **Minimale** : CPU 4 cœurs (2015+), 8 Go RAM, GPU compatible OpenGL 3.3, montage 1080p.
- **Recommandée** : CPU 6–8 cœurs, 16 Go RAM, GPU avec décodage/encodage matériel, montage 4K avec proxys.

### 4.3 Performances
| ID | Exigence |
|----|----------|
| NF-PRF-01 | Démarrage de l'application < 3 s (machine recommandée, SSD). |
| NF-PRF-02 | Lecture temps réel d'une timeline 1080p30 avec 2 pistes vidéo + 1 transition + 1 texte, sans image perdue en qualité d'aperçu 1/2. |
| NF-PRF-03 | Réponse aux actions de la timeline (déplacer, scinder) < 100 ms. |
| NF-PRF-04 | Export 1080p H.264 d'une minute en < 1 min (encodage matériel) / < 2 min (logiciel), machine recommandée. |
| NF-PRF-05 | Toutes les tâches lourdes (import, vignettes, proxys, export) s'exécutent hors du fil de l'interface. |

### 4.4 Fiabilité et données
- Le fichier projet est un format **texte lisible** (JSON ou XML) versionné, avec migration automatique entre versions.
- Écriture atomique du projet (fichier temporaire puis renommage) pour éviter toute corruption.
- Les fichiers sources ne sont **jamais modifiés**.
- Chemins des médias stockés en relatif au projet quand c'est possible (portabilité du dossier projet Linux ↔ Windows).

### 4.5 Confidentialité et fonctionnement hors ligne
- Toutes les fonctions P1 et P2 fonctionnent **sans connexion Internet**.
- Aucun compte utilisateur.
- Aucune donnée envoyée sans action explicite (vérification de mise à jour désactivable, désactivée par défaut dans le `.deb` puisque gérée par le gestionnaire de paquets).

### 4.6 Sécurité des modules
- Un module déclare ses permissions dans son manifeste (accès fichiers hors projet, réseau).
- Avertissement à l'installation d'un module non signé.
- Signature des modules officiels.

### 4.7 Maintenabilité / qualité
- Tests unitaires du modèle (timeline, projet, calcul des durées, Timelapse) ; couverture ≥ 70 % sur le cœur.
- Tests de rendu automatisés (comparaison d'images sur mires de test).
- Intégration continue : compilation et tests Linux + Windows à chaque commit ; génération automatique du `.deb`.
- Journalisation (logs) dans un fichier local rotatif.

### 4.8 Accessibilité
- Navigation complète au clavier des menus et dialogues.
- Contrastes conformes WCAG AA ; taille d'interface réglable (mise à l'échelle HiDPI).

### 4.9 Licence
À décider (voir §8). Les dépendances envisagées (FFmpeg, MLT, Qt) imposent des contraintes LGPL/GPL à respecter, notamment en cas de distribution Windows.

---

## 5. Architecture technique proposée

### 5.1 Choix technologiques (proposition)
| Couche | Technologie proposée | Justification |
|--------|---------------------|---------------|
| Langage cœur | **C++20** | Performances temps réel, accès direct aux bibliothèques multimédia. |
| Interface | **Qt 6 (QML / Qt Quick)** | Multiplateforme Linux/Windows, rendu GPU, interface moderne type Clipchamp, système de plugins natif. |
| Moteur de montage | **MLT Framework 7** | Moteur éprouvé (Kdenlive, Shotcut) : timeline multipiste, transitions, filtres, changement de vitesse (`timewarp`), rendu ; évite de réécrire un moteur. |
| Décodage / encodage | **FFmpeg 6+** (via MLT) | Couverture formats/codecs, accélération matérielle. |
| Effets supplémentaires | frei0r, filtres FFmpeg (`framestep`, `tmix`, `deflicker`), shaders GLSL | Base d'effets riche. |
| Scripts de modules | API C++ + **modules déclaratifs QML/JSON** ; Python embarqué en option (P3) | Les modules simples n'ont pas besoin de compilation. |
| Build | CMake + CPack | Génère directement le `.deb` ; NSIS/WiX pour Windows. |
| CI | GitHub Actions (Ubuntu + Windows) | Paquets générés à chaque version. |

*Alternative étudiée* : Tauri/Electron + FFmpeg en ligne de commande — plus rapide à prototyper côté interface, mais prévisualisation temps réel et précision à l'image nettement plus difficiles. **Non retenue** pour le cœur.

### 5.2 Découpage en modules logiciels
```
montar/
├── app/            # Point d'entrée, fenêtre principale
├── ui/             # QML : bibliothèque, timeline, aperçu, inspecteur, export
├── core/           # Modèle : Projet, Piste, Clip, Effet, Transition, Undo/Redo
├── engine/         # Adaptateur MLT : construction du graphe, lecture, rendu
├── media/          # Import, analyse, vignettes, formes d'onde, proxys, cache
├── plugins-api/    # Interfaces publiques stables (en-têtes) pour les modules
├── plugins/        # Modules intégrés : timelapse, filtres de base, transitions
├── export/         # Préréglages et file d'export
├── platform/       # Abstractions OS (chemins, encodage matériel, intégration bureau)
├── packaging/      # debian/, windows/ (NSIS), icônes, .desktop
└── tests/
```

### 5.3 API de modules (principes)
- Chaque module = dossier/archive contenant un **manifeste** (`module.json` : id, nom, version, version d'API requise, type, permissions, paramètres exposés) + code (bibliothèque partagée `.so`/`.dll` **ou** description déclarative s'appuyant sur des filtres existants).
- Les **paramètres** déclarés dans le manifeste génèrent automatiquement l'interface dans l'inspecteur (curseurs, listes, couleurs, cases).
- **Versionnage sémantique** de l'API ; compatibilité ascendante garantie à l'intérieur d'une version majeure.
- Points d'extension : `VideoEffect`, `AudioEffect`, `Transition`, `Generator`, `ExportFormat`, `Tool`.
- Emplacements : modules système (`/usr/lib/montar/modules`, `C:\Program Files\Montar\modules`) et utilisateur (`~/.local/share/montar/modules`, `%APPDATA%\Montar\modules`).

### 5.4 Implémentation envisagée du Timelapse
- Découpage du clip en 3 producteurs MLT partageant la même source.
- Segment central :
  - *Échantillonnage* : producteur `timewarp` (vitesse = facteur) ou filtre `framestep`.
  - *Fusion* : moyenne de N images (`tmix` FFmpeg ou filtre dédié) puis décimation, avec cache de rendu.
  - *Rampe* : courbe de vitesse appliquée sur les bords du segment.
- Persistance dans le projet sous forme d'effet paramétré (pas de fichier intermédiaire obligatoire).

---

## 6. Interface utilisateur (maquette fonctionnelle)

```
┌───────────────────────────────────────────────────────────────────────┐
│ Menu  |  Projet: Vacances.montar   [16:9 ▾]        [Annuler][Rétablir] [Exporter] │
├──────────┬──────────────────────────────────────┬─────────────────────┤
│ Médias   │                                      │ Inspecteur          │
│ Texte    │           APERÇU VIDÉO               │ (propriétés du      │
│ Audio    │                                      │  clip sélectionné : │
│ Transit. │      ◀◀   ▶   ▶▶   00:01:23 / 04:09  │  Vitesse, Couleur,  │
│ Effets   │                                      │  Timelapse, Audio…) │
│ Modules  │                                      │                     │
├──────────┴──────────────────────────────────────┴─────────────────────┤
│ [✂ Scinder][🗑][🧲]                                    zoom ─────●──  │
│ T1 ▸ [Titre ]                                                         │
│ V2 ▸        [ Logo ]                                                  │
│ V1 ▸ [ Clip A ][ Clip B ▓▓ TL ×40 ▓▓ Clip B ][ Clip C ]               │
│ A1 ▸ [~~~~~~~~~~~~~~~~ musique.mp3 ~~~~~~~~~~~~~~~~~~~]               │
└───────────────────────────────────────────────────────────────────────┘
```
- Panneau gauche : onglets de ressources (style Clipchamp).
- Centre : aperçu, contrôles de lecture.
- Droite : inspecteur contextuel.
- Bas : timeline multipiste.

---

## 7. Packaging et distribution

### 7.1 Linux (phase 1)
- Paquet `.deb` généré par CPack (ou `debian/` + `dpkg-buildpackage`) :
  - Nom : `montar`, architecture `amd64`.
  - Dépendances déclarées : `libmlt++7`, `libavcodec60` (ou version de la distribution), `qt6-declarative`, `frei0r-plugins`…
  - Installe : binaire `/usr/bin/montar`, ressources `/usr/share/montar`, modules `/usr/lib/montar/modules`, entrée de menu `.desktop`, icônes, type MIME `application/x-montar-project` (double-clic sur un `.montar`).
- Vérification avec `lintian` sans erreur.
- Option : AppImage pour les distributions non Debian.

### 7.2 Windows (phase 2)
- Toutes les dépendances embarquées (Qt, MLT, FFmpeg en version LGPL).
- Installeur NSIS/Inno Setup : raccourcis, association `.montar`, désinstallation propre.
- Signature de code de l'exécutable (certificat à prévoir).
- Version portable `.zip`.

---

## 8. Points ouverts / décisions à prendre
1. **Licence du projet** : GPLv3 (compatible MLT/FFmpeg GPL, simple) ou propriétaire / LGPL (contraintes plus fortes sur les dépendances).
2. **Nom définitif** et identité visuelle (« Montar » provisoire).
3. **Langage des modules** : C++ uniquement en v1, ou Python embarqué dès la v1 pour faciliter les contributions ?
4. Fournir une **bibliothèque de ressources libres** (musiques, autocollants, fonds) embarquée, ou téléchargeable à part pour limiter la taille du paquet ?
5. Distributions Linux visées en priorité au-delà de Debian/Ubuntu (Fedora → `.rpm`, Flatpak) ?

---

## 9. Planning prévisionnel (jalons)

| Jalon | Contenu | Livrable |
|-------|---------|----------|
| **J0 — Socle** | Architecture CMake/Qt/MLT, fenêtre, import, aperçu d'un clip, CI Linux | Build de dev |
| **J1 — Timeline** | Pistes, glisser-déposer, rogner, scinder, undo/redo, sauvegarde projet | Alpha interne |
| **J2 — Édition de base** | Texte, transitions, audio, couleur, filtres, vitesse | Alpha |
| **J3 — Timelapse + API modules** | Module Timelapse, gestionnaire de modules, API v1 documentée | Bêta |
| **J4 — Export & packaging Linux** | Préréglages, file d'export, accélération matérielle, `.deb` | **v1.0 Linux** |
| **J5 — Portage Windows** | CI Windows, encodage matériel Windows, installeur | **v1.0 Windows** |
| **J6+** | Fonctions P3, catalogue de modules, Flatpak/macOS | v1.x |

---

## 10. Critères de recette globaux (v1.0)
- Toutes les exigences **P1** implémentées et testées.
- Scénario de bout en bout réussi sans connexion réseau : *créer un projet 16:9 → importer 3 vidéos + 1 musique → couper, ordonner, ajouter 2 transitions et un titre → appliquer un Timelapse ×20 sur une portion → exporter en MP4 1080p → relire le fichier dans un lecteur tiers.*
- Le paquet `.deb` s'installe et se désinstalle proprement sur Ubuntu 24.04 et Debian 12 ; `lintian` sans erreur.
- Un module d'exemple tiers (effet « négatif ») s'installe depuis un fichier local et fonctionne sans recompiler l'application.
- Aucun plantage sur la suite de tests de robustesse (fichiers corrompus, médias manquants, module défaillant).

---

## Annexe A — Glossaire
- **Clip** : portion d'un média placée sur la timeline.
- **Proxy** : copie basse résolution d'un média pour fluidifier le montage.
- **Ripple delete** : suppression qui décale automatiquement les clips suivants.
- **Timelapse** : accélération forte d'une séquence pour condenser un temps long.
- **Rampe de vitesse** : transition progressive entre vitesse normale et vitesse accélérée.
- **Module** : extension installable ajoutant une fonction (effet, transition, export…).
