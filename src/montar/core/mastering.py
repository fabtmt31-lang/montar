# SPDX-License-Identifier: GPL-3.0-or-later
"""Finition pro : étalonnage et mastering appliqués à tout le projet au moment de l'export
(et, sur demande, dans l'aperçu). Réglages enregistrés dans le projet, préréglages intégrés
et préréglages de l'utilisateur."""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from montar.core.project import ColorAdjust, Grade

log = logging.getLogger(__name__)

# Looks intégrés : identifiant → libellé (« lut » : fichier .cube de l'utilisateur)
LOOKS = {
    "natural": "Naturel",
    "cinema": "Cinéma doux",
    "warm": "Chaud",
    "cool": "Froid",
    "teal_orange": "Teal & orange",
    "film": "Argentique",
    "bw": "N & B",
}
COLOR_SPACES = {"rec709": "Rec.709 (SDR)", "srgb": "sRGB (Web)"}

# Destinations du son : identifiant → (libellé, loudness intégrée en LUFS, crête vraie en dBTP)
DESTINATIONS = {
    "web": ("YouTube · Web", -14.0, -1.0),
    "podcast": ("Podcast · Spotify · Apple", -16.0, -1.0),
    "tv": ("Télévision (EBU R128)", -23.0, -1.0),
    "cinema": ("Cinéma / festival", -24.0, -2.0),
}
EQ_BANDS = (60, 250, 1000, 4000, 12000)  # fréquences centrales de l'égaliseur, en Hz
TONES = {
    "neutral": ("Neutre", (0.0, 0.0, 0.0, 0.0, 0.0)),
    "voice": ("Voix claire", (-3.0, -1.0, 0.0, 2.5, 1.5)),
    "warm": ("Chaleureuse", (2.0, 1.5, 0.0, -1.0, -2.0)),
    "bright": ("Brillante", (-1.0, 0.0, 0.0, 2.0, 3.5)),
}
# Sortie du son : stéréo (mixage unique), 5.1, ou stéréo plus pistes séparées (stems)
LAYOUTS = {
    "stereo": "Stéréo",
    "surround": "5.1",
    "stems": "Stéréo + pistes séparées",
}
PRESETS = {
    "youtube": "Vlog YouTube",
    "podcast": "Podcast vidéo",
    "tv": "Diffusion TV (EBU R128)",
    "social": "Réseaux sociaux",
    "cinema": "Cinéma / festival",
}
DEFAULT_PRESET = "youtube"


@dataclass
class VideoMaster:
    """Étalonnage de tout le projet, appliqué après les réglages de chaque clip."""

    look: str = ""  # clé de LOOKS, « lut » ou vide
    look_amount: float = 0.6  # intensité du look, 0 à 1
    lut: str = ""  # fichier .cube du look « lut », relatif au dossier du projet
    color: ColorAdjust = field(default_factory=ColorAdjust)  # exposition, contraste…
    tint: float = 0.0  # -1 (vert) à 1 (magenta)
    grade: Grade = field(default_factory=Grade)  # roues, courbes, teinte, vibrance
    match_shots: bool = False  # harmoniser les plans sur la référence
    match_reference: str = ""  # identifiant du clip de référence (vide : le plus long)
    match_amount: float = 1.0
    # corrections calculées par l'analyse : clip → [gain R, V, B, décalage R, V, B]
    matches: dict[str, list[float]] = field(default_factory=dict)
    legal: bool = True  # niveaux légaux (hautes lumières et noirs adoucis, plage TV)
    color_space: str = "rec709"
    grain: float = 0.0  # 0 à 1
    vignette: float = 0.0  # 0 à 1


@dataclass
class AudioMaster:
    """Mastering du mixage final."""

    destination: str = "web"  # clé de DESTINATIONS ou « custom »
    lufs: float = -14.0  # loudness intégrée visée
    true_peak: float = -1.0  # crête vraie maximale, en dBTP
    cleanup: bool = True  # coupe-bas 70 Hz et dé-esseur
    tone: str = "neutral"  # clé de TONES ou « custom »
    eq: list[float] = field(default_factory=lambda: [0.0] * len(EQ_BANDS))  # gains en dB
    compress: float = 0.4  # compression « colle », 0 à 1
    voice_front: float = 0.0  # voix devant la musique, 0 à 1
    width: float = 1.0  # largeur stéréo, 0 (mono) à 2
    limiter: bool = True
    layout: str = "stereo"  # clé de LAYOUTS


@dataclass
class Mastering:
    enabled: bool = False
    preset: str = DEFAULT_PRESET  # préréglage d'origine (affiché), ou nom d'un préréglage
    preview: bool = False  # voir et écouter la finition dans l'aperçu de l'éditeur
    video: VideoMaster = field(default_factory=VideoMaster)
    audio: AudioMaster = field(default_factory=AudioMaster)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Mastering:
        if not isinstance(data, dict):
            return cls()
        try:
            video = _build(VideoMaster, data.get("video"))
            audio = _build(AudioMaster, data.get("audio"))
            if len(audio.eq) != len(EQ_BANDS):
                audio.eq = [0.0] * len(EQ_BANDS)
            return cls(bool(data.get("enabled", False)), str(data.get("preset", DEFAULT_PRESET)),
                       bool(data.get("preview", False)), video, audio)
        except (TypeError, ValueError, AttributeError) as exc:
            log.warning("réglages de finition ignorés : %s", exc)
            return cls()

    def summary_video(self) -> str:
        from montar.i18n import _

        v = self.video
        parts = []
        if v.look == "lut":
            parts.append(_("LUT personnalisée"))
        elif v.look in LOOKS:
            parts.append(_("Look « {look} » · {n} %").format(look=_(LOOKS[v.look]),
                                                             n=round(v.look_amount * 100)))
        else:
            parts.append(_("Sans look"))
        details = []
        if v.match_shots:
            details.append(_("Plans harmonisés"))
        if v.legal:
            details.append(_("Niveaux légaux"))
        details.append(_(COLOR_SPACES.get(v.color_space, COLOR_SPACES["rec709"])).split(" (")[0])
        return parts[0] + "\n" + " · ".join(details)

    def summary_audio(self) -> str:
        from montar.i18n import _

        a = self.audio
        name = _(DESTINATIONS[a.destination][0]) if a.destination in DESTINATIONS \
            else _("Personnalisé")
        lufs = f"{a.lufs:g}".replace("-", "−").replace(".", ",")
        details = []
        if any(a.eq):
            details.append(_("Égaliseur"))
        if a.compress > 0:
            details.append(_("Compresseur"))
        if a.limiter:
            details.append(_("Limiteur {tp} dBTP").format(
                tp=f"{a.true_peak:g}".replace("-", "−").replace(".", ",")))
        details.append(_(LAYOUTS.get(a.layout, LAYOUTS["stereo"])))
        return f"{name} · {lufs} LUFS\n" + " · ".join(details)


_NESTED = {"color": ColorAdjust, "grade": Grade}


def _build(cls, data: Any):
    """Instancie une dataclass en ignorant les champs inconnus (fichiers plus récents)."""
    if not isinstance(data, dict):
        return cls()
    known = {f.name for f in fields(cls)}
    values = {}
    for key, value in data.items():
        if key not in known:
            continue
        if key in _NESTED and isinstance(value, dict):
            value = _build(_NESTED[key], value)
        values[key] = value
    return cls(**values)


def set_destination(audio: AudioMaster, key: str) -> None:
    if key in DESTINATIONS:
        _label, lufs, peak = DESTINATIONS[key]
        audio.destination, audio.lufs, audio.true_peak = key, lufs, peak
    else:
        audio.destination = "custom"


def set_tone(audio: AudioMaster, key: str) -> None:
    if key in TONES:
        audio.tone, audio.eq = key, list(TONES[key][1])
    else:
        audio.tone = "custom"


def preset(key: str, current: Mastering | None = None) -> Mastering:
    """Réglages d'un préréglage intégré ; garde l'état (activé, aperçu), la référence et les
    corrections calculées de `current`."""
    m = Mastering(preset=key)
    v, a = m.video, m.audio
    if key == "podcast":
        set_destination(a, "podcast")
        set_tone(a, "voice")
        a.compress, a.voice_front = 0.55, 0.6
    elif key == "tv":
        set_destination(a, "tv")
        set_tone(a, "neutral")
        a.compress, a.voice_front = 0.3, 0.4
        v.look, v.look_amount = "natural", 0.5
    elif key == "social":
        set_destination(a, "web")
        set_tone(a, "bright")
        a.compress = 0.6
        v.look, v.look_amount = "teal_orange", 0.5
        v.color.contrast, v.color.saturation = 0.1, 0.1
    elif key == "cinema":
        set_destination(a, "cinema")
        set_tone(a, "neutral")
        a.compress, a.layout = 0.25, "surround"
        v.look, v.look_amount = "cinema", 0.7
        v.grain, v.vignette = 0.15, 0.15
    else:  # youtube
        m.preset = "youtube" if key == "youtube" else key
        set_destination(a, "web")
        set_tone(a, "voice")
        a.compress, a.voice_front = 0.4, 0.4
        v.look, v.look_amount = "cinema", 0.6
        v.match_shots = True
    if current is not None:
        m.enabled, m.preview = current.enabled, current.preview
        v.match_reference = current.video.match_reference
        v.matches = copy.deepcopy(current.video.matches)
    return m


# --- préréglages de l'utilisateur ------------------------------------------------------

def _user_file():
    from montar.platform.paths import config_dir

    return config_dir() / "finition.json"


def user_presets() -> dict[str, Mastering]:
    try:
        data = json.loads(_user_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): Mastering.from_dict(v) for k, v in data.items()}


def save_user_preset(name: str, mastering: Mastering) -> None:
    """Enregistre les réglages sous `name` (sans l'état, la référence ni les corrections
    propres au projet)."""
    presets = {k: v.to_dict() for k, v in user_presets().items()}
    m = copy.deepcopy(mastering)
    m.enabled = m.preview = False
    m.preset = name
    m.video.matches, m.video.match_reference = {}, ""
    presets[name] = m.to_dict()
    path = _user_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")
