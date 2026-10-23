#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Ajoute des traductions à un catalogue : i18n_add.py CATALOGUE.json 'source=traduction'…"""
import json
import sys
from pathlib import Path

catalog = Path(sys.argv[1])
data = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else {}
for pair in sys.argv[2:]:
    source, _sep, text = pair.partition("=")
    data[source] = text
catalog.parent.mkdir(parents=True, exist_ok=True)
catalog.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
