# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnostic CI : charge chaque module de MLT seul (dans un processus à part, avec un délai
maximum) pour trouver celui qui bloque ou fait échouer l'initialisation de MLT.

Usage : python probe_modules.py <dossier lib/mlt> [délai en s]"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INIT = "import mlt7; f = mlt7.Factory().init(); print('init', f is not None)"


def main() -> int:
    modules = Path(sys.argv[1])
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    bad = []
    for dll in sorted(modules.glob("*.dll")):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy2(dll, tmp)
            env = dict(os.environ, MLT_REPOSITORY=tmp, MLT_REPOSITORY_DENY="")
            try:
                done = subprocess.run([sys.executable, "-X", "utf8", "-c", INIT], env=env,
                                      capture_output=True, text=True, timeout=delay)
                state = "ok" if done.returncode == 0 else f"échec ({done.returncode})"
                detail = (done.stderr.strip().splitlines() or [""])[-1]
            except subprocess.TimeoutExpired:
                state, detail = "BLOQUÉ", f"plus de {delay:g} s"
        if state != "ok":
            bad.append(dll.name)
        print(f"{state:12} {dll.name} {detail}", flush=True)
    print("modules en cause :", ", ".join(bad) or "aucun", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
