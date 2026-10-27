# SPDX-License-Identifier: GPL-3.0-or-later
"""Séparation de la personne et du fond sur la webcam (flou ou effacement du fond).

Le modèle « selfie segmenter » de MediaPipe (assets/models, licence Apache 2.0) est un petit
réseau TensorFlow Lite. Plutôt que de dépendre de TensorFlow, montar lit le fichier et
l'exécute avec NumPy : seules les quelques opérations de ce modèle sont prises en charge
(convolutions, convolutions par canal, moyennes, activations, redimensionnement…).

`webcam_masks` calcule, après l'enregistrement, une vidéo de masques (blanc = personne) à
partir de la vidéo de la webcam ; ffmpeg s'en sert ensuite pour flouter ou effacer le fond."""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np

from montar.platform.paths import assets_dir

MODEL = "selfie_segmenter_landscape.tflite"


def model_path() -> Path:
    return assets_dir() / "models" / MODEL


# --- lecture du format FlatBuffers de TensorFlow Lite -----------------------------------


class _Table:
    """Table FlatBuffers : champs lus d'après leur numéro (schéma de TensorFlow Lite)."""

    def __init__(self, buf: bytes, pos: int) -> None:
        self.buf, self.pos = buf, pos
        vtable = pos - struct.unpack_from("<i", buf, pos)[0]
        self._vsize = struct.unpack_from("<H", buf, vtable)[0]
        self._vtable = vtable

    def _offset(self, field: int) -> int:
        at = 4 + 2 * field
        if at >= self._vsize:
            return 0
        return struct.unpack_from("<H", self.buf, self._vtable + at)[0]

    def scalar(self, field: int, fmt: str, default=0):
        off = self._offset(field)
        return struct.unpack_from("<" + fmt, self.buf, self.pos + off)[0] if off else default

    def _target(self, field: int) -> int | None:
        off = self._offset(field)
        if not off:
            return None
        at = self.pos + off
        return at + struct.unpack_from("<I", self.buf, at)[0]

    def table(self, field: int) -> _Table | None:
        at = self._target(field)
        return _Table(self.buf, at) if at is not None else None

    def vector(self, field: int) -> tuple[int, int]:
        """(position du premier élément, nombre d'éléments)."""
        at = self._target(field)
        if at is None:
            return 0, 0
        return at + 4, struct.unpack_from("<I", self.buf, at)[0]

    def tables(self, field: int) -> list[_Table]:
        start, n = self.vector(field)
        return [_Table(self.buf, start + 4 * i + struct.unpack_from("<I", self.buf,
                                                                  start + 4 * i)[0])
                for i in range(n)]

    def ints(self, field: int) -> list[int]:
        start, n = self.vector(field)
        return list(struct.unpack_from(f"<{n}i", self.buf, start)) if n else []

    def raw(self, field: int) -> bytes:
        start, n = self.vector(field)
        return self.buf[start:start + n]

    def string(self, field: int) -> str:
        return self.raw(field).decode("utf-8", "replace")


# codes des opérations de TensorFlow Lite (schema.fbs, BuiltinOperator)
_ADD, _CONV, _DEPTHWISE, _DEQUANTIZE, _LOGISTIC, _MUL, _RELU = 0, 3, 4, 6, 14, 18, 19
_RESIZE, _CUSTOM, _MEAN, _HARD_SWISH = 23, 32, 40, 117
_DTYPES = {0: np.float32, 1: np.float16, 2: np.int32}


class SegmentationError(RuntimeError):
    pass


class _Op:
    def __init__(self, kind: int, inputs: list[int], outputs: list[int], options, custom):
        self.kind, self.inputs, self.outputs = kind, inputs, outputs
        self.options, self.custom = options, custom


class Segmenter:
    """Exécute le modèle : `mask(image)` → probabilité « personne » de chaque point."""

    def __init__(self, path: Path | None = None) -> None:
        buf = (path or model_path()).read_bytes()
        model = _Table(buf, struct.unpack_from("<I", buf, 0)[0])
        codes = []
        for code in model.tables(1):
            builtin = max(code.scalar(0, "b"), code.scalar(3, "i"))
            codes.append((builtin, code.string(1)))
        buffers = [b.raw(0) for b in model.tables(4)]
        graph = model.tables(2)[0]
        self._tensors: dict[int, np.ndarray] = {}
        shapes = []
        for i, t in enumerate(graph.tables(0)):
            shape = t.ints(0)
            shapes.append(shape)
            data = buffers[t.scalar(2, "I")] if t.scalar(2, "I") < len(buffers) else b""
            if data:
                dtype = _DTYPES.get(t.scalar(1, "b"))
                if dtype is None:
                    raise SegmentationError(f"type de tenseur inconnu ({t.scalar(1, 'b')})")
                self._tensors[i] = np.frombuffer(data, dtype=dtype).reshape(shape)
        self.input = graph.ints(1)[0]
        self.output = graph.ints(2)[0]
        _n, self.height, self.width, _c = shapes[self.input]
        self._ops = []
        for op in graph.tables(3):
            kind, custom = codes[op.scalar(0, "I")]
            options = op.table(4)
            raw = op.raw(5)
            self._ops.append(_Op(kind, op.ints(1), op.ints(2), options,
                                 (custom, raw) if kind == _CUSTOM else None))
        known = {_ADD, _CONV, _DEPTHWISE, _DEQUANTIZE, _LOGISTIC, _MUL, _RELU, _RESIZE,
                 _CUSTOM, _MEAN, _HARD_SWISH}
        unknown = {o.kind for o in self._ops} - known
        if unknown:
            raise SegmentationError(f"opérations non prises en charge : {sorted(unknown)}")
        # poids en demi-précision : convertis une fois pour toutes
        for op in [o for o in self._ops if o.kind == _DEQUANTIZE]:
            self._tensors[op.outputs[0]] = self._tensors[op.inputs[0]].astype(np.float32)
        self._ops = [o for o in self._ops if o.kind != _DEQUANTIZE]

    def mask(self, rgb: np.ndarray) -> np.ndarray:
        """`rgb` : image (hauteur × largeur × 3, uint8) à la taille du modèle ; renvoie un
        tableau hauteur × largeur de valeurs entre 0 (fond) et 1 (personne)."""
        if rgb.shape[:2] != (self.height, self.width):
            raise SegmentationError("image à la mauvaise taille")
        values = dict(self._tensors)
        values[self.input] = (rgb.astype(np.float32) / 255.0)[None]
        for op in self._ops:
            values[op.outputs[0]] = self._run(op, values)
        return values[self.output][0, :, :, 0]

    # --- opérations --------------------------------------------------------------------

    def _run(self, op: _Op, values: dict) -> np.ndarray:
        x = values[op.inputs[0]]
        if op.kind == _CONV:
            o = op.options
            out = _conv(x, values[op.inputs[1]], values[op.inputs[2]], o.scalar(0, "b"),
                        o.scalar(1, "i", 1), o.scalar(2, "i", 1))
            return _activation(out, o.scalar(3, "b"))
        if op.kind == _DEPTHWISE:
            o = op.options
            out = _depthwise(x, values[op.inputs[1]], values[op.inputs[2]], o.scalar(0, "b"),
                             o.scalar(1, "i", 1), o.scalar(2, "i", 1))
            return _activation(out, o.scalar(4, "b"))
        if op.kind in (_ADD, _MUL):
            y = values[op.inputs[1]]
            out = x + y if op.kind == _ADD else x * y
            return _activation(out, op.options.scalar(0, "b") if op.options else 0)
        if op.kind == _RELU:
            return np.maximum(x, 0)
        if op.kind == _HARD_SWISH:
            return x * np.clip(x + 3, 0, 6) / 6
        if op.kind == _LOGISTIC:
            return 1 / (1 + np.exp(-np.clip(x, -60, 60)))
        if op.kind == _MEAN:
            axes = tuple(int(a) for a in values[op.inputs[1]].ravel())
            return x.mean(axis=axes, keepdims=bool(op.options.scalar(0, "b")))
        if op.kind == _RESIZE:
            h, w = (int(v) for v in values[op.inputs[1]].ravel())
            return _resize(x, h, w, bool(op.options.scalar(3, "b")))
        if op.kind == _CUSTOM and op.custom[0] == "Convolution2DTransposeBias":
            _pad, sw, sh = struct.unpack_from("<3i", op.custom[1], 0)
            return _transpose_conv(x, values[op.inputs[1]], values[op.inputs[2]], sw, sh)
        raise SegmentationError(f"opération inconnue : {op.kind} {op.custom}")


def _activation(x: np.ndarray, kind: int) -> np.ndarray:
    if kind == 1:
        return np.maximum(x, 0)
    if kind == 3:
        return np.clip(x, 0, 6)
    return x


def _same_padding(size: int, k: int, s: int) -> tuple[int, int]:
    out = -(-size // s)
    total = max((out - 1) * s + k - size, 0)
    return total // 2, total - total // 2


def _pad(x: np.ndarray, kh: int, kw: int, sh: int, sw: int, padding: int) -> np.ndarray:
    if padding != 0:  # VALID
        return x
    top, bottom = _same_padding(x.shape[1], kh, sh)
    left, right = _same_padding(x.shape[2], kw, sw)
    return np.pad(x, ((0, 0), (top, bottom), (left, right), (0, 0)))


def _conv(x, weights, bias, padding, sw, sh):
    out_c, kh, kw, in_c = weights.shape
    if kh == kw == 1 and sw == sh == 1:
        n, h, w, c = x.shape
        return (x.reshape(-1, c) @ weights.reshape(out_c, in_c).T + bias).reshape(n, h, w,
                                                                                  out_c)
    x = _pad(x, kh, kw, sh, sw, padding)
    oh = (x.shape[1] - kh) // sh + 1
    ow = (x.shape[2] - kw) // sw + 1
    out = np.zeros((1, oh, ow, out_c), dtype=np.float32)
    for i in range(kh):
        for j in range(kw):
            patch = x[:, i:i + sh * (oh - 1) + 1:sh, j:j + sw * (ow - 1) + 1:sw, :]
            out += patch @ weights[:, i, j, :].T
    return out + bias


def _depthwise(x, weights, bias, padding, sw, sh):
    _one, kh, kw, c = weights.shape
    x = _pad(x, kh, kw, sh, sw, padding)
    oh = (x.shape[1] - kh) // sh + 1
    ow = (x.shape[2] - kw) // sw + 1
    out = np.zeros((1, oh, ow, c), dtype=np.float32)
    for i in range(kh):
        for j in range(kw):
            out += x[:, i:i + sh * (oh - 1) + 1:sh, j:j + sw * (ow - 1) + 1:sw, :] \
                * weights[0, i, j, :]
    return out + bias


def _resize(x, h, w, half_pixel: bool):
    _n, ih, iw, _c = x.shape

    def coords(out_size, in_size):
        scale = in_size / out_size
        src = (np.arange(out_size) + 0.5) * scale - 0.5 if half_pixel \
            else np.arange(out_size) * scale
        src = np.clip(src, 0, in_size - 1)
        low = np.floor(src).astype(int)
        high = np.minimum(low + 1, in_size - 1)
        return low, high, (src - low).astype(np.float32)

    y0, y1, fy = coords(h, ih)
    x0, x1, fx = coords(w, iw)
    top = x[:, y0][:, :, x0] * (1 - fx)[None, None, :, None] + \
        x[:, y0][:, :, x1] * fx[None, None, :, None]
    bottom = x[:, y1][:, :, x0] * (1 - fx)[None, None, :, None] + \
        x[:, y1][:, :, x1] * fx[None, None, :, None]
    return top * (1 - fy)[None, :, None, None] + bottom * fy[None, :, None, None]


def _transpose_conv(x, weights, bias, sw, sh):
    """Convolution transposée sans recouvrement (noyau = pas), comme dans le modèle."""
    out_c, kh, kw, _in_c = weights.shape
    _n, h, w, _c = x.shape
    out = np.zeros((1, h * sh, w * sw, out_c), dtype=np.float32)
    for i in range(kh):
        for j in range(kw):
            out[:, i::sh, j::sw, :] = x @ weights[:, i, j, :].T
    return out + bias


# --- vidéo de masques -----------------------------------------------------------------------


def webcam_masks(source: Path, target: Path, fps: int,
                 progress: Callable[[int], None] = lambda n: None,
                 cancelled: Callable[[], bool] = lambda: False,
                 segmenter: Segmenter | None = None) -> int:
    """Masques (blanc = personne) de chaque image de la vidéo `source`, écrits en vidéo
    sans perte `target` à la taille du modèle. Renvoie le nombre d'images traitées."""
    seg = segmenter or Segmenter()
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    w, h = seg.width, seg.height
    errors = tempfile.TemporaryFile()
    reader = subprocess.Popen([ffmpeg, "-v", "error", "-i", str(source), "-vf",
                               f"scale={w}:{h},format=rgb24", "-r", str(fps), "-f", "rawvideo",
                               "-"], stdout=subprocess.PIPE, stderr=errors,
                              stdin=subprocess.DEVNULL)
    writer = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                               "gray", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v",
                               "ffv1", str(target)], stdin=subprocess.PIPE, stderr=errors)
    assert reader.stdout is not None and writer.stdin is not None
    size, count, previous = w * h * 3, 0, None
    step = 2 if fps > 20 else 1  # au-delà de 20 i/s, un calcul pour deux images suffit
    try:
        while not cancelled():
            data = reader.stdout.read(size)
            if len(data) < size:
                break
            if previous is None or count % step == 0:
                frame = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
                mask = seg.mask(frame)
                if previous is not None:  # un peu de lissage dans le temps : moins de
                    mask = 0.65 * mask + 0.35 * previous  # scintillement
            else:
                mask = previous
            previous = mask
            writer.stdin.write((np.clip(mask, 0, 1) * 255).astype(np.uint8).tobytes())
            count += 1
            progress(count)
    finally:
        writer.stdin.close()
        reader.stdout.close()
        reader.wait()
        writer.wait()
        errors.close()
    if writer.returncode != 0 and not cancelled():
        raise SegmentationError("écriture des masques impossible")
    return count


class LiveMasker:
    """Détourage pendant l'enregistrement : lit les images réduites de la webcam que ffmpeg
    écrit sur sa sortie standard et écrit, pour chacune, le dernier masque calculé.

    La lecture ne s'arrête jamais (ffmpeg ne doit pas attendre) ; le calcul, plus lent que
    la webcam sur un petit ordinateur, porte sur la dernière image reçue : les masques
    suivent avec une ou deux images de retard au pire."""

    def __init__(self, stream, target: Path, fps: int,
                 segmenter: Segmenter | None = None) -> None:
        import threading

        self.seg = segmenter or Segmenter()
        self.stream, self.target, self.fps = stream, target, fps
        self.frames = 0  # images reçues (= masques écrits)
        self.computed = 0  # masques réellement calculés
        self.error = ""
        self._latest: np.ndarray | None = None
        self._fresh = threading.Event()
        self._mask = np.zeros((self.seg.height, self.seg.width), np.uint8)
        self._done = False
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        self._errors = tempfile.TemporaryFile()
        self._writer = subprocess.Popen(
            [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s",
             f"{self.seg.width}x{self.seg.height}", "-r", str(fps), "-i", "-", "-c:v", "ffv1",
             str(target)], stdin=subprocess.PIPE, stderr=self._errors)
        self._reader = threading.Thread(target=self._read, name="montar-webcam-lecture",
                                        daemon=True)
        self._worker = threading.Thread(target=self._work, name="montar-detourage",
                                        daemon=True)
        self._reader.start()
        self._worker.start()

    def _read(self) -> None:
        w, h = self.seg.width, self.seg.height
        size = w * h * 3
        try:
            while True:
                data = self.stream.read(size)
                if not data or len(data) < size:
                    break
                frame = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
                if self.frames == 0:  # premier masque tout de suite (pas d'image vide)
                    self._mask = self._compute(frame, None)
                else:
                    self._latest = frame
                    self._fresh.set()
                self._writer.stdin.write(self._mask.tobytes())
                self.frames += 1
        except Exception as exc:  # tuyau fermé, ffmpeg arrêté : on s'arrête
            self.error = self.error or str(exc)
        finally:
            self._done = True
            self._fresh.set()

    def _compute(self, frame: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
        mask = self.seg.mask(frame)
        if previous is not None:  # un peu de lissage dans le temps : moins de scintillement
            mask = 0.65 * mask + 0.35 * previous.astype(np.float32) / 255
        self.computed += 1
        return (np.clip(mask, 0, 1) * 255).astype(np.uint8)

    def _work(self) -> None:
        while True:
            self._fresh.wait()
            self._fresh.clear()
            frame, self._latest = self._latest, None
            if frame is not None:
                try:
                    self._mask = self._compute(frame, self._mask)
                except Exception as exc:
                    self.error = str(exc)
            if self._done and self._latest is None:
                break

    def close(self, timeout: float = 30.0) -> bool:
        """Après la fin de ffmpeg : termine la vidéo de masques ; True si elle est complète."""
        self._reader.join(timeout)
        self._fresh.set()
        self._worker.join(timeout)
        try:
            self._writer.stdin.close()
        except OSError:
            pass
        try:
            self._writer.wait(timeout)
        except subprocess.TimeoutExpired:
            self._writer.kill()
        self._errors.close()
        return self._writer.returncode == 0 and self.frames > 0 and not self.error
