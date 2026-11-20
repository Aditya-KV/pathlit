"""Image canvas for the labelling tool: show a screenshot scaled to fit, drag a box, get it back in IMAGE pixels."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget


def fit_scale(image_size: tuple[int, int], view_size: tuple[int, int]) -> float:
    """Largest scale that fits the whole image in the view."""
    return min(view_size[0] / image_size[0], view_size[1] / image_size[1])


def view_to_image(pt: tuple[float, float], scale: float, offset: tuple[float, float]) -> tuple[float, float]:
    return ((pt[0] - offset[0]) / scale, (pt[1] - offset[1]) / scale)


def image_to_view(pt: tuple[float, float], scale: float, offset: tuple[float, float]) -> tuple[float, float]:
    return (pt[0] * scale + offset[0], pt[1] * scale + offset[1])


def drag_to_bbox(a: tuple[float, float], b: tuple[float, float], image_size: tuple[int, int],
                 min_size: int = 4) -> list[int] | None:
    """Two corners (in image pixels, any order) -> [x, y, w, h] clipped to the image, or None if it is a stray click."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(image_size[0]), x1), min(float(image_size[1]), y1)
    if x1 - x0 < min_size or y1 - y0 < min_size:
        return None
    return [round(x0), round(y0), round(x1 - x0), round(y1 - y0)]


class ImageCanvas(QWidget):
    box_drawn = pyqtSignal(list)              # [x, y, w, h] in image pixels

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 400)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._image: QImage | None = None
        self._boxes: list[tuple[str, list[int]]] = []
        self._active: str | None = None
        self._start: QPointF | None = None
        self._now: QPointF | None = None

    def set_image(self, path: str) -> tuple[int, int]:
        self._image = QImage(path)
        self.update()
        return (self._image.width(), self._image.height()) if self._image and not self._image.isNull() else (0, 0)

    def set_boxes(self, boxes: list[tuple[str, list[int]]], active: str | None) -> None:
        self._boxes, self._active = boxes, active
        self.update()

    def _geometry(self) -> tuple[float, tuple[float, float]]:
        if not self._image or self._image.isNull():
            return 1.0, (0.0, 0.0)
        sc = fit_scale((self._image.width(), self._image.height()), (self.width(), self.height()))
        return sc, ((self.width() - self._image.width() * sc) / 2, (self.height() - self._image.height() * sc) / 2)

    def mousePressEvent(self, e) -> None:
        self._start = e.position()
        self._now = e.position()

    def mouseMoveEvent(self, e) -> None:
        if self._start is not None:
            self._now = e.position()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._start is None or not self._image:
            return
        sc, off = self._geometry()
        a = view_to_image((self._start.x(), self._start.y()), sc, off)
        b = view_to_image((e.position().x(), e.position().y()), sc, off)
        self._start = self._now = None
        box = drag_to_bbox(a, b, (self._image.width(), self._image.height()))
        if box:
            self.box_drawn.emit(box)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(24, 24, 28))
        if not self._image or self._image.isNull():
            return
        sc, off = self._geometry()
        p.drawImage(QRectF(off[0], off[1], self._image.width() * sc, self._image.height() * sc), self._image)
        p.setFont(QFont("Segoe UI", 10))
        for text, (x, y, w, h) in self._boxes:
            vx, vy = image_to_view((x, y), sc, off)
            r = QRectF(vx, vy, w * sc, h * sc)
            col = QColor(255, 214, 0) if text == self._active else QColor(80, 220, 120)
            p.setPen(QPen(col, 2))
            p.drawRect(r)
            p.drawText(r.topLeft() + QPointF(2, -4), text)
        if self._start is not None and self._now is not None:
            p.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(self._start, self._now))
