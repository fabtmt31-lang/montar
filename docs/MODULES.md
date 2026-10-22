# Écrire un module montar

Un module ajoute à montar des **effets vidéo** ou **audio**, des **transitions**, des
**générateurs** (fonds, motifs), des **formats d'export**, des **outils** (actions sur un
clip) ou des **sources de clip** (rendu de remplacement, comme le Timelapse). Il est écrit en
Python et utilise l'API publique `montar.api` (version 1.2).

> Un module s'exécute avec les droits de l'utilisateur : montar affiche un avertissement
> avant d'installer un module tiers. Les modules chargés dans montar sont des œuvres
> dérivées au sens de la GPL : publiez-les sous une licence compatible (GPL-3.0-or-later).

## Structure

```
mon-module/
├── module.json
└── __init__.py      # définit register(api)
```

`module.json` :

```json
{
  "id": "exemple.negatif",
  "name": "Négatif",
  "version": "1.0.0",
  "api_version": "1.0",
  "author": "Moi",
  "license": "GPL-3.0-or-later",
  "description": "Inverse les couleurs d'un clip.",
  "permissions": []
}
```

- `id` : identifiant unique (lettres, chiffres, `.`, `-`, `_`) ; c'est aussi la clé des
  réglages du module dans le projet (`clip.modules[id]`).
- `api_version` : version majeure de l'API attendue (`1.x`).
- `permissions` : liste indicative affichée avant l'installation (`"réseau"`, `"fichiers"`…).

## Exemple : un effet vidéo

```python
from montar.api import Param, VideoEffect


class Negatif(VideoEffect):
    id = "exemple.negatif"
    name = "Négatif"
    description = "Inverse les couleurs de l'image, plus ou moins fortement."
    params = [Param.float("intensite", "Intensité", 0.0, 1.0, default=1.0)]

    def filters(self, values):
        a = float(values["intensite"])
        expr = f"(1-{a:.3f})*val+{a:.3f}*(maxval-val)"
        return [("avfilter.lutrgb", {"av.r": expr, "av.g": expr, "av.b": expr})]


def register(api):
    api.add_video_effect(Negatif)
```

`filters` renvoie une liste de filtres MLT (`service`, propriétés) : filtres FFmpeg
(`avfilter.*`), frei0r (`frei0r.*`) ou filtres MLT. Aucun traitement image par image n'est
fait en Python. Les paramètres (`Param.float`, `Param.bool`, `Param.choice`) génèrent les
contrôles du panneau **Effets**.

Les effets et les outils des modules apparaissent aussi dans la fenêtre **Appliquer un effet
ou un module…** (clic droit sur un clip de la timeline), avec leur `name`, leur
`description` et leur `icon` (nom d'une icône Lucide) — `description` et `icon` des effets
sont apparus avec l'API 1.1 et restent facultatifs.

## Effets audio, transitions, générateurs, formats d'export (API 1.2)

Ces quatre types sont apparus avec l'API **1.2** (`"api_version": "1.2"` dans le manifeste).

- `AudioEffect` : comme `VideoEffect`, mais `filters(valeurs)` renvoie des filtres **audio**
  MLT (`volume`, `avfilter.aecho`, `avfilter.bass`…). Il est réglé dans le panneau
  **Effets** (rubrique « Effets audio ») pour un clip qui a du son, et proposé dans
  **Appliquer un effet ou un module…**.
- `Transition` (`id` avec un point, ex. `monmodule.cercle`, `name`, `icon`, `description`) :
  `transition(context, durée)` renvoie `(service MLT, propriétés)`, par exemple
  `("luma", {"resource": motif.pgm, "softness": 0.1})`. La transition apparaît dans le
  panneau **Transitions** et dans l'inspecteur. Préférez des propriétés sans images clés :
  la durée change si l'export se fait à une autre fréquence. Si le module est absent, la
  transition est rendue comme un fondu enchaîné.
- `Generator` (`id`, `name`, `icon`, `description`, `suffix`, `params`) :
  `generate(context, valeurs, cible)` écrit un fichier (image ou vidéo) à `cible` ;
  `context.width` et `context.height` donnent la taille de la toile. Le média est ajouté au
  projet par le bouton **Créer…** du panneau Médias. `Param.color(clé, libellé, "#RRGGBB")`
  donne un choix de couleur.
- `ExportFormat` (`id`, `name`, `extension`, `description`, `audio_only`) :
  `properties(réglages)` renvoie les propriétés du consommateur MLT `avformat` (`f`,
  `vcodec`, `acodec`, `crf`…) ; `réglages.level` vaut 0, 1 ou 2 selon la qualité choisie,
  `réglages.fps` la fréquence. Le format est proposé dans la fenêtre d'export.

On les enregistre avec `api.add_audio_effect`, `api.add_transition`, `api.add_generator` et
`api.add_export_format`. Le module intégré **Essentiels** (`src/montar/modules/essentiels/`)
en donne un exemple de chaque : écho, graves et aigus, volume égalisé ; transitions cercle,
volet et diagonale ; fond uni et dégradé ; exports MKV et ProRes.

## Outils et sources de clip

- `Tool` (`id`, `name`, `icon`, `section`, `description`) : `available(editor, clip)` et
  `run(editor, clip)`. `editor` donne accès au projet, à la timeline, à
  `editor.edit(libellé, opération)` (modification annulable), à la plage marquée avec I / O
  (`editor.selection_range`) et à `editor.schedule_job(clé, titre, travail)` pour les calculs
  en arrière-plan. `section = "speed"` place l'outil dans l'onglet **Vitesse**.
- `ClipSource` : `resolve(context, clip, media)` renvoie un `SourceOverride` (autre fichier,
  point d'entrée, vitesse) ou `None` ; `badge(réglages)` donne le libellé affiché sur le clip.

Le module intégré **Timelapse** (`src/montar/modules/timelapse/`) est un exemple complet
d'outil et de source de clip.

## Traduire un module

Les textes d'un module (`name`, `description`, libellés des paramètres…) sont affichés tels
quels en français et traduits si le module fournit `locale/<langue>.json` (par exemple
`locale/en.json`) : un objet JSON « texte d'origine → traduction ». Le script
`scripts/i18n_extract.py` de montar relève les chaînes des modules intégrés.

## Installer

Compressez le dossier du module en `.zip`, renommez-le en `mon-module.montar-module`, puis
**Préférences → Extensions → Installer un module…**. Les modules installés se trouvent dans
`~/.local/share/montar/modules/`. Un module qui lève une exception est désactivé sans
interrompre montar ; un projet qui utilise un module absent s'ouvre quand même (ses réglages
sont conservés et ignorés au rendu).
