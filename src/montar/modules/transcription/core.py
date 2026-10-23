# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcription locale de la parole (F-TXT-06) avec Whisper.

Trois moteurs sont reconnus, dans cet ordre : le module Python `faster_whisper`, le module
Python `whisper` (openai-whisper) et le programme whisper.cpp (`whisper-cli`). Aucun n'est
fourni : l'utilisateur en installe un ; le modèle est téléchargé une fois par le moteur,
ensuite tout se fait sans connexion."""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MODELS = ("tiny", "base", "small", "medium")
MAX_CHARS = 84  # deux lignes de sous-titre environ
INSTALL_HINT = "pip install --user faster-whisper"


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Segment:
    start: float  # secondes, depuis le début de l'extrait
    end: float
    text: str


class Backend:
    name = ""

    def available(self) -> bool:
        raise NotImplementedError

    def transcribe(self, wav: Path, model: str, language: str,
                   progress: Callable[[float], None],
                   cancelled: Callable[[], bool]) -> list[Segment]:
        raise NotImplementedError


class FasterWhisper(Backend):
    name = "faster-whisper"

    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(self, wav, model, language, progress, cancelled):
        from faster_whisper import WhisperModel

        engine = WhisperModel(model, device="cpu", compute_type="int8")
        segments, info = engine.transcribe(str(wav), language=language or None,
                                           vad_filter=True)
        result = []
        for seg in segments:  # générateur : la transcription avance au fil de la boucle
            if cancelled():
                raise TranscriptionError("annulé")
            result.append(Segment(float(seg.start), float(seg.end), seg.text.strip()))
            if info.duration:
                progress(min(1.0, seg.end / info.duration))
        return result


class OpenAIWhisper(Backend):
    name = "openai-whisper"

    def available(self) -> bool:
        # « whisper » est aussi le nom d'une base de données sans rapport (python3-whisper)
        try:
            return importlib.util.find_spec("whisper") is not None and \
                importlib.util.find_spec("whisper.transcribe") is not None
        except (ImportError, ValueError):
            return False

    def transcribe(self, wav, model, language, progress, cancelled):
        import whisper

        result = whisper.load_model(model).transcribe(str(wav), language=language or None,
                                                      fp16=False)
        if cancelled():
            raise TranscriptionError("annulé")
        return [Segment(float(s["start"]), float(s["end"]), str(s["text"]).strip())
                for s in result.get("segments", [])]


def _ggml_dirs() -> list[Path]:
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return [data / "montar" / "whisper", data / "whisper.cpp", Path("/usr/share/whisper.cpp")]


class WhisperCpp(Backend):
    """Programme whisper.cpp ; modèles `ggml-<taille>.bin` cherchés dans
    ~/.local/share/montar/whisper (ou indiqués par WHISPER_CPP_MODEL)."""

    name = "whisper.cpp"
    PROGRAMS = ("whisper-cli", "whisper-cpp", "whisper.cpp")

    def program(self) -> str | None:
        return next((p for p in map(shutil.which, self.PROGRAMS) if p), None)

    def model_file(self, model: str) -> Path | None:
        forced = os.environ.get("WHISPER_CPP_MODEL")
        if forced and Path(forced).is_file():
            return Path(forced)
        for folder in _ggml_dirs():
            for name in (f"ggml-{model}.bin", f"ggml-{model}.en.bin"):
                if (folder / name).is_file():
                    return folder / name
        return None

    def available(self) -> bool:
        return self.program() is not None and any(self.model_file(m) for m in MODELS)

    def transcribe(self, wav, model, language, progress, cancelled):
        from montar.core.subtitles import parse_srt

        program = self.program()
        weights = self.model_file(model) or next(
            (f for f in map(self.model_file, MODELS) if f), None)
        if program is None or weights is None:
            raise TranscriptionError("whisper.cpp ou son modèle est introuvable")
        out = wav.with_suffix("")
        cmd = [program, "-m", str(weights), "-f", str(wav), "-osrt", "-of", str(out),
               "-l", language or "auto"]
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                   text=True)
        assert process.stderr is not None
        for line in process.stderr:
            if cancelled():
                process.kill()
                process.wait()
                raise TranscriptionError("annulé")
            found = re.search(r"progress\s*=\s*(\d+)%", line)
            if found:
                progress(int(found.group(1)) / 100)
        if process.wait() != 0:
            raise TranscriptionError("whisper.cpp a échoué")
        fps = 1000  # sous-titres relus au millième de seconde
        subs = parse_srt(Path(f"{out}.srt").read_text(encoding="utf-8"), fps)
        return [Segment(s.start / fps, s.end / fps, s.text) for s in subs]


BACKENDS: list[Backend] = [FasterWhisper(), OpenAIWhisper(), WhisperCpp()]


def backend() -> Backend | None:
    return next((b for b in BACKENDS if b.available()), None)


def extract_audio(source: str, start: float, duration: float, target: Path) -> None:
    """Extrait le passage en WAV mono 16 kHz, le format attendu par Whisper."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise TranscriptionError("ffmpeg est introuvable")
    result = subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{start:.3f}", "-t",
                             f"{duration:.3f}", "-i", source, "-vn", "-ac", "1", "-ar",
                             "16000", str(target)], capture_output=True, text=True,
                            timeout=600)
    if result.returncode != 0 or not target.exists():
        raise TranscriptionError(result.stderr.strip() or "extraction du son impossible")


def split_long(segments: list[Segment], max_chars: int = MAX_CHARS) -> list[Segment]:
    """Coupe les phrases trop longues à l'écran, entre deux mots, au prorata des lettres."""
    result = []
    for seg in segments:
        text = " ".join(seg.text.split())
        if not text:
            continue
        if len(text) <= max_chars:
            result.append(Segment(seg.start, seg.end, text))
            continue
        chunks, line = [], ""
        for word in text.split(" "):
            if line and len(line) + 1 + len(word) > max_chars:
                chunks.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        chunks.append(line)
        total = sum(len(c) for c in chunks)
        t = seg.start
        for chunk in chunks:
            length = (seg.end - seg.start) * len(chunk) / total
            result.append(Segment(t, t + length, chunk))
            t += length
    return result


def to_timeline(segments: list[Segment], clip_start: int, clip_duration: int, speed: float,
                fps: int) -> list[tuple[int, int, str]]:
    """(début, fin, texte) en images de la timeline, bornés au clip."""
    result = []
    end_of_clip = clip_start + clip_duration
    for seg in segments:
        a = clip_start + round(seg.start * fps / speed)
        b = min(end_of_clip, clip_start + round(seg.end * fps / speed))
        if b > a and a < end_of_clip:
            result.append((a, max(a + 1, b), seg.text))
    return result


def transcribe_clip(source: str, source_in: int, frames: int, speed: float, fps: int,
                    model: str, language: str, progress: Callable[[float], None],
                    cancelled: Callable[[], bool]) -> list[Segment]:
    engine = backend()
    if engine is None:
        raise TranscriptionError(f"aucun moteur Whisper : {INSTALL_HINT}")
    with tempfile.TemporaryDirectory(prefix="montar-whisper-") as tmp:
        wav = Path(tmp) / "voix.wav"
        extract_audio(source, source_in / fps, frames * speed / fps, wav)
        progress(0.05)
        segments = engine.transcribe(wav, model, language,
                                     lambda r: progress(0.05 + 0.95 * r), cancelled)
    progress(1.0)
    return split_long(segments)
