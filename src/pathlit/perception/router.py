"""Chooses which engine reads the screen (FR-9).

Owner decision after Phase 0: Azure Vision is primary (it found far more Blender UI text than Mirage). Mirage, which
runs on the laptop, is the fallback when Azure Vision fails, so Pathlit keeps working without the network.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from PIL import Image

from ..models import ScreenReport

log = logging.getLogger(__name__)


class Reader(Protocol):
    def read(self, image: Image.Image) -> ScreenReport: ...


class Router:
    def __init__(self, primary: Any, fallback: Any | None = None) -> None:
        self.primary, self.fallback = primary, fallback
        self.last_engine: str | None = None
        self.last_error: str | None = None

    def warm_up(self) -> None:
        if hasattr(self.primary, "warm_up"):
            self.primary.warm_up()

    def read(self, image: Image.Image) -> ScreenReport:
        try:
            rep = self.primary.read(image)
            self.last_engine, self.last_error = rep.engine, None
            return rep
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)[:150]}"
            if self.fallback is None:
                raise
            log.warning("primary reader failed (%s); using %s", self.last_error, type(self.fallback).__name__)
            rep = self.fallback.read(image)
            self.last_engine = rep.engine
            return rep
