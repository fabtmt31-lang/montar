# SPDX-License-Identifier: GPL-3.0-or-later
"""Traduction des textes de l'interface.

Les chaînes sources sont en français ; les traductions (.qm) sont chargées par Qt.
"""
from __future__ import annotations


def _(text: str) -> str:
    try:
        from PyQt6.QtCore import QCoreApplication
    except ImportError:  # modèle utilisable sans Qt (tests, scripts)
        return text
    return QCoreApplication.translate("montar", text)
