"""The Pathlit control panel: type a task, watch the steps tick off (SRS 4: "small control panel").

Styled after shadcn/ui: a quiet zinc palette, 1 px borders, small radii, flat surfaces, a thin progress bar and one
white primary button. A tab-style mode switch with a sliding thumb, an input with a focus ring, outline suggestion
badges, step rows that check off, and an alert-style status line. Everything is drawn with plain Qt (no new dependency).
The panel never touches Blender, and it is hidden from screen capture, so its text is never read as Blender's screen.

The public interface is unchanged: signals plan_requested / start_requested / mode_requested and the slots
set_mode, set_busy, set_status, show_state (fed by PanelBridge from other threads).
"""
from __future__ import annotations

import math

from PyQt6.QtCore import (QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                          QVariantAnimation, pyqtProperty, pyqtSignal)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLayout, QLineEdit,
                             QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..overlay.capture_exclusion import exclude_from_capture

# ---- design tokens (shadcn "zinc", dark) ----
BACKGROUND = QColor("#09090b")
FOREGROUND = QColor("#fafafa")
MUTED_FG = QColor("#a1a1aa")
SUBTLE_FG = QColor("#71717a")
SECONDARY = QColor("#18181b")        # zinc-900: soft fills
BORDER = QColor("#27272a")           # zinc-800
BORDER_STRONG = QColor("#3f3f46")    # zinc-700
RING = QColor("#a1a1aa")
SUCCESS = QColor("#34d399")
DESTRUCTIVE = QColor("#f87171")
MODE_DOT = {"teach": QColor("#60a5fa"), "show": QColor("#fbbf24"), "do": QColor("#f87171")}
ACCENT = MODE_DOT                    # kept for callers that import the old name

MODES = (("teach", "Teach me"), ("show", "Show me"), ("do", "Do it"))
TAGLINE = {"teach": "I point. You click.", "show": "I move the mouse. You approve each step.",
           "do": "I do it for you. Esc stops me."}
SUGGESTIONS = ("a coffee mug", "a simple house", "a donut")
FAMILIES = ["Inter", "Segoe UI Variable Text", "Segoe UI"]
OUTER = 16                           # transparent margin that holds the drop shadow
WIDTH, HEIGHT = 420, 640
COLLAPSED_H = 60 + 2 * OUTER
MAX_STATUS_CHARS = 320


def _alpha(c: QColor, a: int) -> QColor:
    return QColor(c.red(), c.green(), c.blue(), max(0, min(255, a)))


def _font(points: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(FAMILIES[0])
    f.setFamilies(FAMILIES)
    f.setPointSizeF(points)
    f.setWeight(weight)
    return f


def _animate(target: QObject, prop: bytes, end: float, ms: int = 200,
             curve: QEasingCurve.Type = QEasingCurve.Type.OutCubic) -> QPropertyAnimation:
    anim = QPropertyAnimation(target, prop, target)
    anim.setDuration(ms)
    anim.setEndValue(end)
    anim.setEasingCurve(curve)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


class PanelBridge(QObject):
    """Thread-safe way for background threads to update the panel."""
    state = pyqtSignal(object)       # lesson progress: {"title", "steps", "index", "complete", "custom"}
    status = pyqtSignal(str)         # a line of text under the task box
    busy = pyqtSignal(bool)
    mode = pyqtSignal(str)           # the current mode, so the buttons follow the tray menu


# =====================================================================================================================
# small custom widgets
# =====================================================================================================================
class Card(QFrame):
    """The window body: flat background, 1 px border, 12 px radius."""

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(BACKGROUND)
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(r, 12, 12)


class TitleBar(QWidget):
    """Drag the window by this bar (the system handles the move)."""

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()


class Dot(QWidget):
    """A small dot in the mode's colour (a tiny status light, like a shadcn badge dot)."""

    def __init__(self, size: int = 10) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._color = MODE_DOT["teach"]

    def set_color(self, c: QColor) -> None:
        self._color = c
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        outer = min(self.width(), self.height()) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(self._color, 50))
        p.drawEllipse(c, outer, outer)
        p.setBrush(self._color)
        p.drawEllipse(c, outer * 0.55, outer * 0.55)


class Chevron(QWidget):
    """Ghost icon button that collapses or expands the panel; the arrow turns smoothly."""
    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Collapse or expand")
        self._turn = 0.0
        self._hover = 0.0

    @pyqtProperty(float)
    def turn(self) -> float:
        return self._turn

    @turn.setter
    def turn(self, v: float) -> None:
        self._turn = v
        self.update()

    @pyqtProperty(float)
    def hover(self) -> float:
        return self._hover

    @hover.setter
    def hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        _animate(self, b"turn", 1.0 if collapsed else 0.0, 220)

    def enterEvent(self, _e) -> None:
        _animate(self, b"hover", 1.0, 120)

    def leaveEvent(self, _e) -> None:
        _animate(self, b"hover", 0.0, 160)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(BORDER, int(255 * self._hover)))
        p.drawRoundedRect(QRectF(self.rect()), 7, 7)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(180 * self._turn)
        pen = QPen(MUTED_FG if self._hover < 0.5 else FOREGROUND, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(-4, -2), QPointF(0, 2), QPointF(4, -2)])


class Segmented(QWidget):
    """shadcn Tabs: a muted track and a raised thumb that slides to the chosen mode."""
    changed = pyqtSignal(str)

    def __init__(self, items: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self._items = items
        self._pill = 0.0
        self._hover = -1
        self.setFixedHeight(38)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @pyqtProperty(float)
    def pill(self) -> float:
        return self._pill

    @pill.setter
    def pill(self, v: float) -> None:
        self._pill = v
        self.update()

    def current(self) -> str:
        return self._items[int(round(self._pill))][0]

    def set_current(self, key: str, animate: bool = True) -> None:
        idx = [k for k, _ in self._items].index(key)
        if animate:
            _animate(self, b"pill", float(idx), 240, QEasingCurve.Type.OutCubic)
        else:
            self.pill = float(idx)

    def _index_at(self, x: float) -> int:
        seg = (self.width() - 6) / len(self._items)
        return max(0, min(len(self._items) - 1, int((x - 3) // seg)))

    def mouseMoveEvent(self, e) -> None:
        i = self._index_at(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.changed.emit(self._items[self._index_at(e.position().x())][0])

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(SECONDARY)
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(r, 9, 9)
        n = len(self._items)
        seg = (r.width() - 6) / n
        thumb = QRectF(r.left() + 3 + self._pill * seg, r.top() + 3, seg, r.height() - 6)
        p.setBrush(QColor("#27272a"))
        p.setPen(QPen(BORDER_STRONG, 1))
        p.drawRoundedRect(thumb, 7, 7)
        for i, (_k, label) in enumerate(self._items):
            near = max(0.0, 1.0 - abs(i - self._pill))
            if near > 0.5:
                col = FOREGROUND
            else:
                col = QColor(MUTED_FG)
                if i == self._hover:
                    col = QColor("#d4d4d8")
            p.setPen(col)
            p.setFont(_font(9.5, QFont.Weight.Medium))
            p.drawText(QRectF(r.left() + 3 + i * seg, r.top(), seg, r.height()), int(Qt.AlignmentFlag.AlignCenter), label)


class SendButton(QPushButton):
    """Small primary icon button (arrow up) inside the input."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = 0.0

    @pyqtProperty(float)
    def hover(self) -> float:
        return self._hover

    @hover.setter
    def hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def enterEvent(self, _e) -> None:
        _animate(self, b"hover", 1.0, 110)

    def leaveEvent(self, _e) -> None:
        _animate(self, b"hover", 0.0, 160)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isDown():
            r = r.adjusted(1, 1, -1, -1)
        on = self.isEnabled()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(250, 250, 250, int(255 - 25 * self._hover)) if on else SECONDARY)
        p.drawRoundedRect(r, 8, 8)
        pen = QPen(QColor("#18181b") if on else QColor("#52525b"), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = r.center()
        p.drawLine(QPointF(c.x(), c.y() + 5), QPointF(c.x(), c.y() - 5))
        p.drawPolyline([QPointF(c.x() - 4.5, c.y() - 0.5), QPointF(c.x(), c.y() - 5), QPointF(c.x() + 4.5, c.y() - 0.5)])


class PromptBox(QFrame):
    """shadcn Input: 1 px border, and a soft ring while it has focus."""
    submitted = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._glow = 0.0
        self._busy = False
        self.last_goal = ""
        self.setFixedHeight(46)
        self.edit = QLineEdit()
        self.edit.setFrame(False)
        self.edit.setPlaceholderText("What do you want to make in Blender?")
        self.edit.installEventFilter(self)
        self.send = SendButton()
        self.send.setToolTip("Plan the steps (Enter)")
        self.send.setDisabled(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(8)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.send)
        self.edit.textChanged.connect(self._refresh)
        self.edit.returnPressed.connect(self._submit)
        self.send.clicked.connect(self._submit)

    @pyqtProperty(float)
    def glow(self) -> float:
        return self._glow

    @glow.setter
    def glow(self, v: float) -> None:
        self._glow = v
        self.update()

    def set_accent(self, _c: QColor) -> None:           # the input stays neutral in every mode
        pass

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.edit.setDisabled(busy)
        self._refresh()
        self.update()

    def _refresh(self) -> None:
        self.send.setEnabled(bool(self.edit.text().strip()) and not self._busy)

    def _submit(self) -> None:
        goal = self.edit.text().strip()
        if goal and not self._busy:
            self.last_goal = goal
            self.edit.clear()
            self.submitted.emit(goal)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.edit:
            t = ev.type()
            if t == QEvent.Type.FocusIn:
                _animate(self, b"glow", 1.0, 150)
            elif t == QEvent.Type.FocusOut:
                _animate(self, b"glow", 0.0, 200)
            elif t == QEvent.Type.KeyPress:
                if ev.key() == Qt.Key.Key_Escape and self.edit.text():
                    self.edit.clear()
                    return True
                if ev.key() == Qt.Key.Key_Up and not self.edit.text() and self.last_goal:
                    self.edit.setText(self.last_goal)
                    return True
        return super().eventFilter(obj, ev)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
        if self._glow > 0.01:                                   # focus ring
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_alpha(RING, int(70 * self._glow)), 3))
            p.drawRoundedRect(r, 9, 9)
        p.setBrush(_alpha(SECONDARY, 160 if not self._busy else 90))
        edge = QColor(BORDER_STRONG if self._glow < 0.01 else RING)
        if 0.01 < self._glow < 1.0:
            edge = QColor(int(BORDER_STRONG.red() + (RING.red() - BORDER_STRONG.red()) * self._glow),
                          int(BORDER_STRONG.green() + (RING.green() - BORDER_STRONG.green()) * self._glow),
                          int(BORDER_STRONG.blue() + (RING.blue() - BORDER_STRONG.blue()) * self._glow))
        p.setPen(QPen(edge if self._glow > 0.01 else BORDER, 1))
        p.drawRoundedRect(r, 8, 8)


class BusyBar(QWidget):
    """A thin indeterminate bar while the plan is being written."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(3)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1100)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)
        self.hide()

    def set_accent(self, _c: QColor) -> None:
        pass

    def _tick(self, v) -> None:
        self._t = float(v)
        self.update()

    def run(self, on: bool) -> None:
        if on:
            self.show()
            self._anim.start()
        else:
            self._anim.stop()
            self.hide()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BORDER)
        p.drawRoundedRect(self.rect(), 1.5, 1.5)
        w = self.width() * 0.3
        x = -w + (self.width() + w) * self._t
        p.setBrush(FOREGROUND)
        p.drawRoundedRect(QRectF(x, 0, w, self.height()).intersected(QRectF(self.rect())), 1.5, 1.5)


class Progress(QWidget):
    """shadcn Progress: a slim rounded bar that fills smoothly."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(6)
        self._value = 0.0
        self._done = False

    @pyqtProperty(float)
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float) -> None:
        self._value = v
        self.update()

    def set_progress(self, fraction: float, done: bool = False) -> None:
        self._done = done
        _animate(self, b"value", max(0.0, min(1.0, fraction)), 500)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BORDER)
        r = QRectF(self.rect())
        p.drawRoundedRect(r, 3, 3)
        if self._value > 0.004:
            p.setBrush(SUCCESS if self._done else FOREGROUND)
            p.drawRoundedRect(QRectF(0, 0, max(6.0, r.width() * self._value), r.height()), 3, 3)


class AlertIcon(QWidget):
    """Info / success / error glyph for the status line."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(16, 16)
        self.kind = "info"

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = {"info": MUTED_FG, "ok": SUCCESS, "error": DESTRUCTIVE}[self.kind]
        pen = QPen(col, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.drawEllipse(r)
        c = r.center()
        if self.kind == "ok":
            p.drawPolyline([QPointF(c.x() - 2.6, c.y() + 0.2), QPointF(c.x() - 0.6, c.y() + 2.2), QPointF(c.x() + 3, c.y() - 2)])
        elif self.kind == "error":
            p.drawLine(QPointF(c.x(), c.y() - 3), QPointF(c.x(), c.y() + 0.6))
            p.drawPoint(QPointF(c.x(), c.y() + 3))
        else:
            p.drawLine(QPointF(c.x(), c.y() - 0.2), QPointF(c.x(), c.y() + 3))
            p.drawPoint(QPointF(c.x(), c.y() - 3))


class StepRow(QWidget):
    """One step. Drawn by hand so the marker, fill and text can animate together."""
    PAD_L, PAD_R, PAD_V = 46, 14, 10

    def __init__(self, number: int, text: str, accent: QColor = FOREGROUND) -> None:
        super().__init__()
        self.number, self.text = number, text
        self.state = "todo"
        self._emph = 0.0
        self._hover = 0.0
        self._appear = 0.0
        self._pulse = 0.0
        self._done_t = 0.0
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setToolTip(text)

    # ---- animated properties ----
    @pyqtProperty(float)
    def emph(self) -> float:
        return self._emph

    @emph.setter
    def emph(self, v: float) -> None:
        self._emph = v
        self.update()

    @pyqtProperty(float)
    def hover(self) -> float:
        return self._hover

    @hover.setter
    def hover(self, v: float) -> None:
        self._hover = v
        self.update()

    @pyqtProperty(float)
    def appear(self) -> float:
        return self._appear

    @appear.setter
    def appear(self, v: float) -> None:
        self._appear = v
        self.update()

    @pyqtProperty(float)
    def done_t(self) -> float:
        return self._done_t

    @done_t.setter
    def done_t(self, v: float) -> None:
        self._done_t = v
        self.update()

    def reveal(self) -> None:
        _animate(self, b"appear", 1.0, 260)

    def set_pulse(self, v: float) -> None:
        self._pulse = v
        if self.state == "current":
            self.update()

    def set_accent(self, _c: QColor) -> None:
        pass

    def set_state(self, state: str, animate: bool = True) -> None:
        if state == self.state:
            return
        was = self.state
        self.state = state
        target = 1.0 if state == "current" else 0.0
        done = 1.0 if state == "done" else 0.0
        if animate:
            _animate(self, b"emph", target, 240)
            _animate(self, b"done_t", done, 340, QEasingCurve.Type.OutBack if was == "current" else QEasingCurve.Type.OutCubic)
        else:
            self.emph, self.done_t = target, done

    # ---- size: the text wraps, so the height depends on the width ----
    def _text_height(self, w: int) -> int:
        fm = QFontMetrics(_font(10, QFont.Weight.Medium))
        return fm.boundingRect(QRectF(0, 0, max(40, w - self.PAD_L - self.PAD_R), 10000).toRect(),
                               int(Qt.TextFlag.TextWordWrap), self.text).height()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return max(42, self._text_height(w) + 2 * self.PAD_V)

    def sizeHint(self) -> QSize:
        return QSize(320, self.heightForWidth(320))

    def minimumSizeHint(self) -> QSize:
        return QSize(120, 42)

    def enterEvent(self, _e) -> None:
        _animate(self, b"hover", 1.0, 100)

    def leaveEvent(self, _e) -> None:
        _animate(self, b"hover", 0.0, 160)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._appear)
        p.translate(0, (1.0 - self._appear) * 6)
        card = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        p.setPen(Qt.PenStyle.NoPen)
        if self._hover > 0.01 and self._emph < 0.99:
            p.setBrush(_alpha(SECONDARY, int(150 * self._hover)))
            p.drawRoundedRect(card, 8, 8)
        if self._emph > 0.01:
            p.setBrush(_alpha(SECONDARY, int(255 * self._emph)))
            p.setPen(QPen(_alpha(BORDER_STRONG, int(255 * self._emph)), 1))
            p.drawRoundedRect(card, 8, 8)
        cx, cy = 24.0, self.PAD_V + 9.0
        # marker
        if self.state == "done" or self._done_t > 0.01:
            s = 0.6 + 0.4 * min(1.0, self._done_t)
            t = min(1.0, self._done_t)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alpha(FOREGROUND, int(255 * t)))
            p.drawEllipse(QPointF(cx, cy), 9 * s, 9 * s)
            pen = QPen(_alpha(QColor("#18181b"), int(255 * t)), 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([QPointF(cx - 3.6 * s, cy + 0.1 * s), QPointF(cx - 1.0 * s, cy + 2.8 * s),
                            QPointF(cx + 3.9 * s, cy - 2.8 * s)])
        if self.state != "done":
            fade = 1.0 - min(1.0, self._done_t)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self.state == "current":
                p.setPen(QPen(_alpha(FOREGROUND, int(255 * fade)), 1.5))
                p.drawEllipse(QPointF(cx, cy), 9, 9)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(FOREGROUND)
                p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(_alpha(FOREGROUND, int(70 * (1.0 - self._pulse))), 1.2))
                grow = 9 + 6 * self._pulse
                p.drawEllipse(QPointF(cx, cy), grow, grow)
            else:
                p.setPen(QPen(_alpha(BORDER_STRONG, int(255 * fade)), 1.2))
                p.drawEllipse(QPointF(cx, cy), 9, 9)
                p.setPen(_alpha(SUBTLE_FG, int(255 * fade)))
                p.setFont(_font(8, QFont.Weight.Medium))
                p.drawText(QRectF(cx - 10, cy - 10, 20, 20), int(Qt.AlignmentFlag.AlignCenter), str(self.number))
        # text
        col = {"current": FOREGROUND, "done": SUBTLE_FG, "todo": MUTED_FG}[self.state]
        p.setPen(col)
        p.setFont(_font(10, QFont.Weight.Medium if self.state == "current" else QFont.Weight.Normal))
        p.drawText(QRectF(self.PAD_L, self.PAD_V, self.width() - self.PAD_L - self.PAD_R, self.height() - 2 * self.PAD_V),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap), self.text)


class PrimaryButton(QPushButton):
    """shadcn default Button: near-white fill, dark text, the hotkey shown as a small kbd."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key
        self._label = "Start"
        self._hover = 0.0
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @pyqtProperty(float)
    def hover(self) -> float:
        return self._hover

    @hover.setter
    def hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def set_label(self, label: str) -> None:
        self._label = label
        self.update()

    def set_accent(self, _c: QColor) -> None:
        pass

    def enterEvent(self, _e) -> None:
        _animate(self, b"hover", 1.0, 120)

    def leaveEvent(self, _e) -> None:
        _animate(self, b"hover", 0.0, 180)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            r = r.adjusted(0, 1, 0, 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(250, 250, 250, int(255 - 28 * self._hover)) if self.isEnabled() else SECONDARY)
        p.drawRoundedRect(r, 9, 9)
        ink = QColor("#18181b")
        font = _font(10.5, QFont.Weight.DemiBold)
        kfont = _font(8, QFont.Weight.Medium)
        tw = QFontMetrics(font).horizontalAdvance(self._label)
        kw = QFontMetrics(kfont).horizontalAdvance(self.key) + 12
        x = r.center().x() - (tw + 10 + kw) / 2
        p.setPen(ink)
        p.setFont(font)
        p.drawText(QRectF(x, r.top(), tw + 2, r.height()), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   self._label)
        key_rect = QRectF(x + tw + 10, r.center().y() - 9, kw, 18)
        p.setBrush(_alpha(ink, 22))
        p.setPen(QPen(_alpha(ink, 40), 1))
        p.drawRoundedRect(key_rect, 5, 5)
        p.setPen(_alpha(ink, 200))
        p.setFont(kfont)
        p.drawText(key_rect, int(Qt.AlignmentFlag.AlignCenter), self.key)


# =====================================================================================================================
# the panel
# =====================================================================================================================
STYLE = f"""
QWidget {{ background: transparent; color: {FOREGROUND.name()}; font-family: 'Inter', 'Segoe UI Variable Text', 'Segoe UI';
          font-size: 13px; }}
QToolTip {{ background: {BACKGROUND.name()}; color: {FOREGROUND.name()}; border: 1px solid {BORDER_STRONG.name()};
            padding: 5px 9px; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#tagline {{ color: {MUTED_FG.name()}; font-size: 12px; }}
QLabel#kind {{ color: {SUBTLE_FG.name()}; font-size: 11px; font-weight: 500; }}
QLabel#count {{ color: {MUTED_FG.name()}; font-size: 11px; font-weight: 500; }}
QLabel#lesson {{ font-size: 16px; font-weight: 600; }}
QLabel#statusText {{ color: {MUTED_FG.name()}; font-size: 12px; }}
QLabel#try {{ color: {SUBTLE_FG.name()}; font-size: 12px; }}
QLineEdit {{ background: transparent; border: none; color: {FOREGROUND.name()}; font-size: 14px;
            selection-background-color: {BORDER_STRONG.name()}; }}
QLineEdit:disabled {{ color: {SUBTLE_FG.name()}; }}
QPushButton#chip {{ background: transparent; color: {MUTED_FG.name()}; border: 1px solid {BORDER.name()}; border-radius: 13px;
                    padding: 4px 11px; font-size: 12px; }}
QPushButton#chip:hover {{ background: {SECONDARY.name()}; color: {FOREGROUND.name()}; border-color: {BORDER_STRONG.name()}; }}
QPushButton#chip:pressed {{ background: {BORDER.name()}; }}
QPushButton#chip:disabled {{ color: #52525b; border-color: {SECONDARY.name()}; }}
QFrame#rule {{ background: {BORDER.name()}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 1px 2px 0; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG.name()}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #52525b; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


def _alert_style(kind: str) -> str:
    border = {"info": BORDER, "ok": BORDER, "error": QColor("#7f1d1d")}[kind].name()
    return f"QFrame#sc {{ background: transparent; border: 1px solid {border}; border-radius: 8px; }}"


class PathlitPanel(QWidget):
    plan_requested = pyqtSignal(str)
    start_requested = pyqtSignal()
    mode_requested = pyqtSignal(str)

    def __init__(self, hotkey_label: str = "F8") -> None:
        super().__init__()
        self.setWindowTitle("Pathlit")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.mode = "teach"
        self._accent = MODE_DOT["teach"]
        self._rows: list[StepRow] = []
        self._sig: tuple | None = None
        self._collapsed = False
        self._expanded_h = HEIGHT
        self._hint = ""
        self._busy = False
        self._shown_once = False
        self.setStyleSheet(STYLE)
        self.resize(WIDTH, HEIGHT)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - WIDTH - 6, screen.top() + 40)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(OUTER, OUTER, OUTER, OUTER)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.card = Card()
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        root = QVBoxLayout(self.card)
        root.setContentsMargins(18, 0, 18, 18)
        root.setSpacing(0)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # header
        self.bar = TitleBar()
        self.bar.setFixedHeight(60)
        self.bar.setCursor(Qt.CursorShape.SizeAllCursor)
        bar_l = QHBoxLayout(self.bar)
        bar_l.setContentsMargins(0, 0, 0, 0)
        bar_l.setSpacing(10)
        self.dot = Dot(10)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Pathlit")
        title.setObjectName("title")
        self.tagline = QLabel(TAGLINE["teach"])
        self.tagline.setObjectName("tagline")
        texts.addStretch(1)
        texts.addWidget(title)
        texts.addWidget(self.tagline)
        texts.addStretch(1)
        self.chevron = Chevron()
        self.chevron.clicked.connect(self._toggle)
        bar_l.addWidget(self.dot)
        bar_l.addLayout(texts, 1)
        bar_l.addWidget(self.chevron)
        root.addWidget(self.bar)

        # body (everything under the header; hidden when collapsed)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.addWidget(self.body, 1)

        self.seg = Segmented(MODES)
        self.seg.changed.connect(self._mode_clicked)
        body.addWidget(self.seg)

        self.prompt = PromptBox()
        self.prompt.submitted.connect(self.plan_requested)
        self.goal = self.prompt.edit                          # kept for tests and callers
        body.addWidget(self.prompt)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.setContentsMargins(1, 0, 0, 0)
        tryl = QLabel("Try")
        tryl.setObjectName("try")
        chips.addWidget(tryl)
        self.chips: list[QPushButton] = []
        for s in SUGGESTIONS:
            b = QPushButton(s)
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c, text=s: self._chip(text))
            chips.addWidget(b)
            self.chips.append(b)
        chips.addStretch(1)
        body.addLayout(chips)

        self.busy_bar = BusyBar()
        body.addWidget(self.busy_bar)

        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        body.addWidget(rule)

        # lesson header
        self.header = QWidget()
        head = QVBoxLayout(self.header)
        head.setContentsMargins(1, 0, 1, 0)
        head.setSpacing(3)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        self.kind = QLabel("Lesson")
        self.kind.setObjectName("kind")
        self.count = QLabel("")
        self.count.setObjectName("count")
        meta.addWidget(self.kind)
        meta.addStretch(1)
        meta.addWidget(self.count)
        self.lesson_title = QLabel("")
        self.lesson_title.setObjectName("lesson")
        self.lesson_title.setWordWrap(True)
        self.progress = Progress()
        head.addLayout(meta)
        head.addWidget(self.lesson_title)
        head.addSpacing(5)
        head.addWidget(self.progress)
        body.addWidget(self.header)
        self.header.hide()

        # steps
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.steps_host = QWidget()
        self.steps_lay = QVBoxLayout(self.steps_host)
        self.steps_lay.setContentsMargins(0, 0, 4, 0)
        self.steps_lay.setSpacing(1)
        self.steps_lay.addStretch(1)
        self.scroll.setWidget(self.steps_host)
        body.addWidget(self.scroll, 1)

        # status (alert)
        self.status_card = QFrame()
        self.status_card.setObjectName("sc")
        self.status_card.setStyleSheet(_alert_style("info"))
        sl = QHBoxLayout(self.status_card)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(10)
        self.status_icon = AlertIcon()
        self.status = QLabel("")
        self.status.setObjectName("statusText")
        self.status.setWordWrap(True)
        sl.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        sl.addWidget(self.status, 1)
        body.addWidget(self.status_card)

        self.start_btn = PrimaryButton(hotkey_label)
        body.addWidget(self.start_btn)

        # a slow pulse on the current step's marker
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(1800)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse)

        self.start_btn.clicked.connect(self.start_requested)
        self.dot.set_color(self._accent)
        self.set_status("Type a task above, or press the start button to begin the next lesson.")

    # ---- events ----
    def showEvent(self, event) -> None:                       # the window exists now, so it can be hidden from capture
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            exclude_from_capture(self)

    # ---- internals ----
    def _mode_clicked(self, key: str) -> None:
        self.set_mode(key)
        self.mode_requested.emit(key)

    def _chip(self, text: str) -> None:
        if not self._busy:
            self.plan_requested.emit(text)

    def _on_pulse(self, v) -> None:
        for r in self._rows:
            if r.state == "current":
                r.set_pulse(float(v))

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self.chevron.set_collapsed(self._collapsed)
        if self._collapsed:
            self._expanded_h = self.height()
            self.body.hide()
            end = COLLAPSED_H
        else:
            self.body.show()
            end = self._expanded_h
        self._refresh_tagline()
        anim = QVariantAnimation(self)
        anim.setStartValue(self.height())
        anim.setEndValue(end)
        anim.setDuration(260)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: self.resize(self.width(), int(v)))
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _refresh_tagline(self) -> None:
        if self._collapsed and self._hint:
            fm = QFontMetrics(self.tagline.font())
            self.tagline.setText(fm.elidedText(self._hint, Qt.TextElideMode.ElideRight, 290))
        else:
            self.tagline.setText(TAGLINE[self.mode])

    def _build_rows(self, steps: list[str]) -> None:
        for r in self._rows:
            self.steps_lay.removeWidget(r)
            r.hide()                                           # gone at once, not at the next event-loop pass
            r.setParent(None)
            r.deleteLater()
        self._rows = []
        for i, text in enumerate(steps):
            row = StepRow(i + 1, text)
            self.steps_lay.insertWidget(self.steps_lay.count() - 1, row)
            self._rows.append(row)
            QTimer.singleShot(35 * min(i, 12), row.reveal)

    def _scroll_to(self, idx: int) -> None:
        if not (0 <= idx < len(self._rows)):
            return
        row, bar = self._rows[idx], self.scroll.verticalScrollBar()
        target = row.y() + row.height() // 2 - self.scroll.viewport().height() // 2
        target = max(0, min(bar.maximum(), target))
        anim = QPropertyAnimation(bar, b"value", self)
        anim.setDuration(320)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---- slots (same names as before) ----
    def set_mode(self, mode: str) -> None:
        if mode not in MODE_DOT:
            return
        self.mode = mode
        self._accent = MODE_DOT[mode]
        self.seg.set_current(mode)
        self.dot.set_color(self._accent)
        self._refresh_tagline()
        if mode != "teach":
            self.set_status("Press the start key and I will do the steps while you watch. Esc stops me at any time.")

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.prompt.set_busy(busy)
        for b in self.chips:
            b.setDisabled(busy)
        self.busy_bar.run(busy)
        if busy:
            self.set_status("Planning the steps...")

    def set_status(self, text: str) -> None:
        full = text
        if len(text) > MAX_STATUS_CHARS:
            text = text[:MAX_STATUS_CHARS].rstrip() + "…"
        low = full.lower()
        if any(w in low for w in ("failed", "error", "http ", "could not", "not connected", "out of date")):
            kind = "error"
        elif low.startswith("done") or "all done" in low:
            kind = "ok"
        else:
            kind = "info"
        self.status_icon.set_kind(kind)
        self.status_card.setStyleSheet(_alert_style(kind))
        self.status.setText(text)
        self.status.setToolTip(full if text != full else "")

    def show_state(self, st: dict) -> None:
        steps = [str(s) for s in st["steps"]]
        idx, complete = st["index"], bool(st["complete"])
        custom = bool(st.get("custom"))
        sig = (st["title"], tuple(steps), custom)
        fresh = sig != self._sig
        if fresh:
            self._sig = sig
            self.kind.setText("Your task" if custom else "Lesson")
            self.lesson_title.setText(st["title"])
            self.header.show()
            self._build_rows(steps)
        n = len(steps)
        done_count = n if complete else max(idx, 0)
        self.progress.set_progress(done_count / n if n else 0.0, done=complete and n > 0)
        self.count.setText("Completed" if complete else f"{done_count} of {n} done")
        for i, row in enumerate(self._rows):
            state = "done" if complete or i < idx else "current" if i == idx else "todo"
            row.set_state(state, animate=not fresh)
        if idx >= 0 and not complete:
            self._pulse.start()
            self._hint = f"Step {idx + 1} of {n}: {steps[idx]}" if idx < n else ""
            self.start_btn.set_label("Check now")
        else:
            self._pulse.stop()
            self._on_pulse(0.0)
            self._hint = "Done. Type another task." if complete else f"{st['title']} · {n} steps"
            self.start_btn.set_label("Start next lesson" if complete else "Start")
        self._refresh_tagline()
        QTimer.singleShot(60, lambda: self._scroll_to(idx if not complete else n - 1))
        if complete:
            self.set_status("Done. Type another task, or press the key for the next lesson.")
        elif idx < 0:
            self.set_status("Press the start key (or the button) when you are ready.")
        else:
            self.set_status("Just do the highlighted step in Blender. I will follow along.")
