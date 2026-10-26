# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran (F-MED-06)."""
import shutil
import subprocess
import time

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
    assert "amix=inputs=2" in line and "overlay=W-w-24:H-h-24" in line
    assert "-f v4l2 -i /dev/video0" in line and cmd[-1] == "out.mp4"
    region = " ".join(command(RecordOptions(source="region", microphone=False), "x.mp4"))
    assert "-select_region 1" in region and "pulse" not in region and "-c:a" not in region
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
    assert "-i video=Integrated Camera" in line and "overlay=W-w-24:H-h-24" in line
    assert "x11grab" not in line and "pulse" not in line and cmd[-1] == "out.mp4"
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
    assert "[0:v]hwdownload,format=bgra,scale=" in line and "gdigrab" not in line
    zone = " ".join(command(RecordOptions(source="region", region=(10, 20, 301, 200),
                                          microphone=False), "z.mp4"))
    assert ":offset_x=10:offset_y=20:video_size=300x200" in zone

    # fenêtre : par son titre
    window = " ".join(command(RecordOptions(source="window", window_title="Bloc-notes",
                                            microphone=False), "w.mp4"))
    assert "-f gdigrab" in window and "-i title=Bloc-notes" in window

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
