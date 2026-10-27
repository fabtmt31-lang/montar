# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran (F-MED-06)."""
import dataclasses
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from montar.media import recorder
from montar.media.recorder import RecordOptions, command


def test_command(monkeypatch):
    monkeypatch.setattr(recorder, "ON_WINDOWS", False)  # commande X11 / PulseAudio
    cmd = command(RecordOptions(geometry=(1920, 0, 1281, 720), display=":1",
                                microphone=True, system_audio=True,
                                webcam="/dev/video0"), "out.mp4")
    line = " ".join(cmd)
    assert "-video_size 1280x720 -i :1+1920,0" in line
    assert "-f pulse -i default" in line and "-f pulse -i @DEFAULT_MONITOR@" in line
    assert "amix=inputs=2" in line and "overlay" not in line
    # l'écran (avec le son) et la webcam dans deux fichiers ; vignettes « webcam prête »
    assert "-f v4l2 -i /dev/video0" in line and "+faststart out.mp4" in line
    assert "out.webcam-brut.mkv" in line and line.endswith("-f rawvideo pipe:1")
    region = " ".join(command(RecordOptions(source="region", geometry=(1920, 0, 1280, 720),
                                            region=(10, 20, 301, 200), microphone=False,
                                            display=":1"), "x.mp4"))
    assert "-video_size 300x200 -i :1+1930,20" in region
    assert "pulse" not in region and "-c:a" not in region
    # horloge commune : chaque source datée à la lecture, ramenée au même départ
    timed = command(RecordOptions(geometry=(0, 0, 640, 360), webcam="/dev/video0"), "t.mp4",
                    t0=1000.5)
    line = " ".join(timed)
    assert line.count("-use_wallclock_as_timestamps 1") == 3 and "-copyts" in line
    assert "[0:v]setpts=PTS-1000.500000/TB,trim=start=0" in line
    assert "[2:v]setpts=PTS-1000.500000/TB" in line
    assert "asetpts=PTS-1000.500000/TB,atrim=start=0,aresample=async=1000" in line
    # ffmpeg lancé pendant le compte à rebours : l'écran et le son d'avant sont jetés, la
    # webcam garde tout (elle a eu le temps de s'ouvrir)
    early = " ".join(command(RecordOptions(geometry=(0, 0, 640, 360), webcam="/dev/video0"),
                             "t.mp4", t0=1003.5, origin=1000.5))
    assert "[0:v]setpts=PTS-1003.500000/TB,trim=start=0" in early
    assert "[2:v]setpts=PTS-1000.500000/TB" in early
    window = " ".join(command(RecordOptions(source="window", window_id="0x3a0000a",
                                            microphone=False), "x.mp4"))
    assert "-window_id 0x3a0000a" in window


def test_session_problem(monkeypatch):
    monkeypatch.setattr(recorder, "ON_WINDOWS", False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert "Wayland" in recorder.session_problem()
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert recorder.session_problem() == "" or "ffmpeg" in recorder.session_problem()
    monkeypatch.setattr(recorder, "ON_WINDOWS", True)
    assert recorder.session_problem() in ("", "ffmpeg est introuvable")


@pytest.fixture(scope="module")
def xvfb():
    if shutil.which("Xvfb") is None or shutil.which("ffmpeg") is None:
        pytest.skip("Xvfb ou ffmpeg absent")
    devices = subprocess.run(["ffmpeg", "-hide_banner", "-devices"], capture_output=True,
                             text=True).stdout
    if "x11grab" not in devices:
        pytest.skip("ffmpeg sans x11grab")
    display = ":97"
    proc = subprocess.Popen(["Xvfb", display, "-screen", "0", "640x360x24"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    yield display
    proc.terminate()
    proc.wait(5)


def _duration(path) -> float:
    out = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout
    return float(out.strip() or 0)


def test_record_screen(xvfb, tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", xvfb)
    target = tmp_path / "ecran.mp4"
    rec = recorder.Recorder(RecordOptions(geometry=(0, 0, 640, 360), microphone=False),
                            target)
    rec.start()
    time.sleep(2)
    assert rec.running
    assert rec.stop(), rec.error  # message de ffmpeg en cas d'échec
    assert _duration(target) == pytest.approx(2.0, abs=0.8)
    assert not list(tmp_path.glob("*.log"))


def test_failed_recording_reports_error(xvfb, tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", xvfb)
    rec = recorder.Recorder(RecordOptions(geometry=(0, 0, 640, 360), microphone=False,
                                          display=":1234"), tmp_path / "x.mp4")
    rec.start()
    time.sleep(1)
    assert not rec.running and not rec.stop() and rec.error


def test_voice_over_command(monkeypatch):
    from montar.media import voiceover

    monkeypatch.setattr(voiceover, "ON_WINDOWS", False)
    cmd = voiceover.command("alsa_input.usb", "/tmp/v.wav")
    assert cmd[cmd.index("-f") + 1] == "pulse"
    assert cmd[cmd.index("-i") + 1] == "alsa_input.usb"
    assert "pcm_s16le" in cmd and cmd[-1] == "/tmp/v.wav"
    monkeypatch.setattr(voiceover.shutil, "which", lambda _n: None)
    assert voiceover.microphones() == [("default", "Micro par défaut")]


DSHOW_LISTING = """[dshow @ 0000] "Integrated Camera" (video)
[dshow @ 0000]   Alternative name "@device_pnp_\\?\\usb#vid"
[dshow @ 0000] "Microphone (Realtek(R) Audio)" (audio)
[dshow @ 0000]   Alternative name "@device_cm_{33D9A762}\\wave_{1}"
[dshow @ 0000] "Casque (USB Audio)" (audio)
dummy: Immediate exit requested
"""


def test_voice_over_on_windows(monkeypatch):
    from montar.media import voiceover

    assert recorder.parse_dshow(DSHOW_LISTING) == ["Microphone (Realtek(R) Audio)",
                                                   "Casque (USB Audio)"]
    assert recorder.parse_dshow(DSHOW_LISTING, "video") == ["Integrated Camera"]
    monkeypatch.setattr(voiceover, "ON_WINDOWS", True)
    monkeypatch.setattr(voiceover, "dshow_microphones",
                        lambda: recorder.parse_dshow(DSHOW_LISTING))
    assert voiceover.microphones()[1:] == [("Microphone (Realtek(R) Audio)",) * 2,
                                           ("Casque (USB Audio)",) * 2]
    cmd = voiceover.command("default", "v.wav")
    assert cmd[cmd.index("-f") + 1] == "dshow"
    assert cmd[cmd.index("-i") + 1] == "audio=Microphone (Realtek(R) Audio)"
    cmd = voiceover.command("Casque (USB Audio)", "v.wav")
    assert cmd[cmd.index("-i") + 1] == "audio=Casque (USB Audio)"


def test_command_on_windows(monkeypatch):
    monkeypatch.setattr(recorder, "ON_WINDOWS", True)
    monkeypatch.setattr(recorder, "recording_encoder", lambda: recorder.SOFTWARE_ENCODER)
    monkeypatch.setattr(recorder, "dshow_devices",
                        lambda kind: recorder.parse_dshow(DSHOW_LISTING, kind))
    # repli gdigrab (ffmpeg sans ddagrab)
    monkeypatch.setattr(recorder, "windows_grabber", lambda: "gdigrab")
    cmd = command(RecordOptions(geometry=(1920, 0, 1281, 720), microphone=True,
                                webcam="Integrated Camera"), "out.mp4")
    line = " ".join(cmd)
    assert "-f gdigrab" in line and "-i desktop" in line
    assert "-offset_x 1920 -offset_y 0 -video_size 1280x720" in line
    assert "-i audio=Microphone (Realtek(R) Audio)" in line
    assert "-i video=Integrated Camera" in line and "out.webcam-brut.mkv" in line
    assert "x11grab" not in line and "pulse" not in line and "+faststart out.mp4" in line
    zone = " ".join(command(RecordOptions(source="region", geometry=(1920, 0, 2560, 1440),
                                          region=(100, 50, 641, 360), microphone=False),
                            "z.mp4"))
    assert "-offset_x 2020 -offset_y 50 -video_size 640x360" in zone
    silent = " ".join(command(RecordOptions(microphone=False), "x.mp4"))
    assert "dshow" not in silent and "-c:a" not in silent

    # ddagrab : écran choisi, pixels réels, images à rapatrier de la carte graphique
    monkeypatch.setattr(recorder, "windows_grabber", lambda: "ddagrab")
    line = " ".join(command(RecordOptions(screen_index=1, microphone=False), "d.mp4"))
    assert "-f lavfi -i ddagrab=output_idx=1:framerate=30:draw_mouse=1" in line
    assert "[0:v]hwdownload,format=bgra,setpts=" in line and "gdigrab" not in line
    zone = " ".join(command(RecordOptions(source="region", region=(10, 20, 301, 200),
                                          microphone=False), "z.mp4"))
    assert ":offset_x=10:offset_y=20:video_size=300x200" in zone

    # fenêtre : la zone qu'elle occupe sur son écran (filmée seule, elle sortait noire),
    # par ddagrab (fluide) ; ici sur le second écran, à droite du premier
    monkeypatch.setattr(recorder, "window_rect", lambda title: (2020, 80, 801, 600))
    monkeypatch.setattr(recorder, "monitors", lambda: [(0, 0, 1920, 1080),
                                                       (1920, 0, 2560, 1440)])
    window = " ".join(command(RecordOptions(source="window", window_title="Bloc-notes",
                                            microphone=False), "w.mp4"))
    assert "ddagrab=output_idx=1:" in window
    assert ":offset_x=100:offset_y=80:video_size=800x600" in window
    monkeypatch.setattr(recorder, "windows_grabber", lambda: "gdigrab")  # sans ddagrab
    window = " ".join(command(RecordOptions(source="window", window_title="Bloc-notes",
                                            microphone=False), "w.mp4"))
    assert "-f gdigrab" in window and "-i desktop" in window
    assert "-offset_x 2020 -offset_y 80 -video_size 800x600" in window
    monkeypatch.setattr(recorder, "window_rect", lambda title: None)  # fenêtre introuvable
    window = " ".join(command(RecordOptions(source="window", window_title="Bloc-notes",
                                            microphone=False), "w.mp4"))
    assert "-i title=Bloc-notes" in window
    # micro choisi
    chosen = " ".join(command(RecordOptions(microphone_device="Casque USB"), "m.mp4"))
    assert "-i audio=Casque USB" in chosen

    # son de l'ordinateur : entrée « Mixage stéréo » si Windows la propose
    assert not recorder.can_record_system_audio()
    listing = DSHOW_LISTING + '[dshow @ 0000] "Mixage stéréo (Realtek(R) Audio)" (audio)\n'
    monkeypatch.setattr(recorder, "dshow_devices",
                        lambda kind: recorder.parse_dshow(listing, kind))
    assert recorder.can_record_system_audio()
    both = " ".join(command(RecordOptions(microphone=True, system_audio=True), "s.mp4"))
    assert "-i audio=Mixage stéréo (Realtek(R) Audio)" in both and "amix=inputs=2" in both
    assert recorder.can_select_region() and recorder.can_pick_window()


def test_physical_region():
    from PyQt6.QtCore import QRect

    from montar.ui.dialogs.recorder import physical_region

    class Screen:
        def devicePixelRatio(self):
            return 1.5

    assert physical_region(Screen(), QRect(10, 20, 200, 100)) == (15, 30, 300, 150)


def test_on_monitor():
    screens = [(0, 0, 1920, 1080), (-1280, 0, 1280, 1024)]
    assert recorder.on_monitor((100, 100, 401, 300), screens) == (0, (100, 100, 400, 300))
    # fenêtre qui dépasse de l'écran de gauche : seule la partie visible est filmée
    assert recorder.on_monitor((-1000, 800, 800, 400), screens) == (1, (280, 800, 800, 224))
    assert recorder.on_monitor((5000, 0, 100, 100), screens) is None


def test_webcam_parts_and_processed_layer(monkeypatch):
    monkeypatch.setattr(recorder, "ON_WINDOWS", False)
    base = dict(geometry=(0, 0, 1280, 720), microphone=False, webcam="/dev/video0")
    # micro choisi (PulseAudio)
    mic = " ".join(command(RecordOptions(geometry=(0, 0, 640, 360),
                                         microphone_device="alsa_input.usb"), "m.mp4"))
    assert "-f pulse -i alsa_input.usb" in mic
    # la disposition ne change plus la commande : elle sert dans la timeline
    plain = command(RecordOptions(**base, webcam_position="split_left", webcam_shape="round"),
                    "/tmp/rec.mp4")
    assert "overlay" not in " ".join(plain) and "geq" not in " ".join(plain)
    assert "/tmp/rec.mp4" in plain and recorder.camera_part("/tmp/rec.mp4") in plain
    assert "fps=2,scale=8:8,format=gray[campix]" in " ".join(plain)
    options = RecordOptions(**base, webcam_background="blur")
    live = " ".join(command(options, "/tmp/rec.mp4", live_masks=True))  # détourage en direct
    assert "split=2[camfile][camtap]" in live and "scale=256:144,format=rgb24" in live
    assert live.endswith("-f rawvideo pipe:1")
    blur = " ".join(recorder.layer_command(options, "c.mkv", "m.mkv", "w.mp4", []))
    assert "alphamerge" in blur and "gblur=sigma=18" in blur and "libx264" in blur
    removed = " ".join(recorder.layer_command(
        dataclasses.replace(options, webcam_background="remove"), "c.mkv", "m.mkv", "w.webm",
        recorder.VP9_ALPHA))
    assert "alphamerge" in removed and "gblur=sigma=18" not in removed
    assert "yuva420p" in removed and "libvpx-vp9" in removed


def test_pactl_sources():
    listing = """Source #0
	Name: alsa_output.pci.analog-stereo.monitor
	Description: Monitor of Built-in Audio
Source #1
	Name: alsa_input.usb-Blue.analog-stereo
	Description: Blue Yeti
"""
    assert recorder.parse_pactl_sources(listing) == [("alsa_input.usb-Blue.analog-stereo",
                                                      "Blue Yeti")]


def _person(np):
    """Silhouette simple (cheveux, visage, cou, épaules) sur un fond dégradé, 256 × 144."""
    h, w = 144, 256
    y, x = np.mgrid[0:h, 0:w]
    image = np.zeros((h, w, 3), np.uint8)
    image[...] = np.stack([127 + x * 0.3, 156 + y * 0.1, 176 - x * 0.1], -1).astype(np.uint8)
    image[30:90, 20:60] = (90, 62, 43)  # meuble
    shoulders = ((x - 128) / 50) ** 2 + ((y - 140) / 45) ** 2 <= 1
    face = ((x - 128) / 25) ** 2 + ((y - 59) / 31) ** 2 <= 1
    neck = (abs(x - 128) <= 12) & (y >= 80) & (y <= 104)
    hair = ((x - 128) / 28) ** 2 + ((y - 35) / 15) ** 2 <= 1
    image[shoulders] = (43, 76, 126)
    image[neck | face] = (224, 177, 140)
    image[hair] = (59, 42, 26)
    return image


def test_segmenter_finds_the_person():
    np = pytest.importorskip("numpy")
    from montar.media.segment import Segmenter

    seg = Segmenter()
    assert (seg.width, seg.height) == (256, 144)
    mask = seg.mask(_person(np))
    assert mask.shape == (144, 256) and 0 <= mask.min() and mask.max() <= 1
    assert mask[60, 128] > 0.8 and mask[125, 128] > 0.8  # visage, épaules
    assert mask[10, 240] < 0.2 and mask[60, 40] < 0.2  # fond, meuble


def _webcam_file(np, tmp_path, path):
    frame = tmp_path / "person.raw"
    frame.write_bytes(_person(np).tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", "256x144", "-i", str(frame), "-vf", "loop=24:1,setpts=N/25/TB",
                    "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)


@pytest.mark.parametrize("background", ["remove", "blur"])
def test_finisher_makes_the_webcam_layer(tmp_path, background):
    np = pytest.importorskip("numpy")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg absent")
    target = tmp_path / "rec.mp4"
    camera = recorder.camera_part(str(target))
    _webcam_file(np, tmp_path, camera)
    options = RecordOptions(webcam="cam", webcam_background=background, fps=25)
    job = recorder.Finisher(options, target, 1.0)
    job.start()
    assert job.wait(120) and not job.error, job.error
    assert job.layer is not None and job.layer.exists() and not Path(camera).exists()
    assert not Path(recorder.mask_part(str(target))).exists()
    assert _duration(job.layer) == pytest.approx(1.0, abs=0.3)
    if background == "blur":
        assert job.layer.suffix == ".mp4"
        return
    # fond effacé : vidéo transparente que le moteur relit (personne opaque, fond transparent)
    mlt = pytest.importorskip("mlt7")
    from montar.engine.base import Canvas
    from montar.engine.mlt_engine import _ensure_factory, _profile

    _ensure_factory()
    producer = mlt.Producer(_profile(Canvas(256, 144, 25)), str(job.layer))
    frame = producer.get_frame()
    frame.set("consumer.rescale", "none")
    image = frame.get_image(mlt.mlt_image_rgba, 256, 144)
    alpha = lambda x, y: image[(y * 256 + x) * 4 + 3]  # noqa: E731
    assert alpha(128, 60) > 200 and alpha(240, 10) < 60


def test_finisher_keeps_the_raw_webcam_on_failure(tmp_path):
    target = tmp_path / "rec.mp4"
    camera = Path(recorder.camera_part(str(target)))
    camera.write_bytes(b"pas une video")
    job = recorder.Finisher(RecordOptions(webcam="cam", webcam_background="remove"), target,
                            1.0)
    job.start()
    assert job.wait(60) and job.error
    assert job.layer == Path(recorder.webcam_layer(str(target), "mkv")) and job.layer.exists()


def test_parse_xwininfo():
    listing = """xwininfo: Window id: 0x3a0000a "Terminal"
  Absolute upper-left X:  120
  Absolute upper-left Y:  64
  Width: 801
  Height: 600
"""
    assert recorder.parse_xwininfo(listing) == ("0x3a0000a", (120, 64, 801, 600))
    assert recorder.parse_xwininfo("") == ("", None)


def test_level_meter_keeps_last_seconds(tmp_path):
    import wave

    meter = recorder.LevelMeter.__new__(recorder.LevelMeter)
    meter._samples = bytearray(b"\x00\x10" * recorder.LevelMeter.RATE)  # 1 s
    assert meter.seconds == 1.0
    assert meter.save_wav(tmp_path / "t.wav")
    with wave.open(str(tmp_path / "t.wav")) as w:
        assert w.getframerate() == recorder.LevelMeter.RATE and w.getnframes() == 16000
