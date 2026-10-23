# SPDX-License-Identifier: GPL-3.0-or-later
"""Module intégré « Sous-titres automatiques » (F-TXT-06) : la parole d'un clip devient des
sous-titres, transcrite sur l'ordinateur par Whisper (aucun envoi en ligne)."""
from __future__ import annotations

from montar.api import ModuleAPI, Tool
from montar.i18n import _

from . import core

LANGUAGES = (("", "Détecter automatiquement"), ("fr", "Français"), ("en", "Anglais"),
             ("es", "Espagnol"), ("de", "Allemand"), ("it", "Italien"), ("pt", "Portugais"),
             ("nl", "Néerlandais"))
MODEL_LABELS = (("tiny", "Rapide (tiny)"), ("base", "Équilibré (base)"),
                ("small", "Précis (small)"), ("medium", "Très précis (medium, lent)"))


def _speech_clip(editor, clip) -> bool:
    if clip is None or clip.is_text or clip.reverse:
        return False
    media = editor.project.find_media(clip.media_id)
    return media is not None and media.has_audio and media.kind in ("video", "audio")


def add_subtitles(project, found, replace: bool, span: tuple[int, int]) -> int:
    """Ajoute les sous-titres trouvés ; `replace` retire d'abord ceux du passage."""
    from montar.core.project import Subtitle

    if replace:
        a, b = span
        project.subtitles = [s for s in project.subtitles if s.end <= a or s.start >= b]
    for start, end, text in found:
        project.subtitles.append(Subtitle(start, end, text))
    project.subtitles_shown = True
    return len(found)


class AutoSubtitlesTool(Tool):
    id = "transcription.sous_titres"
    name = "Sous-titres automatiques…"
    icon = "captions"
    description = ("Transcrit la parole du clip en sous-titres, sur l'ordinateur (Whisper), "
                   "sans rien envoyer en ligne.")

    def available(self, editor, clip) -> bool:
        return _speech_clip(editor, clip)

    def run(self, editor, clip) -> None:
        from PyQt6.QtWidgets import QMessageBox

        if core.backend() is None:
            QMessageBox.information(editor.parent, _("Sous-titres automatiques"), _(
                "Aucun moteur de reconnaissance vocale n'est installé. Installez par exemple "
                "faster-whisper :\n\n    {cmd}\n\nLe modèle choisi est téléchargé une seule "
                "fois ; ensuite, tout se fait sur l'ordinateur, sans connexion. Le programme "
                "whisper.cpp convient aussi (modèles ggml-*.bin dans "
                "~/.local/share/montar/whisper).").format(cmd=core.INSTALL_HINT))
            return
        choice = _ask(editor.parent)
        if choice is None:
            return
        model, language, replace = choice
        media = editor.project.find_media(clip.media_id)
        job = (media.path, clip.source_in, clip.duration, clip.speed, editor.fps, model,
               language)
        span = (clip.start, clip.start + clip.duration)
        clip_start, clip_duration, clip_speed = clip.start, clip.duration, clip.speed

        def work(progress, cancelled):
            source, source_in, frames, speed, fps, size, lang = job
            return core.transcribe_clip(source, source_in, frames, speed, fps, size, lang,
                                        progress, cancelled)

        def done(segments):
            found = core.to_timeline(segments or [], clip_start, clip_duration, clip_speed,
                                     editor.fps)
            if not found:
                editor.error(_("Aucune parole reconnue dans ce clip."))
                return
            editor.edit(_("Sous-titres automatiques"),
                        lambda t: add_subtitles(t.project, found, replace, span))

        editor.schedule_job(f"transcription:{clip.id}:{model}:{language}",
                            _("Sous-titres automatiques"), work, done)


def _ask(parent):
    """(modèle, langue, remplacer) ou None."""
    from PyQt6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLabel,
        QVBoxLayout,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle(_("Sous-titres automatiques"))
    layout = QVBoxLayout(dialog)
    engine = core.backend()
    info = QLabel(_("Moteur : {name}. La transcription se fait sur l'ordinateur ; elle peut "
                    "prendre quelques minutes.").format(name=engine.name if engine else "—"))
    info.setWordWrap(True)
    layout.addWidget(info)
    form = QFormLayout()
    language = QComboBox()
    for key, text in LANGUAGES:
        language.addItem(_(text), key)
    model = QComboBox()
    for key, text in MODEL_LABELS:
        model.addItem(_(text), key)
    model.setCurrentIndex(1)
    form.addRow(_("Langue"), language)
    form.addRow(_("Modèle"), model)
    layout.addLayout(form)
    replace = QCheckBox(_("Remplacer les sous-titres déjà présents sur ce clip"))
    replace.setChecked(True)
    layout.addWidget(replace)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                               QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Transcrire"))
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Annuler"))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return model.currentData(), language.currentData(), replace.isChecked()


def register(api: ModuleAPI) -> None:
    api.add_tool(AutoSubtitlesTool)
