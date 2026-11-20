"""Pointer and bubble geometry. Pure math (no Qt), so it is unit tested (FR-5).

The pointer is a proper mouse-cursor shape whose tip sits INSIDE the target. The bubble is small and is placed where it
covers the least on-screen text, so it never hides the menu the learner has to read.
"""
from __future__ import annotations

import math

Rect = tuple[float, float, float, float]          # x, y, width, height

CURSOR_SCALE = 1.5
# classic arrow pointer, tip at (0, 0), pointing up-left
_CURSOR_POINTS = [(0, 0), (0, 16), (4, 12.6), (6.9, 19), (9.7, 17.8), (6.9, 11.5), (12, 11)]
CURSOR_W, CURSOR_H = 12 * CURSOR_SCALE, 19 * CURSOR_SCALE


def cursor_polygon(tip: tuple[float, float], scale: float = CURSOR_SCALE) -> list[tuple[float, float]]:
    return [(tip[0] + px * scale, tip[1] + py * scale) for px, py in _CURSOR_POINTS]


def cursor_rect(tip: tuple[float, float], scale: float = CURSOR_SCALE) -> Rect:
    return (tip[0], tip[1], 12 * scale, 19 * scale)


def tip_for(target: Rect) -> tuple[float, float]:
    """Where the pointer tip lands: horizontally centred on the target, a little below its middle (always inside)."""
    x, y, w, h = target
    return (x + w / 2, y + h * 0.55)


def ease_out_cubic(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def glide_ms(distance_px: float) -> int:
    """Short hops are quick, long flights take a little longer, always between 350 and 800 ms."""
    return int(min(800, max(350, 300 + distance_px * 0.35)))


def intersect_area(a: Rect, b: Rect) -> float:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def place_bubble(target: Rect, size: tuple[float, float], screen: tuple[int, int],
                 obstacles: list[Rect] | None = None, gap: float = 12, margin: float = 8) -> Rect:
    """Choose the spot around the target where the bubble hides the least text.

    obstacles = boxes of text already on screen (logical px). The target's own text is ignored.
    """
    bw, bh = size
    tx, ty, tw, th = target
    cur = cursor_rect(tip_for(target))
    below_y = max(ty + th, cur[1] + cur[3]) + gap
    candidates = [
        (tx + tw + gap + CURSOR_W, ty + th / 2 - bh / 2),   # right of the pointer
        (tx - bw - gap, ty + th / 2 - bh / 2),              # left
        (tx + tw / 2 - bw / 2, ty - bh - gap),              # above
        (tx + tw / 2 - bw / 2, below_y),                    # below
        (tx + tw + gap, ty - bh - gap),                     # above right
        (tx - bw - gap, ty - bh - gap),                     # above left
        (tx + tw + gap, below_y),                           # below right
        (tx - bw - gap, below_y),                           # below left
    ]
    relevant = [o for o in (obstacles or [])
                if o[2] * o[3] > 0 and intersect_area(o, target) / (o[2] * o[3]) < 0.3]
    best: tuple[float, Rect] | None = None
    for i, (cx, cy) in enumerate(candidates):
        x = min(max(cx, margin), screen[0] - bw - margin)
        y = min(max(cy, margin), screen[1] - bh - margin)
        r = (x, y, bw, bh)
        cost = sum(intersect_area(r, o) for o in relevant)
        cost += 20 * (intersect_area(r, target) + intersect_area(r, cur))       # never cover the target or the pointer
        cost += 30 * (abs(x - cx) + abs(y - cy))                                # moved by the screen edge: worse
        cost += i * 40                                                          # prefer earlier (nearer) spots
        if best is None or cost < best[0]:
            best = (cost, r)
    assert best is not None
    return best[1]
