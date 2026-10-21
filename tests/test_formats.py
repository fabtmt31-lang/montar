# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from montar.core import formats
from montar.core.timecode import frames_to_timecode, seconds_to_short


@pytest.mark.parametrize(("aspect", "res", "size"), [
    ("16:9", "1080p", (1920, 1080)),
    ("16:9", "720p", (1280, 720)),
    ("16:9", "4K", (3840, 2160)),
    ("9:16", "1080p", (1080, 1920)),
    ("1:1", "1080p", (1080, 1080)),
    ("4:5", "1080p", (1080, 1350)),
    ("21:9", "1080p", (2520, 1080)),
])
def test_canvas_size(aspect, res, size):
    assert formats.canvas_size(aspect, res) == size


def test_canvas_size_is_even():
    for ar in formats.ASPECT_RATIOS:
        for res in formats.RESOLUTIONS:
            w, h = formats.canvas_size(ar.id, res)
            assert w % 2 == 0 and h % 2 == 0


def test_unknown_aspect():
    with pytest.raises(ValueError):
        formats.canvas_size("3:2", "1080p")


def test_timecode():
    assert frames_to_timecode(0, 25) == "00:00:00:00"
    assert frames_to_timecode(2558, 25) == "00:01:42:08"
    assert frames_to_timecode(25 * 3600 + 1, 25) == "01:00:00:01"
    assert frames_to_timecode(59, 29.97) == "00:00:01:29"


def test_short_duration():
    assert seconds_to_short(48) == "0:48"
    assert seconds_to_short(755) == "12:35"
    assert seconds_to_short(3723) == "1:02:03"
