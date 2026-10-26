# SPDX-License-Identifier: GPL-3.0-or-later
"""Bouton « Appliquer la pluie » dans les réglages de l'effet (panneau Effets).

L'API des modules ne prévoit pas de bouton dans les réglages d'un effet : le module ajoute
le sien sous le titre « PLUIE », et le remet chaque fois que montar reconstruit le panneau.
Tout est protégé : si l'interface change, le bouton n'apparaît pas, mais montar et l'effet
continuent de fonctionner."""
from __future__ import annotations

import logging

from montar.i18n import _

log = logging.getLogger(__name__)

NAME = "pluie-appliquer"


class ApplyButton:
    def __init__(self, rain) -> None:
        self.rain = rain
        self._hooked: set[int] = set()
        self._widgets: dict[int, tuple] = {}  # panneau → (bouton, aide)

    # --- branchement -----------------------------------------------------------------

    def attach(self, context) -> None:
        try:
            self._attach(context)
        except Exception:  # l'interface a changé : pas de bouton, l'effet fonctionne
            log.debug("bouton « Appliquer la pluie » indisponible", exc_info=True)

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
            jobs = getattr(context, "jobs", None)
            if jobs is not None:
                jobs.changed.connect(later)
        later()

    # --- affichage -------------------------------------------------------------------

    def refresh(self, context, panel) -> None:
        try:
            self._refresh(context, panel)
        except Exception:
            log.debug("bouton « Appliquer la pluie » : mise à jour impossible", exc_info=True)

    def _refresh(self, context, panel) -> None:
        from PyQt6.QtWidgets import QLabel

        from montar.ui.widgets import button, label

        from . import MODULE_ID, core

        box = panel._modules_box
        clip = context.controller.selected_clip()
        values = clip.modules.get(MODULE_ID) if clip is not None else None
        controls = [c for e, c, _a in getattr(panel, "_module_controls", ())
                    if e is self.rain]
        current = self._widgets.get(id(panel))
        shown = current is not None and box.indexOf(current[0]) >= 0
        if not isinstance(values, dict) or not controls:
            if shown:
                for widget in current:
                    box.removeWidget(widget)
                    widget.deleteLater()
                self._widgets.pop(id(panel), None)
            return
        if not shown:  # panneau reconstruit par montar : le bouton est remis
            btn = button(_("Appliquer la pluie"), "primary", "droplets")
            btn.setObjectName(NAME)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda: self.apply(context))
            hint: QLabel = label("", "muted")
            hint.setWordWrap(True)
            index = box.indexOf(controls[0].widget)
            box.insertWidget(max(0, index), hint)
            box.insertWidget(max(0, index), btn)
            current = self._widgets[id(panel)] = (btn, hint)
        btn, hint = current
        s = core.Settings.from_values({**self.rain.defaults(), **values})
        applied = core.is_applied(s, values.get(self.rain.APPLIED))
        job = self.rain.job_of(context, clip.id)
        if job is not None:
            btn.setText(_("Calcul des gouttes… {n} %").format(n=round(100 * job)))
            btn.setEnabled(False)
            hint.setText(_("Les gouttes vont ruisseler dès la fin du calcul."))
        elif applied:
            btn.setText(_("✓ Pluie appliquée"))
            btn.setEnabled(False)
            hint.setText(_("Modifiez un réglage des gouttes, puis appliquez à nouveau."))
        else:
            btn.setText(_("Appliquer la pluie"))
            btn.setEnabled(True)
            hint.setText(_("Aperçu : les gouttes sont figées. « Appliquer » les fait "
                           "ruisseler (calcul de quelques secondes)."))

    # --- action ----------------------------------------------------------------------

    def apply(self, context) -> None:
        try:
            clip = context.controller.selected_clip()
            if clip is not None:
                self.rain.apply(context, clip.id)
        except Exception as exc:
            log.exception("Appliquer la pluie")
            context.error(_("La pluie n'a pas pu être appliquée :\n{e}").format(e=exc))
