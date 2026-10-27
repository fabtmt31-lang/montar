# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from montar.core.history import History
from montar.core.project import MediaItem, Project
from montar.core.timeline import Timeline, TimelineError, snapshot

FPS = 25


@pytest.fixture
def project():
    p = Project("Montage", fps=FPS)
    p.media = [
        MediaItem("/v.mp4", "video", duration=4.0, width=640, height=360, fps=25,
                  has_audio=True, id="video"),
        MediaItem("/i.png", "image", width=320, height=240, id="image"),
        MediaItem("/s.wav", "audio", duration=10.0, has_audio=True, id="audio"),
    ]
    return p


@pytest.fixture
def tl(project):
    return Timeline(project)


def media(tl, media_id):
    return tl.project.find_media(media_id)


def test_default_tracks_and_labels(tl):
    v1 = tl.first_track("video")
    a1 = tl.first_track("audio")
    v2 = tl.add_track("video")
    a2 = tl.add_track("audio")
    labels = tl.track_labels()
    assert (labels[v1.id], labels[v2.id], labels[a1.id], labels[a2.id]) == ("V1", "V2", "A1", "A2")
    assert [t.id for t in tl.project.tracks] == [v2.id, v1.id, a1.id, a2.id]


def test_add_clips_follow_each_other(tl):
    a = tl.add_clip(media(tl, "video"))
    b = tl.add_clip(media(tl, "image"))
    c = tl.add_clip(media(tl, "audio"))
    assert (a.start, a.duration) == (0, 100)
    assert (b.start, b.duration) == (100, 125)  # image : 5 s par défaut
    assert b.track_id == a.track_id == tl.first_track("video").id
    assert (c.start, c.duration, c.track_id) == (0, 250, tl.first_track("audio").id)
    assert tl.length() == 250


def test_incompatible_track_is_refused(tl):
    with pytest.raises(TimelineError):
        tl.add_clip(media(tl, "audio"), tl.first_track("video").id)


def test_no_overlap_on_drop(tl):
    track = tl.first_track("video").id
    tl.add_clip(media(tl, "video"), track, 0)  # 0–100
    tl.add_clip(media(tl, "video"), track, 200)  # 200–300
    # déposé à 30 : chevauche le premier clip, placé dans l'espace libre le plus proche
    c = tl.add_clip(media(tl, "image"), track, 30, duration=50)
    assert c.start == 100
    # trop long pour le trou de 100 images : placé après le dernier clip
    d = tl.add_clip(media(tl, "image"), track, 120, duration=150)
    assert d.start == 300


def test_move_between_tracks(tl):
    v1 = tl.first_track("video").id
    v2 = tl.add_track("video").id
    a1 = tl.first_track("audio").id
    clip = tl.add_clip(media(tl, "video"), v1, 0)
    tl.move_clip(clip.id, v2, 40)
    assert (clip.track_id, clip.start) == (v2, 40)
    tl.move_clip(clip.id, a1, 10)  # piste audio incompatible : reste sur sa piste
    assert (clip.track_id, clip.start) == (v2, 10)
    tl.move_clip(clip.id, v2, -50)
    assert clip.start == 0


def test_trim_respects_source_and_neighbours(tl):
    track = tl.first_track("video").id
    clip = tl.add_clip(media(tl, "video"), track, 50)  # 50–150, source 0–100
    other = tl.add_clip(media(tl, "image"), track, 200, duration=20)
    tl.trim(clip.id, "start", 70)
    assert (clip.start, clip.duration, clip.source_in) == (70, 80, 20)
    tl.trim(clip.id, "start", 0)  # pas avant le début du média
    assert (clip.start, clip.source_in) == (50, 0)
    tl.trim(clip.id, "end", 400)  # pas au-delà de la fin du média
    assert clip.end == 150
    tl.trim(clip.id, "end", 100)
    assert clip.end == 100
    image = tl.trim(other.id, "end", 1000)  # une image peut durer autant que l'on veut
    assert image.end == 1000
    tl.trim(other.id, "start", 0)
    assert other.start == 100  # bloqué par le clip précédent


def test_split_and_split_at(tl):
    clip = tl.add_clip(media(tl, "video"))
    tl.add_clip(media(tl, "audio"))
    assert tl.split(clip.id, 0) is None and tl.split(clip.id, 100) is None
    second = tl.split(clip.id, 40)
    assert (clip.duration, second.start, second.duration, second.source_in) == (40, 40, 60, 40)
    parts = tl.split_at(70)  # aucun clip choisi : coupe tout ce qui est sous la tête
    assert len(parts) == 2
    assert tl.length() == 250
    assert len(tl.project.clips) == 5


def test_delete_and_ripple(tl):
    track = tl.first_track("video").id
    a = tl.add_clip(media(tl, "video"), track)
    b = tl.add_clip(media(tl, "image"), track)
    c = tl.add_clip(media(tl, "image"), track)
    tl.delete(b.id, ripple=True)
    assert (a.start, c.start) == (0, 100)
    tl.delete(a.id)
    assert c.start == 100


def test_duplicate(tl):
    a = tl.add_clip(media(tl, "video"))
    b = tl.duplicate(a.id)
    assert (b.start, b.duration, b.source_in, b.track_id) == (100, 100, 0, a.track_id)


def test_remove_track_and_media(tl):
    v2 = tl.add_track("video")
    tl.add_clip(media(tl, "image"), v2.id)
    tl.add_clip(media(tl, "video"))
    tl.remove_track(v2.id)
    assert len(tl.project.clips) == 1
    with pytest.raises(TimelineError):
        tl.remove_track(tl.first_track("video").id)  # dernière piste vidéo
    tl.remove_media("video")
    assert tl.project.clips == [] and len(tl.project.media) == 2


def test_free_start_with_gaps(tl):
    track = tl.first_track("video").id
    tl.add_clip(media(tl, "image"), track, 0, duration=10)
    tl.add_clip(media(tl, "image"), track, 30, duration=10)
    assert tl.free_start(track, 12, 10) == 12
    assert tl.free_start(track, 25, 10) == 20
    assert tl.free_start(track, 33, 10) == 40


def test_history_undo_redo(project):
    tl = Timeline(project)
    history = History()

    def edit(label, fn):
        before = snapshot(project)
        fn()
        history.record(label, before)

    edit("ajout", lambda: tl.add_clip(media(tl, "video")))
    clip_id = project.clips[0].id
    edit("coupe", lambda: tl.split(clip_id, 50))
    assert len(project.clips) == 2
    assert history.undo(project) == "coupe" and len(project.clips) == 1
    assert project.clips[0].duration == 100
    assert history.undo(project) == "ajout" and project.clips == []
    assert history.undo(project) is None
    assert history.redo(project) == "ajout" and len(project.clips) == 1
    edit("nouvelle", lambda: tl.add_clip(media(tl, "audio")))
    assert not history.can_redo  # une nouvelle action efface le « rétablir »


def test_clips_survive_save(tmp_path, project):
    tl = Timeline(project)
    tl.add_clip(media(tl, "video"))
    tl.add_track("audio").muted = True
    path = project.save(tmp_path / "p.montar")
    loaded = Project.load(path)
    assert [(c.media_id, c.start, c.duration) for c in loaded.clips] == [("video", 0, 100)]
    assert [t.muted for t in loaded.tracks] == [False, False, True]


def test_version_1_projects_still_open(tmp_path):
    f = tmp_path / "ancien.montar"
    f.write_text('{"format_version": 1, "name": "Ancien", "media": [], '
                 '"tracks": [{"kind": "video", "name": "Vidéo", "id": "v"}]}', encoding="utf-8")
    p = Project.load(f)
    assert p.clips == [] and p.tracks[0].muted is False


# --- J2 : vitesse, transitions, textes, son détaché ------------------------------------


def test_speed_changes_duration_and_shifts_followers(tl):
    track = tl.first_track("video").id
    a = tl.add_clip(media(tl, "video"), track)  # 0–100
    b = tl.add_clip(media(tl, "image"), track)  # 100–225
    tl.set_speed(a.id, 2.0)
    assert (a.duration, b.start) == (50, 50)
    tl.set_speed(a.id, 0.5)
    assert (a.duration, b.start) == (200, 200)
    tl.set_speed(a.id, 100)  # borné à ×16
    assert a.speed == 16.0 and a.duration == 6
    with pytest.raises(TimelineError):
        tl.set_speed(b.id, 2.0)  # pas de vitesse pour une image


def test_speed_bounds_trim_and_split(tl):
    clip = tl.add_clip(media(tl, "video"))
    tl.set_speed(clip.id, 2.0)  # 100 images source → 50 images de timeline
    assert tl.trim_bounds(clip.id, "end")[1] == 50
    second = tl.split(clip.id, 20)
    assert second.source_in == 40 and second.speed == 2.0
    assert tl.trim_bounds(second.id, "start")[0] == 20  # bloqué par la première partie


def test_transition_overlaps_and_shifts(tl):
    track = tl.first_track("video").id
    a = tl.add_clip(media(tl, "video"), track)  # 0–100
    b = tl.add_clip(media(tl, "video"), track)  # 100–200
    c = tl.add_clip(media(tl, "image"), track)  # 200–325
    t = tl.add_transition(a.id, b.id, "wipe_left", 20)
    assert (b.start, c.start, tl.length()) == (80, 180, 305)
    assert tl.neighbour(a.id, "right") is b and tl.neighbour(b.id, "left") is a
    with pytest.raises(TimelineError):
        tl.add_transition(a.id, b.id)  # déjà reliés
    tl.set_transition(t.id, duration=40)
    assert (b.start, c.start, t.duration) == (60, 160, 40)
    tl.set_transition(t.id, duration=1000)  # borné par la durée des clips
    assert t.duration == 99
    tl.remove_transition(t.id)
    assert (b.start, c.start) == (100, 200)


def test_transition_requires_adjacent_clips(tl):
    track = tl.first_track("video").id
    a = tl.add_clip(media(tl, "image"), track, 0, duration=50)
    b = tl.add_clip(media(tl, "image"), track, 60, duration=50)
    with pytest.raises(TimelineError):
        tl.add_transition(a.id, b.id)


def test_audio_tracks_only_crossfade(tl):
    a = tl.add_clip(media(tl, "audio"))
    b = tl.add_clip(media(tl, "audio"))
    t = tl.add_transition(a.id, b.id, "zoom", 25)
    assert t.kind == "dissolve"


def test_edges_in_transition_are_locked_and_moves_drop_it(tl):
    track = tl.first_track("video").id
    a = tl.add_clip(media(tl, "image"), track, duration=50)
    b = tl.add_clip(media(tl, "image"), track, duration=50)
    tl.add_transition(a.id, b.id, duration=10)
    assert tl.trim_bounds(a.id, "end") == (a.end, a.end)
    assert tl.trim_bounds(b.id, "start") == (b.start, b.start)
    assert tl.split(a.id, 45) is None  # dans la zone de transition
    part = tl.split(a.id, 20)
    assert tl.transition_after(part.id) is not None  # la transition suit la seconde partie
    tl.move_clip(b.id, track, 300)
    assert tl.project.transitions == []


def test_delete_with_transition_ripples_correctly(tl):
    track = tl.first_track("video").id
    a = tl.add_clip(media(tl, "image"), track, duration=100)
    b = tl.add_clip(media(tl, "image"), track, duration=100)
    c = tl.add_clip(media(tl, "image"), track, duration=50)
    tl.add_transition(a.id, b.id, duration=20)  # b 80–180, c 180–230
    tl.delete(b.id, ripple=True)
    assert c.start == 100 and tl.project.transitions == []


def test_texts_live_on_text_tracks(tl):
    from montar.core.project import TextStyle

    clip = tl.add_text(TextStyle(content="Bonjour"), 50)
    track = tl.track(clip.track_id)
    assert track.kind == "text" and tl.project.tracks[0] is track
    assert (clip.start, clip.duration, clip.media_id) == (50, 125, "")
    assert tl.track_labels()[track.id] == "T1"
    v2 = tl.add_track("video")
    assert tl.project.tracks[1] is v2  # sous les textes, au-dessus de V1
    with pytest.raises(TimelineError):
        tl.add_clip(media(tl, "video"), track.id)
    tl.remove_track(track.id)  # on peut retirer toutes les pistes texte
    assert tl.first_track("text") is None


def test_detach_audio(tl):
    clip = tl.add_clip(media(tl, "video"), start=10)
    tl.add_clip(media(tl, "audio"), start=0)  # A1 occupée : le son va sur une nouvelle piste
    audio = tl.detach_audio(clip.id)
    assert clip.volume == 0.0
    assert (audio.media_id, audio.start, audio.duration) == ("video", 10, 100)
    track = tl.track(audio.track_id)
    assert track.kind == "audio" and track is not tl.first_track("audio")
    image = tl.add_clip(media(tl, "image"))
    with pytest.raises(TimelineError):
        tl.detach_audio(image.id)


def test_clip_settings_survive_save(tmp_path, project):
    from montar.core.project import TextStyle

    tl = Timeline(project)
    clip = tl.add_clip(media(tl, "video"))
    clip.transform.scale, clip.transform.flip_h = 0.5, True
    clip.color.saturation, clip.preset, clip.fade_in = -0.4, "sepia", 12
    clip.effects.blur = 0.3
    other = tl.add_clip(media(tl, "video"))
    tl.add_transition(clip.id, other.id, "zoom", 10)
    tl.add_text(TextStyle(content="Fin", background="#FFFFFF"), 0)
    loaded = Project.load(project.save(tmp_path / "p.montar"))
    c = loaded.clips[0]
    assert (c.transform.scale, c.transform.flip_h, c.color.saturation) == (0.5, True, -0.4)
    assert (c.preset, c.fade_in, c.effects.blur) == ("sepia", 12, 0.3)
    assert loaded.transitions[0].kind == "zoom"
    assert loaded.clips[2].text.content == "Fin" and loaded.clips[2].text.background == "#FFFFFF"


# --- 0.4.1 : pistes et plages -------------------------------------------------------


def test_insert_and_move_tracks_stay_grouped(tl):
    tl.add_track("text")
    v1, a1 = tl.first_track("video"), tl.first_track("audio")
    v2 = tl.insert_track("video", 99)  # ramenée en bas du groupe vidéo, au-dessus de l'audio
    kinds = [t.kind for t in tl.project.tracks]
    assert kinds == ["text", "video", "video", "audio"]
    assert tl.project.tracks.index(v2) == 2 and tl.track_labels()[v2.id] == "V1"
    tl.move_track(v2.id, 0)  # ne passe pas au-dessus des textes
    assert [t.kind for t in tl.project.tracks] == kinds
    assert tl.project.tracks[1] is v2 and tl.project.tracks[2] is v1
    tl.move_track(a1.id, 0)  # l'audio reste en bas
    assert tl.project.tracks[-1] is a1


def test_move_clip_to_new_track(tl):
    a = tl.add_clip(media(tl, "video"))
    b = tl.add_clip(media(tl, "image"))
    v1 = tl.first_track("video")
    index = tl.project.tracks.index(v1)
    moved = tl.move_clip_to_new_track(b.id, index, 20)  # au-dessus de V1, par-dessus « a »
    assert moved.track_id != v1.id and moved.start == 20
    assert tl.project.tracks.index(tl.track(moved.track_id)) == index
    assert a.track_id == v1.id


def test_isolate_range(tl):
    clip = tl.add_clip(media(tl, "video"))  # 0–100
    middle = tl.isolate(clip.id, 30, 60)
    assert (middle.start, middle.end) == (30, 60)
    assert middle.source_in == 30
    assert sorted((c.start, c.end) for c in tl.project.clips) == [(0, 30), (30, 60), (60, 100)]
    assert tl.isolate(middle.id, 0, 200) is middle  # plage = clip entier : rien à couper
    with pytest.raises(TimelineError):
        tl.isolate(middle.id, 50, 50)


def test_fit_to_media_after_replacement(tl):
    clip = tl.add_clip(media(tl, "video"))  # 4 s = 100 images
    clip.source_in, clip.duration = 40, 60
    media(tl, "video").duration = 2.0  # version modifiée, plus courte
    tl.fit_to_media(clip.id)
    assert (clip.source_in, clip.duration) == (40, 10)
    media(tl, "video").duration = 1.0
    tl.fit_to_media(clip.id)
    assert (clip.source_in, clip.duration) == (0, 10)


# --- J5-E : marqueurs et voix off ---------------------------------------------------------------


def test_markers(tmp_path, project, tl):
    first = tl.toggle_marker(50)
    second = tl.toggle_marker(10)
    assert [m.frame for m in tl.markers()] == [10, 50]
    assert first.name == "Marqueur 1"
    tl.move_marker(second.id, 80)
    tl.rename_marker(first.id, "  Intro  ")
    assert [(m.frame, m.name) for m in tl.markers()] == [(50, "Intro"), (80, "Marqueur 2")]
    assert tl.adjacent_marker(50, 1).id == second.id
    assert tl.adjacent_marker(50, -1) is None
    assert tl.adjacent_marker(100, -1).id == second.id
    assert tl.toggle_marker(80) is None  # même endroit : retiré
    project.save(tmp_path / "p.montar")
    loaded = Project.load(tmp_path / "p.montar")
    assert [(m.frame, m.name, m.id) for m in loaded.markers] == [(50, "Intro", first.id)]


def test_markers_are_undoable(project, tl):
    history = History()
    before = snapshot(project)
    tl.toggle_marker(5)
    history.record("Marqueur", before)
    history.undo(project)
    assert project.markers == []


def test_voice_over_placement(tl):
    voice = MediaItem("/voix.wav", "audio", duration=2.0, has_audio=True, id="voice")
    tl.project.media.append(voice)
    first = tl.add_voice_over(voice, 30, trim=5)
    track = tl.track(first.track_id)
    assert track.name == "Voix off" and track.kind == "audio"
    assert (first.start, first.source_in, first.duration) == (30, 5, 45)
    # même endroit : la piste est occupée, une seconde piste « Voix off » est créée
    second = tl.add_voice_over(voice, 40)
    assert second.start == 40 and second.track_id != first.track_id
    # plus loin : la première piste est libre
    third = tl.add_voice_over(voice, 200)
    assert third.track_id == first.track_id and third.start == 200


def test_overlay_placement(tl):
    image = media(tl, "image")
    main = next(t for t in tl.project.tracks if t.kind == "video")
    tl.add_clip(media(tl, "video"), main.id, 0)
    first = tl.add_overlay(image, 10)
    tracks = [t for t in tl.project.tracks if t.kind == "video"]
    assert first.start == 10 and first.track_id == tracks[0].id != main.id  # au-dessus
    second = tl.add_overlay(image, 20)  # piste occupée : une autre au-dessus
    assert len([t for t in tl.project.tracks if t.kind == "video"]) == 3
    assert second.track_id != first.track_id
    third = tl.add_overlay(image, 500)  # plus loin : la première piste du dessus est libre
    assert third.track_id == [t for t in tl.project.tracks if t.kind == "video"][0].id
    background = tl.add_overlay(image, 0, below=True)  # sous la vidéo principale
    video = [t for t in tl.project.tracks if t.kind == "video"]
    assert background.track_id == video[-1].id and video[-2].id == main.id


# --- P2-1 : lecture inversée, image fixe, verrou -------------------------------------------------


def test_reverse_split_and_trim(tl):
    video = media(tl, "video")  # 4 s = 100 images
    clip = tl.add_clip(video, None, 0)
    clip.source_in, clip.duration = 10, 60  # plage 10 → 70, lue à l'envers
    tl.set_reverse(clip.id, True)
    second = tl.split(clip.id, 20)
    # première partie : le haut de la plage (50 → 70) ; seconde : le bas (10 → 50)
    assert (clip.source_in, clip.duration) == (50, 20)
    assert (second.source_in, second.duration) == (10, 40)
    tl.trim(second.id, "end", 50)  # retire 10 images du bas
    assert (second.source_in, second.duration) == (20, 30)
    tl.trim(clip.id, "start", 5)  # retire 5 images du haut : le point d'entrée ne bouge pas
    assert (clip.source_in, clip.duration) == (50, 15)
    with pytest.raises(TimelineError):
        tl.set_reverse(tl.add_clip(media(tl, "image")).id, True)


def test_insert_freeze(tl):
    video = media(tl, "video")
    first = tl.add_clip(video, None, 0)
    after = tl.add_clip(video, None, 100)
    still_media = MediaItem("/f.png", "image", width=640, height=360, id="still")
    tl.project.media.append(still_media)
    still = tl.insert_freeze(first.id, 40, still_media, 50)
    assert (still.start, still.duration) == (40, 50)
    parts = sorted((c for c in tl.project.clips if c.media_id == "video"), key=lambda c: c.start)
    assert [(c.start, c.duration) for c in parts] == [(0, 40), (90, 60), (150, 100)]
    assert after.start == 150


def test_locked_track_refuses_changes(project):
    from montar.ui.editor.controller import EditorController

    pytest.importorskip("PyQt6.QtCore")
    controller = EditorController(project)
    errors = []
    controller.error.connect(errors.append)
    clip = controller.edit("ajout", lambda t: t.add_clip(t.project.find_media("video")))
    track_id = clip.track_id
    controller.edit("verrou", lambda t: setattr(t.track(track_id), "locked", True))
    assert controller.edit("couper", lambda t: t.split(clip.id, 10)) is None
    assert errors and "verrouillée" in errors[-1] and len(project.clips) == 1
    controller.edit("ailleurs", lambda t: t.add_clip(t.project.find_media("audio")))
    assert len(project.clips) == 2  # les autres pistes restent modifiables
    controller.edit("déverrou", lambda t: setattr(t.track(track_id), "locked", False))
    controller.edit("couper", lambda t: t.split(project.clips[0].id, 10))
    assert len(project.clips) == 3


def test_move_several_clips_together(tl):
    v, a = tl.first_track("video").id, tl.first_track("audio").id
    x = tl.add_clip(media(tl, "image"), v, 0, duration=50)
    y = tl.add_clip(media(tl, "audio"), a, 10, duration=50)
    z = tl.add_clip(media(tl, "image"), v, 200, duration=50)
    tl.move_clips([x.id, y.id], 40)  # chacun garde sa piste
    assert (x.start, y.start, x.track_id, y.track_id) == (40, 50, v, a)
    with pytest.raises(TimelineError):
        tl.move_clips([x.id, y.id], 130)  # x arriverait sur z
    with pytest.raises(TimelineError):
        tl.move_clips([x.id, y.id], -50)  # avant le début
    tl.move_clips([x.id, z.id], 10)  # z bouge aussi : pas de conflit avec lui-même
    assert (x.start, z.start) == (50, 210)


def test_merge_group_rules(tl):
    v = tl.first_track("video").id
    a = tl.add_clip(media(tl, "image"), v, 0, duration=50)
    b = tl.add_clip(media(tl, "image"), v, 50, duration=50)
    c = tl.add_clip(media(tl, "image"), v, 120, duration=50)  # espace avant c
    s = tl.add_clip(media(tl, "audio"), tl.first_track("audio").id, 0, duration=50)
    assert tl.merge_group([b.id, a.id]) == [a, b]
    for ids in ([a.id], [a.id, c.id], [b.id, c.id], [a.id, s.id]):
        with pytest.raises(TimelineError):
            tl.merge_group(ids)


def test_join_pieces_after_split(tl):
    clip = tl.add_clip(media(tl, "video"))
    second = tl.split(clip.id, 40)
    third = tl.split(second.id, 70)
    second.fade_in = 0
    third.fade_out = 5
    assert tl.join_pieces([clip.id, second.id, third.id]) is clip
    assert (clip.start, clip.duration, clip.source_in, clip.fade_out) == (0, 100, 0, 5)
    assert len(tl.project.clips) == 1
    # médias différents : rien n'est recollé (il faudra un rendu)
    other = tl.add_clip(media(tl, "image"), clip.track_id, 100, duration=25)
    assert tl.join_pieces([clip.id, other.id]) is None and len(tl.project.clips) == 2


def test_replace_with_media(tl):
    v = tl.first_track("video").id
    a = tl.add_clip(media(tl, "video"), v)  # 0–100
    b = tl.add_clip(media(tl, "image"), v)  # 100–225
    c = tl.add_clip(media(tl, "image"), v)  # 225–350
    tl.add_transition(a.id, b.id, "dissolve", 20)  # b : 80–205, c : 205–330
    out = tl.add_transition(b.id, c.id, "dissolve", 10)  # vers le voisin : gardée
    from montar.core.project import MediaItem
    rendered = MediaItem("/u.mp4", "video", duration=8.2, width=640, height=360, fps=25,
                         id="unified")
    merged = tl.replace_with_media([a.id, b.id], rendered)
    assert (merged.start, merged.duration, merged.media_id) == (0, 205, "unified")
    assert tl.project.find_media("unified") is rendered
    assert [x.id for x in tl.clips_on(v)] == [merged.id, c.id]
    assert tl.project.transitions == [out] and out.left_id == merged.id
    tl.sanitize()  # toujours valide : le clip unifié couvre la même durée
    assert tl.project.transitions == [out]
