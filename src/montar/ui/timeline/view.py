# SPDX-License-Identifier: GPL-3.0-or-later
"""Timeline multipiste (maquette 02) : règle, pistes, clips, tête de lecture.

Interactions : clic sur la règle = déplacer la tête de lecture ; glisser un clip = le
déplacer (y compris vers une autre piste compatible) ; glisser un bord = rogner ;
Ctrl + molette = zoom ; dépôt d'un média depuis le panneau Médias = nouveau clip.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import QAbstractScrollArea, QMenu

from montar.core.project import Clip, MediaItem, Track
from montar.i18n import _
from montar.media.waveform import PEAKS_PER_SECOND
from montar.ui.editor.controller import EditorController
from montar.ui.editor.media_panel import MEDIA_MIME
from montar.ui.editor.panels import TRANSITION_MIME
from montar.ui.theme import theme
from montar.ui.theme.icons import pixmap as icon_pixmap
from montar.ui.theme.tokens import FONT_MONO, FONT_UI

HEADER_W = 176
RULER_H = 30
ROW_H = {"video": 56, "audio": 46}
EDGE_PX = 6  # zone de saisie des bords d'un clip
SNAP_PX = 8
MIN_PPS, MAX_PPS = 2.0, 400.0  # zoom : pixels par seconde
_TICK_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600)  # secondes


@dataclass
class _Row:
    track: Track
    label: str
    top: int  # coordonnée dans le contenu (sans défilement)
    height: int


@dataclass
class _Drag:
    mode: str  # playhead | move | start | end
    clip_id: str | None = None
    press: QPoint | None = None
    offset: int = 0  # écart entre le début du clip et l'image saisie
    track_id: str | None = None
    start: int = 0
    duration: int = 0
    moved: bool = False


class TimelineView(QAbstractScrollArea):
    seekRequested = pyqtSignal(int)
    zoomChanged = pyqtSignal(float)

    def __init__(self, controller: EditorController,
                 thumbnail_for: Callable[[str], str | None],
                 peaks_for: Callable[[str], bytes | None]) -> None:
        super().__init__()
        self.controller = controller
        self._thumbnail_for = thumbnail_for
        self._peaks_for = peaks_for
        self._thumb_cache: dict[tuple[str, int], QPixmap] = {}
        self.pps = 40.0
        self.playhead = 0
        self.snap = True
        self._drag: _Drag | None = None
        self._drop: tuple[str | None, int, int, str] | None = None  # piste, début, durée, type
        self._junction: tuple[Clip, Clip] | None = None  # jonction visée par une transition
        # Plage marquée avec I / O sur un clip : (clip, début, fin) en images de timeline
        self.selection_range: tuple[str, int, int] | None = None
        # Fournis par la page de montage (modules) : badges d'un clip, actions d'outils
        self.badge_provider: Callable[[Clip], list[str]] = lambda clip: []
        self.tool_provider: Callable[[Clip], list[tuple[str, Callable[[], None]]]] = \
            lambda clip: []
        self._hover_header: tuple[str, str] | None = None
        self.setAcceptDrops(True)
        self.viewport().setMouseTracking(True)
        self.setMinimumHeight(RULER_H + 2 * ROW_H["audio"] + 20)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.horizontalScrollBar().setSingleStep(20)
        self.verticalScrollBar().setSingleStep(20)
        controller.changed.connect(self.refresh)
        controller.selectionChanged.connect(lambda _id: self.viewport().update())
        theme().changed.connect(self.viewport().update)
        self.refresh()

    # --- géométrie --------------------------------------------------------------

    @property
    def fps(self) -> int:
        return self.controller.project.fps

    @property
    def ppf(self) -> float:
        return self.pps / self.fps

    def frame_to_x(self, frame: float) -> float:
        return HEADER_W + frame * self.ppf - self.horizontalScrollBar().value()

    def x_to_frame(self, x: float) -> int:
        return max(0, round((x - HEADER_W + self.horizontalScrollBar().value()) / self.ppf))

    def rows(self) -> list[_Row]:
        labels = self.controller.timeline.track_labels()
        rows, top = [], RULER_H
        for t in self.controller.project.tracks:
            h = ROW_H.get(t.kind, 48)
            rows.append(_Row(t, labels.get(t.id, ""), top, h))
            top += h
        return rows

    def _row_rect(self, row: _Row) -> QRect:
        return QRect(0, row.top - self.verticalScrollBar().value(), self.viewport().width(),
                     row.height)

    def row_at(self, y: int) -> _Row | None:
        for row in self.rows():
            r = self._row_rect(row)
            if r.top() <= y < r.bottom() + 1:
                return row
        return None

    def clip_rect(self, clip: Clip, start: int | None = None, duration: int | None = None,
                  track_id: str | None = None) -> QRectF | None:
        tid = track_id or clip.track_id
        row = next((r for r in self.rows() if r.track.id == tid), None)
        if row is None:
            return None
        s = clip.start if start is None else start
        d = clip.duration if duration is None else duration
        r = self._row_rect(row)
        return QRectF(self.frame_to_x(s), r.top() + 4, d * self.ppf, r.height() - 8)

    def _content_width(self) -> int:
        length = self.controller.timeline.length()
        visible = (self.viewport().width() - HEADER_W) / self.ppf
        return int((max(length, visible * 0.9) + 10 * self.fps) * self.ppf)

    def _content_height(self) -> int:
        return sum(r.height for r in self.rows()) + RULER_H + 24

    def refresh(self) -> None:
        self._update_scrollbars()
        self.viewport().update()

    def _update_scrollbars(self) -> None:
        h = self.horizontalScrollBar()
        page = max(1, self.viewport().width() - HEADER_W)
        h.setRange(0, max(0, self._content_width() - page))
        h.setPageStep(page)
        v = self.verticalScrollBar()
        vpage = max(1, self.viewport().height())
        v.setRange(0, max(0, self._content_height() - vpage))
        v.setPageStep(vpage)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_scrollbars()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        self.viewport().update()

    # --- zoom et tête de lecture ----------------------------------------------------

    def set_zoom(self, pps: float, anchor_x: float | None = None) -> None:
        pps = max(MIN_PPS, min(MAX_PPS, pps))
        if abs(pps - self.pps) < 1e-6:
            return
        if anchor_x is None:
            anchor_x = self.frame_to_x(self.playhead)
            if not HEADER_W <= anchor_x <= self.viewport().width():
                anchor_x = HEADER_W
        anchor_frame = (anchor_x - HEADER_W + self.horizontalScrollBar().value()) / self.ppf
        self.pps = pps
        self._update_scrollbars()
        self.horizontalScrollBar().setValue(int(anchor_frame * self.ppf - (anchor_x - HEADER_W)))
        self.viewport().update()
        self.zoomChanged.emit(pps)

    def zoom_to_fit(self) -> None:
        length = max(self.controller.timeline.length(), self.fps)
        available = max(100, self.viewport().width() - HEADER_W - 40)
        self.set_zoom(available / (length / self.fps))
        self.horizontalScrollBar().setValue(0)

    def set_playhead(self, frame: int, follow: bool = False) -> None:
        self.playhead = max(0, frame)
        if follow:
            x = self.frame_to_x(self.playhead)
            right = self.viewport().width() - 40
            if x > right or x < HEADER_W:
                self.horizontalScrollBar().setValue(
                    int(self.playhead * self.ppf - (self.viewport().width() - HEADER_W) * 0.1))
        self.viewport().update()

    # --- aimantation --------------------------------------------------------------

    def _snap_points(self, ignore: str | None) -> list[int]:
        points = {0, self.playhead}
        for c in self.controller.project.clips:
            if c.id != ignore:
                points.update((c.start, c.end))
        return sorted(points)

    def _snap(self, frame: int, ignore: str | None, extra: tuple[int, ...] = ()) -> int:
        """Rapproche `frame` (et les décalages `extra`) du point d'aimantation le plus proche."""
        if not self.snap:
            return frame
        best, best_dist = frame, SNAP_PX / self.ppf
        for point in self._snap_points(ignore):
            for off in (0, *extra):
                dist = abs(point - (frame + off))
                if dist < best_dist:
                    best, best_dist = point - off, dist
        return best

    # --- dessin -----------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme().palette
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.viewport().width(), self.viewport().height()
        painter.fillRect(0, 0, w, h, QColor(p.surface))
        rows = self.rows()

        painter.save()
        painter.setClipRect(QRect(HEADER_W, RULER_H, w - HEADER_W, h - RULER_H))
        for row in rows:
            r = self._row_rect(row)
            painter.fillRect(QRect(HEADER_W, r.bottom(), w, 1), QColor(p.border))
        dragged = self._drag.clip_id if self._drag and self._drag.mode != "playhead" else None
        for clip in sorted(self.controller.project.clips, key=lambda c: c.start):
            if clip.id == dragged:
                continue
            rect = self.clip_rect(clip)
            if rect is not None and rect.right() >= HEADER_W and rect.left() <= w:
                self._paint_clip(painter, clip, rect, clip.id == self.controller.selected)
        for transition in self.controller.project.transitions:
            self._paint_transition(painter, transition)
        self._paint_range(painter)
        if dragged:
            d = self._drag
            clip = self._find_clip(dragged)
            if clip is not None:
                rect = self.clip_rect(clip, d.start, d.duration, d.track_id)
                if rect is not None:
                    self._paint_clip(painter, clip, rect, True, ghost=True)
        if not self.controller.project.clips and self._drop is None:
            f = QFont(FONT_UI)
            f.setPixelSize(13)
            painter.setFont(f)
            painter.setPen(QColor(p.text_muted))
            painter.drawText(QRect(HEADER_W, RULER_H, w - HEADER_W, h - RULER_H),
                             Qt.AlignmentFlag.AlignCenter,
                             _("Glissez ici un média du panneau « Médias du projet »"))
        if self._junction is not None:
            self._paint_junction(painter, self._junction)
        if self._drop is not None:
            track_id, start, duration, kind = self._drop
            self._paint_drop(painter, track_id, start, duration, kind, rows)
        painter.restore()

        self._paint_ruler(painter, w)
        self._paint_headers(painter, rows, h)
        self._paint_playhead(painter, h)
        painter.end()

    def _clip_color(self, clip: Clip, media: MediaItem | None) -> str:
        p = theme().palette
        if clip.is_text:
            return p.water
        track = next((t for t in self.controller.project.tracks if t.id == clip.track_id), None)
        if track is not None and track.kind == "audio":
            first = self.controller.timeline.first_track("audio")
            return p.pistachio if first is not None and first.id == track.id else p.voiceover
        return p.mint

    def _paint_clip(self, painter: QPainter, clip: Clip, rect: QRectF, selected: bool,
                    ghost: bool = False) -> None:
        p = theme().palette
        media = self.controller.project.find_media(clip.media_id)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.save()
        if ghost:
            painter.setOpacity(0.85)
        painter.fillPath(path, QColor(self._clip_color(clip, media)))
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
        on_audio_track = self.controller.timeline.track(clip.track_id).kind == "audio"
        text_x = rect.left() + 10
        if media is not None and media.kind in ("video", "image") and not on_audio_track:
            text_x = self._paint_thumbnails(painter, media, rect)
        if media is not None and media.has_audio and media.kind in ("audio", "video"):
            self._paint_waveform(painter, clip, media, rect, on_audio_track)
        f = QFont(FONT_UI)
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f)
        painter.setPen(QColor(p.ink))
        fm = QFontMetrics(f)
        badges = self._badges(clip, media)
        available = int(rect.right() - text_x - 8 - 30 * len(badges))
        if clip.is_text:
            name = clip.text.content.replace("\n", " ") or _("Texte")
            painter.drawPixmap(int(text_x), int(rect.center().y() - 8),
                               icon_pixmap("type", p.forest, 16))
            text_x += 22
            available -= 22
        else:
            name = media.name if media is not None else ""
        if available > 20:
            name = fm.elidedText(name, Qt.TextElideMode.ElideRight, available)
            top_label = on_audio_track or (media is not None and media.kind == "audio")
            ty = rect.top() + (14 if top_label else rect.height() / 2 + 4)
            painter.drawText(int(text_x), int(ty), name)
        x = rect.right() - 6
        for badge in badges:
            x = self._paint_badge(painter, badge, x, rect.top() + 5)
        self._paint_fades(painter, clip, rect)
        if media is not None and not media.exists:
            icon = icon_pixmap("triangle-alert", "#B4452F", 16)
            painter.drawPixmap(int(rect.left()) + 6, int(rect.top()) + 4, icon)
        painter.restore()
        pen = QPen(QColor(p.forest if selected else p.sage))
        pen.setWidthF(2.0 if selected else 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if selected and rect.width() > 24:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.forest))
            cy = rect.center().y()
            for x in (rect.left() + 3, rect.right() - 6):
                painter.drawRoundedRect(QRectF(x, cy - 9, 3, 18), 1.5, 1.5)

    def _badges(self, clip: Clip, media: MediaItem | None) -> list[str]:
        badges = list(self.badge_provider(clip))
        if clip.speed != 1.0 and not badges:
            badges.append(f"×{clip.speed:g}")
        if media is not None and media.has_audio and clip.volume == 0:
            badges.append("mute")
        if clip.preset or not clip.color.is_identity() or not clip.effects.is_identity():
            badges.append("fx")
        return badges

    def _paint_badge(self, painter: QPainter, badge: str, right: float, top: float) -> float:
        f = QFont(FONT_MONO)
        f.setPixelSize(10)
        f.setWeight(QFont.Weight.Bold)
        painter.setFont(f)
        if badge in ("mute", "fx"):
            width = 20.0
        else:
            width = QFontMetrics(f).horizontalAdvance(badge) + 10.0
        rect = QRectF(right - width, top, width, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#17261E"))
        painter.drawRoundedRect(rect, 4, 4)
        if badge == "mute":
            painter.drawPixmap(int(rect.left()) + 3, int(rect.top()) + 1,
                               icon_pixmap("volume-x", "#FFFFFF", 14))
        elif badge == "fx":
            painter.drawPixmap(int(rect.left()) + 3, int(rect.top()) + 1,
                               icon_pixmap("sparkles", "#FFFFFF", 14))
        else:
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge)
        return rect.left() - 4

    # --- plage I / O -------------------------------------------------------------------

    def _range_clip(self) -> Clip | None:
        """Clip visé par les touches I / O : le clip sélectionné, s'il est sous la tête."""
        clip = self.controller.selected_clip()
        if clip is not None and clip.start <= self.playhead <= clip.end:
            return clip
        return None

    def mark_in(self) -> None:
        clip = self._range_clip()
        if clip is None:
            return
        current = self.selection_range
        end = current[2] if current and current[0] == clip.id else clip.end
        start = min(self.playhead, end - 1)
        self.selection_range = (clip.id, max(clip.start, start), end)
        self.viewport().update()

    def mark_out(self) -> None:
        clip = self._range_clip()
        if clip is None:
            return
        current = self.selection_range
        start = current[1] if current and current[0] == clip.id else clip.start
        end = max(self.playhead, start + 1)
        self.selection_range = (clip.id, start, min(clip.end, end))
        self.viewport().update()

    def clear_range(self) -> None:
        self.selection_range = None
        self.viewport().update()

    def _paint_range(self, painter: QPainter) -> None:
        if self.selection_range is None:
            return
        clip_id, start, end = self.selection_range
        clip = self._find_clip(clip_id)
        if clip is None or not (clip.start <= start < end <= clip.end):
            self.selection_range = None
            return
        rect = self.clip_rect(clip, start, end - start)
        if rect is None:
            return
        p = theme().palette
        fill = QColor(p.forest)
        fill.setAlphaF(0.28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRect(rect)
        painter.setBrush(QColor(p.forest))
        for x in (rect.left(), rect.right() - 3):
            painter.drawRect(QRectF(x, rect.top() - 3, 3, rect.height() + 6))

    def _paint_fades(self, painter: QPainter, clip: Clip, rect: QRectF) -> None:
        """Rampes de fondu en haut du clip."""
        color = QColor("#17261E")
        color.setAlphaF(0.35)
        painter.setPen(QPen(color, 1.5))
        for frames, left in ((clip.fade_in, True), (clip.fade_out, False)):
            if frames <= 0:
                continue
            width = min(rect.width() / 2, frames * self.ppf)
            if left:
                painter.drawLine(int(rect.left()), int(rect.bottom()) - 2,
                                 int(rect.left() + width), int(rect.top()) + 2)
            else:
                painter.drawLine(int(rect.right() - width), int(rect.top()) + 2,
                                 int(rect.right()), int(rect.bottom()) - 2)

    def transition_rect(self, transition) -> QRectF | None:
        right = self._find_clip(transition.right_id)
        if right is None:
            return None
        row = next((r for r in self.rows() if r.track.id == transition.track_id), None)
        if row is None:
            return None
        r = self._row_rect(row)
        x0 = self.frame_to_x(right.start)
        width = max(24.0, transition.duration * self.ppf)
        cx = x0 + transition.duration * self.ppf / 2
        return QRectF(cx - width / 2, r.center().y() - 12, width, 24)

    def _paint_transition(self, painter: QPainter, transition) -> None:
        from montar.ui.labels import TRANSITIONS

        rect = self.transition_rect(transition)
        if rect is None:
            return
        p = theme().palette
        selected = self.controller.selected_transition == transition.id
        painter.setPen(QPen(QColor(p.forest), 2 if selected else 1))
        painter.setBrush(QColor(p.surface))
        painter.drawRoundedRect(rect, 8, 8)
        icon = TRANSITIONS.get(transition.kind, ("", "blend"))[1]
        painter.drawPixmap(int(rect.center().x()) - 8, int(rect.center().y()) - 8,
                           icon_pixmap(icon, p.forest, 16))

    def transition_at(self, pos: QPoint):
        for t in self.controller.project.transitions:
            rect = self.transition_rect(t)
            if rect is not None and rect.contains(pos.x(), pos.y()):
                return t
        return None

    def _thumbnail(self, media: MediaItem, height: int) -> QPixmap | None:
        key = (media.path, height)
        if key not in self._thumb_cache:
            path = self._thumbnail_for(media.path)
            if not path:
                return None
            pm = QPixmap(path)
            if pm.isNull():
                return None
            self._thumb_cache[key] = pm.scaledToHeight(
                height * 2, Qt.TransformationMode.SmoothTransformation)
        return self._thumb_cache[key]

    def _paint_thumbnails(self, painter: QPainter, media: MediaItem, rect: QRectF) -> float:
        """Deux vignettes au début du clip (comme la maquette) ; renvoie l'abscisse du texte."""
        pm = self._thumbnail(media, int(rect.height()))
        if pm is None:
            return rect.left() + 10
        tw = pm.width() / 2
        x = rect.left()
        for _i in range(2):
            if x + 8 > rect.right():
                break
            painter.drawPixmap(QRectF(x, rect.top(), tw, rect.height()), pm, QRectF(pm.rect()))
            x += tw
        return min(x, rect.right()) + 10

    def _paint_waveform(self, painter: QPainter, clip: Clip, media: MediaItem,
                        rect: QRectF, full: bool = False) -> None:
        peaks = self._peaks_for(media.path)
        if not peaks:
            return
        p = theme().palette
        color = QColor(p.forest)
        color.setAlphaF(0.55)
        painter.setPen(QPen(color, 1))
        if media.kind == "audio" or full:
            mid, amp = rect.center().y() + 5, rect.height() / 2 - 8
        else:  # bande sous les vignettes
            mid, amp = rect.bottom() - 8, 6
        visible_left = max(rect.left(), HEADER_W)
        visible_right = min(rect.right(), self.viewport().width())
        peak_scale = max(1, max(peaks))
        x = visible_left
        while x < visible_right:
            frame = clip.source_in + (x - rect.left()) / self.ppf * clip.speed
            index = int(frame / self.fps * PEAKS_PER_SECOND)
            if 0 <= index < len(peaks):
                span = max(1, int(PEAKS_PER_SECOND / self.pps * 2 * clip.speed))
                value = max(peaks[index:index + span]) / peak_scale
                dy = max(0.5, value * amp)
                painter.drawLine(int(x), int(mid - dy), int(x), int(mid + dy))
            x += 2

    def _paint_drop(self, painter: QPainter, track_id: str | None, start: int, duration: int,
                    kind: str, rows: list[_Row]) -> None:
        p = theme().palette
        if track_id is None:  # nouvelle piste
            last = rows[-1] if rows else None
            top = (last.top + last.height if last else RULER_H) - self.verticalScrollBar().value()
            rect = QRectF(self.frame_to_x(start), top + 4, duration * self.ppf, 40)
        else:
            row = next((r for r in rows if r.track.id == track_id), None)
            if row is None:
                return
            r = self._row_rect(row)
            rect = QRectF(self.frame_to_x(start), r.top() + 4, duration * self.ppf,
                          r.height() - 8)
        color = QColor(p.pistachio if kind == "audio" else p.mint)
        color.setAlphaF(0.7)
        painter.setBrush(color)
        pen = QPen(QColor(p.forest), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 8, 8)

    def _tick_step(self) -> int:
        for step in _TICK_STEPS:
            if step * self.pps >= 90:
                return step
        return _TICK_STEPS[-1]

    def _paint_ruler(self, painter: QPainter, w: int) -> None:
        p = theme().palette
        painter.fillRect(0, 0, w, RULER_H, QColor(p.surface))
        painter.fillRect(0, RULER_H - 1, w, 1, QColor(p.border))
        f = QFont(FONT_MONO)
        f.setPixelSize(10)
        painter.setFont(f)
        step = self._tick_step()
        first = int(self.x_to_frame(HEADER_W) / self.fps / step) * step
        sec = first
        while True:
            x = self.frame_to_x(sec * self.fps)
            if x > w:
                break
            if x >= HEADER_W:
                painter.setPen(QColor(p.border))
                painter.drawLine(int(x), 8, int(x), RULER_H - 1)
                painter.setPen(QColor(p.text_muted))
                mm, ss = divmod(sec, 60)
                hh, mm = divmod(mm, 60)
                text = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
                painter.drawText(int(x) + 4, 18, text)
            for minor in range(1, 5):
                mx = self.frame_to_x((sec + step * minor / 5) * self.fps)
                if HEADER_W <= mx <= w:
                    painter.setPen(QColor(p.border))
                    painter.drawLine(int(mx), RULER_H - 6, int(mx), RULER_H - 1)
            sec += step

    def _header_buttons(self, row: _Row) -> list[tuple[str, QRect]]:
        r = self._row_rect(row)
        cy = r.top() + r.height() // 2
        x = HEADER_W - 34
        if row.track.kind == "text":
            return [("hide", QRect(x, cy - 13, 26, 26))]
        buttons = [("mute", QRect(x, cy - 13, 26, 26))]
        if row.track.kind == "video":
            buttons.append(("hide", QRect(x - 28, cy - 13, 26, 26)))
        return buttons

    def _paint_headers(self, painter: QPainter, rows: list[_Row], h: int) -> None:
        p = theme().palette
        painter.save()
        painter.setClipRect(QRect(0, RULER_H, HEADER_W, h - RULER_H))
        painter.fillRect(0, RULER_H, HEADER_W, h, QColor(p.surface))
        for row in rows:
            r = self._row_rect(row)
            painter.fillRect(QRect(0, r.bottom(), HEADER_W, 1), QColor(p.border))
            badge = QRectF(12, r.center().y() - 11, 28, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.mist))
            painter.drawRoundedRect(badge, 6, 6)
            f = QFont(FONT_UI)
            f.setPixelSize(11)
            f.setWeight(QFont.Weight.Bold)
            painter.setFont(f)
            painter.setPen(QColor(p.forest))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, row.label)
            f.setPixelSize(13)
            f.setWeight(QFont.Weight.DemiBold)
            painter.setFont(f)
            painter.setPen(QColor(p.ink))
            name = QFontMetrics(f).elidedText(_(row.track.name), Qt.TextElideMode.ElideRight, 64)
            painter.drawText(QRect(48, r.top(), 70, r.height()),
                             Qt.AlignmentFlag.AlignVCenter, name)
            for key, rect in self._header_buttons(row):
                off = row.track.muted if key == "mute" else row.track.hidden
                icon = {"mute": ("volume-x", "volume-2"),
                        "hide": ("eye-off", "eye")}[key][0 if off else 1]
                if self._hover_header == (row.track.id, key):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(p.mist))
                    painter.drawRoundedRect(QRectF(rect), 6, 6)
                color = "#B4452F" if off else p.text_muted
                painter.drawPixmap(rect.left() + 4, rect.top() + 4, icon_pixmap(icon, color, 18))
        painter.restore()
        painter.fillRect(HEADER_W - 1, RULER_H, 1, h, QColor(p.border))
        painter.fillRect(0, 0, HEADER_W, RULER_H, QColor(p.surface))
        painter.fillRect(0, RULER_H - 1, HEADER_W, 1, QColor(p.border))

    def _paint_playhead(self, painter: QPainter, h: int) -> None:
        x = self.frame_to_x(self.playhead)
        if x < HEADER_W - 1 or x > self.viewport().width() + 1:
            return
        p = theme().palette
        painter.setPen(QPen(QColor(p.forest), 2))
        painter.drawLine(int(x), 6, int(x), h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.forest))
        painter.drawRoundedRect(QRectF(x - 6, 4, 12, 14), 3, 3)

    # --- souris ------------------------------------------------------------------

    def _find_clip(self, clip_id: str | None) -> Clip | None:
        return next((c for c in self.controller.project.clips if c.id == clip_id), None)

    def hit_test(self, pos: QPoint) -> tuple[Clip, str] | None:
        """Clip sous le pointeur et zone saisie : "start", "end" ou "body"."""
        # dans une zone de transition, le clip de droite (dessiné par-dessus) a priorité
        ordered = sorted(self.controller.project.clips, key=lambda c: c.start)
        for clip in reversed(ordered):
            rect = self.clip_rect(clip)
            if rect is None or not rect.contains(pos.x(), pos.y()):
                continue
            if rect.width() > 3 * EDGE_PX:
                if pos.x() - rect.left() <= EDGE_PX:
                    return clip, "start"
                if rect.right() - pos.x() <= EDGE_PX:
                    return clip, "end"
            return clip, "body"
        return None

    def _header_hit(self, pos: QPoint) -> tuple[Track, str] | None:
        if pos.x() >= HEADER_W or pos.y() < RULER_H:
            return None
        row = self.row_at(pos.y())
        if row is None:
            return None
        for key, rect in self._header_buttons(row):
            if rect.contains(pos):
                return row.track, key
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if pos.x() < HEADER_W:
            hit = self._header_hit(pos)
            if hit is not None:
                track, key = hit
                self._toggle_track(track, key)
            return
        if pos.y() < RULER_H:
            self._drag = _Drag("playhead")
            self._seek_to(pos.x())
            return
        transition = self.transition_at(pos)
        if transition is not None:
            self.controller.select_transition(transition.id)
            self.viewport().update()
            return
        hit = self.hit_test(pos)
        if hit is None:
            self.controller.select(None)
            self._drag = _Drag("playhead")
            self._seek_to(pos.x())
            return
        clip, zone = hit
        self.controller.select(clip.id)
        mode = "move" if zone == "body" else zone
        self._drag = _Drag(mode, clip.id, pos, self.x_to_frame(pos.x()) - clip.start,
                           clip.track_id, clip.start, clip.duration)
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor if mode == "move"
                                  else Qt.CursorShape.SizeHorCursor)

    def _seek_to(self, x: float) -> None:
        frame = self.x_to_frame(max(HEADER_W, x))
        self.set_playhead(frame)
        self.seekRequested.emit(frame)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        d = self._drag
        if d is None:
            self._update_hover(pos)
            return
        if d.mode == "playhead":
            self._seek_to(pos.x())
            return
        if not d.moved and (pos - d.press).manhattanLength() < 3:
            return
        d.moved = True
        clip = self._find_clip(d.clip_id)
        if clip is None:
            return
        timeline = self.controller.timeline
        frame = self.x_to_frame(pos.x())
        if d.mode == "move":
            start = self._snap(frame - d.offset, clip.id, (clip.duration,))
            row = self.row_at(pos.y())
            track_id = clip.track_id
            if row is not None and timeline.accepts_clip(row.track, clip):
                track_id = row.track.id
            d.track_id = track_id
            d.start = timeline.free_start(track_id, start, clip.duration, ignore=clip.id)
            d.duration = clip.duration
        else:
            # le bord suit le déplacement du pointeur depuis le clic
            grabbed = clip.start if d.mode == "start" else clip.end
            low, high = timeline.trim_bounds(clip.id, d.mode)
            edge = self._snap(grabbed + frame - self.x_to_frame(d.press.x()), clip.id)
            edge = max(low, min(high, edge))
            if d.mode == "start":
                d.start, d.duration = edge, clip.end - edge
            else:
                d.start, d.duration = clip.start, edge - clip.start
        self.viewport().update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        d, self._drag = self._drag, None
        self.viewport().unsetCursor()
        if d is None or d.mode == "playhead" or not d.moved or d.clip_id is None:
            self.viewport().update()
            return
        clip_id = d.clip_id
        if d.mode == "move":
            self.controller.edit(_("Déplacer le clip"),
                                 lambda t: t.move_clip(clip_id, d.track_id, d.start))
        elif d.mode == "start":
            self.controller.edit(_("Rogner le clip"), lambda t: t.trim(clip_id, "start", d.start))
        else:
            self.controller.edit(_("Rogner le clip"),
                                 lambda t: t.trim(clip_id, "end", d.start + d.duration))
        self.viewport().update()

    def _update_hover(self, pos: QPoint) -> None:
        header = self._header_hit(pos)
        hover = (header[0].id, header[1]) if header else None
        if hover != self._hover_header:
            self._hover_header = hover
            self.viewport().update()
        hit = self.hit_test(pos) if pos.x() >= HEADER_W and pos.y() >= RULER_H else None
        if hit is None:
            self.viewport().unsetCursor()
        elif hit[1] == "body":
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.SizeHorCursor)

    def _toggle_track(self, track: Track, key: str) -> None:
        track_id = track.id
        if key == "mute":
            label = _("Réactiver le son") if track.muted else _("Couper le son de la piste")
            self.controller.edit(label, lambda t: setattr(t.track(track_id), "muted",
                                                          not t.track(track_id).muted))
        else:
            label = _("Afficher la piste") if track.hidden else _("Masquer la piste")
            self.controller.edit(label, lambda t: setattr(t.track(track_id), "hidden",
                                                          not t.track(track_id).hidden))

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 ** (delta.y() / 120)
            self.set_zoom(self.pps * factor, event.position().x())
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier or delta.x():
            amount = delta.x() or delta.y()
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - amount)
            return
        if self.verticalScrollBar().maximum() > 0:
            super().wheelEvent(event)
        else:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta.y())

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        pos = event.pos()
        menu = QMenu(self)
        if pos.x() < HEADER_W:
            row = self.row_at(pos.y())
            if row is None:
                return
            track_id = row.track.id
            if row.track.kind != "text":
                menu.addAction(self._volume_action(menu, row.track))
                menu.addSeparator()
            menu.addAction(_("Supprimer la piste"), lambda: self.controller.edit(
                _("Supprimer la piste"), lambda t: t.remove_track(track_id)))
        else:
            hit = self.hit_test(pos)
            if hit is None:
                return
            clip_id = hit[0].id
            self.controller.select(clip_id)
            menu.addAction(_("Couper à la tête de lecture"), lambda: self.controller.edit(
                _("Couper"), lambda t: t.split_at(self.playhead, clip_id)))
            menu.addAction(_("Dupliquer"), lambda: self.controller.edit(
                _("Dupliquer"), lambda t: t.duplicate(clip_id)))
            timeline = self.controller.timeline
            right = timeline.neighbour(clip_id, "right")
            if right is not None and timeline.transition_after(clip_id) is None:
                right_id = right.id
                menu.addAction(_("Ajouter un fondu enchaîné avec le clip suivant"),
                               lambda: self.controller.edit(
                                   _("Ajouter une transition"),
                                   lambda t: t.add_transition(clip_id, right_id, "dissolve")))
            media = self.controller.project.find_media(hit[0].media_id)
            if (media is not None and media.kind == "video" and media.has_audio
                    and timeline.track(hit[0].track_id).kind == "video" and hit[0].volume > 0):
                menu.addAction(_("Détacher l'audio"), lambda: self.controller.edit(
                    _("Détacher l'audio"), lambda t: t.detach_audio(clip_id)))
            tools = self.tool_provider(hit[0])
            if tools:
                menu.addSeparator()
                for text, action in tools:
                    menu.addAction(text, action)
            menu.addSeparator()
            menu.addAction(_("Supprimer"), lambda: self.controller.edit(
                _("Supprimer"), lambda t: t.delete(clip_id)))
            menu.addAction(_("Supprimer et refermer l'espace"), lambda: self.controller.edit(
                _("Supprimer et refermer l'espace"), lambda t: t.delete(clip_id, ripple=True)))
        menu.exec(event.globalPos())

    def _volume_action(self, menu: QMenu, track: Track):
        """Curseur « Volume de la piste » intégré au menu contextuel de l'en-tête."""
        from PyQt6.QtWidgets import QWidgetAction

        from montar.ui.editor.controls import SliderRow

        action = QWidgetAction(menu)
        row = SliderRow(_("Volume de la piste"), 0, 200, lambda v: f"{v:.0f} %")
        row.setContentsMargins(12, 4, 12, 4)
        row.setMinimumWidth(220)
        row.set_value(track.volume * 100)
        track_id = track.id
        row.moved.connect(lambda v: self.controller.edit(
            _("Volume de la piste"), lambda t: setattr(t.track(track_id), "volume", v / 100),
            merge=(track_id, "volume")))
        action.setDefaultWidget(row)
        return action

    # --- dépôt de médias ---------------------------------------------------------------

    def _drop_target(self, pos: QPoint, media: MediaItem) -> tuple[str | None, int, int]:
        """(piste, début, durée) du clip qui serait créé ; piste None = nouvelle piste."""
        timeline = self.controller.timeline
        duration = timeline.default_duration(media)
        frame = self.x_to_frame(pos.x())
        row = self.row_at(pos.y())
        if row is not None and timeline.accepts(row.track, media):
            track_id = row.track.id
        elif row is None and pos.y() > RULER_H:
            return None, self._snap(frame, None, (duration,)), duration
        else:
            kind = "audio" if media.kind == "audio" else "video"
            track = timeline.first_track(kind)
            if track is None:
                return None, frame, duration
            track_id = track.id
        start = self._snap(frame, None, (duration,))
        return track_id, timeline.free_start(track_id, start, duration), duration

    def _dragged_media(self, event) -> MediaItem | None:
        if not event.mimeData().hasFormat(MEDIA_MIME):
            return None
        media_id = bytes(event.mimeData().data(MEDIA_MIME)).decode()
        return self.controller.project.find_media(media_id)

    # --- dépôt de transitions sur une jonction --------------------------------------------

    def junction_at(self, pos: QPoint) -> tuple[Clip, Clip] | None:
        """Paire de clips collés dont la jonction est la plus proche du pointeur (≤ 40 px)."""
        row = self.row_at(pos.y())
        if row is None or pos.x() < HEADER_W:
            return None
        timeline = self.controller.timeline
        best, best_dist = None, 40.0
        clips = timeline.clips_on(row.track.id)
        for left, right in zip(clips, clips[1:], strict=False):
            if right.start != left.end or timeline.transition_after(left.id) is not None:
                continue
            dist = abs(self.frame_to_x(left.end) - pos.x())
            if dist < best_dist:
                best, best_dist = (left, right), dist
        return best

    def _dragged_transition(self, event) -> str | None:
        if not event.mimeData().hasFormat(TRANSITION_MIME):
            return None
        return bytes(event.mimeData().data(TRANSITION_MIME)).decode()

    def _paint_junction(self, painter: QPainter, pair: tuple[Clip, Clip]) -> None:
        p = theme().palette
        rect = self.clip_rect(pair[0])
        if rect is None:
            return
        x = rect.right()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.forest))
        painter.drawRoundedRect(QRectF(x - 2, rect.top() - 4, 4, rect.height() + 8), 2, 2)
        badge = QRectF(x - 14, rect.center().y() - 12, 28, 24)
        painter.setBrush(QColor(p.surface))
        painter.setPen(QPen(QColor(p.forest), 2))
        painter.drawRoundedRect(badge, 8, 8)
        painter.drawPixmap(int(badge.center().x()) - 8, int(badge.center().y()) - 8,
                           icon_pixmap("blend", p.forest, 16))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._dragged_media(event) is not None or self._dragged_transition(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragged_transition(event):
            self._junction = self.junction_at(event.position().toPoint())
            self.viewport().update()
            if self._junction is not None:
                event.acceptProposedAction()
            else:
                event.ignore()
            return
        media = self._dragged_media(event)
        if media is None:
            return
        track_id, start, duration = self._drop_target(event.position().toPoint(), media)
        self._drop = (track_id, start, duration, media.kind)
        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop = None
        self._junction = None
        self.viewport().update()

    def dropEvent(self, event) -> None:  # noqa: N802
        kind = self._dragged_transition(event)
        if kind:
            self._junction = None
            pair = self.junction_at(event.position().toPoint())
            self.viewport().update()
            if pair is not None:
                self.add_transition(pair[0].id, pair[1].id, kind)
                event.acceptProposedAction()
            return
        media = self._dragged_media(event)
        self._drop = None
        if media is None:
            return
        track_id, start, duration = self._drop_target(event.position().toPoint(), media)
        self.add_media(media, track_id, start)
        event.acceptProposedAction()

    def add_transition(self, left_id: str, right_id: str, kind: str) -> None:
        transition = self.controller.edit(_("Ajouter une transition"),
                                          lambda t: t.add_transition(left_id, right_id, kind))
        if transition is not None:
            self.controller.select_transition(transition.id)

    def add_media(self, media: MediaItem, track_id: str | None, start: int | None) -> None:
        def operation(t):
            tid = track_id
            if tid is None:
                tid = t.add_track("audio" if media.kind == "audio" else "video").id
            return t.add_clip(media, tid, start)

        clip = self.controller.edit(_("Ajouter à la timeline"), operation)
        if clip is not None:
            self.controller.select(clip.id)

    def clear_caches(self) -> None:
        self._thumb_cache.clear()
        self.viewport().update()

