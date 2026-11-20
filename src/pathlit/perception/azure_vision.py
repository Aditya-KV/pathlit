"""Azure Vision Read (OCR) -> ScreenReport. Words and lines both become elements (SRS 8.2, 9)."""
from __future__ import annotations

import io
import logging
import time
from typing import Any

from PIL import Image

from ..config import env
from ..models import Element, ScreenReport

log = logging.getLogger(__name__)


def _bbox(polygon: Any, factor: float) -> tuple[int, int, int, int]:
    xs = [p.x for p in polygon]
    ys = [p.y for p in polygon]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return round(x0 * factor), round(y0 * factor), round((x1 - x0) * factor), round((y1 - y0) * factor)


def report_from_result(result: Any, image_size: tuple[int, int], factor: float, elapsed_ms: int) -> ScreenReport:
    """Pure converter: takes the SDK result (or a look-alike in tests) and builds a ScreenReport in REAL pixels."""
    elements: list[Element] = []
    line_idx = 0
    blocks = result.read.blocks if getattr(result, "read", None) else []
    for block in blocks:
        for line in block.lines:
            confs = [w.confidence for w in line.words if w.confidence is not None]
            elements.append(Element(text=line.text, bbox=_bbox(line.bounding_polygon, factor),
                                    confidence=round(sum(confs) / len(confs), 3) if confs else None,
                                    kind="line", line=line_idx))
            for w in line.words:
                elements.append(Element(text=w.text, bbox=_bbox(w.bounding_polygon, factor),
                                        confidence=w.confidence, kind="word", line=line_idx))
            line_idx += 1
    return ScreenReport(engine="azure_vision", image_size=image_size, elements=elements, elapsed_ms=elapsed_ms)


class AzureVisionReader:
    def __init__(self, endpoint: str | None = None, key: str | None = None, max_edge: int = 0) -> None:
        from azure.ai.vision.imageanalysis import ImageAnalysisClient
        from azure.core.credentials import AzureKeyCredential

        endpoint = endpoint or env("AZURE_VISION_ENDPOINT")
        key = key or env("AZURE_VISION_KEY")
        if not endpoint or not key:
            raise RuntimeError("AZURE_VISION_ENDPOINT / AZURE_VISION_KEY missing in .env")
        self._client = ImageAnalysisClient(endpoint, AzureKeyCredential(key))
        self._max_edge = max_edge

    def warm_up(self) -> None:
        """First call is slow (connection setup); do it at startup with a blank image."""
        try:
            self.read(Image.new("RGB", (64, 64), "white"))
        except Exception as e:  # warm-up must never stop startup
            log.warning("vision warm-up failed: %s", e)

    def read(self, image: Image.Image) -> ScreenReport:
        from azure.ai.vision.imageanalysis.models import VisualFeatures

        from ..capture import downscale

        t0 = time.perf_counter()
        small, factor = downscale(image, self._max_edge)
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=85)           # measured: 4x smaller upload than PNG, same targets found
        result = self._client.analyze(image_data=buf.getvalue(), visual_features=[VisualFeatures.READ])
        elapsed = round((time.perf_counter() - t0) * 1000)
        return report_from_result(result, image.size, factor, elapsed)
