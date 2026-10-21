# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

from montar.core.project import (
    FORMAT_VERSION,
    MediaItem,
    Project,
    ProjectError,
    unique_project_path,
)
from montar.core.recent import RecentProjects
from montar.core.settings import Settings


def test_defaults():
    p = Project("Essai")
    assert p.canvas_size == (1920, 1080)
    assert [t.kind for t in p.tracks] == ["video", "audio"]


def test_invalid_values():
    with pytest.raises(ValueError):
        Project("x", aspect="5:3")
    with pytest.raises(ValueError):
        Project("x", resolution="8K")


def test_round_trip_and_relative_paths(tmp_path):
    folder = tmp_path / "projet"
    (folder / "rushes").mkdir(parents=True)
    inside = folder / "rushes" / "a.mp4"
    inside.write_bytes(b"")
    outside = tmp_path / "ailleurs" / "b.mp3"
    p = Project("Vlog Pyrénées", aspect="9:16", resolution="720p", fps=30)
    p.media = [MediaItem(str(inside), "video", 4.0, 640, 360, 25.0, True, "h264", "aac"),
               MediaItem(str(outside), "audio", 12.0)]
    path = p.save(folder / "vlog.montar")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format_version"] == FORMAT_VERSION
    assert data["media"][0]["path"] == "rushes/a.mp4"
    assert data["media"][1]["path"] == str(outside)
    assert "Pyrénées" in path.read_text(encoding="utf-8")

    loaded = Project.load(path)
    assert loaded.name == "Vlog Pyrénées"
    assert (loaded.aspect, loaded.resolution, loaded.fps) == ("9:16", "720p", 30)
    assert loaded.media[0].path == str(inside)
    assert loaded.media[0].id == p.media[0].id
    assert loaded.canvas_size == (720, 1280)


def test_project_folder_can_move(tmp_path):
    src = tmp_path / "a"
    src.mkdir()
    (src / "clip.mp4").write_bytes(b"")
    p = Project("Déplacé")
    p.media = [MediaItem(str(src / "clip.mp4"))]
    p.save(src / "p.montar")
    dst = tmp_path / "b"
    src.rename(dst)
    assert Project.load(dst / "p.montar").media[0].exists


def test_save_is_atomic(tmp_path, monkeypatch):
    p = Project("Atomique")
    path = p.save(tmp_path / "p.montar")
    before = path.read_text(encoding="utf-8")
    p.name = "Modifié"

    def boom(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr("montar.core.project.os.replace", boom)
    with pytest.raises(OSError):
        p.save()
    assert path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob(".*.tmp"))  # pas de fichier temporaire oublié


@pytest.mark.parametrize("content", ["pas du json", "[1, 2]", '{"format_version": 99}',
                                     '{"format_version": 1}'])
def test_invalid_files(tmp_path, content):
    f = tmp_path / "bad.montar"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(ProjectError):
        Project.load(f)


def test_unknown_fields_are_ignored(tmp_path):
    f = tmp_path / "p.montar"
    f.write_text(json.dumps({"format_version": 1, "name": "x", "futur": True,
                             "media": [{"path": "/a.mp4", "inconnu": 1}]}), encoding="utf-8")
    assert Project.load(f).media[0].path == "/a.mp4"


def test_unique_project_path(tmp_path):
    first = unique_project_path(tmp_path, "Mon film")
    assert first.name == "Mon film.montar"
    first.write_text("{}")
    assert unique_project_path(tmp_path, "Mon film").name == "Mon film 2.montar"
    assert unique_project_path(tmp_path, 'a/b:c*').name == "abc.montar"
    assert unique_project_path(tmp_path, "  ").name == "Sans titre.montar"


def test_recent_projects(tmp_path):
    recent = RecentProjects(tmp_path / "recent.json")
    a = Project("A").save(tmp_path / "a.montar")
    b = Project("B").save(tmp_path / "b.montar")
    recent.add(a)
    recent.add(b)
    recent.add(a)
    assert recent.paths() == [a.resolve(), b.resolve()]
    b.unlink()
    assert [e.name for e in recent.entries()] == ["A"]
    recent.remove(a)
    assert recent.paths() == [b.resolve()]


def test_settings(tmp_path):
    f = tmp_path / "settings.json"
    assert Settings.load(f).theme == "light"
    s = Settings(theme="dark", preview_quality="full", projects_dir=str(tmp_path))
    s.save(f)
    loaded = Settings.load(f)
    assert (loaded.theme, loaded.preview_quality, loaded.projects_path) == (
        "dark", "full", tmp_path)
    f.write_text('{"theme": "fluo", "preview_quality": 3}')
    loaded = Settings.load(f)
    assert (loaded.theme, loaded.preview_quality) == ("light", "medium")


def test_project_folder_and_copied_media(tmp_path):
    from montar.core.project import MediaItem, unique_project_folder

    first = unique_project_folder(tmp_path, "Mon film")
    assert first == tmp_path / "Mon film" / "Mon film.montar"
    first.parent.mkdir()
    assert unique_project_folder(tmp_path, "Mon film") == \
        tmp_path / "Mon film 2" / "Mon film 2.montar"
    project = Project("Mon film")
    project.save(first)
    assert project.media_dir == tmp_path / "Mon film" / "medias"
    copy = project.media_dir / "plage.mp4"
    project.media.append(MediaItem(str(copy), "video", original_path="/ailleurs/plage.mp4"))
    assert project.has_media_path("/ailleurs/plage.mp4") and project.has_media_path(copy)
    project.save()
    data = json.loads(first.read_text(encoding="utf-8"))
    assert data["media"][0]["path"] == "medias/plage.mp4"  # dossier déplaçable d'un bloc
    moved = tmp_path / "sauvegarde"
    first.parent.rename(moved)
    loaded = Project.load(moved / "Mon film.montar")
    assert loaded.media[0].path == str(moved / "medias" / "plage.mp4")
    assert loaded.media[0].original_path == "/ailleurs/plage.mp4"


def test_settings_flags_round_trip(tmp_path):
    file = tmp_path / "settings.json"
    s = Settings(hardware_export=True, video_waveforms=False, snap=False)
    s.save(file)
    loaded = Settings.load(file)
    assert (loaded.hardware_export, loaded.video_waveforms, loaded.snap) == (True, False, False)
    file.write_text('{"snap": "oui", "video_waveforms": 1, "theme": "dark"}', encoding="utf-8")
    loaded = Settings.load(file)  # types inattendus : valeurs par défaut
    assert (loaded.snap, loaded.video_waveforms, loaded.theme) == (True, True, "dark")
