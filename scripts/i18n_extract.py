#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chaînes à traduire de montar et de ses modules intégrés.

Sont relevées : les chaînes littérales passées à `_()` ou `N_()`, les messages d'erreur
littéraux de la timeline et des projets (affichés tels quels), les libellés des tables
définies au niveau d'un fichier (dictionnaires, tuples) et, dans les modules, les attributs
`name` / `description` des classes et les libellés des `Param`.

    python3 scripts/i18n_extract.py             # chaînes manquantes du catalogue anglais
    python3 scripts/i18n_extract.py --update    # les ajoute (valeur vide) aux catalogues
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "montar"
MODULES = ROOT / "modules"
ERRORS = {"TimelineError", "ProjectError"}
SKIP = {"plugins/devtools.py"}  # modèles de code des nouveaux modules, pas de l'interface
LANGUAGE = "en"


def _is_label(text: str) -> bool:
    if not text.strip() or text.startswith(("#", "/", "av.", "frei0r")) or "{{" in text:
        return False  # couleurs, chemins, filtres, feuilles de style
    if text.isidentifier() and any(c.isupper() for c in text[1:]):
        return False  # nom de classe (__all__…)
    return text[0].isupper() or " " in text or any(ord(c) > 127 for c in text)


def _labels(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and _is_label(n.value)]


def strings(path: Path, module: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else \
                func.attr if isinstance(func, ast.Attribute) else ""
            first = node.args[0]
            if name in ("_", "N_") or name in ERRORS:
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value)
            elif module and isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "Param":
                found.update(_labels(ast.Tuple(elts=node.args[1:], ctx=ast.Load())))
                for kw in node.keywords:
                    found.update(_labels(kw.value))
        if module and isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id in ("name", "description")
                        for t in item.targets) and isinstance(item.value, ast.Constant):
                    found.add(item.value.value)
    for node in tree.body:  # tables de libellés
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
                node.value, (ast.Dict, ast.Tuple, ast.List, ast.Constant)):
            found.update(_labels(node.value))
    return {s for s in found if isinstance(s, str) and s.strip()}


def groups() -> dict[Path, set[str]]:
    """Catalogue → chaînes : celui de montar, puis un par module intégré."""
    result: dict[Path, set[str]] = {ROOT / "locale" / f"{LANGUAGE}.json": set()}
    for path in sorted(ROOT.rglob("*.py")):
        if path.relative_to(ROOT).as_posix() in SKIP:
            continue
        if MODULES in path.parents:
            module = MODULES / path.relative_to(MODULES).parts[0]
            target = module / "locale" / f"{LANGUAGE}.json"
            result.setdefault(target, set()).update(strings(path, True))
        else:
            result[ROOT / "locale" / f"{LANGUAGE}.json"].update(strings(path, False))
    for path in sorted(MODULES.glob("*/module.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        target = path.parent / "locale" / f"{LANGUAGE}.json"
        result.setdefault(target, set()).update({data["name"], data.get("description", "")}
                                                - {""})
    return result


def missing() -> dict[Path, list[str]]:
    result = {}
    for catalog, texts in groups().items():
        known = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else {}
        absent = sorted(t for t in texts if not known.get(t))
        if absent:
            result[catalog] = absent
    return result


def main() -> int:
    gaps = missing()
    if "--update" in sys.argv:
        for catalog, absent in gaps.items():
            known = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else {}
            known.update({t: known.get(t, "") for t in absent})
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps(dict(sorted(known.items())), ensure_ascii=False,
                                          indent=1) + "\n", encoding="utf-8")
    for catalog, absent in gaps.items():
        print(f"{catalog.relative_to(ROOT.parent.parent)} : {len(absent)} manquantes")
        for t in absent:
            print("   ", json.dumps(t, ensure_ascii=False))
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
