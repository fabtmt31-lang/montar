# SPDX-License-Identifier: GPL-3.0-or-later
"""Fenêtre des scopes de l'étalonnage : forme d'onde, parade RVB, vecteurscope, histogramme,
calculés sur l'image affichée dans l'aperçu (réduite, pour rester fluide)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from montar.i18n import _
from montar.ui.widgets import Segmented

SCOPES = (("waveform", "Forme d'onde"), ("parade", "Parade RVB"),
          ("vector", "Vecteurscope"), ("histogram", "Histogramme"))
SAMPLE_WIDTH = 320  # largeur de l'image analysée
SIZE = (480, 300)  # taille du scope dessiné


def _rgb(image: QImage):
    import numpy as np

    small = image.scaledToWidth(SAMPLE_WIDTH, Qt.TransformationMode.FastTransformation) \
        .convertToFormat(QImage.Format.Format_RGB888)
    w, h = small.width(), small.height()
    data = np.frombuffer(small.constBits().asstring(small.sizeInBytes()), dtype=np.uint8)
    return data.reshape(h, small.bytesPerLine())[:, :w * 3].reshape(h, w, 3).astype(np.int32)


def _to_image(counts, color: tuple[int, int, int]):
    """Densité (h × w) → image : plus de pixels, plus lumineux."""
    import numpy as np

    # échelle logarithmique éclaircie : les zones peu peuplées restent visibles
    level = np.clip(np.log1p(counts) / np.log1p(max(1, counts.max())) * 1.8 * 255, 0, 255)
    rgba = np.zeros(counts.shape + (4,), dtype=np.uint8)
    for k, c in enumerate(color):
        rgba[..., k] = (level * c / 255).astype(np.uint8)
    rgba[..., 3] = 255
    h, w = counts.shape
    return QImage(rgba.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


def waveform(rgb, channel: int | None = None):
    """Luminance (ou un canal) par colonne : x = position, y = niveau."""
    import numpy as np

    h, w = SIZE[1], rgb.shape[1]
    values = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) \
        if channel is None else rgb[..., channel]
    rows = (255 - np.clip(values, 0, 255)).astype(np.int32) * (h - 1) // 255
    counts = np.zeros((h, w), dtype=np.int32)
    cols = np.broadcast_to(np.arange(w), rows.shape)
    np.add.at(counts, (rows.ravel(), cols.ravel()), 1)
    return counts


def render_scope(image: QImage, kind: str) -> QImage:
    import numpy as np

    rgb = _rgb(image)
    w, h = SIZE
    if kind == "waveform":
        out = _to_image(waveform(rgb), (190, 240, 205)).scaled(
            w, h, transformMode=Qt.TransformationMode.SmoothTransformation)
    elif kind == "parade":
        parts = [_to_image(waveform(rgb, c), col).scaled(w // 3, h) for c, col in
                 enumerate(((255, 90, 90), (90, 230, 110), (100, 150, 255)))]
        out = QImage(w, h, QImage.Format.Format_RGB32)
        out.fill(QColor("#0B120E"))
        painter = QPainter(out)
        for i, part in enumerate(parts):
            painter.drawImage(i * (w // 3), 0, part)
        painter.end()
    elif kind == "vector":
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        cb = -0.1146 * r - 0.3854 * g + 0.5 * b  # chrominance BT.709, de -128 à 128
        cr = 0.5 * r - 0.4542 * g - 0.0458 * b
        n = h
        xs = np.clip((cb / 256 + 0.5) * (n - 1), 0, n - 1).astype(np.int32)
        ys = np.clip((0.5 - cr / 256) * (n - 1), 0, n - 1).astype(np.int32)
        counts = np.zeros((n, n), dtype=np.int32)
        np.add.at(counts, (ys.ravel(), xs.ravel()), 1)
        out = QImage(w, h, QImage.Format.Format_RGB32)
        out.fill(QColor("#0B120E"))
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left = (w - n) // 2
        painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
        painter.drawEllipse(left, 0, n - 1, n - 1)
        painter.drawLine(left + n // 2, 0, left + n // 2, n)
        painter.drawLine(left, n // 2, left + n, n // 2)
        painter.drawImage(left, 0, _to_image(counts, (200, 255, 210)))
        painter.end()
    else:  # histogramme
        out = QImage(w, h, QImage.Format.Format_ARGB32)
        out.fill(QColor("#0B120E"))
        painter = QPainter(out)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        hists = [np.bincount(rgb[..., c].ravel(), minlength=256)[:256] for c in range(3)]
        top = max(1, max(int(hh.max()) for hh in hists))
        for hist, color in zip(hists, ("#E5484D", "#46A758", "#3E7BFA"), strict=True):
            c = QColor(color)
            c.setAlpha(170)
            painter.setPen(QPen(c, 1))
            for x in range(w):
                value = hist[x * 256 // w] / top
                painter.drawLine(x, h, x, h - int(value * (h - 4)))
        painter.end()
    return out


class ScopesWindow(QWidget):
    """Fenêtre à part (à poser à côté de l'aperçu, ou sur un autre écran)."""

    closed = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("Page")
        self.setWindowTitle(_("Scopes"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.kind = Segmented([(k, _(t)) for k, t in SCOPES], "waveform", compact=True)
        self.kind.changed.connect(lambda _k: self.update_frame(self._last))
        layout.addWidget(self.kind)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(*SIZE)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setStyleSheet("background: #0B120E; border-radius: 8px; color: #C8D6CE;")
        layout.addWidget(self.view, 1)
        self._last: QImage | None = None
        self.resize(SIZE[0] + 24, SIZE[1] + 80)

    def update_frame(self, image: QImage | None) -> None:
        self._last = image
        if image is None or image.isNull() or not self.isVisible():
            return
        try:
            scope = render_scope(image, self.kind.current())
        except ImportError:
            self.view.setText(_("Les scopes demandent NumPy (paquet python3-numpy)."))
            return
        from PyQt6.QtGui import QPixmap

        self.view.setPixmap(QPixmap.fromImage(scope).scaled(
            self.view.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)
