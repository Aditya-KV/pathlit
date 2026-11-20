"""Reads and validates lesson JSON (FR-7). A bad file gives an error that names the step."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, model_validator


class LessonError(Exception):
    """Raised with a message that names the lesson file and, when known, the step id."""


class Target(BaseModel):
    text: str


class Check(BaseModel):
    kind: Literal["screen_text_present", "blender_state", "clicked_target", "none"]
    text: str | None = None                           # screen_text_present
    mode: str | None = None                           # blender_state fields
    active_object_name_contains: str | None = None
    active_object_type: str | None = None
    modifier_present: str | None = None
    object_count_at_least: int | None = None
    location_approx: list[float | None] | None = None        # active object's location, three numbers (null = ignore that axis)
    rotation_approx: list[float | None] | None = None        # degrees
    scale_approx: list[float | None] | None = None
    tolerance: float = 0.05                                  # for the three checks above (rotation allows 20x, at least 1 degree)
    fallback_text: str | None = None                  # screen text used instead when the Blender link is down

    @model_validator(mode="after")
    def _fields_match_kind(self) -> "Check":
        state_fields = [self.mode, self.active_object_name_contains, self.active_object_type,
                        self.modifier_present, self.object_count_at_least, self.location_approx, self.rotation_approx,
                        self.scale_approx]
        if self.kind == "screen_text_present" and not self.text:
            raise ValueError("screen_text_present needs 'text'")
        if self.kind == "blender_state" and all(f is None for f in state_fields):
            raise ValueError("blender_state needs at least one of mode, active_object_name_contains, "
                             "active_object_type, modifier_present, object_count_at_least, location_approx, "
                             "rotation_approx, scale_approx")
        return self


def _is_progress_marker(check: "Check") -> bool:
    """True for checks that prove something was CREATED (a modifier, an object, a named object). Those stay true once
    done, so passing one means the learner is at least that far, even if they skipped the steps in between.
    Mode-only checks are excluded: 'mode is OBJECT' is already true before the step is done."""
    return check.kind == "blender_state" and any(
        v is not None for v in (check.modifier_present, check.active_object_name_contains, check.object_count_at_least))


Check.is_progress_marker = property(_is_progress_marker)          # type: ignore[attr-defined]


class DoHint(BaseModel):
    """How Show me / Do it may perform this step. Optional: by default a step with a target is done by clicking that target."""
    skip_in_do: bool = False             # navigation-only step; in Do it mode a later direct action replaces it
    click: bool = True                   # False = move the cursor to the target and narrate, but do not click (explanation steps)
    direct: dict | None = None           # {"action": "...", "args": {...}} from the Blender allow-list, validated on load
    allow: bool = False                  # this step may click an item that is normally refused (Save, Delete...)

    @model_validator(mode="after")
    def _direct_is_allowed(self) -> "DoHint":
        if self.direct is not None:
            from ..control.actions import ActionRefused, validate_direct
            try:
                validate_direct(str(self.direct.get("action", "")), self.direct.get("args"))
            except ActionRefused as e:
                raise ValueError(f"direct action refused: {e}") from e
        return self


class Step(BaseModel):
    id: str
    instruction: str
    spoken: str
    why: str
    target: Target | None = None                      # None = nothing with a text label to point at
    shortcut: str | None = None
    check: Check
    docs_query: str | None = None
    hint_if_stuck: str | None = None
    do: DoHint | None = None                          # how Show me / Do it perform this step (optional)


class Lesson(BaseModel):
    id: str
    title: str
    tool: str
    skills_taught: list[str]
    prereqs: list[str] = []                           # skill ids that must be finished first
    steps: list[Step]

    @model_validator(mode="after")
    def _steps_ok(self) -> "Lesson":
        if not self.steps:
            raise ValueError("a lesson needs at least one step")
        ids = [s.id for s in self.steps]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate step ids: {sorted(dupes)}")
        return self


def _step_id_for(raw: dict, loc: tuple) -> str | None:
    if len(loc) >= 2 and loc[0] == "steps" and isinstance(loc[1], int):
        steps = raw.get("steps")
        if isinstance(steps, list) and loc[1] < len(steps) and isinstance(steps[loc[1]], dict):
            return steps[loc[1]].get("id") or f"#{loc[1] + 1}"
        return f"#{loc[1] + 1}"
    return None


def load_lesson(path: Path) -> Lesson:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LessonError(f"{path.name}: not valid JSON ({e})") from e
    try:
        return Lesson.model_validate(raw)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            step = _step_id_for(raw, err["loc"])
            where = f"step {step}" if step else "lesson"
            field = ".".join(str(p) for p in err["loc"][2:] if not isinstance(p, int)) if step else ".".join(map(str, err["loc"]))
            problems.append(f"{where}: {field or '(whole step)'} - {err['msg']}")
        raise LessonError(f"{path.name}: " + "; ".join(problems)) from e


def load_all(directory: Path) -> list[Lesson]:
    """All lessons in a folder, sorted by file name."""
    return [load_lesson(p) for p in sorted(Path(directory).glob("*.json"))]
