# SPDX-License-Identifier: GPL-3.0-or-later
"""« Appliquer un effet ou un module » : tout ce qui peut s'appliquer à un clip (outils et
effets des modules, filtres et effets intégrés), choisi dans une seule fenêtre."""
from __future__ import annotations

from dataclasses import dataclass

from montar.core.project import Clip
from montar.engine.looks import PRESETS
from montar.i18n import _

# catégorie → titre affiché, dans l'ordre de la fenêtre
CATEGORIES = {"tool": "Modules", "module_effect": "Effets des modules",
              "audio_effect": "Effets audio", "preset": "Filtres", "effect": "Effets"}
EFFECTS = {"blur": ("Flou", "Adoucit l'image."), "sharpen": ("Netteté", "Accentue les détails."),
           "vignette": ("Vignettage", "Assombrit les bords de l'image.")}
EFFECT_DEFAULT = 0.5  # intensité donnée à un effet intégré à son application
PRESET_DESCRIPTIONS = {
    "bw": "Retire les couleurs.", "noir": "Noir et blanc contrasté.",
    "sepia": "Teinte brune des photos anciennes.", "vintage": "Sépia léger, contraste doux, "
    "bords assombris.", "warm": "Tons plus chauds.", "cold": "Tons plus froids.",
    "vivid": "Couleurs et contraste renforcés.", "fade": "Couleurs délavées, contraste doux.",
}


@dataclass(frozen=True)
class ApplyAction:
    kind: str  # tool | module_effect | audio_effect | preset | effect
    key: str  # identifiant de l'outil, de l'effet ou du filtre
    title: str
    description: str = ""
    icon: str = "sparkles"
    module_id: str = ""  # module qui fournit l'outil ou l'effet
    module_name: str = ""
    tool: object = None  # montar.api.Tool (outils des modules)

    @property
    def category(self) -> str:
        return _(CATEGORIES[self.kind])


def actions_for(clip: Clip, visual: bool, modules, audible: bool = False) -> list[ApplyAction]:
    """Actions possibles pour le clip. `visual` : image ou vidéo sur une piste vidéo ;
    `audible` : le clip a du son (effets audio des modules)."""
    result: list[ApplyAction] = []
    names = {m.id: m.name for m in modules.manager.modules.values()} if modules else {}
    if modules is not None:
        for module_id, tool in modules.tools_for(clip):
            result.append(ApplyAction("tool", tool.id, _(tool.name), _(tool.description),
                                      tool.icon, module_id, names.get(module_id, ""), tool))
        if visual:
            for module_id, effect in modules.manager.effects():
                result.append(ApplyAction(
                    "module_effect", effect.id, _(effect.name),
                    _(getattr(effect, "description", "")),
                    getattr(effect, "icon", "sparkles"), module_id,
                    names.get(module_id, "")))
        if audible:
            for module_id, effect in modules.manager.audio_effects():
                result.append(ApplyAction("audio_effect", effect.id, _(effect.name),
                                          _(effect.description), effect.icon, module_id,
                                          names.get(module_id, "")))
    if visual:
        for key, title in PRESETS.items():
            result.append(ApplyAction("preset", key, _(title),
                                      _(PRESET_DESCRIPTIONS.get(key, "")), "blend"))
        for key, (title, description) in EFFECTS.items():
            result.append(ApplyAction("effect", key, _(title), _(description), "sparkles"))
    return result


def apply_change(action: ApplyAction, effect_defaults: dict | None = None):
    """Modification du clip pour un filtre ou un effet (les outils agissent eux-mêmes)."""
    def change(c: Clip) -> None:
        if action.kind == "preset":
            c.preset, c.preset_amount = action.key, 1.0
        elif action.kind == "effect":
            if not getattr(c.effects, action.key):
                setattr(c.effects, action.key, EFFECT_DEFAULT)
        elif action.kind in ("module_effect", "audio_effect"):
            c.modules.setdefault(action.key, dict(effect_defaults or {}))
    return change
