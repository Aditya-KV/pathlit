"""See-through, click-through, always-on-top overlay (FR-5). It only draws; it never touches the learner's apps.

A pointer glides smoothly from where it last was to the next target, pulses once it arrives, and a small bubble is
placed where it hides the least text.
"""
from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QWidget

from ..capture import px_to_logical
from .arrow import cursor_polygon, cursor_rect, glide_ms, place_bubble, tip_for
from .capture_exclusion import exclude_from_capture

ACCENT = QColor(79, 124, 255)
BUBBLE_MAX_W = 300
HISTORY_S = 120          # glide from the last position only if it was shown this recently


class OverlayWindow(QWidget):
    _show_sig = pyqtSignal(object)
    _hide_sig = pyqtSignal()
    _clear_sig = pyqtSignal()
    _control_sig = pyqtSignal(bool)
    _banner_sig = pyqtSignal(object)

    def __init__(self, arrow_seconds: float = 15) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self._logical_size = (screen.geometry().width(), screen.geometry().height())
        self.logical_width = screen.geometry().width()
        self._seconds = arrow_seconds
        self._hidden_ack = threading.Event()

        self._target: tuple[float, float, float, float] | None = None
        self._tip: tuple[float, float] | None = None
        self._last_tip: tuple[float, float] | None = None
        self._last_time = 0.0
        self._bubble: tuple[float, float, float, float] | None = None
        self._text = ""
        self._opacity = 0.0
        self._pulse_v = 1.0
        self._start = (0.0, 0.0)
        self._end = (0.0, 0.0)

        self._glide = QVariantAnimation(self)
        self._glide.setStartValue(0.0)
        self._glide.setEndValue(1.0)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.valueChanged.connect(self._on_glide)
        self._glide.finished.connect(self._on_arrived)

        self._fade = QVariantAnimation(self)
        self._fade.setDuration(180)
        self._fade.valueChanged.connect(self._on_fade)

        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(900)
        self._pulse.setLoopCount(2)
        self._pulse.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._pulse.valueChanged.connect(self._on_pulse)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade_done = QTimer(self)
        self._fade_done.setSingleShot(True)
        self._fade_done.timeout.connect(self._do_hide)

        self._show_sig.connect(self._do_show)
        self._hide_sig.connect(self._do_hide)
        self._clear_sig.connect(self._fade_out)
        self._control_sig.connect(self._do_set_controlling)
        self._banner_sig.connect(self._do_set_banner)
        self.excluded_from_capture = False
        self._controlling = False                    # Pathlit is moving the real mouse: red border and banner (FR-30)
        self._banner: str | None = None

    def _exclude_from_capture(self) -> None:
        if not self.excluded_from_capture:
            self.excluded_from_capture = exclude_from_capture(self)

    # ---- thread-safe API used by the controller (any thread) ----
    def show_arrow(self, bbox_px: tuple[int, int, int, int], text: str, capture_size: tuple[int, int],
                   obstacles: list[tuple[int, int, int, int]] | None = None) -> None:
        self._show_sig.emit((bbox_px, text, capture_size, obstacles or []))

    def set_controlling(self, on: bool) -> None:
        """FR-30: a red border and a banner while Pathlit is sending mouse input. Safe from any thread."""
        self._control_sig.emit(bool(on))

    def set_banner(self, text: str | None) -> None:
        """A line of text at the top of the screen, for actions that have no pointer target (direct Blender actions)."""
        self._banner_sig.emit(text)

    def clear(self) -> None:
        """Fade the pointer and bubble away (the step is over, or the next step has nothing to point at)."""
        self._clear_sig.emit()

    dismiss = clear                                      # the learner clicked the target: same quick fade

    def hide_and_wait(self, timeout: float = 0.5) -> None:
        self._hidden_ack.clear()
        self._hide_sig.emit()
        self._hidden_ack.wait(timeout)

    # ---- helpers ----
    def _to_logical_rect(self, bbox, capture_size):
        x, y, w, h = bbox
        lx, ly = px_to_logical(x, y, capture_size, self._logical_size)
        lx2, ly2 = px_to_logical(x + w, y + h, capture_size, self._logical_size)
        return (lx, ly, lx2 - lx, ly2 - ly)

    def _bubble_size(self, text: str) -> tuple[float, float]:
        fm = QFontMetrics(self._font())
        r = fm.boundingRect(0, 0, BUBBLE_MAX_W - 24, 10_000, int(Qt.TextFlag.TextWordWrap), text)
        return float(min(BUBBLE_MAX_W, r.width() + 24)), float(r.height() + 16)

    @staticmethod
    def _font() -> QFont:
        f = QFont("Segoe UI", 12)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _invalidate(self, *rects) -> None:
        for r in rects:
            if r is not None:
                self.update(QRectF(*r).adjusted(-26, -26, 26, 26).toAlignedRect())

    # ---- main-thread slots ----
    def _do_set_controlling(self, on: bool) -> None:
        self._controlling = on
        if on:
            self.show()
            self.raise_()
            self._exclude_from_capture()
        elif self._tip is None and not self._banner:
            self.hide()
        self.update()

    def _do_set_banner(self, text) -> None:
        self._banner = text
        if text:
            self.show()
            self.raise_()
            self._exclude_from_capture()
        elif not self._controlling and self._tip is None:
            self.hide()
        self.update()

    def _do_show(self, payload) -> None:
        bbox_px, text, capture_size, obstacles_px = payload
        self._timer.stop()
        self._fade_done.stop()
        old_target, old_bubble, old_tip = self._target, self._bubble, self._tip
        target = self._to_logical_rect(bbox_px, capture_size)
        obstacles = [self._to_logical_rect(o, capture_size) for o in obstacles_px]
        end = tip_for(target)

        if self.isVisible() and self._tip is not None:
            start = self._tip                                    # keep gliding from where the pointer is now
        elif self._last_tip is not None and time.time() - self._last_time < HISTORY_S:
            start = self._last_tip                               # carry on from the previous step's target
        else:
            start = (self._logical_size[0] / 2, self._logical_size[1] / 2)   # first time: fly in from the middle
        dist = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5

        self._target, self._text = target, text
        self._bubble = place_bubble(target, self._bubble_size(text), self._logical_size, obstacles)
        self._start, self._end, self._tip = start, end, start
        self._pulse.stop()
        self._pulse_v = 1.0
        self._glide.stop()
        self._glide.setDuration(glide_ms(dist) if dist > 4 else 1)
        self.show()
        self.raise_()
        self._exclude_from_capture()
        self._fade.stop()
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._glide.start()
        self._invalidate(old_target, old_bubble, cursor_rect(old_tip) if old_tip else None, self._bubble, target)
        self._timer.start(int(self._seconds * 1000))

    def _on_glide(self, v) -> None:
        old = self._tip
        self._tip = (self._start[0] + (self._end[0] - self._start[0]) * v,
                     self._start[1] + (self._end[1] - self._start[1]) * v)
        self._invalidate(cursor_rect(old) if old else None, cursor_rect(self._tip))

    def _on_arrived(self) -> None:
        self._tip = self._end
        self._last_tip, self._last_time = self._end, time.time()
        self._pulse.start()
        self._invalidate(self._target, cursor_rect(self._end))

    def _on_pulse(self, v) -> None:
        self._pulse_v = float(v)
        self._invalidate(self._target)

    def _on_fade(self, v) -> None:
        self._opacity = float(v)
        self.update()

    def _fade_out(self) -> None:
        if self._tip is None:
            return                                       # nothing on screen
        self._timer.stop()
        self._glide.stop()
        self._pulse.stop()
        self._fade.setDuration(140)
        self._fade.stop()
        self._fade.setStartValue(self._opacity)
        self._fade.setEndValue(0.0)
        self._fade.start()
        self._fade_done.start(220)

    def _do_hide(self) -> None:
        for t in (self._timer, self._fade_done):
            t.stop()
        for a in (self._glide, self._fade, self._pulse):
            a.stop()
        if self._tip is not None:
            self._last_tip, self._last_time = self._tip, time.time()      # remember where we were for the next glide
        self._tip = self._target = self._bubble = None
        self._opacity = 0.0
        if self._controlling or self._banner:
            self.update()                                # the red border and banner stay while input is being sent
        else:
            self.hide()
        self._hidden_ack.set()

    # ---- drawing ----
    def _paint_control_banner(self, p: QPainter) -> None:
        w = self.width()
        if self._controlling:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(220, 38, 38), 8))
            p.drawRect(self.rect().adjusted(4, 4, -4, -4))
        lines = []
        if self._controlling:
            lines.append("Pathlit is controlling your mouse. Press Esc to stop.")
        if self._banner:
            lines.append(self._banner)
        if not lines:
            return
        f = QFont("Segoe UI", 13)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        bw = min(w - 40, max(fm.horizontalAdvance(t) for t in lines) + 40)
        bh = len(lines) * (fm.height() + 6) + 14
        rect = QRectF((w - bw) / 2, 14, bw, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(185, 28, 28, 240) if self._controlling else QColor(24, 26, 32, 240))
        p.drawRoundedRect(rect, 12, 12)
        p.setPen(QColor(255, 255, 255))
        for i, t in enumerate(lines):
            p.drawText(QRectF(rect.left(), rect.top() + 8 + i * (fm.height() + 6), rect.width(), fm.height() + 4),
                       int(Qt.AlignmentFlag.AlignCenter), t)

    def paintEvent(self, _event) -> None:
        if self._controlling or self._banner:
            q = QPainter(self)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_control_banner(q)
            q.end()
        if self._tip is None or self._target is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)

        # target highlight and arrival pulse
        t = QRectF(*self._target).adjusted(-4, -3, 4, 3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 230), 2))
        p.drawRoundedRect(t, 6, 6)
        if self._pulse_v < 1.0:
            grow = 14 * self._pulse_v
            p.setPen(QPen(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), int(200 * (1 - self._pulse_v))), 2))
            p.drawRoundedRect(t.adjusted(-grow, -grow, grow, grow), 8 + grow / 2, 8 + grow / 2)

        # bubble
        if self._bubble:
            b = QRectF(*self._bubble)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawRoundedRect(b.translated(0, 2), 10, 10)
            p.setBrush(QColor(24, 26, 32, 240))
            p.drawRoundedRect(b, 10, 10)
            p.setBrush(ACCENT)
            p.drawRoundedRect(QRectF(b.left(), b.top() + 8, 3, b.height() - 16), 1.5, 1.5)
            p.setFont(self._font())
            p.setPen(QColor(255, 255, 255))
            p.drawText(b.adjusted(14, 8, -10, -8), int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap), self._text)

        # the pointer: soft shadow, then white outline with the accent fill
        poly = [QPointF(*pt) for pt in cursor_polygon(self._tip)]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 85))
        p.drawPolygon(QPolygonF([QPointF(pt.x() + 2, pt.y() + 3) for pt in poly]))
        p.setPen(QPen(QColor(255, 255, 255), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(ACCENT)
        p.drawPolygon(QPolygonF(poly))
        p.end()
