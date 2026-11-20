"""Notices the learner's clicks and key presses so the lesson can follow along (auto-advance).

LISTENING ONLY: pynput's Listener classes are used, never its Controller classes, so Pathlit cannot click or type.
Privacy: nothing is recorded here. A callback is fired, and the controller decides (it checks that Blender is the focused
window and that a lesson is running) before it ever looks at the screen.
"""
from __future__ import annotations

import ctypes
import sys
from typing import Callable

from pynput import keyboard, mouse

_MODIFIERS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.ctrl, keyboard.Key.ctrl_l,
              keyboard.Key.ctrl_r, keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.cmd,
              keyboard.Key.caps_lock}


def foreground_title() -> str:
    """Title of the window that has focus right now ('' if unknown)."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value
    except Exception:
        return ""


def make_foreground_check(title_contains: str) -> Callable[[], bool]:
    needle = title_contains.lower()
    return lambda: needle in foreground_title().lower()


class ActivityListener:
    def __init__(self, on_activity: Callable[..., None], ignore_keys: tuple = ()) -> None:
        self._cb = on_activity
        self._ignore = set(ignore_keys)
        self._mouse: mouse.Listener | None = None
        self._keys: keyboard.Listener | None = None

    def _on_click(self, x, y, _button, pressed) -> None:
        if pressed:
            self._cb(x, y)                                  # the position lets the lesson see a click on the pointed target

    def _on_key(self, key) -> None:
        if key in _MODIFIERS or key in self._ignore:
            return
        self._cb()

    def start(self) -> None:
        self._mouse = mouse.Listener(on_click=self._on_click)
        self._keys = keyboard.Listener(on_press=self._on_key)
        for lst in (self._mouse, self._keys):
            lst.daemon = True
            lst.start()

    def stop(self) -> None:
        for lst in (self._mouse, self._keys):
            if lst:
                lst.stop()
