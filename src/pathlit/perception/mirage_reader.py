"""Mirage (local, offline) -> ScreenReport. Used only as the fallback reader (see router.py).

Verified in Phase 0: Mirage().describe(img, sections=["text"]) returns {"text": [{"string", "bbox", "score"}]} where
bbox is [x1, y1, x2, y2] normalised to 0-1000 on both axes. Mirage returns whole strings, not words, so word boxes are
estimated by sharing the string's width in proportion to word length (approximate, good enough to point at a menu item).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from PIL import Image

from ..models import Element, ScreenReport

log = logging.getLogger(__name__)
NORM = 1000.0


def report_from_mirage(result: dict[str, Any], image_size: tuple[int, int], elapsed_ms: int) -> ScreenReport:
    w, h = image_size
    elements: list[Element] = []
    for i, item in enumerate(result.get("text", [])):
        text = str(item.get("string", "")).strip()
        bbox = item.get("bbox")
        if not text or not bbox or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = (bbox[0] / NORM * w, bbox[1] / NORM * h, bbox[2] / NORM * w, bbox[3] / NORM * h)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        conf = item.get("score")
        elements.append(Element(text=text, bbox=(round(x1), round(y1), round(x2 - x1), round(y2 - y1)),
                                confidence=conf, kind="line", line=i))
        words = text.split()
        total = sum(len(wd) for wd in words) or 1
        cx = x1
        for wd in words:
            ww = (x2 - x1) * len(wd) / total
            elements.append(Element(text=wd, bbox=(round(cx), round(y1), round(ww), round(y2 - y1)),
                                    confidence=conf, kind="word", line=i))
            cx += ww
    return ScreenReport(engine="mirage", image_size=image_size, elements=elements, elapsed_ms=elapsed_ms)


class MirageReader:
    """Loads the local model on first use (about 16 s the first time), so it costs nothing unless the fallback is needed."""

    def __init__(self) -> None:
        self._mirage = None

    def read(self, image: Image.Image) -> ScreenReport:
        t0 = time.perf_counter()
        if self._mirage is None:
            from cactus import Mirage
            self._mirage = Mirage()
        result = self._mirage.describe(image, sections=["text"])
        return report_from_mirage(result, image.size, round((time.perf_counter() - t0) * 1000))
