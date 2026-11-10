# SPDX-License-Identifier: GPL-3.0-or-later
"""Aide à la prise en main de l'écran de montage : fiche des raccourcis (touche ?),
visite guidée à la première ouverture, toast nommant l'action annulée."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPolygon
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from montar.core import shortcuts
from montar.i18n import N_, _
from montar.ui.theme import theme
from montar.ui.widgets import button, label

# fiche des raccourcis : sections de la fiche → actions (identifiants de core.shortcuts)
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (N_("Lecture"), ("play", "start", "end", "previous_frame", "next_frame",
                     "shuttle_back", "pause", "shuttle_forward", "fullscreen")),
    (N_("Montage"), ("split", "delete", "ripple_delete", "duplicate", "copy", "cut", "paste",
                     "paste_settings", "select_all", "merge", "undo", "redo")),
    (N_("Timeline"), ("zoom_in", "zoom_out", "zoom_fit", "mark_in", "mark_out",
                      "clear_range", "marker", "previous_marker", "next_marker")),
    (N_("Projet"), ("save", "export", "shortcuts_help")),
)
# gestes à la souris (non personnalisables)
GESTURES: tuple[tuple[str, str], ...] = (
    (N_("Ctrl + clic"), N_("Ajouter un clip à la sélection")),
    (N_("Glisser dans le vide"), N_("Sélectionner plusieurs clips (rectangle)")),
    (N_("Maj + glisser sur un clip"), N_("Choisir un passage du clip")),
    (N_("Alt + glisser un clip"), N_("Déposer une copie")),
    (N_("Ctrl + molette"), N_("Zoomer sur la timeline")),
)


# noms de touches affichés dans la langue de l'interface
# (appel à dict : les noms anglais des touches ne sont pas à traduire)
KEY_NAMES = dict(Shift=N_("Maj"), Space=N_("Espace"), Del=N_("Suppr"),
                 Backspace=N_("Retour arrière"), Esc=N_("Échap"), Home=N_("Début"),
                 End=N_("Fin"), Left="←", Right="→", Up="↑", Down="↓")


def key_text(key: str) -> str:
    """Touche lisible dans la langue de l'interface (« Ctrl+Maj+Z »)."""
    if not key:
        return "—"
    if key in ("?", "Shift+?"):
        return "?"
    parts = key.split("+")
    if key.endswith("++"):  # Ctrl++
        parts = [*key[:-2].split("+"), "+"]
    return "+".join(_(KEY_NAMES[p]) if p in KEY_NAMES else p for p in parts if p)


class ShortcutsSheet(QDialog):
    """Fiche des raccourcis, avec les touches personnalisées dans les préférences."""

    def __init__(self, overrides: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Raccourcis clavier"))
        self.resize(1060, 620)
        names = dict(shortcuts.ACTIONS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(label(_("Raccourcis clavier"), "h2"))
        outer.addWidget(label(_("Les touches se changent dans Préférences → Raccourcis."),
                              "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(4)
        self.rows: dict[str, QLabel] = {}  # action → touche affichée
        columns = (SECTIONS[:2], SECTIONS[2:])
        for col, sections in enumerate(columns):
            row = 0
            for title, actions in sections:
                grid.addWidget(label(_(title), "section"), row, col * 2, 1, 2)
                row += 1
                for action in actions:
                    keys = dict.fromkeys(key_text(k) for k in
                                         shortcuts.keys_for(overrides, action))
                    cap = label(" · ".join(keys) or "—", "kbd")
                    cap.setAlignment(Qt.AlignmentFlag.AlignRight)
                    self.rows[action] = cap
                    grid.addWidget(label(_(names[action])), row, col * 2)
                    grid.addWidget(cap, row, col * 2 + 1)
                    row += 1
                row += 1
            if col == 1:
                grid.addWidget(label(_("À la souris"), "section"), row, 2, 1, 2)
                row += 1
                for gesture, meaning in GESTURES:
                    grid.addWidget(label(_(meaning)), row, 2)
                    cap = label(_(gesture), "kbd")
                    cap.setAlignment(Qt.AlignmentFlag.AlignRight)
                    grid.addWidget(cap, row, 3)
                    row += 1
        grid.setRowStretch(grid.rowCount(), 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        close = button(_("Fermer"), "primary")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(close)
        outer.addLayout(bottom)


class Toast(QLabel):
    """Message bref en bas de l'écran (« Annulé : Couper »), qui s'efface seul."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 2200) -> None:
        p = theme().palette
        self.setStyleSheet(f"QLabel#Toast {{ background: {p.ink}; color: {p.background};"
                           " border-radius: 16px; padding: 7px 18px; font-weight: 600; }")
        self.setText(text)
        self.adjustSize()
        host = self.parentWidget()
        self.move((host.width() - self.width()) // 2, host.height() - self.height() - 28)
        self.raise_()
        self.show()
        self._timer.start(ms)


class _Bubble(QFrame):
    """Bulle d'une étape de la visite, avec une pointe vers l'élément présenté."""

    ARROW = 10

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("TourBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(340)
        self.arrow_at: QPoint | None = None  # pointe (coordonnées de la bulle)
        self.arrow_up = True
        layout = QVBoxLayout(self)
        m = self.ARROW + 14
        layout.setContentsMargins(18, m, 18, m)
        layout.setSpacing(6)
        self.step = label("", "small")
        self.title = label("", "h3")
        self.text = label("")
        self.text.setWordWrap(True)
        self.text.setFixedWidth(340 - 36)  # hauteur juste du texte replié
        layout.addWidget(self.step)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        row = QHBoxLayout()
        self.skip = button(_("Passer la visite"), "ghost")
        self.next = button(_("Suivant"), "primary")
        row.addWidget(self.skip)
        row.addStretch()
        row.addWidget(self.next)
        layout.addSpacing(4)
        layout.addLayout(row)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRect(self.rect()).adjusted(1, self.ARROW + 1, -1, -self.ARROW - 1)
        path = QPainterPath()
        path.addRoundedRect(body.toRectF(), 14, 14)
        if self.arrow_at is not None:
            x = max(body.left() + 20, min(body.right() - 20, self.arrow_at.x()))
            a = self.ARROW
            tip = QPolygon([QPoint(x - a, body.top() + 1), QPoint(x, body.top() - a),
                            QPoint(x + a, body.top() + 1)]) if self.arrow_up else QPolygon(
                [QPoint(x - a, body.bottom() - 1), QPoint(x, body.bottom() + a),
                 QPoint(x + a, body.bottom() - 1)])
            arrow = QPainterPath()
            arrow.addPolygon(tip.toPolygonF())
            path = path.united(arrow)
        painter.setPen(QColor(p.forest))
        painter.setBrush(QColor(p.surface))
        painter.drawPath(path)


class Tour(QWidget):
    """Visite guidée : quelques bulles successives, chacune posée près de l'élément
    qu'elle présente. `finished` est émis à la fin comme si on la passe."""

    finished = pyqtSignal()

    def __init__(self, host: QWidget,
                 steps: list[tuple[Callable[[], QWidget | None], str, str]]) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.steps = steps
        self.index = 0
        self.bubble = _Bubble(host)
        self.bubble.skip.clicked.connect(self.close_tour)
        self.bubble.next.clicked.connect(self.advance)
        self.hide()

    def start(self) -> None:
        self.index = 0
        self._show_step()

    def advance(self) -> None:
        self.index += 1
        if self.index >= len(self.steps):
            self.close_tour()
        else:
            self._show_step()

    def close_tour(self) -> None:
        self.bubble.hide()
        self.bubble.deleteLater()
        self.deleteLater()
        self.finished.emit()

    def reposition(self) -> None:
        if self.bubble.isVisible():
            self._place()

    def _show_step(self) -> None:
        _target, title, text = self.steps[self.index]
        b = self.bubble
        b.step.setText(_("Étape {n} sur {total}").format(n=self.index + 1,
                                                          total=len(self.steps)))
        b.title.setText(_(title))
        b.text.setText(_(text))
        last = self.index == len(self.steps) - 1
        b.next.setText(_("C'est parti") if last else _("Suivant"))
        b.skip.setVisible(not last)
        b.text.setFixedHeight(b.text.heightForWidth(b.text.width()))
        b.adjustSize()
        self._place()
        b.show()
        b.raise_()

    def _place(self) -> None:
        host, b = self.parentWidget(), self.bubble
        target = self.steps[self.index][0]()
        if target is None or not target.isVisible():
            b.arrow_at = None
            b.move((host.width() - b.width()) // 2, (host.height() - b.height()) // 2)
            return
        top_left = target.mapTo(host, QPoint(0, 0))
        rect = QRect(top_left, target.size())
        below = rect.bottom() + b.height() < host.height() - 8
        y = rect.bottom() + 2 if below else rect.top() - b.height() - 2
        # bulle sous un élément haut et large (la timeline) : on la pose dedans, en haut
        if rect.height() > host.height() * 0.3 and not below:
            y = rect.top() + 8
            below = True
        x = rect.center().x() - b.width() // 2
        x = max(8, min(host.width() - b.width() - 8, x))
        y = max(8, min(host.height() - b.height() - 8, y))
        b.arrow_up = below
        b.arrow_at = QPoint(rect.center().x() - x, 0)
        b.move(x, y)
        b.update()


# étapes de la visite de la première ouverture
TOUR_STEPS = (
    (N_("Importez vos médias"),
     N_("Vidéos, photos et sons : cliquez ici ou déposez vos fichiers dans le panneau.")),
    (N_("Glissez-les sur la timeline"),
     N_("Faites glisser un média vers la timeline pour le monter. Coupez avec S, "
        "annulez avec Ctrl+Z ; la touche ? affiche tous les raccourcis.")),
    (N_("Exportez votre vidéo"),
     N_("Quand le montage vous plaît, exportez-le en MP4 ou dans un autre format.")),
)
