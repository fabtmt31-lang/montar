# SPDX-License-Identifier: GPL-3.0-or-later
"""Étalonnage avancé : roues, courbes, teinte, vibrance, LUT."""
import math
import subprocess

import pytest

from montar.core.project import Grade, MediaItem, Project
from montar.core.timeline import Timeline
from montar.engine.base import Canvas, ClipSpec, TimelineSpec, TrackSpec, timeline_spec
from montar.engine.grading import channel_values, grade_filters, wheel_rgb

from .conftest import needs_ffmpeg


def test_wheel_directions():
    assert wheel_rgb(0, 0) == (0, 0, 0)
    r, g, b = wheel_rgb(1, 0)  # vers le rouge
    assert r > 0 > g and r > 0 > b and abs(r + g + b) < 1e-9
    r, g, b = wheel_rgb(math.cos(2 * math.pi / 3), math.sin(2 * math.pi / 3))  # vert
    assert g > 0 > r
    assert max(wheel_rgb(5, 0)) == pytest.approx(2 / 3)  # bornée au bord du disque


def test_filters_follow_grade():
    assert grade_filters(Grade()) == []
    names = [n for n, _p in grade_filters(Grade(
        gain=[1.0, 0.0], curves={"master": [[0, 0], [0.5, 0.7], [1, 1]],
                                 "red": [[0, 0], [1, 1]]},
        hue=15, vibrance=0.4), "/x.cube")]
    assert names == ["avfilter.lutrgb", "avfilter.curves", "avfilter.hue", "avfilter.vibrance",
                     "avfilter.lut3d"]
    curves = dict(grade_filters(Grade(curves={"master": [[0, 0], [0.5, 0.7], [1, 1]]})))
    assert curves["avfilter.curves"] == {"av.m": "0.0000/0.0000 0.5000/0.7000 1.0000/1.0000"}
    lift, gamma, gain = channel_values(Grade(lift_level=-0.4))[0]
    assert lift == pytest.approx(-0.1) and gamma == 1 and gain == 1


def test_timeline_spec_resolves_lut(tmp_path):
    (tmp_path / "i.png").write_bytes(b"")
    (tmp_path / "medias").mkdir()
    (tmp_path / "medias" / "look.cube").write_text("LUT_3D_SIZE 2\n")
    project = Project("p", fps=25)
    project.path = tmp_path / "p.montar"
    project.media = [MediaItem(str(tmp_path / "i.png"), "image", width=64, height=36, id="m")]
    clip = Timeline(project).add_clip(project.media[0], duration=10)
    clip.grade = Grade(lut="medias/look.cube")
    spec = timeline_spec(project).tracks[0].clips[0]
    assert spec.lut == str(tmp_path / "medias" / "look.cube")
    clip.grade = Grade(lut="medias/absente.cube", hue=10)
    assert timeline_spec(project).tracks[0].clips[0].lut == ""
    assert Project.from_dict(project.to_dict()).clips[0].grade.hue == 10


@needs_ffmpeg
def test_grade_renders(tmp_path):
    pytest.importorskip("mlt7")
    from montar.engine import get_engine

    grey = tmp_path / "grey.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x808080:size=64x36:rate=25:duration=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(grey)], check=True)
    cube = tmp_path / "rouge.cube"  # LUT 2×2×2 : sortie = rouge partout
    cube.write_text("LUT_3D_SIZE 2\n" + "1 0 0\n" * 8)
    engine = get_engine()

    def pixel(grade, lut=""):
        clip = ClipSpec(str(grey), "video", 0, 25, media_size=(64, 36), grade=grade, lut=lut)
        source = engine.build(TimelineSpec(Canvas(64, 36, 25),
                                           (TrackSpec("video", False, False, (clip,)),)))
        data = source.render(3, 64, 36)
        source.close()
        i = (18 * 64 + 32) * 4
        return tuple(data[i:i + 3])

    base = pixel(Grade())
    warm = pixel(Grade(gain=[1.0, 0.0]))  # gain vers le rouge
    assert warm[0] > base[0] + 20 and warm[2] < base[2] - 10
    darker = pixel(Grade(lift_level=-1.0, gamma_level=-0.5))
    assert sum(darker) < sum(base) - 60
    red = pixel(Grade(lut="x"), str(cube))
    assert red[0] > 230 and red[1] < 30
