# SPDX-License-Identifier: GPL-3.0-or-later
"""Outils pour les auteurs de modules : squelette d'un nouveau module et archive
`.montar-module` à distribuer (`montar --new-module`, `montar --pack-module`)."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from montar.api import API_VERSION
from montar.plugins.manager import ARCHIVE_SUFFIX, ModuleError, read_manifest

# type → (import depuis montar.api, code de l'exemple, ligne d'enregistrement)
TEMPLATES: dict[str, tuple[str, str, str]] = {
    "effet-video": ("Param, VideoEffect", '''
class Negatif(VideoEffect):
    """Effet vidéo : renvoie des filtres MLT (avfilter.*, frei0r.*…)."""

    id = "{id}.negatif"
    name = "Négatif"
    description = "Inverse les couleurs de l'image."
    icon = "contrast"
    params = [Param.float("intensite", "Intensité", 0.0, 1.0, default=1.0)]

    def filters(self, values):
        a = float(values["intensite"])
        expr = f"(1-{{a:.3f}})*val+{{a:.3f}}*(maxval-val)"
        return [("avfilter.lutrgb", {{"av.r": expr, "av.g": expr, "av.b": expr}})]
''', "api.add_video_effect(Negatif)"),
    "effet-audio": ("AudioEffect, Param", '''
class Telephone(AudioEffect):
    """Effet audio : renvoie des filtres audio MLT."""

    id = "{id}.telephone"
    name = "Téléphone"
    description = "Son étroit, comme au téléphone."
    params = [Param.float("force", "Force", 0.0, 1.0, default=0.8)]

    def filters(self, values):
        low = round(300 + 500 * float(values["force"]))
        return [("avfilter.highpass", {{"av.f": low}}),
                ("avfilter.lowpass", {{"av.f": 3400}})]
''', "api.add_audio_effect(Telephone)"),
    "transition": ("Transition", '''
class Fondu(Transition):
    """Transition : service MLT et propriétés (sans images clés de préférence)."""

    id = "{id}.fondu_doux"
    name = "Fondu doux"
    description = "Fondu enchaîné aux bords adoucis."
    icon = "blend"

    def transition(self, context, duration):
        return "luma", {{"softness": 0.3}}
''', "api.add_transition(Fondu)"),
    "generateur": ("Generator, Param", '''
class Uni(Generator):
    """Générateur : écrit un fichier (image ou vidéo) qui devient un média du projet."""

    id = "{id}.uni"
    name = "Fond uni"
    description = "Image d'une seule couleur, à la taille du projet."
    suffix = ".bmp"
    params = [Param.color("couleur", "Couleur", "#2F7A56")]

    def generate(self, context, values, target):
        import struct

        c = values["couleur"].lstrip("#")
        bgr = bytes(int(c[i:i + 2], 16) for i in (4, 2, 0))
        w, h = context.width, context.height
        row = bgr * w + b"\\0" * (-3 * w % 4)  # lignes alignées sur 4 octets
        data = row * h
        header = b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54) + struct.pack(
            "<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data), 2835, 2835, 0, 0)
        target.write_bytes(header + data)
''', "api.add_generator(Uni)"),
    "graphisme": ("Graphic", '''
# Graphismes : fichiers SVG ou PNG du dossier du module, rangés par rubrique
# (annotations, figures, formes, arriere-plans, superpositions, cadres, stickers).
ETOILE = Graphic("{id}.etoile", "Étoile", "stickers", "etoile.svg")
''', "api.add_graphic(ETOILE)"),
    "format": ("ExportFormat", '''
class Mkv(ExportFormat):
    """Format d'export : propriétés du consommateur MLT « avformat »."""

    id = "{id}.mkv"
    name = "MKV"
    extension = ".mkv"
    description = "Matroska, H.264 et AAC."

    def properties(self, settings):
        crf = (28, 23, 18)[settings.level]
        return {{"f": "matroska", "vcodec": "libx264", "crf": crf, "acodec": "aac"}}
''', "api.add_export_format(Mkv)"),
    "outil": ("Tool", '''
class Couper(Tool):
    """Outil : action sur un clip (clic droit, panneau Modules)."""

    id = "{id}.couper_milieu"
    name = "Couper au milieu"
    description = "Coupe le clip en deux parties égales."
    icon = "scissors"

    def run(self, editor, clip):
        middle = clip.start + clip.duration // 2
        editor.edit(self.name, lambda t: t.split_at(middle, clip.id))
''', "api.add_tool(Couper)"),
}

STAR_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><path d="M150 18 '
            'L 186 104 L 280 112 L 208 172 L 232 264 L 150 214 L 68 264 L 92 172 L 20 112 L 114 '
            '104 Z" fill="#FFD23F" stroke="#17261E" stroke-width="8"/></svg>\n')


def new_module(folder: Path, module_id: str | None = None, name: str | None = None,
               kinds: list[str] | None = None, author: str = "") -> Path:
    """Crée le dossier d'un module prêt à modifier ; renvoie son dossier."""
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise ModuleError(f"le dossier n'est pas vide : {folder}")
    module_id = module_id or re.sub(r"[^a-z0-9_-]+", "-", folder.name.lower()).strip("-")
    if not module_id or not module_id.replace("_", "").replace("-", "").replace(".", "")\
            .isalnum():
        raise ModuleError(f"identifiant de module invalide : {module_id!r}")
    kinds = kinds or ["effet-video"]
    unknown = [k for k in kinds if k not in TEMPLATES]
    if unknown:
        raise ModuleError("type inconnu : " + ", ".join(unknown) + " (types : "
                          + ", ".join(TEMPLATES) + ")")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"id": module_id, "name": name or folder.name, "version": "0.1.0",
                "api_version": f"{API_VERSION[0]}.{API_VERSION[1]}", "author": author,
                "license": "GPL-3.0-or-later", "description": "", "permissions": []}
    (folder / "module.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)
                                        + "\n", encoding="utf-8")
    imports = sorted({n.strip() for k in kinds for n in TEMPLATES[k][0].split(",")})
    code = [f'"""Module montar « {manifest["name"]} »."""',
            "from montar.api import " + ", ".join(imports), ""]
    for k in kinds:
        code.append(TEMPLATES[k][1].format(id=module_id).rstrip() + "\n")
    code.append("\ndef register(api):")
    code += [f"    {TEMPLATES[k][2]}" for k in kinds]
    (folder / "__init__.py").write_text("\n".join(code) + "\n", encoding="utf-8")
    if "graphisme" in kinds:
        (folder / "etoile.svg").write_text(STAR_SVG, encoding="utf-8")
    return folder


def pack_module(folder: Path, out: Path | None = None) -> Path:
    """Archive `.montar-module` du module (vérifie d'abord son manifeste)."""
    folder = Path(folder).resolve()
    data = read_manifest(folder)
    out = Path(out) if out else folder.parent / f"{data['id']}-{data['version']}{ARCHIVE_SUFFIX}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts \
                    and not path.name.endswith(ARCHIVE_SUFFIX):
                zf.write(path, Path(data["id"]) / path.relative_to(folder))
    return out
