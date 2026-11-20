"""Global hotkey listener. Uses pynput only to LISTEN for keys, never its controller classes (SRS 11 Safety)."""
from __future__ import annotations

from typing import Callable

from pynput import keyboard


def parse_key(name: str):
    """'f8' -> keyboard.Key.f8, 'a' -> KeyCode('a')."""
    name = name.strip().lower()
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    key = getattr(keyboard.Key, name, None)
    if key is None:
        raise ValueError(f"unknown key name in settings.yaml: {name!r}")
    return key


class HotkeyListener:
    def __init__(self, hotkey: str, on_hotkey: Callable[[], None]) -> None:
        self._key = parse_key(hotkey)
        self._on_hotkey = on_hotkey
        self._listener: keyboard.Listener | None = None

    def _on_press(self, key) -> None:
        if key == self._key:
            self._on_hotkey()

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
