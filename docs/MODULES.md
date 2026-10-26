# Écrire un module montar

Ce guide explique comment ajouter à montar vos propres **effets vidéo et audio**,
**transitions**, **graphismes**, **générateurs de médias**, **formats d'export** et
**outils**, puis comment les partager. Un module est un petit dossier Python ; il ne demande
ni compilation ni outil particulier.

- API publique : `montar.api`, version **1.4**.
- Exemples complets : les modules intégrés, dans `src/montar/modules/` (`effets`,
  `essentiels`, `graphismes`, `timelapse`), et `examples/modules/negatif/`.

> **Sécurité et licence.** Un module s'exécute avec les droits de l'utilisateur ; montar
> affiche un avertissement avant d'installer un module tiers. Un module chargé dans montar
> est une œuvre dérivée au sens de la GPL : publiez-le sous une licence compatible
> (GPL-3.0-or-later).

## Sommaire

1. [Démarrer en trois commandes](#1-démarrer-en-trois-commandes)
2. [Structure d'un module](#2-structure-dun-module)
3. [Paramètres réglables](#3-paramètres-réglables)
4. [Effet vidéo](#4-effet-vidéo)
5. [Effet audio](#5-effet-audio)
6. [Transition](#6-transition)
7. [Graphismes](#7-graphismes)
8. [Générateur de média](#8-générateur-de-média)
9. [Format d'export](#9-format-dexport)
10. [Outil](#10-outil)
11. [Source de clip et calculs en arrière-plan](#11-source-de-clip-et-calculs-en-arrière-plan)
12. [Traduire un module](#12-traduire-un-module)
13. [Tester et mettre au point](#13-tester-et-mettre-au-point)
14. [Distribuer et installer](#14-distribuer-et-installer)
15. [Compatibilité des versions](#15-compatibilité-des-versions)

## 1. Démarrer en trois commandes

```sh
montar --new-module ~/mes-modules/mon-effet --type effet-video   # 1. squelette
#  … modifiez ~/mes-modules/mon-effet/__init__.py …
#  2. montar : accueil → Modules → Installer un module
#     → « Lier un dossier (développement) » ; après chaque modification : « Recharger »
montar --pack-module ~/mes-modules/mon-effet                     # 3. archive à partager
```

`--type` accepte `effet-video`, `effet-audio`, `transition`, `graphisme`, `generateur`,
`format` et `outil` ; il est répétable (`--type effet-video --type transition`) ou séparé
par des virgules. Le squelette contient un exemple fonctionnel de chaque type demandé.

## 2. Structure d'un module

```
mon-effet/
├── module.json      # manifeste (obligatoire)
├── __init__.py      # définit register(api) (obligatoire)
├── locale/en.json   # traductions (facultatif)
└── …                # autres fichiers Python, images SVG / PNG…
```

### Le manifeste `module.json`

```json
{
  "id": "moi.mon-effet",
  "name": "Mon effet",
  "version": "1.0.0",
  "api_version": "1.3",
  "author": "Moi",
  "license": "GPL-3.0-or-later",
  "description": "Ce que fait le module, en une phrase.",
  "permissions": []
}
```

| Champ | Rôle |
|-------|------|
| `id` | Identifiant unique (lettres, chiffres, `.`, `-`, `_`). Préfixez-le de votre nom (`moi.…`) pour éviter les collisions. |
| `name`, `description`, `author` | Affichés dans la page Modules de l'accueil. |
| `version` | Version du module (libre, par exemple `1.2.0`). |
| `api_version` | Version de l'API attendue, `1.x` (voir §15). |
| `permissions` | Liste indicative affichée avant l'installation (`"réseau"`, `"fichiers"`…). |

### `register(api)`

montar importe le paquet et appelle `register(api)` une fois. `api` (`montar.api.ModuleAPI`)
reçoit ce que le module apporte :

```python
def register(api):
    api.add_video_effect(MonEffet)      # une classe ou une instance
    api.add_audio_effect(MonEffetAudio)
    api.add_transition(MaTransition)
    api.add_graphic(Graphic(...))
    api.add_generator(MonGenerateur)
    api.add_export_format(MonFormat)
    api.add_tool(MonOutil)
    api.add_clip_source(MaSource)
```

`api.module_id` et `api.module_dir` (dossier du module) sont disponibles. Les imports
relatifs fonctionnent (`from .outils import calcul`).

### Où apparaît ce que le module apporte

| Type | Où le trouver dans montar |
|------|---------------------------|
| Effet vidéo, effet audio | Rail **Modules**, clic droit sur un clip → **Appliquer un effet ou un module…** ; réglages dans le panneau **Effets** |
| Transition | Panneau **Transitions** (à glisser entre deux clips), rail **Modules**, inspecteur de la transition |
| Graphisme | Rail **Graphiques**, dans sa rubrique |
| Générateur | Bouton **Créer…** du panneau Médias, rail **Modules** |
| Format d'export | Fenêtre **Exporter**, rail **Modules** |
| Outil | Clic droit sur un clip, rail **Modules**, onglet **Vitesse** (`section = "speed"`) |

### Identifiants et réglages enregistrés

Les réglages d'un effet appliqué à un clip sont enregistrés dans le projet, dans
`clip.modules[<id de l'effet>]` (un dictionnaire `clé → valeur`). Gardez donc des
identifiants **stables** : les changer rend les anciens projets muets pour votre effet.
Un projet qui utilise un module absent s'ouvre quand même : ses réglages sont conservés et
ignorés au rendu (une transition inconnue devient un fondu enchaîné).

## 3. Paramètres réglables

Les effets et les générateurs déclarent leurs `params` ; montar génère les contrôles.

```python
from montar.api import Param

params = [
    Param.float("force", "Force", 0.0, 1.0, default=0.5),         # curseur
    Param.float("retard", "Retard", 50, 1000, default=300, unit="ms"),
    Param("lignes", "Nombre de lignes", "int", 4, 1, 12),          # entier
    Param.bool("grain", "Ajouter du grain", True),                 # case à cocher
    Param.choice("sens", "Sens", [("h", "Horizontal"), ("v", "Vertical")]),
    Param.color("teinte", "Teinte", "#2F7A56"),                    # choix de couleur
]
```

La méthode `defaults()` renvoie les valeurs par défaut ; les valeurs reçues par `filters`
ou `generate` sont toujours complètes (valeurs par défaut + réglages de l'utilisateur).

## 4. Effet vidéo

Un effet vidéo ne traite pas les images en Python : il décrit une liste de **filtres MLT**
appliqués au clip, ce qui garde la lecture fluide.

```python
from montar.api import Param, VideoEffect


class Negatif(VideoEffect):
    id = "moi.negatif"
    name = "Négatif"
    description = "Inverse les couleurs de l'image."   # affichée dans les listes
    icon = "contrast"                                  # icône Lucide (voir plus bas)
    params = [Param.float("intensite", "Intensité", 0.0, 1.0, default=1.0)]

    def filters(self, values):
        a = float(values["intensite"])
        expr = f"(1-{a:.3f})*val+{a:.3f}*(maxval-val)"
        return [("avfilter.lutrgb", {"av.r": expr, "av.g": expr, "av.b": expr})]
```

`filters` renvoie des couples `(service, propriétés)` :

- `avfilter.<nom>` : tout filtre vidéo **FFmpeg** ; ses options s'écrivent `av.<option>`
  (`("avfilter.gblur", {"av.sigma": 4})`) ;
- `frei0r.<nom>` : greffons **frei0r** (`frei0r.cartoon`, `frei0r.posterize`,
  `frei0r.scanline0r`…), options par leur nom (`{"triplevel": 0.98}`) ;
- filtres **MLT** natifs (`brightness`, `oldfilm`, `grain`, `vignette`…).

Depuis l'API 1.4, un filtre dont les propriétés contiennent `in` et `out` (images
relatives au début du clip) ne s'applique qu'à cette partie du clip ; le module `suivi` s'en
sert pour faire suivre une pixelisation à un objet.

La liste des filtres disponibles sur une machine s'obtient avec
`melt -query filters` (paquet `melt`) ; leur documentation avec
`melt -query filter=avfilter.gblur`. Un filtre absent est ignoré (un avertissement est
écrit dans le journal).

### Zoom animé : `montar.api.ZOOM` (1.3)

Un effet peut aussi renvoyer le pseudo-filtre `ZOOM`, que montar applique au cadre du
clip (zoom autour de son centre, animé sur la durée du clip) :

```python
from montar.api import ZOOM, VideoEffect


class ZoomLent(VideoEffect):
    id = "moi.zoom"
    name = "Zoom lent"

    def filters(self, values):
        # start / end : facteurs (1 = taille normale) ; seconds : durée du mouvement
        # depuis le début du clip (0 = tout le clip) ; ease : "smooth" ou "linear"
        return [(ZOOM, {"start": 1.0, "end": 1.3, "seconds": 0, "ease": "linear"})]
```

Plusieurs zooms se multiplient. Le module intégré `effets` (`zoom_lent`, `zoom_rapide`,
`dezoom_lent`, `dezoom_rapide`) en donne des exemples.

### Icônes

`icon` est le nom d'une icône du jeu [Lucide](https://lucide.dev) fourni avec montar
(dossier `src/montar/assets/icons/`) : `sparkles`, `palette`, `droplets`, `zoom-in`,
`zoom-out`, `music`, `blend`, `contrast`, `monitor-play`, `circle-dot`, `scissors`…

## 5. Effet audio

Même principe, avec des filtres **audio** (`volume`, `avfilter.aecho`, `avfilter.bass`,
`avfilter.treble`, `avfilter.highpass`, `avfilter.dynaudnorm`…) :

```python
from montar.api import AudioEffect, Param


class Telephone(AudioEffect):
    id = "moi.telephone"
    name = "Téléphone"
    description = "Son étroit, comme au téléphone."
    params = [Param.float("force", "Force", 0.0, 1.0, default=0.8)]

    def filters(self, values):
        low = round(300 + 500 * float(values["force"]))
        return [("avfilter.highpass", {"av.f": low}), ("avfilter.lowpass", {"av.f": 3400})]
```

Un effet audio s'applique aux clips qui ont du son (vidéos avec piste son, sons).

## 6. Transition

```python
from montar.api import Transition


class Cercle(Transition):
    id = "moi.cercle"                 # avec un point : stocké tel quel dans le projet
    name = "Cercle"
    description = "La vidéo suivante apparaît dans un cercle."
    icon = "circle-dot"

    def transition(self, context, duration):
        motif = context.cache_dir / "moi" / "cercle.pgm"   # image de niveaux de gris
        if not motif.exists():
            ecrire_motif(motif)                            # à vous de la produire
        return "luma", {"resource": str(motif), "softness": 0.12}
```

`transition(context, durée)` renvoie le **service MLT** de la transition et ses propriétés.
La transition `luma` avec une image `resource` permet de nombreux volets : les zones sombres
de l'image passent en premier. Préférez des propriétés **sans images clés** : la durée
change si l'utilisateur exporte à une autre fréquence d'images. Le module `essentiels`
(fichier `images.py`) écrit ses motifs PGM en quelques lignes.

## 7. Graphismes

Un graphisme est un fichier **SVG** ou **PNG** du module, proposé dans le rail Graphiques.

```python
from montar.api import Graphic


def register(api):
    api.add_graphic(Graphic("moi.etoile", "Étoile", "stickers", "svg/etoile.svg"))
    api.add_graphic(Graphic("moi.cadre", "Cadre doré", "cadres", "svg/cadre.svg", fill=True))
```

- `category` : `annotations`, `figures`, `formes`, `arriere-plans`, `superpositions`,
  `cadres` ou `stickers` ; une autre valeur crée une rubrique à ce nom.
- `fill=True` : l'élément couvre toute la toile (fonds, cadres, superpositions). Sinon il est
  placé au centre, sur environ la moitié du petit côté de la toile.
- Les **arrière-plans** se placent sous la vidéo, les autres éléments au-dessus, à la tête
  de lecture. montar en fait une image PNG transparente à la taille du projet.

Pour un SVG : un `viewBox` donne les proportions ; dessinez sur fond transparent. Le moteur
SVG de Qt 6.4 (Debian 12) ne gère ni `<pattern>`, ni `clipPath`, ni les filtres : utilisez
des formes simples et des dégradés (`linearGradient`, `radialGradient`).

## 8. Générateur de média

Un générateur crée un fichier (image ou vidéo) qui devient un média du projet.

```python
from montar.api import Generator, Param


class Damier(Generator):
    id = "moi.damier"
    name = "Damier"
    description = "Fond à carreaux."
    icon = "layout-grid"
    suffix = ".png"                     # extension du fichier créé
    params = [Param.color("couleur", "Couleur", "#2F7A56")]

    def generate(self, context, values, target):
        # context.width, context.height : taille de la toile ; context.fps
        dessiner_damier(target, context.width, context.height, values["couleur"])
```

Écrivez exactement le fichier `target`. Formats acceptés : images (`.png`, `.jpg`, `.bmp`,
`.webp`…), vidéos (`.mp4`, `.mkv`, `.webm`…) et sons. Pour une vidéo, lancez `ffmpeg` avec
`subprocess` (montar en dépend).

## 9. Format d'export

```python
from montar.api import ExportFormat


class Mkv(ExportFormat):
    id = "moi.mkv"
    name = "MKV"
    extension = ".mkv"
    description = "Matroska, H.264 et AAC."
    audio_only = False                  # True : proposé dans l'onglet « Audio seul »

    def properties(self, settings):
        crf = (28, 23, 18)[settings.level]   # 0, 1, 2 : qualité Légère → Maximale
        return {"f": "matroska", "vcodec": "libx264", "crf": crf,
                "acodec": "aac", "g": settings.fps * 2}
```

`properties` renvoie les propriétés du consommateur MLT **avformat** (FFmpeg) : `f`
(conteneur), `vcodec`, `acodec`, `crf`, `preset`, `ab`, `pix_fmt`… La taille, la fréquence
d'images et le chemin du fichier sont réglés par montar (`settings.width`,
`settings.height`, `settings.fps`, `settings.path`).

## 10. Outil

Un outil agit sur un clip : couper, recalculer, ouvrir une fenêtre de réglages…

```python
from montar.api import Tool


class CouperAuMilieu(Tool):
    id = "moi.couper_milieu"
    name = "Couper au milieu"
    description = "Coupe le clip en deux parties égales."
    icon = "scissors"
    section = ""                        # "speed" : aussi dans l'onglet Vitesse

    def available(self, editor, clip):
        return clip.duration >= 2

    def run(self, editor, clip):
        middle = clip.start + clip.duration // 2
        editor.edit(self.name, lambda t: t.split_at(middle, clip.id))
```

`editor` (`montar.api.EditorContext`) donne accès à :

| Membre | Rôle |
|--------|------|
| `editor.project` | Le projet : `media`, `tracks`, `clips`, `transitions`, `markers`, `fps`, `canvas_size` |
| `editor.timeline` | Opérations sur la timeline (`split_at`, `move_clip`, `trim`, `add_clip`, `add_text`, `set_speed`, `add_transition`, `toggle_marker`…), voir `src/montar/core/timeline.py` |
| `editor.edit(libellé, opération)` | **Seule** façon de modifier le projet : l'opération reçoit la timeline ; la modification est annulable (Ctrl+Z) et l'aperçu se met à jour |
| `editor.playhead` | Position de la tête de lecture (images) |
| `editor.selection_range` | Plage marquée (`(clip, début, fin)`) ou `None` |
| `editor.parent` | Widget parent pour vos fenêtres (PyQt6) |
| `editor.error(message)` | Message d'erreur à l'utilisateur |
| `editor.schedule_job(clé, titre, travail)` | Calcul en arrière-plan (§11) |

Un clip (`montar.core.project.Clip`) porte `start`, `duration`, `source_in`, `speed`,
`volume`, `fade_in`, `fade_out`, `transform`, `color`, `effects`, `modules` ; ses valeurs
sont en **images** du projet.

## 11. Source de clip et calculs en arrière-plan

Une `ClipSource` remplace la source d'un clip au rendu, par exemple par un fichier calculé
à l'avance (c'est ainsi que fonctionne le **Timelapse**) :

```python
from montar.api import ClipSource, SourceOverride


class MaSource(ClipSource):
    def resolve(self, context, clip, media):
        settings = clip.modules.get("moi.module")
        cible = context.cache_dir / "moi" / f"{clip.id}.mp4"
        if cible.exists():
            return SourceOverride(str(cible), source_in=0, speed=1.0)
        context.schedule_job(f"moi:{clip.id}", "Mon calcul",
                             lambda progress, cancelled: calculer(media.path, cible,
                                                                 progress, cancelled))
        return None                     # en attendant : le clip d'origine

    def badge(self, settings):
        return "MOI"                    # court libellé affiché sur le clip
```

`schedule_job(clé, titre, travail)` lance `travail(progress, cancelled)` dans un fil à part
(une seule tâche par clé) : appelez `progress(0.0 … 1.0)` et arrêtez-vous dès que
`cancelled()` est vrai. La grande fenêtre d'avancement de montar s'affiche pendant le
calcul et l'aperçu est rafraîchi à la fin. Le module `timelapse` est l'exemple complet.

Depuis l'API **1.4**, `schedule_job(clé, titre, travail, done)` accepte une fonction `done`
appelée dans le fil principal avec la valeur renvoyée par `travail`, une fois le calcul
réussi : c'est là qu'on modifie le projet (`editor.edit(…)`), jamais dans le fil du calcul.
Le module `transcription` (sous-titres automatiques) s'en sert.

## 12. Traduire un module

Écrivez les textes (`name`, `description`, libellés des `Param`) dans votre langue, puis
ajoutez `locale/<langue>.json`, par exemple `locale/en.json` :

```json
{ "Négatif": "Negative", "Intensité": "Intensity" }
```

montar affiche la traduction de la langue de l'interface si elle existe, sinon le texte
d'origine. Pour une fenêtre écrite en PyQt6, utilisez `from montar.i18n import _`.

## 13. Tester et mettre au point

- **Recharger** : avec un dossier lié (§1), « Recharger » relit tout le code du module.
- **Erreurs** : une exception dans `register` ou pendant le rendu désactive le module (pas
  montar) ; le message apparaît dans la page Modules de l'accueil. Le journal détaillé est dans
  `~/.cache/montar/logs/montar.log`.
- **Tests automatiques** : les classes du module se testent sans interface.

```python
from montar.plugins import ModuleManager, builtin_modules_dir


def test_mon_effet(tmp_path):
    manager = ModuleManager(builtin_modules_dir(), tmp_path)
    info = manager.install_folder("chemin/vers/mon-effet")
    assert info.active, info.error
    effet = info.loaded.effects[0]
    assert effet.filters(effet.defaults())
```

## 14. Distribuer et installer

`montar --pack-module DOSSIER` vérifie le manifeste et crée `<id>-<version>.montar-module`
(une archive zip ; un `.zip` contenant le dossier du module convient aussi).

Dans montar : **accueil → Modules → Installer un module** :

- *Depuis un fichier* : `.montar-module` ou `.zip` ;
- *Depuis un dossier* : le dossier est copié ;
- *Lier un dossier (développement)* : le dossier reste à sa place.

Les modules installés se trouvent dans `~/.local/share/montar/modules/` ; on peut les
activer, les désactiver ou les supprimer dans la page Modules de l'accueil.

### Catalogue en ligne

**Préférences → Catalogue de modules** (désactivé par défaut) lit un fichier JSON servi en
HTTPS et propose d'installer ou de mettre à jour les modules qu'il liste. Le catalogue de
montar est `catalogue/index.json` dans le dépôt, reconstruit à partir de `examples/modules`
par `python3 scripts/build_catalogue.py` ; on peut indiquer l'adresse d'un autre catalogue.

```json
{"format": 1, "modules": [
  {"id": "mon.module", "name": "Mon module", "version": "1.0.0",
   "description": "…", "author": "…", "license": "GPL-3.0-or-later",
   "api_version": "1.4", "url": "modules/mon.module-1.0.0.montar-module",
   "sha256": "<empreinte SHA-256 de l'archive>"}
]}
```

`url` peut être relative au catalogue ; seules les adresses HTTPS sont acceptées et une
archive dont l'empreinte ne correspond pas est refusée. L'installation demande ensuite la
même confirmation qu'une installation depuis un fichier.

## 15. Compatibilité des versions

| API | Nouveautés |
|-----|------------|
| 1.0 | `VideoEffect`, `Tool`, `ClipSource`, `Param` |
| 1.1 | `description` des outils et des effets, `icon` des effets |
| 1.2 | `AudioEffect`, `Transition`, `Generator`, `ExportFormat`, `Param.color` |
| 1.3 | `Graphic` (`api.add_graphic`), pseudo-filtre `ZOOM` |
| 1.4 | `schedule_job(…, done)` : résultat d'un calcul remis au fil principal ; propriétés `in` / `out` d'un filtre (images relatives au clip) |

montar charge les modules dont la version **majeure** est la sienne (`1.x`). Indiquez dans
`api_version` la plus petite version qui contient ce que vous utilisez : un module `1.2`
fonctionne avec montar 1.4, mais pas l'inverse.
