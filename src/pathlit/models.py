"""Pydantic models shared across modules (SRS 8.2, 8.3)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class Element(BaseModel):
    text: str
    bbox: tuple[int, int, int, int]          # x, y, width, height in pixels of the captured image
    confidence: float | None = None
    kind: Literal["line", "word"] = "line"
    line: int | None = None                  # index of the line this element belongs to

    @field_validator("bbox")
    @classmethod
    def _non_negative_size(cls, v: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        if v[2] < 0 or v[3] < 0:
            raise ValueError("bbox width/height must be >= 0")
        return v


class ScreenReport(BaseModel):
    engine: str
    image_size: tuple[int, int]
    elements: list[Element]
    elapsed_ms: int

    @field_validator("image_size")
    @classmethod
    def _positive(cls, v: tuple[int, int]) -> tuple[int, int]:
        if v[0] <= 0 or v[1] <= 0:
            raise ValueError("image_size must be positive")
        return v


class ActiveObject(BaseModel):
    name: str
    type: str
    modifiers: list[str] = []
    location: list[float] | None = None            # Blender units
    rotation: list[float] | None = None            # degrees
    scale: list[float] | None = None
    dimensions: list[float] | None = None          # size in Blender units (scale included)


class BlenderState(BaseModel):
    """What the Blender add-on reports (SRS 8.3)."""
    blender_version: str
    mode: str
    active_object: ActiveObject | None = None
    selected_count: int = 0
    object_count: int = 0
