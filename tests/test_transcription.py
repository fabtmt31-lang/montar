# SPDX-License-Identifier: GPL-3.0-or-later
"""Sous-titres automatiques (F-TXT-06) : découpe, minutage, moteur remplaçable."""
from montar.core.project import Project, Subtitle
from montar.modules.transcription import add_subtitles, core


def test_split_long_lines():
    long = core.Segment(0.0, 10.0, " ".join(["mot"] * 60))
    parts = core.split_long([long, core.Segment(10, 11, "  "), core.Segment(11, 12, "Fin")])
    assert all(len(p.text) <= core.MAX_CHARS for p in parts)
    assert parts[0].start == 0.0 and abs(parts[-2].end - 10.0) < 1e-6
    assert parts[-1].text == "Fin"


def test_to_timeline_follows_clip_position_and_speed():
    segs = [core.Segment(0.0, 1.0, "a"), core.Segment(2.0, 3.0, "b"),
            core.Segment(9.0, 10.0, "hors du clip")]
    found = core.to_timeline(segs, 100, 60, 2.0, 25)  # clip accéléré ×2
    assert found == [(100, 112, "a"), (125, 138, "b")]


def test_add_subtitles_replaces_span():
    project = Project("p", fps=25)
    project.subtitles = [Subtitle(0, 10, "avant"), Subtitle(105, 120, "ancien")]
    project.subtitles_shown = False
    assert add_subtitles(project, [(100, 112, "a")], True, (100, 160)) == 1
    assert [s.text for s in project.subtitles] == ["avant", "a"] and project.subtitles_shown


class FakeBackend(core.Backend):
    name = "faux"

    def available(self):
        return True

    def transcribe(self, wav, model, language, progress, cancelled):
        assert wav.exists() and wav.stat().st_size > 1000
        progress(0.5)
        return [core.Segment(0.2, 1.0, "Bonjour"), core.Segment(1.2, 1.9, "à tous")]


def test_transcribe_clip_with_fake_backend(media_dir, monkeypatch):
    monkeypatch.setattr(core, "BACKENDS", [FakeBackend()])
    steps = []
    segs = core.transcribe_clip(str(media_dir / "son.wav"), 25, 50, 1.0, 25, "base", "fr",
                                steps.append, lambda: False)
    assert [s.text for s in segs] == ["Bonjour", "à tous"] and steps[-1] == 1.0


def test_no_backend(monkeypatch):
    class Missing(core.Backend):
        def available(self):
            return False
    monkeypatch.setattr(core, "BACKENDS", [Missing()])
    assert core.backend() is None
