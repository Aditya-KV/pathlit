"""Screenshot of the main monitor at real pixel size. Never writes to disk unless DEBUG_SAVE_SCREENS=true (FR-2)."""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

import mss
from PIL import Image

from .config import env


def make_dpi_aware() -> None:
    """Call BEFORE creating the Qt app, so Windows reports real pixels and arrows do not drift."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


@dataclass
class Capture:
    image: Image.Image          # real pixels, in memory only
    monitor_left: int
    monitor_top: int
    width: int
    height: int


def grab_main_monitor() -> Capture:
    with mss.MSS() as sct:      # mss handles are per-thread, so make one per grab
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return Capture(img, mon["left"], mon["top"], shot.width, shot.height)


def downscale(img: Image.Image, max_edge: int) -> tuple[Image.Image, float]:
    """Return (smaller copy, factor) where original_px = small_px * factor. max_edge<=0 means no resize."""
    longest = max(img.size)
    if max_edge <= 0 or longest <= max_edge:
        return img, 1.0
    factor = longest / max_edge
    return img.resize((round(img.width / factor), round(img.height / factor))), factor


def px_to_logical(x: float, y: float, capture_size: tuple[int, int],
                  logical_size: tuple[int, int]) -> tuple[float, float]:
    """Convert real captured pixels to the overlay's logical (Qt) coordinates. Works for any scaling."""
    return x * logical_size[0] / capture_size[0], y * logical_size[1] / capture_size[1]


def save_debug(img: Image.Image, directory: Path, name: str) -> Path | None:
    """Writes an image ONLY when DEBUG_SAVE_SCREENS=true. Otherwise does nothing."""
    if env("DEBUG_SAVE_SCREENS").lower() != "true":
        return None
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    img.save(path)
    return path
