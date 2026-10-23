# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalogue de modules en ligne (F-MOD-08), facultatif et désactivé par défaut.

Le catalogue est un fichier JSON servi en HTTPS :

    {"format": 1, "modules": [{"id": "…", "name": "…", "version": "1.0.0",
      "description": "…", "author": "…", "license": "GPL-3.0-or-later",
      "api_version": "1.4", "url": "https://…/module.montar-module",
      "sha256": "…"}]}

`url` peut être relative au catalogue. L'archive téléchargée doit avoir l'empreinte SHA-256
annoncée, sinon elle est refusée."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_URL = "https://raw.githubusercontent.com/fabtmt31-lang/montar/main/catalogue/index.json"
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    id: str
    name: str
    version: str
    description: str
    author: str
    license: str
    api_version: tuple[int, int]
    url: str
    sha256: str

    def compatible(self, api: tuple[int, int]) -> bool:
        return self.api_version[0] == api[0] and self.api_version[1] <= api[1]


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:4]) or (0,)


def _https(url: str) -> str:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or not parts.netloc:
        raise CatalogError(f"adresse refusée (HTTPS obligatoire) : {url}")
    return url


def parse_index(data: bytes, base_url: str) -> list[Entry]:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"catalogue illisible : {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != 1 or \
            not isinstance(raw.get("modules"), list):
        raise CatalogError("catalogue au format inconnu")
    entries = []
    for item in raw["modules"]:
        if not isinstance(item, dict):
            continue
        try:
            major, minor = (int(x) for x in str(item["api_version"]).split(".")[:2])
            entry = Entry(str(item["id"]), str(item.get("name") or item["id"]),
                          str(item["version"]), str(item.get("description", "")),
                          str(item.get("author", "")), str(item.get("license", "")),
                          (major, minor), urllib.parse.urljoin(base_url, str(item["url"])),
                          str(item["sha256"]).lower())
        except (KeyError, ValueError, TypeError):
            continue  # entrée incomplète : ignorée, le reste du catalogue reste utilisable
        if _ID.match(entry.id) and _SHA.match(entry.sha256) and \
                entry.url.startswith("https://"):
            entries.append(entry)
    return sorted(entries, key=lambda e: e.name.casefold())


def _read(url: str, limit: int, timeout: float) -> bytes:
    request = urllib.request.Request(_https(url), headers={"User-Agent": "montar"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CatalogError(f"connexion impossible : {exc}") from exc
    if len(data) > limit:
        raise CatalogError("fichier trop volumineux")
    return data


def fetch(url: str, timeout: float = 15) -> list[Entry]:
    return parse_index(_read(url, MAX_INDEX_BYTES, timeout), url)


def download(entry: Entry, folder: Path, timeout: float = 60) -> Path:
    """Télécharge l'archive et vérifie son empreinte ; renvoie son chemin."""
    data = _read(entry.url, MAX_ARCHIVE_BYTES, timeout)
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.sha256:
        raise CatalogError(f"empreinte incorrecte pour {entry.id} : archive refusée")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{entry.id}-{entry.version}.montar-module"
    target.write_bytes(data)
    return target


def status(entry: Entry, installed: dict[str, str], api: tuple[int, int]) -> str:
    """« incompatible », « installed », « update » ou « available »."""
    if not entry.compatible(api):
        return "incompatible"
    if entry.id in installed:
        if version_key(entry.version) > version_key(installed[entry.id]):
            return "update"
        return "installed"
    return "available"
