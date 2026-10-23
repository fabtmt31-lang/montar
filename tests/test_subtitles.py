# SPDX-License-Identifier: GPL-3.0-or-later
"""Sous-titres (F-TXT-05) : SRT, projet, incrustation."""
import pytest

from montar.core import subtitles
from montar.core.project import MediaItem, Project, Subtitle
from montar.core.timeline import Timeline, restore, snapshot
from montar.engine.base import timeline_spec

SRT = """1
00:00:01,000 --> 00:00:02,500
Bonjour <i>tout</i> le monde

2
00:00:03,000 --> 00:00:04,000
Deuxième
ligne
"""


def test_parse_and_write_srt():
    subs = subtitles.parse_srt(SRT.replace("\n", "\r\n"), 25)
    assert [(s.start, s.end, s.text) for s in subs] == [
        (25, 62, "Bonjour tout le monde"), (75, 100, "Deuxième\nligne")]
    text = subtitles.to_srt(subs, 25)
    assert text.startswith("1\n00:00:01,000 --> 00:00:02,480\nBonjour tout le monde\n")
    assert [(s.start, s.end) for s in subtitles.parse_srt(text, 25)] == [(25, 62), (75, 100)]
    part = subtitles.parse_srt(subtitles.to_srt(subs, 25, start=50, end=90), 25)
    assert [(s.start, s.end) for s in part] == [(0, 12), (25, 40)]
    with pytest.raises(subtitles.SrtError):
        subtitles.parse_srt("pas un fichier srt", 25)


def test_read_srt_latin1(tmp_path):
    path = tmp_path / "a.srt"
    path.write_bytes("1\n00:00:00,000 --> 00:00:01,000\nÉté\n".encode("cp1252"))
    assert subtitles.read_srt(path, 25)[0].text == "Été"


def test_add_stops_before_next():
    project = Project("p", fps=25)
    later = subtitles.add(project, 50)
    first = subtitles.add(project, 0)
    assert (first.start, first.end, later.end) == (0, 50, 125)
    assert subtitles.at(project, 60) is later
    subtitles.set_bounds(first, end=-5)
    assert first.end == 1


def test_project_roundtrip_and_history(tmp_path):
    project = Project("p", fps=25)
    project.subtitles.append(Subtitle(0, 25, "Salut"))
    project.subtitle_style.size = 60
    before = snapshot(project)
    project.subtitles.clear()
    restore(project, before)
    assert project.subtitles[0].text == "Salut"
    loaded = Project.load(project.save(tmp_path / "p.montar"))
    assert loaded.subtitles == project.subtitles and loaded.subtitle_style.size == 60
    assert loaded.subtitles_shown


def test_timeline_spec_burns_subtitles_on_top(tmp_path):
    (tmp_path / "i.png").write_bytes(b"")
    project = Project("p", fps=25)
    project.media = [MediaItem(str(tmp_path / "i.png"), "image", width=64, height=36, id="m")]
    Timeline(project).add_clip(project.media[0], duration=45)
    project.subtitles = [Subtitle(0, 30, "Un"), Subtitle(20, 50, "Deux"), Subtitle(60, 70, "X"),
                         Subtitle(10, 12, " ")]
    images = []

    def text_image(clip, w, h):
        images.append(clip.text.content)
        return f"/{clip.text.content}.png"

    spec = timeline_spec(project, text_image)
    top = [t for t in spec.tracks if t.kind == "video"][-1]
    assert [(c.start, c.duration) for c in top.clips] == [(0, 30), (30, 15)]
    assert images == ["Un", "Deux", "X"]
    assert len(timeline_spec(project, text_image, subtitles=False).tracks) == \
        len(spec.tracks) - 1
    project.subtitles_shown = False
    assert len(timeline_spec(project, text_image).tracks) == len(spec.tracks) - 1
