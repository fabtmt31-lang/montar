#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Construit le catalogue de modules en ligne (catalogue/index.json et les archives) à partir
des modules de examples/modules. Archives reproductibles (dates fixes).

    python3 scripts/build_catalogue.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from montar.plugins.manager import ARCHIVE_SUFFIX, read_manifest  # noqa: E402

SOURCES = ROOT / "examples" / "modules"
OUT = ROOT / "catalogue"


def pack(folder: Path, data: dict, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                info = zipfile.ZipInfo(str(Path(data["id"]) / path.relative_to(folder)),
                                       (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())


def main() -> None:
    (OUT / "modules").mkdir(parents=True, exist_ok=True)
    entries = []
    for folder in sorted(p for p in SOURCES.iterdir() if (p / "module.json").exists()):
        data = read_manifest(folder)
        name = f"{data['id']}-{data['version']}{ARCHIVE_SUFFIX}"
        target = OUT / "modules" / name
        pack(folder, data, target)
        entries.append({k: data.get(k, "") for k in ("id", "name", "version", "description",
                                                     "author", "license", "api_version")}
                       | {"url": f"modules/{name}",
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (OUT / "index.json").write_text(json.dumps({"format": 1, "modules": entries},
                                               ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print(f"{len(entries)} module(s) dans {OUT / 'index.json'}")


if __name__ == "__main__":
    main()
