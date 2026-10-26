# SPDX-License-Identifier: GPL-3.0-or-later
"""Analyse et export avec la finition pro : mesure du projet (loudness, plans), rendu avec
le gain calculé, son 5.1 ou pistes séparées, puis vérification du fichier et rapport."""
from __future__ import annotations

import dataclasses
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from montar.core.mastering import DESTINATIONS, Mastering
from montar.engine import mastering as mst
from montar.engine.base import Canvas, Engine, ExportJob, TimelineSpec, TrackSpec
from montar.engine.export import ExportSettings
from montar.i18n import _

log = logging.getLogger(__name__)

SHOT_SIZE = 160  # largeur des images analysées pour l'harmonisation
THUMB_SIZE = (96, 54)
SPECTRUM_BANDS = 48
SPECTRUM_RANGE = (30.0, 16000.0)
CURVE_POINTS = 400  # points de la courbe de loudness gardés pour l'affichage
SURROUND_FORMATS = {"mp4": ("aac", "384k"), "mov": ("aac", "384k"), "aac": ("aac", "384k"),
                    "webm": ("libopus", "256k"), "wav": ("pcm_s24le", "")}
LEGAL_RANGE = (16, 235)  # luminance vidéo « légale » (plage TV, 8 bits)
STEM_NAMES = {"dialog": "Dialogues", "music": "Musique et effets"}


class Cancelled(Exception):
    pass


@dataclass
class Loudness:
    integrated: float  # LUFS
    true_peak: float  # dBTP
    lra: float  # LU
    curve: list[float] = field(default_factory=list)  # loudness à court terme (3 s)


@dataclass
class Shot:
    key: str  # identifiant du clip
    start: int
    stats: list[float]  # moyenne et écart type des canaux
    thumb: bytes = b""  # vignette RGBA (THUMB_SIZE)
    deviation: float = 0.0  # écart avec la référence


@dataclass
class Analysis:
    loudness: Loudness | None = None  # son après la chaîne, avant le gain et le limiteur
    gain_db: float = 0.0
    target: float = -14.0
    dialog_lufs: float | None = None
    music_lufs: float | None = None
    spectrum: list[float] = field(default_factory=list)  # dB par bande, maximum à 0
    clipped: float | None = None  # part des pixels écrêtés, avant la finition
    shots: list[Shot] = field(default_factory=list)
    reference: str = ""
    matches: dict[str, list[float]] = field(default_factory=dict)

    @property
    def spread(self) -> float:
        """Écart moyen des plans à la référence."""
        others = [s.deviation for s in self.shots if s.key != self.reference]
        return sum(others) / len(others) if others else 0.0


@dataclass
class ReportRow:
    label: str
    target: str
    result: str
    ok: bool


# --- outils FFmpeg -----------------------------------------------------------------------

def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _number(pattern: str, text: str) -> float | None:
    found = re.findall(pattern, text)
    if not found:
        return None
    value = found[-1]
    return -math.inf if value.startswith("-inf") else float(value)


def parse_ebur128(stderr: str) -> Loudness | None:
    """Résumé et courbe à court terme d'une mesure `ebur128` de FFmpeg."""
    summary = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else ""
    integrated = _number(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    if integrated is None:
        return None
    lra = _number(r"LRA:\s+(-?[\d.]+) LU", summary) or 0.0
    peak = _number(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    curve = [max(-70.0, float(v)) for v in re.findall(r"\bS:\s*(-?[\d.]+)", stderr)]
    if len(curve) > CURVE_POINTS:
        step = len(curve) / CURVE_POINTS
        curve = [curve[int(i * step)] for i in range(CURVE_POINTS)]
    return Loudness(integrated, peak if peak is not None and math.isfinite(peak) else -70.0,
                    lra, curve)


def measure_loudness(path: str) -> Loudness | None:
    """Loudness intégrée (EBU R128), crête vraie, plage dynamique et courbe d'un fichier."""
    done = subprocess.run([_ffmpeg(), "-nostats", "-hide_banner", "-i", path,
                           "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True, errors="replace")
    return parse_ebur128(done.stderr)


def spectrum(path: str) -> list[float]:
    """Spectre moyen (dB, maximum à 0) en bandes logarithmiques, lu par blocs."""
    import numpy as np

    rate, size = 32000, 8192
    proc = subprocess.Popen([_ffmpeg(), "-v", "error", "-i", path, "-ac", "1", "-ar", str(rate),
                             "-f", "f32le", "-"], stdout=subprocess.PIPE)
    power = np.zeros(size // 2 + 1)
    window = np.hanning(size)
    count = 0
    try:
        while True:
            data = proc.stdout.read(size * 4)
            if len(data) < size * 4:
                break
            block = np.frombuffer(data, dtype=np.float32) * window
            power += np.abs(np.fft.rfft(block)) ** 2
            count += 1
    finally:
        proc.stdout.close()
        proc.wait()
    if count == 0:
        return []
    freqs = np.fft.rfftfreq(size, 1 / rate)
    edges = np.geomspace(*SPECTRUM_RANGE, SPECTRUM_BANDS + 1)
    bands = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = (freqs >= lo) & (freqs < hi)
        value = power[sel].mean() if sel.any() else 0.0
        bands.append(10 * math.log10(value / count + 1e-20))
    top = max(bands)
    return [round(max(-60.0, b - top), 2) for b in bands]


def video_levels(path: str, duration: float, samples: int = 12) -> tuple[float, float] | None:
    """Part des pixels dont la luminance est dans la plage légale, et part des pixels
    écrêtés, sur quelques images du fichier exporté."""
    import numpy as np

    w, h = 160, 90
    rate = max(0.05, samples / max(0.1, duration))
    done = subprocess.run([_ffmpeg(), "-v", "error", "-i", path, "-an", "-vf",
                           f"fps={rate:.4f},scale={w}:{h}", "-frames:v", str(samples),
                           "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"], capture_output=True)
    frame = w * h * 3 // 2
    n = len(done.stdout) // frame
    if done.returncode != 0 or n == 0:
        return None
    lumas = np.concatenate([np.frombuffer(done.stdout, dtype=np.uint8)[i * frame:i * frame + w * h]
                            for i in range(n)])
    legal = float(((lumas >= LEGAL_RANGE[0]) & (lumas <= LEGAL_RANGE[1])).mean())
    clipped = float(((lumas >= 234) | (lumas <= 17)).mean())
    return legal, clipped


def probe_color(path: str) -> str:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    done = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=color_transfer", "-of", "default=nw=1:nk=1", path],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


def upmix_command(dialog: str, music: str, target: str) -> list[str]:
    """5.1 à partir des stems (fichier WAV) : dialogues au centre, musique et effets à
    l'avant et, à −6 dB, à l'arrière, basses de la musique sur le caisson."""
    graph = (
        "[0:a]aresample=48000,pan=mono|c0=0.5*c0+0.5*c1[fc];"
        "[1:a]aresample=48000,asplit=3[m1][m2][m3];"
        "[m1]channelsplit=channel_layout=stereo[fl][fr];"
        "[m2]pan=mono|c0=0.5*c0+0.5*c1,lowpass=f=120[lfe];"
        "[m3]pan=stereo|c0=0.5*c0|c1=0.5*c1,channelsplit=channel_layout=stereo[bl][br];"
        "[fl][fr][fc][lfe][bl][br]join=inputs=6:channel_layout=5.1:"
        "map=0.0-FL|1.0-FR|2.0-FC|3.0-LFE|4.0-BL|5.0-BR[out]")
    return [_ffmpeg(), "-v", "error", "-y", "-i", dialog, "-i", music, "-filter_complex", graph,
            "-map", "[out]", "-c:a", "pcm_f32le", target]


def surround_command(source: str, surround: str, target: str, fmt: str, gain_db: float,
                     true_peak: float, video: bool) -> list[str]:
    """Fichier final : image de `source` (copiée), son 5.1 amené à la loudness visée
    (`gain_db`) puis limité sur les six canaux."""
    codec, bitrate = SURROUND_FORMATS[fmt]
    limit = mst.limiter_filter(true_peak)[1]["av.limit"]
    chain = f"volume={gain_db:.2f}dB,alimiter=limit={limit}:level=0:attack=5:release=60"
    cmd = [_ffmpeg(), "-v", "error", "-y"]
    if video:
        cmd += ["-i", source]
    cmd += ["-i", surround, "-filter_complex", f"[{1 if video else 0}:a]{chain}[out]"]
    if video:
        cmd += ["-map", "0:v", "-c:v", "copy"]
    cmd += ["-map", "[out]", "-c:a", codec]
    if bitrate:
        cmd += ["-b:a", bitrate]
    if codec == "libopus":
        cmd += ["-mapping_family", "1"]
    if fmt in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd += ["-shortest", target]
    return cmd


def _run(cmd: list[str]) -> None:
    done = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        raise RuntimeError((done.stderr.strip().splitlines() or ["ffmpeg"])[-1])


# --- rendus intermédiaires ---------------------------------------------------------------

class _Runner:
    """Enchaîne des exports du moteur dans le fil courant, annulables."""

    def __init__(self, engine: Engine, cancelled: Callable[[], bool],
                 progress: Callable[[float], None]) -> None:
        self.engine, self.cancelled, self.progress = engine, cancelled, progress
        self.current: ExportJob | None = None

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled

    def export(self, spec: TimelineSpec, settings: ExportSettings) -> ExportJob:
        self.check()
        job = self.engine.export(spec, settings)
        self.current = job
        job.start()
        while not job.finished:
            if self.cancelled():
                job.cancel()
            job.wait(0.2)
            self.progress(job.progress)
        self.current = None
        self.check()
        if job.error:
            raise RuntimeError(job.error)
        return job

    def wav(self, spec: TimelineSpec, path: str, fps: int, span: tuple[int, int]) -> str:
        self.export(spec, ExportSettings(path, "wav", "", 0, 0, fps, range_start=span[0],
                                         range_end=span[1], subtitles="none"))
        return path


def _single_clip(spec: TimelineSpec, track: TrackSpec, index: int) -> TimelineSpec:
    w, h = spec.canvas.width, spec.canvas.height
    size = (SHOT_SIZE, max(2, round(SHOT_SIZE * h / w / 2) * 2))
    clip = dataclasses.replace(track.clips[index], start=0, fade_in=0, fade_out=0)
    return TimelineSpec(Canvas(*size, spec.canvas.fps),
                        (TrackSpec("video", False, False, (clip,)),))


def analyse_shots(engine: Engine, spec: TimelineSpec, reference: str,
                  check: Callable[[], None] = lambda: None) -> tuple[list[Shot], str]:
    """Statistiques de couleur de chaque plan (clip vidéo ou image des pistes vidéo), seul
    et avec ses propres réglages ; renvoie aussi la référence retenue."""
    shots: list[Shot] = []
    longest = (0, "")
    for track in spec.tracks:
        if track.kind != "video" or track.hidden or track.role != "video":
            continue
        for i, clip in enumerate(track.clips):
            if clip.kind not in ("video", "image") or not clip.key:
                continue
            check()
            single = _single_clip(spec, track, i)
            w, h = single.canvas.width, single.canvas.height
            try:
                source = engine.build(single)
                try:
                    frames = sorted({max(0, round(clip.duration * k)) for k in (0.2, 0.5, 0.8)})
                    images = [source.render(min(f, clip.duration - 1), w, h) for f in frames]
                finally:
                    source.close()
            except Exception as exc:  # plan illisible : ignoré
                log.warning("analyse du plan %s impossible : %s", clip.key, exc)
                continue
            stats = [sum(v) / len(images) for v in zip(*(mst.frame_stats(img, w, h)
                                                         for img in images), strict=True)]
            shots.append(Shot(clip.key, clip.start, stats, _thumb(images[len(images) // 2], w, h)))
            if clip.duration > longest[0]:
                longest = (clip.duration, clip.key)
    shots.sort(key=lambda s: s.start)
    if not any(s.key == reference for s in shots):
        reference = longest[1]
    ref = next((s for s in shots if s.key == reference), None)
    if ref is not None:
        for s in shots:
            s.deviation = mst.deviation(ref.stats, s.stats)
    return shots, reference


def _thumb(rgba: bytes, w: int, h: int) -> bytes:
    import numpy as np

    tw, th = THUMB_SIZE
    image = np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4)
    ys = (np.arange(th) * h // th).clip(0, h - 1)
    xs = (np.arange(tw) * w // tw).clip(0, w - 1)
    return image[ys][:, xs].tobytes()


def _clipped(engine: Engine, spec: TimelineSpec, span: tuple[int, int]) -> float | None:
    w, h = spec.canvas.width, spec.canvas.height
    sw, sh = SHOT_SIZE, max(2, round(SHOT_SIZE * h / w / 2) * 2)
    first, last = span[0], (span[1] or spec.length)
    if last <= first:
        return None
    try:
        source = engine.build(spec)
        try:
            values = [mst.clipped_fraction(source.render(first + (last - first) * k // 9, sw, sh),
                                           sw, sh) for k in range(1, 9)]
        finally:
            source.close()
    except Exception as exc:
        log.warning("analyse de l'image impossible : %s", exc)
        return None
    return sum(values) / len(values)


def analyse(engine: Engine, spec: TimelineSpec, mastering: Mastering, *, lut: str = "",
            span: tuple[int, int] = (0, 0), video: bool = True, audio: bool = True,
            full: bool = False, workdir: str | None = None,
            cancelled: Callable[[], bool] = lambda: False,
            progress: Callable[[float], None] = lambda _p: None) -> Analysis:
    """Première passe : plans à harmoniser et loudness du mixage passé par la chaîne de
    mastering (sans gain ni limiteur). `full` ajoute ce qu'affiche la fenêtre Finition :
    spectre, équilibre voix / musique et pixels écrêtés."""
    result = Analysis(target=mastering.audio.lufs)
    runner = _Runner(engine, cancelled, lambda p: progress(0.3 + 0.6 * p))
    if video:
        result.shots, result.reference = analyse_shots(
            engine, spec, mastering.video.match_reference, runner.check)
        ref = next((s for s in result.shots if s.key == result.reference), None)
        if ref is not None:
            result.matches = {s.key: mst.match_values(ref.stats, s.stats)
                              for s in result.shots}
        if full:
            result.clipped = _clipped(engine, spec, span)
    progress(0.3)
    if audio and mst.has_sound(spec):
        own = workdir is None
        folder = workdir or tempfile.mkdtemp(prefix="montar-finition-")
        try:
            chain = mst.apply_master(spec, mastering, limiter=False, video=False)
            mix = runner.wav(chain, os.path.join(folder, "analyse.wav"), spec.canvas.fps, span)
            result.loudness = measure_loudness(mix)
            if result.loudness is not None:
                result.gain_db = mst.loudness_gain(result.loudness.integrated,
                                                   mastering.audio.lufs)
            if full:
                result.spectrum = spectrum(mix)
                if mst.has_sound(spec, "dialog") and mst.has_sound(spec, "music"):
                    for stem in mst.STEMS:
                        part = mst.apply_master(spec, mastering, limiter=False, video=False,
                                                stem=stem)
                        found = measure_loudness(runner.wav(
                            part, os.path.join(folder, f"{stem}.wav"), spec.canvas.fps, span))
                        value = found.integrated if found else None
                        if stem == "dialog":
                            result.dialog_lufs = value
                        else:
                            result.music_lufs = value
        finally:
            if own:
                shutil.rmtree(folder, ignore_errors=True)
    progress(1.0)
    return result


# --- export complet ----------------------------------------------------------------------

def _db(value: float) -> str:
    return f"{value:+.1f}".replace("-", "−").replace(".", ",") if value > -69 else "−∞"


def _plain(value: float) -> str:
    return f"{value:.1f}".replace("-", "−").replace(".", ",")


class MasteredExport(ExportJob):
    """Export avec la finition, en trois phases : analyse, rendu (puis 5.1 ou stems),
    vérification. `phase` et `progress` sont lus par l'interface."""

    PHASES = (("analyse", 0.15), ("render", 0.75), ("check", 0.10))

    def __init__(self, engine: Engine, spec: TimelineSpec, settings: ExportSettings,
                 mastering: Mastering, lut: str = "", project_name: str = "") -> None:
        self.engine, self.spec, self.settings = engine, spec, settings
        self.mastering, self.lut, self.project_name = mastering, lut, project_name
        self.first = settings.range_start
        last = settings.range_end or spec.length
        self.total = max(1, min(last, spec.length) - self.first)
        self.phase = "analyse"
        self.analysis: Analysis | None = None
        self.report: list[ReportRow] = []
        self.notes: list[str] = []
        self.report_path = ""
        self.extra_files: list[str] = []  # stems écrits à côté de la vidéo
        self._fraction = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- état ---------------------------------------------------------------------------

    @property
    def progress(self) -> float:
        if self.finished and not self.error:
            return 1.0
        done = 0.0
        for name, weight in self.PHASES:
            if name == self.phase:
                return min(1.0, done + weight * self._fraction)
            done += weight
        return min(1.0, done)

    def _set_phase(self, name: str) -> None:
        self.phase, self._fraction = name, 0.0

    def _step(self, start: float, span: float) -> Callable[[float], None]:
        def update(p: float) -> None:
            self._fraction = start + span * max(0.0, min(1.0, p))
            self.done = round(self.total * self.progress)
        return update

    # --- cycle --------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="montar-finition", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.finished

    def _run(self) -> None:
        workdir = tempfile.mkdtemp(prefix="montar-finition-")
        try:
            self._export(workdir)
        except Cancelled:
            self.cancelled, self.error = True, "annulé"
        except Exception as exc:  # jamais d'exception hors du fil
            log.exception("export avec finition")
            self.error = str(exc)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            self.finished = True

    def _export(self, workdir: str) -> None:
        s, m = self.settings, self.mastering
        video = not s.audio_only
        audio = s.format != "gif"
        span = (s.range_start, s.range_end)
        cancelled = self._stop.is_set

        self._set_phase("analyse")
        self.analysis = a = analyse(
            self.engine, self.spec, m, lut=self.lut, span=span,
            video=video and m.video.match_shots, audio=audio, workdir=workdir,
            cancelled=cancelled, progress=self._step(0, 1))
        if a.matches:
            m = dataclasses.replace(m, video=dataclasses.replace(m.video, matches=a.matches))
            self.mastering = m

        self._set_phase("render")
        layout = m.audio.layout if audio else "stereo"
        if layout == "surround" and s.format not in SURROUND_FORMATS:
            self.notes.append(_("Le 5.1 n'est pas possible dans ce format : son exporté en "
                                "stéréo."))
            layout = "stereo"
        steps = 1 + (2 if layout in ("surround", "stems") else 0)
        runner = _Runner(self.engine, cancelled, self._step(0, 1 / steps))
        final = mst.apply_master(self.spec, m, gain_db=a.gain_db, lut=self.lut, video=video,
                                 audio=audio)
        settings = dataclasses.replace(s, extra=tuple(mst.consumer_color(m.video).items())) \
            if video and s.format != "gif" and not s.custom else s
        self.used_encoder = runner.export(final, settings).used_encoder
        stems: dict[str, str] = {}
        for k, stem in enumerate(mst.STEMS if layout != "stereo" else ()):
            runner.progress = self._step((k + 1) / steps, 1 / steps)
            part = mst.apply_master(self.spec, m, gain_db=a.gain_db, limiter=False, video=False,
                                    stem=stem)
            stems[stem] = runner.wav(part, os.path.join(workdir, f"{stem}.wav"),
                                     self.spec.canvas.fps, span)
        if layout == "surround":
            target = s.path
            surround = os.path.join(workdir, "surround.wav")
            _run(upmix_command(stems["dialog"], stems["music"], surround))
            found = measure_loudness(surround)
            gain = mst.loudness_gain(found.integrated if found else None, m.audio.lufs)
            tmp = f"{target}.part51{Path(target).suffix}"
            try:
                _run(surround_command(target, surround, tmp, s.format, gain, m.audio.true_peak,
                                      video))
            except RuntimeError:
                Path(tmp).unlink(missing_ok=True)
                raise
            os.replace(tmp, target)
        elif layout == "stems":
            base = Path(s.path)
            for stem, path in stems.items():
                out = base.with_name(f"{base.stem} - {_(STEM_NAMES[stem])}.wav")
                shutil.copyfile(path, out)
                self.extra_files.append(str(out))

        self._set_phase("check")
        self._check(video, audio, layout)
        self._fraction = 1.0

    # --- vérification -------------------------------------------------------------------

    def _check(self, video: bool, audio: bool, layout: str) -> None:
        s, m = self.settings, self.mastering
        target = s.path
        a = m.audio
        if audio:
            found = measure_loudness(target)
            if found is not None and found.integrated > -69:
                tolerance = 1.0
                self.report.append(ReportRow(
                    _("Loudness intégrée"), f"{_plain(a.lufs)} LUFS",
                    f"{_plain(found.integrated)} LUFS",
                    abs(found.integrated - a.lufs) <= tolerance))
                self.report.append(ReportRow(
                    _("Crête vraie"), f"≤ {_plain(a.true_peak)} dBTP",
                    f"{_plain(found.true_peak)} dBTP", found.true_peak <= a.true_peak + 0.2))
                self.report.append(ReportRow(
                    _("Plage dynamique"), "—", f"{_plain(found.lra)} LU", True))
            else:
                self.notes.append(_("Aucun son à mesurer dans le fichier exporté."))
        self._fraction = 0.5
        if video and s.format != "gif":
            seconds = self.total / max(1, s.fps)
            levels = video_levels(target, seconds)
            if levels is not None:
                legal, _clip = levels
                self.report.append(ReportRow(
                    _("Niveaux vidéo légaux"), "16–235", f"{legal * 100:.1f} %".replace(".", ","),
                    legal >= 0.999 or not m.video.legal))
            color = probe_color(target)
            expected = "iec61966-2-1" if m.video.color_space == "srgb" else "bt709"
            if color:
                label = {"bt709": "Rec.709", "iec61966-2-1": "sRGB"}.get(color, color)
                self.report.append(ReportRow(
                    _("Espace couleur"),
                    "sRGB" if m.video.color_space == "srgb" else "Rec.709", label,
                    color == expected))
        if layout == "surround":
            self.notes.append(_("Son en 5.1 : dialogues au centre, musique et effets autour."))
        elif layout == "stems":
            self.notes.append(_("Pistes séparées : {files}").format(
                files=", ".join(Path(f).name for f in self.extra_files)))
        self.report_path = str(Path(target).with_suffix(".rapport.txt"))
        try:
            Path(self.report_path).write_text(self.report_text(), encoding="utf-8")
        except OSError as exc:
            log.warning("rapport non écrit : %s", exc)
            self.report_path = ""

    @property
    def conform(self) -> bool:
        return all(row.ok for row in self.report)

    def report_text(self) -> str:
        m = self.mastering
        dest = DESTINATIONS.get(m.audio.destination)
        lines = [_("Rapport de finition — montar"), "",
                 f"{_('Projet')} : {self.project_name}",
                 f"{_('Fichier')} : {Path(self.settings.path).name}",
                 f"{_('Date')} : {time.strftime('%Y-%m-%d %H:%M')}",
                 f"{_('Destination')} : {_(dest[0]) if dest else _('Personnalisé')}", ""]
        a = self.analysis
        if a is not None and a.loudness is not None:
            lines.append(_("Avant finition : {lufs} LUFS, crête {peak} dBTP, gain appliqué "
                           "{gain} dB").format(lufs=_plain(a.loudness.integrated),
                                               peak=_plain(a.loudness.true_peak),
                                               gain=_db(a.gain_db)))
            lines.append("")
        width = max([len(r.label) for r in self.report] + [10])
        for row in self.report:
            mark = "OK" if row.ok else _("À VÉRIFIER")
            lines.append(f"{row.label.ljust(width)}  {row.target:>14}  {row.result:>14}  {mark}")
        if self.notes:
            lines.append("")
            lines += [f"- {n}" for n in self.notes]
        lines.append("")
        lines.append(_("Conforme") if self.conform else _("Des mesures sont hors cible."))
        return "\n".join(lines) + "\n"
