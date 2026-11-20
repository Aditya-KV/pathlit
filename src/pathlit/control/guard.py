"""The safety guard for cursor control (addendum Section 5). Every movement and every click goes through it.

It stops everything when: Esc is pressed, the foreground app is not on the allow-list, the learner moves the real mouse
more than `abort_px`, a task would exceed its action limit, or actions come faster than one per second.
"""
from __future__ import annotations

import contextlib
import math
import threading
import time
from typing import Callable


class Stopped(Exception):
    """A safety rule stopped the action. `reason` is safe to speak."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Guard:
    def __init__(self, allowed_apps: list[str], foreground_title: Callable[[], str],
                 mouse_position: Callable[[], tuple[float, float]], abort_px: float = 50, max_actions: int = 40,
                 min_interval_s: float = 1.0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.allowed = [a.lower() for a in allowed_apps]
        self.foreground_title, self.mouse_position = foreground_title, mouse_position
        self.abort_px, self.max_actions, self.min_interval = abort_px, max_actions, min_interval_s
        self.clock, self.sleep = clock, sleep
        self._stop = threading.Event()
        self._reason = ""
        self.actions = 0
        self._last_action_at: float | None = None
        self.last_set: tuple[float, float] | None = None       # where WE last put the cursor
        self.mouse_watch = True                                # off while we merely WAIT for the learner (their mouse is theirs)

    # ---- stopping ----
    def stop(self, reason: str = "Stopped.") -> None:
        """Safe to call from any thread (the Esc key listener calls this)."""
        self._reason = reason
        self._stop.set()

    def clear_stop(self) -> None:
        """A new task starts with a clean slate: an old Esc must not cancel it."""
        self._stop.clear()
        self._reason = ""

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def reset_task(self) -> None:
        self._stop.clear()
        self._reason = ""
        self.actions = 0
        self._last_action_at = None
        self.last_set = tuple(self.mouse_position())

    # ---- checks ----
    def app_allowed(self) -> bool:
        title = self.foreground_title().lower()
        return any(a in title for a in self.allowed)

    def note_set(self, pos: tuple[float, float]) -> None:
        self.last_set = pos

    def rebaseline(self) -> None:
        """Start counting 'the learner moved the mouse' from where the cursor is right now."""
        self.last_set = tuple(self.mouse_position())

    @contextlib.contextmanager
    def mouse_watch_off(self):
        """While waiting for the learner (their OK, Blender to come to the front) they may move the mouse freely."""
        self.mouse_watch = False
        try:
            yield
        finally:
            self.mouse_watch = True
            self.rebaseline()

    def check(self) -> None:
        """Call very often (every frame of a move, every few milliseconds while waiting)."""
        if self._stop.is_set():
            raise Stopped(self._reason or "Stopped.")
        if not self.app_allowed():
            self.stop("The window in front is not an allowed app, so I stopped.")
            raise Stopped(self._reason)
        if self.mouse_watch and self.last_set is not None:
            x, y = self.mouse_position()
            if math.hypot(x - self.last_set[0], y - self.last_set[1]) > self.abort_px:
                self.stop("You moved the mouse, so I stopped.")
                raise Stopped(self._reason)

    def before_action(self) -> None:
        """Rate limit (1 per second) and the per-task action limit."""
        self.check()
        if self.actions >= self.max_actions:
            self.stop(f"This task would go over {self.max_actions} actions, so I stopped to ask you.")
            raise Stopped(self._reason)
        now = self.clock()
        if self._last_action_at is not None:
            wait = self.min_interval - (now - self._last_action_at)
            while wait > 0:
                self.check()
                step = min(wait, 0.02)
                self.sleep(step)
                wait -= step
        self.actions += 1
        self._last_action_at = self.clock()

    def wait(self, seconds: float, until: threading.Event | None = None) -> bool:
        """Wait while still watching every safety rule. Returns True if `until` was set early."""
        end = self.clock() + seconds
        while self.clock() < end:
            self.check()
            if until is not None and until.is_set():
                return True
            self.sleep(0.015)
        return False
