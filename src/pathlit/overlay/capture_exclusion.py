"""Makes one of Pathlit's own windows invisible to screen capture (Windows 10 2004+).

The pointer and the control panel stay visible to the learner, but never appear in the screenshots Pathlit takes, so their
text is never read as part of Blender's screen, and the panel never leaks into a capture.
"""
from __future__ import annotations

import ctypes
import sys

WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_from_capture(widget) -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False
