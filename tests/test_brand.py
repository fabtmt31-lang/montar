# SPDX-License-Identifier: GPL-3.0-or-later
"""Kit de marque (F-PRJ-13)."""
import pytest

from montar.core.brand import BrandError, BrandKit


def test_kit_files_and_colors(tmp_path):
    kit = BrandKit.load(tmp_path / "marque")
    assert kit.logos() == [] and kit.fonts() == [] and kit.colors == []
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    first, second = kit.add_logo(logo), kit.add_logo(logo)
    assert first.name == "logo.png" and second.name == "logo (2).png"
    with pytest.raises(BrandError):
        kit.add_logo(tmp_path / "notes.txt")
    font = tmp_path / "Ma police.ttf"
    font.write_bytes(b"ttf")
    assert kit.add_font(font).parent == kit.fonts_dir
    assert kit.add_color("#ff8800") and not kit.add_color("#FF8800")
    with pytest.raises(BrandError):
        kit.add_color("orange")
    reloaded = BrandKit.load(tmp_path / "marque")
    assert reloaded.colors == ["#FF8800"] and len(reloaded.logos()) == 2
    reloaded.remove(second)
    reloaded.remove_color("#FF8800")
    again = BrandKit.load(tmp_path / "marque")
    assert again.colors == [] and [p.name for p in again.logos()] == ["logo.png"]
    again.remove(tmp_path / "logo.png")  # hors du kit : jamais effacé
    assert logo.exists()
