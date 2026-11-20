"""Shared logic for the Phase 3 evaluation scripts (SRS 12): pointing accuracy, engine comparison, step-check accuracy.

Kept in the package so it is unit tested. The scripts in scripts/ only do the file and network plumbing.
Ground truth comes from a human (labels.json, stepcheck.json), never from the engines under test.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .lessons.checks import run_check
from .lessons.loader import Lesson
from .models import BlenderState, ScreenReport
from .overlay.arrow import tip_for
from .perception.target_match import find_target

HIT_MARGIN_PX = 5                      # SRS 12: a hit when the pointer tip is inside the true box, with a 5 pixel margin


# --------------------------------------------------------------------------- labels
def load_labels(path: Path) -> dict[str, list[dict]]:
    """labels.json: {"file.png": {"targets": [{"text": "Add", "bbox": [x, y, w, h]}]}} -> {file: [targets]}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    for name, entry in raw.items():
        targets = entry["targets"] if isinstance(entry, dict) else entry
        for t in targets:
            if len(t["bbox"]) != 4 or t["bbox"][2] <= 0 or t["bbox"][3] <= 0:
                raise ValueError(f"{name}: bad bbox for {t.get('text')!r}: {t['bbox']}")
        out[name] = targets
    return out


def save_labels(path: Path, labels: dict[str, list[dict]]) -> None:
    data = {name: {"targets": targets} for name, targets in sorted(labels.items()) if targets}
    Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")


def is_hit(tip: tuple[float, float], bbox: list[float] | tuple[float, ...], margin: float = HIT_MARGIN_PX) -> bool:
    x, y = tip
    bx, by, bw, bh = bbox
    return bx - margin <= x <= bx + bw + margin and by - margin <= y <= by + bh + margin


# --------------------------------------------------------------------------- pointing
@dataclass
class PointingResult:
    file: str
    target: str
    engine: str                    # the engine being evaluated: mirage | azure | router
    found: bool
    hit: bool
    score: float
    ms: int
    engine_used: str               # which engine actually answered (matters for the router)
    azure_calls: int
    miss_reason: str = ""


def pointing_outcome(report: ScreenReport, target_text: str, true_bbox: list[float], match_min: float = 80) -> dict[str, Any]:
    """Would the pointer land on the right thing? The tip is where the overlay really puts it (tip_for)."""
    m = find_target(report, target_text, match_min)
    if m is None:
        return {"found": False, "hit": False, "score": 0.0, "reason": "target text not found by the reader"}
    hit = is_hit(tip_for(m.bbox), true_bbox)
    return {"found": True, "hit": hit, "score": m.score,
            "reason": "" if hit else f"found {m.text!r} at {list(m.bbox)}, true box {list(true_bbox)} "
                                     f"({m.candidates} candidate{'s' if m.candidates != 1 else ''})"}


def route_local_first(mirage_read: Callable[[Any], ScreenReport], azure_read: Callable[[Any], ScreenReport], image: Any,
                      target: str, match_min: float = 80) -> tuple[ScreenReport, str, int, int]:
    """The SRS router experiment: try the local engine first, send the screenshot to Azure only if the target is not found.
    Returns (report, engine that answered, total ms, azure calls)."""
    rep = mirage_read(image)
    if find_target(rep, target, match_min) is not None:
        return rep, "mirage", rep.elapsed_ms, 0
    rep2 = azure_read(image)
    return rep2, "azure", rep.elapsed_ms + rep2.elapsed_ms, 1


def summarize_pointing(rows: list[PointingResult]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eng in sorted({r.engine for r in rows}):
        rs = [r for r in rows if r.engine == eng]
        ms = [r.ms for r in rs if r.ms]
        out[eng] = {
            "cases": len(rs), "hits": sum(r.hit for r in rs), "accuracy": round(sum(r.hit for r in rs) / len(rs), 3),
            "found": sum(r.found for r in rs),
            "median_ms": round(statistics.median(ms)) if ms else None,
            "azure_calls": sum(r.azure_calls for r in rs),
            "answered_by": {e: sum(1 for r in rs if r.engine_used == e) for e in sorted({r.engine_used for r in rs})},
        }
    return out


# --------------------------------------------------------------------------- step checks
@dataclass
class StepCheckResult:
    file: str
    lesson: str
    step: str
    check_kind: str
    expected: bool
    passed: bool | None            # None = could not be evaluated from a screenshot
    correct: bool | None
    reason: str


def stepcheck_outcome(case: dict, lesson: Lesson, report: ScreenReport | None, state: BlenderState | None,
                      match_min: float = 80) -> StepCheckResult:
    step = next((s for s in lesson.steps if s.id == case["step"]), None)
    if step is None:
        raise ValueError(f"{case['image']}: lesson {lesson.id} has no step {case['step']!r}")
    kind = step.check.kind
    base = dict(file=case["image"], lesson=lesson.id, step=step.id, check_kind=kind, expected=bool(case["expected"]))
    if kind in ("none", "clicked_target"):
        return StepCheckResult(**base, passed=None, correct=None, reason=f"'{kind}' checks do not depend on the screen")
    res = run_check(step.check, report, state, match_min)
    if not res.verified:
        return StepCheckResult(**base, passed=None, correct=None, reason=res.reason)
    return StepCheckResult(**base, passed=res.passed, correct=res.passed == bool(case["expected"]), reason=res.reason)


def summarize_stepcheck(rows: list[StepCheckResult]) -> dict[str, Any]:
    ev = [r for r in rows if r.correct is not None]
    by_kind = {}
    for k in sorted({r.check_kind for r in ev}):
        ks = [r for r in ev if r.check_kind == k]
        by_kind[k] = {"cases": len(ks), "correct": sum(bool(r.correct) for r in ks)}
    return {
        "cases": len(rows), "evaluated": len(ev), "skipped": len(rows) - len(ev),
        "correct": sum(bool(r.correct) for r in ev),
        "accuracy": round(sum(bool(r.correct) for r in ev) / len(ev), 3) if ev else None,
        "false_pass": sum(1 for r in ev if r.passed and not r.expected),     # said done when it was not
        "false_fail": sum(1 for r in ev if not r.passed and r.expected),     # said not done when it was
        "by_kind": by_kind,
    }


# --------------------------------------------------------------------------- report cache
class ReportCache:
    """Remembers engine output per (engine, image, settings) so a re-run costs no Azure calls and no model time."""

    def __init__(self, directory: Path, tag: str = "") -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tag = tag

    def _path(self, engine: str, image_path: Path) -> Path:
        digest = hashlib.sha1(image_path.read_bytes() + self.tag.encode()).hexdigest()[:16]
        return self.dir / f"{engine}_{image_path.stem}_{digest}.json"

    def get_or_read(self, engine: str, image_path: Path, read: Callable[[], ScreenReport]) -> tuple[ScreenReport, bool]:
        p = self._path(engine, image_path)
        if p.exists():
            return ScreenReport.model_validate_json(p.read_text(encoding="utf-8")), True
        rep = read()
        p.write_text(rep.model_dump_json(), encoding="utf-8")
        return rep, False


def timed(fn: Callable[[], Any]) -> tuple[Any, int]:
    t0 = time.perf_counter()
    out = fn()
    return out, round((time.perf_counter() - t0) * 1000)


def rows_to_dicts(rows: list) -> list[dict]:
    return [asdict(r) for r in rows]
