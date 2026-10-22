# SPDX-License-Identifier: GPL-3.0-or-later
"""Corbeille (F-PRJ-07) et médiathèque (F-MED-04)."""
import time

from montar.core.library import library
from montar.core.project import MediaItem, Project, unique_project_folder
from montar.core.trash import Trash


def _project(root, name, media=()):
    path = unique_project_folder(root, name)
    project = Project(name)
    project.save(path)
    folder = path.parent / "medias"
    folder.mkdir()
    for file_name, original in media:
        (folder / file_name).write_bytes(b"x" * 10)
        project.media.append(MediaItem(str(folder / file_name), "video",
                                       original_path=original))
    project.save()
    return path


def test_trash_put_restore_delete_purge(tmp_path):
    trash = Trash(tmp_path / "corbeille")
    path = _project(tmp_path / "projets", "Vacances", [("a.mp4", "/src/a.mp4")])
    entry = trash.put(path)
    assert not path.parent.exists() and entry.name == "Vacances" and entry.size >= 10
    assert [e.name for e in trash.entries()] == ["Vacances"]
    restored = trash.restore(trash.entries()[0])
    assert restored == path and (path.parent / "medias" / "a.mp4").exists()
    assert trash.entries() == []
    trash.put(path)
    trash.delete(trash.entries()[0])
    assert trash.entries() == [] and not path.exists()
    old = _project(tmp_path / "projets", "Ancien")
    trash.put(old)
    assert trash.purge(days=30, now=time.time() + 29 * 86400) == 0
    assert trash.purge(days=30, now=time.time() + 31 * 86400) == 1
    assert trash.entries() == []


def test_library_merges_projects(tmp_path):
    a = _project(tmp_path, "A", [("plage.mp4", "/src/plage.mp4"), ("son.wav", "/src/son.wav")])
    b = _project(tmp_path, "B", [("plage.mp4", "/src/plage.mp4")])
    items = library([a, b, tmp_path / "absent.montar"])
    by_name = {i.media.name: i for i in items}
    assert set(by_name) == {"plage.mp4", "son.wav"}
    assert by_name["plage.mp4"].projects == ["A", "B"]
