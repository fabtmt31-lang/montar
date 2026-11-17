# SPDX-License-Identifier: GPL-3.0-or-later
"""Bouton « Ajouter le bruit de projecteur » dans les réglages de l'effet (panneau Effets).

L'API des modules ne prévoit pas de bouton dans les réglages d'un effet : le module ajoute
le sien sous le titre « SUPER 8 », et le remet chaque fois que montar reconstruit le
panneau. Tout est protégé : si l'interface change, le bouton n'apparaît pas (l'outil du
même nom reste dans le clic droit), et montar comme l'effet continuent de fonctionner."""
from __future__ import annotations

import logging

from montar.i18n import _

log = logging.getLogger(__name__)

NAME = "super8-bruit"


def _alive(widget) -> bool:
    """Le widget existe-t-il encore côté Qt ? (montar a pu le détruire)"""
    try:
        from PyQt6 import sip

        if sip.isdeleted(widget):
            return False
        widget.objectName()
        return True
    except (ImportError, RuntimeError):
        return False


class SoundButton:
    def __init__(self, effect) -> None:
        self.effect = effect
        self._hooked: set[int] = set()
        self._widgets: dict[int, tuple] = {}  # panneau → (bouton, aide)

    def attach(self, context) -> None:
        try:
            self._attach(context)
        except Exception:  # l'interface a changé : pas de bouton, l'effet fonctionne
            log.debug("bouton « Ajouter le bruit de projecteur » indisponible", exc_info=True)

    def _attach(self, context) -> None:
        from PyQt6.QtCore import QTimer

        page = getattr(context, "parent", None)
        panel = getattr(page, "effects_panel", None)
        controller = getattr(context, "controller", None)
        if panel is None or controller is None or not hasattr(panel, "_modules_box"):
            return

        def later(*_args) -> None:
            QTimer.singleShot(0, lambda: self.refresh(context, panel))

        if id(panel) not in self._hooked:
            self._hooked.add(id(panel))
            controller.selectionChanged.connect(later)
            controller.changed.connect(later)
        later()

    def refresh(self, context, panel) -> None:
        try:
            self._refresh(context, panel)
        except Exception:
            log.debug("bouton du bruit de projecteur : mise à jour impossible", exc_info=True)

    def _refresh(self, context, panel) -> None:
        from montar.ui.widgets import button, label

        from . import MODULE_ID, has_projector_sound

        box = panel._modules_box
        clip = context.controller.selected_clip()
        values = clip.modules.get(MODULE_ID) if clip is not None else None
        controls = [c for e, c, _a in getattr(panel, "_module_controls", ())
                    if e is self.effect]
        current = self._widgets.get(id(panel))
        # montar reconstruit le panneau en détruisant ses éléments, notre bouton compris
        shown = current is not None and all(_alive(w) for w in current) \
            and box.indexOf(current[0]) >= 0
        if not isinstance(values, dict) or not controls:
            if shown:
                for widget in current:
                    box.removeWidget(widget)
                    widget.deleteLater()
            self._widgets.pop(id(panel), None)
            return
        if not shown:  # panneau reconstruit par montar : le bouton est remis
            btn = button(_("Ajouter le bruit de projecteur"), "tonal", "music")
            btn.setObjectName(NAME)
            btn.setMinimumHeight(38)
            btn.clicked.connect(lambda: self.add(context))
            hint = label("", "muted")
            hint.setWordWrap(True)
            index = box.indexOf(controls[0].widget)
            box.insertWidget(max(0, index), hint)
            box.insertWidget(max(0, index), btn)
            current = self._widgets[id(panel)] = (btn, hint)
        btn, hint = current
        if has_projector_sound(context.project, clip):
            btn.setText(_("✓ Bruit de projecteur ajouté"))
            btn.setEnabled(False)
            hint.setText(_("Son posé sur une piste audio, sous le clip ; réglez son volume "
                           "dans l'onglet Audio."))
        else:
            btn.setText(_("Ajouter le bruit de projecteur"))
            btn.setEnabled(True)
            hint.setText(_("En option : ronronnement et claquement du projecteur, posés "
                           "sous le clip sur une piste audio."))

    def add(self, context) -> None:
        try:
            from . import add_projector_sound

            clip = context.controller.selected_clip()
            if clip is not None:
                add_projector_sound(context, clip.id)
        except Exception as exc:
            log.exception("Ajouter le bruit de projecteur")
            context.error(_("Le bruit de projecteur n'a pas pu être ajouté :\n{e}")
                          .format(e=exc))
