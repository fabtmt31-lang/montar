# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistreur d'écran (F-MED-06)."""
import shutil
import subprocess
import time

import pytest

from montar.media import recorder
from montar.media.recorder import RecordOptions, command


def test_command():
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
    assert "Windows" in recorder.session_problem() or "ffmpeg" in recorder.session_problem()


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

    assert voiceover.parse_dshow(DSHOW_LISTING) == ["Microphone (Realtek(R) Audio)",
                                                    "Casque (USB Audio)"]
    monkeypatch.setattr(voiceover, "ON_WINDOWS", True)
    monkeypatch.setattr(voiceover, "dshow_microphones",
                        lambda: voiceover.parse_dshow(DSHOW_LISTING))
    assert voiceover.microphones()[1:] == [("Microphone (Realtek(R) Audio)",) * 2,
                                           ("Casque (USB Audio)",) * 2]
    cmd = voiceover.command("default", "v.wav")
    assert cmd[cmd.index("-f") + 1] == "dshow"
    assert cmd[cmd.index("-i") + 1] == "audio=Microphone (Realtek(R) Audio)"
    cmd = voiceover.command("Casque (USB Audio)", "v.wav")
    assert cmd[cmd.index("-i") + 1] == "audio=Casque (USB Audio)"
