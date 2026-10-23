# SPDX-License-Identifier: GPL-3.0-or-later
from montar.core.notifications import MAX_KEPT, Notifications


def test_notifications_are_kept_and_counted(tmp_path):
    file = tmp_path / "n.json"
    n = Notifications(file)
    calls = []
    n.listeners.append(lambda: calls.append(1))
    n.add("Export terminé", "film.mp4", "success", "/tmp/film.mp4")
    n.add("Module désactivé", "erreur", "error")
    assert n.unread == 2 and n.items[0].title == "Module désactivé" and len(calls) == 2
    n.mark_all_read()
    assert n.unread == 0
    again = Notifications(file)  # relu depuis le disque
    assert [i.title for i in again.items] == ["Module désactivé", "Export terminé"]
    assert again.items[1].path == "/tmp/film.mp4" and again.unread == 0
    for i in range(MAX_KEPT + 5):
        again.add(f"n{i}")
    assert len(again.items) == MAX_KEPT
    again.clear()
    assert Notifications(file).items == []
