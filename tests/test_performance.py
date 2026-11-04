# SPDX-License-Identifier: GPL-3.0-or-later
"""Gros projets : historique léger, index des médias, existence des fichiers gardée."""
import time

from montar.core import project as project_module
from montar.core.history import History
from montar.core.project import MediaItem, Project, file_exists, forget_exists
from montar.core.timeline import Timeline, snapshot


def big_project(n: int) -> Project:
    p = Project("Gros", fps=25)
    p.media = [MediaItem(f"/x/{i}.mp4", "video", duration=60, width=1920, height=1080,
                         fps=25, has_audio=True, id=f"m{i}") for i in range(n)]
    t = Timeline(p)
    for m in p.media:
        t.add_clip(m, duration=250)
    return p


def test_history_is_light_and_exact():
    p = big_project(300)
    t, history = Timeline(p), History()
    start = time.monotonic()
    before = snapshot(p)
    t.clip(p.clips[0].id).volume = 0.5
    assert snapshot(p) != before  # une seule valeur changée se voit
    history.record("volume", before)
    elapsed = time.monotonic() - start
    assert elapsed < 0.2  # 45 ms auparavant pour la copie et la comparaison (300 clips)
    assert snapshot(p) == snapshot(p)  # même état : mêmes octets
    assert len(history._undo[0][1]) < len(before) / 3  # gardé compressé
    history.undo(p)
    assert p.clips[0].volume == 1.0
    history.redo(p)
    assert p.clips[0].volume == 0.5


def test_find_media_index_follows_changes():
    p = big_project(5)
    assert p.find_media("m3") is p.media[3]
    replacement = MediaItem("/x/autre.mp4", "video", id="m3")
    p.media[3] = replacement  # remplacé sur place (« Modifier le média »)
    assert p.find_media("m3") is replacement
    del p.media[0]
    assert p.find_media("m4") is p.media[3] and p.find_media("m0") is None
    p.media.append(MediaItem("/x/n.mp4", id="neuf"))
    assert p.find_media("neuf") is p.media[-1]


def test_file_existence_is_kept_briefly(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    assert not file_exists(str(path))
    path.write_bytes(b"x")
    assert not file_exists(str(path))  # réponse gardée
    forget_exists(str(path))
    assert file_exists(str(path))
    path.unlink()
    monkeypatch.setattr(project_module, "EXISTS_TTL", 0.0)
    assert not file_exists(str(path))


def test_garbage_collector_runs_in_the_interface_thread():
    import gc

    from PyQt6.QtWidgets import QApplication

    from montar.ui.gc_guard import GarbageCollector

    QApplication.instance() or QApplication(["t"])  # (une seule application par essai)
    guard = GarbageCollector(interval=10)
    try:
        assert not gc.isenabled()  # plus de ramassage dans le fil qui alloue
        for _ in range(3000):
            a = []
            a.append(a)  # cycles à ramasser
        before = gc.get_count()[0]
        guard.check()
        assert gc.get_count()[0] < before
    finally:
        guard.stop()
    assert gc.isenabled()
