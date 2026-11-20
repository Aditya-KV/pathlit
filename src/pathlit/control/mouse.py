"""Moves the real mouse cursor and clicks (Show me and Do it modes only).

pyautogui is imported ONLY when a mover is created, so Teach me mode never loads any mouse-control code. Every frame of a move
goes through the guard, so Esc stops it within one frame (about 16 ms).
Coordinates are real screen pixels, the same as the screenshots: the process is DPI aware (see capture.make_dpi_aware).
"""
from __future__ import annotations

import time
from typing import Protocol

from .guard import Guard, Stopped


class Mover(Protocol):
    def position(self) -> tuple[float, float]: ...
    def move_to(self, x: float, y: float, duration: float, guard: Guard) -> None: ...
    def click(self) -> None: ...


def smoothstep(t: float) -> float:
    """Ease in and out, so the cursor accelerates and slows like a hand."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


class LazyMover:
    """Loads pyautogui only on first use, so Teach me mode never imports any mouse-control code."""

    def __init__(self) -> None:
        self._m: PyAutoGuiMover | None = None

    def _get(self) -> "PyAutoGuiMover":
        if self._m is None:
            self._m = PyAutoGuiMover()
        return self._m

    def position(self) -> tuple[float, float]:
        return self._get().position()

    def move_to(self, x: float, y: float, duration: float, guard: Guard) -> None:
        self._get().move_to(x, y, duration, guard)

    def click(self) -> None:
        self._get().click()


class PyAutoGuiMover:
    def __init__(self) -> None:
        try:
            import pyautogui
        except ImportError as e:
            raise RuntimeError("Show me / Do it need the 'pyautogui' package: run  pip install pyautogui") from e
        pyautogui.FAILSAFE = True            # slamming the mouse into a screen corner aborts (raises FailSafeException)
        pyautogui.PAUSE = 0.05
        self._pg = pyautogui

    def position(self) -> tuple[float, float]:
        p = self._pg.position()
        return float(p[0]), float(p[1])

    def move_to(self, x: float, y: float, duration: float, guard: Guard) -> None:
        x0, y0 = self.position()
        frames = max(8, int(duration * 60))
        for i in range(1, frames + 1):
            guard.check()
            k = smoothstep(i / frames)
            px, py = x0 + (x - x0) * k, y0 + (y - y0) * k
            try:
                self._pg.moveTo(round(px), round(py), _pause=False)
            except self._pg.FailSafeException:             # the mouse was slammed into a screen corner: the emergency stop
                guard.stop("You moved the mouse to a corner, so I stopped.")
                raise Stopped(guard._reason)
            guard.note_set((float(round(px)), float(round(py))))
            time.sleep(duration / frames)

    def click(self) -> None:
        self._pg.click()
