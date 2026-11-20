"""Step checks (SRS 8.1). The code decides pass or fail. The language model is never asked."""
from __future__ import annotations

from dataclasses import dataclass

from ..models import BlenderState, ScreenReport
from ..perception.target_match import find_target
from .loader import Check


@dataclass
class CheckResult:
    passed: bool
    reason: str
    verified: bool = True        # False when the check could not really be run (Blender link down, no fallback)


def run_check(check: Check, report: ScreenReport | None, state: BlenderState | None, match_min: float = 80) -> CheckResult:
    if check.kind == "none":
        return CheckResult(True, "no check (hotkey pressed)")

    if check.kind == "screen_text_present":
        return _screen(check.text or "", report, match_min)

    # blender_state
    if state is None:
        if check.fallback_text:
            r = _screen(check.fallback_text, report, match_min)
            return CheckResult(r.passed, f"blender link down, screen fallback: {r.reason}")
        return CheckResult(True, "blender link down, step could not be verified", verified=False)

    problems: list[str] = []
    obj = state.active_object
    if check.mode is not None and state.mode.upper() != check.mode.upper():
        problems.append(f"mode is {state.mode}, expected {check.mode}")
    if check.active_object_name_contains is not None:
        if obj is None or check.active_object_name_contains.lower() not in obj.name.lower():
            problems.append(f"active object {obj.name if obj else None!r} lacks {check.active_object_name_contains!r}")
    if check.active_object_type is not None and (obj is None or obj.type.upper() != check.active_object_type.upper()):
        problems.append(f"active object type is {obj.type if obj else None}, expected {check.active_object_type}")
    if check.modifier_present is not None and (obj is None or check.modifier_present.upper() not in
                                               [m.upper() for m in obj.modifiers]):
        problems.append(f"modifier {check.modifier_present} not on active object")
    if check.object_count_at_least is not None and state.object_count < check.object_count_at_least:
        problems.append(f"{state.object_count} objects, need at least {check.object_count_at_least}")
    for field, label, tol in (("location_approx", "location", check.tolerance), ("scale_approx", "scale", check.tolerance),
                              ("rotation_approx", "rotation", max(check.tolerance * 20, 1.0))):
        want = getattr(check, field)
        if want is None:
            continue
        have = getattr(obj, label, None) if obj else None
        if have is None:
            problems.append(f"Blender did not report the {label} of the active object")
            continue
        bad = [f"{'XYZ'[i]} is {have[i]:g}, want {w:g}" for i, w in enumerate(want) if w is not None and abs(have[i] - w) > tol]
        if bad:
            problems.append(f"{label}: " + ", ".join(bad))
    return CheckResult(not problems, "; ".join(problems) or "blender state matches")


def _screen(text: str, report: ScreenReport | None, match_min: float) -> CheckResult:
    if report is None:
        return CheckResult(False, "screen could not be read")
    m = find_target(report, text, match_min)
    return CheckResult(m is not None, f"{text!r} {'found' if m else 'not found'} on screen")
