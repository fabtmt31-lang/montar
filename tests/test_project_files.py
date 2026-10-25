# SPDX-License-Identifier: GPL-3.0-or-later
"""Dupliquer, sauvegardes, session interrompue (cahier des charges F-PRJ-01, F-PRJ-03)."""
import json
import os
import subprocess
import sys

from montar.core.project import MediaItem, Project, unique_project_folder
from montar.core.project_files import Session, backup, backups, duplicate


def _project(root):
    path = unique_project_folder(root, "Vacances")
    project = Project("Vacances")
    project.save(path)
    medias = path.parent / "medias"
    medias.mkdir()
    (medias / "plage.mp4").write_bytes(b"video")
    project.media.append(MediaItem(str(medias / "plage.mp4"), "video"))
    (path.parent / "exports").mkdir()
    (path.parent / "exports" / "film.mp4").write_bytes(b"x" * 100)
    project.save()
    return path


def test_duplicate_copies_folder_and_relocates_media(tmp_path):
    path = _project(tmp_path)
    backup(Project.load(path))
    copy = duplicate(path, "Vacances (copie)", tmp_path)
    assert copy == tmp_path / "Vacances (copie)" / "Vacances (copie).montar"
    loaded = Project.load(copy)
    assert loaded.name == "Vacances (copie)"
    assert loaded.media[0].path == str(copy.parent / "medias" / "plage.mp4")
    assert (copy.parent / "medias" / "plage.mp4").read_bytes() == b"video"
    # ni exports ni sauvegardes ni l'ancien fichier de projet
    assert sorted(p.name for p in copy.parent.iterdir()) == ["Vacances (copie).montar",
                                                              "medias"]
    assert Project.load(path).media[0].path == str(path.parent / "medias" / "plage.mp4")


def test_backups_rotate(tmp_path):
    path = _project(tmp_path)
    project = Project.load(path)
    first = backup(project, every=0)
    assert first is not None and backup(project, every=3600) is None  # trop récente
    folder = path.parent / "sauvegardes"
    for i in range(12):
        (folder / f"Vacances 2026-01-01 00-00-{i:02d}.montar").write_text("{}")
    backup(project, every=0, keep=5)
    assert len(backups(path)) == 5


def test_session_detects_interruption(tmp_path):
    session = Session(tmp_path / "session.json")
    project = _project(tmp_path)
    assert session.interrupted() is None
    session.open(project)
    assert session.interrupted() == project  # même processus : vue comme interrompue
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    session.file.write_text(json.dumps({"project": str(project), "pid": dead.pid}))
    assert session.interrupted() == project
    session.file.write_text(json.dumps({"project": str(project), "pid": os.getppid()}))
    assert session.interrupted() is None  # un autre montar tourne encore
    session.close()
    assert not session.file.exists() and session.interrupted() is None
