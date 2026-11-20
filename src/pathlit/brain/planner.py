"""Turns a task the learner types ("make a coffee mug") into a short step-by-step lesson.

The model only WRITES the plan. Everything it returns is validated before use:
- the reply must be JSON in the lesson shape (pydantic, same models as the built-in lessons, FR-7);
- 2 to 14 steps, short text, spoken lines cut to 2 sentences and 30 words;
- a target must be short on-screen text; anything else becomes "no pointer, instruction only";
- steps that mention scripts or code are dropped (the app never runs code from a model, and never tells the learner to);
- every pointed step gets the check `clicked_target` (it passes when the learner clicks the pointed thing); steps without
  a target pass on the next interaction.
Pointer positions still come only from the screen reader. The model never gives coordinates.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..lessons.loader import Lesson
from .teacher import ChatClient, _limit_sentences
from .builder import BuildState, build_step, default_cube_warning, geometry_warnings, parts_table
from .vocabulary import MENU_PARENT, WRENCH_STEP, is_known, known_labels, opening_chain

log = logging.getLogger(__name__)

MIN_STEPS, MAX_STEPS = 2, 45

PLAN_SYSTEM = """You plan Blender 4.1 builds for a complete beginner. Be SPECIFIC: real shapes, real sizes, real positions.
The learner starts in the default scene: a Cube (selected, centred at the origin), a Camera and a Light. Z is up, the ground is z=0.

Return only JSON: {"title": "short title", "steps": [ ... ]}
If the goal is not about Blender, return {"error": "one short sentence saying you can only plan Blender tasks"}.

Each step is ONE of:
 {"kind":"add",  "shape":"CUBE|SPHERE|ICOSPHERE|CYLINDER|CONE|TORUS|PLANE|MONKEY", "part":"walls", "spoken":"...", "why":"...", "hint":"..."}
     adds a new shape at the origin. It becomes the active object.
 {"kind":"set",  "property":"scale|location|rotation", "values":[x,y,z], "part":"walls", "spoken":"...", "why":"...", "hint":"..."}
     sets that property of the ACTIVE object. Use null for an axis you do not want to change. Rotation is in degrees.
 {"kind":"ui", "instruction":"Click Shade Smooth.", "target":"Shade Smooth", "spoken":"...", "why":"...", "hint":"..."}
     clicks ONE labelled menu item. Use only labels from the two lists you are given. Items inside a menu need the menu opened first.

How shapes work (this is what you need for the geometry):
- Every primitive is 2 units across, centred on its own origin: Cube 2x2x2, Plane 2x2, Cylinder radius 1 height 2, Cone radius 1 height 2 (point
  up, base at the bottom), UV Sphere radius 1. Scale MULTIPLIES this: a cube with scale [3,2,1] is 6 wide (X), 4 deep (Y), 2 high (Z).
- A shape scaled by s reaches s from its centre. So to make a cube, cylinder or cone SIT ON THE GROUND set Location Z = its Scale Z.
  To stack a part on top of another, set its Location Z = (the top of the lower part) + (its own half-height).
- Do the arithmetic. Every part must be the right size and touch the parts it belongs to. Nothing may float or sink below the ground.
- STACKING RECIPE: for a part resting on the ground, its z range is 0 to 2 x ScaleZ and Location Z = ScaleZ. For a part resting ON another
  part: Location Z = (TOP of the lower part) + (its own ScaleZ), where TOP of the lower part = its Location Z + its ScaleZ.
  Example: walls ScaleZ 1.25 at Location Z 1.25 reach z 2.5; a roof cone with ScaleZ 0.75 on top needs Location Z = 2.5 + 0.75 = 3.25.
  Parts that must stick OUT of a wall (a door, a window) go on its outer face: Location Y = (wall half-depth) + (their own half-depth).
- NEVER use PLANE for a door, window or wall: a plane has no thickness and lies flat, so it becomes an invisible sliver. Use a thin CUBE
  instead: a door is a cube with scale [0.5, 0.06, 0.9] (1 wide, 0.12 thick, 1.8 tall) at Location Y = wall half-depth + 0.06 and
  Location Z = 0.9; a window is a cube like [0.35, 0.06, 0.35] on the same face at Location Z about 1.4. Use PLANE only for the ground.
- A cone's point is thin: a tall part (a chimney) on a roof must start INSIDE the roof, with its bottom lower than the roof surface at its
  spot, or it will float. Near the middle of a cone the surface is high, near its edge it is low.
- A cone or cylinder is round. For a square building make the roof cone wide enough to cover the corners (radius about 1.4 x the wall half-width).
- The default cube is already selected: use it as your FIRST part. Start with "set" steps for it instead of adding another cube.

Plan it like a careful 3D artist:
- First decide the parts (4 to 8 parts for something recognisable), each with a size and a position.
- For each part: add it (except the first), then set Scale, then set Location, then Rotation only if needed. Give EVERY part a "part" name.
- Use plain numbers a beginner can type (0.5 steps).
- Details matter: a recognisable object has the little parts people expect (for a table: top and legs; for a house: more than just walls and a roof).
- At most 40 steps. If the goal is too big, build a good simplified version.

Other rules:
- "spoken": at most 2 short sentences, under 30 words, plain words, about THIS step only, ideally why the number matters. Never mention later steps.
- "why": one short everyday-comparison sentence.
- "hint": one short sentence telling the learner where to look. Never tell the learner to run scripts or install add-ons. Never give pixel coordinates.

Example for "a simple table" (it uses the default cube as the table top):
{"title":"A simple table","steps":[
 {"kind":"set","property":"scale","values":[1.5,1,0.08],"part":"table top","spoken":"Squash the cube into a flat board.","why":"A tabletop is a thin slab.","hint":"Properties panel, Object tab, Scale."},
 {"kind":"set","property":"location","values":[0,0,1.58],"part":"table top","spoken":"Lift it up so it sits at table height.","why":"Like putting the board on legs.","hint":"Same panel, Location."},
 {"kind":"add","shape":"CYLINDER","part":"first leg","spoken":"Add a cylinder for a leg.","why":"A leg is a tall round post.","hint":"Add, then Mesh, then Cylinder."},
 {"kind":"set","property":"scale","values":[0.08,0.08,0.75],"part":"first leg","spoken":"Make it thin and tall.","why":"Thin like a table leg.","hint":"Scale."},
 {"kind":"set","property":"location","values":[1.3,0.8,0.75],"part":"first leg","spoken":"Put it under the corner.","why":"Legs go under the corners.","hint":"Location."}]}"""

_UNSAFE = re.compile(r"\bbpy\b|\bimport\s|exec\(|eval\(|```|\.py\b|python console|scripting workspace|add-?on", re.I)


def retry_after_seconds(exc: Exception) -> float | None:
    """Groq's rate-limit error says 'Please try again in 7.2s' (or '830ms'). None if it is not a rate limit."""
    text = str(exc)
    if "429" not in text and "rate limit" not in text.lower():
        return None
    m = re.search(r"try again in ([\d.]+)\s*(ms|s|m)\b", text)
    if not m:
        return 8.0
    v = float(m.group(1))
    return v / 1000 if m.group(2) == "ms" else v * 60 if m.group(2) == "m" else v


MAX_WAIT_S = 30.0


def _complete(client, model, messages, timeout, on_wait=None):
    """One model call. If the free tier says 'too many tokens this minute', wait as long as it asks (up to 30 s) and retry once."""
    try:
        return client.complete(model, messages, timeout, effort="medium")
    except Exception as e:
        wait = retry_after_seconds(e)
        if wait is None or wait > MAX_WAIT_S:
            raise
        if on_wait:
            on_wait(wait)
        time.sleep(wait + 0.5)
        return client.complete(model, messages, timeout, effort="medium")


class PlanError(Exception):
    """The plan could not be made. The message is safe to show to the learner."""


@dataclass
class PlanResult:
    lesson: Lesson
    unverified_labels: list[str]        # targets that are in neither label list
    dropped_steps: int
    compound_steps: int = 0             # steps that still seem to combine several actions
    inserted_steps: int = 0             # menu-opening steps the planner added because the model left them out
    retargeted: int = 0                 # targets removed because the instruction did not mention them (or named an icon)
    warnings: list[str] = field(default_factory=list)      # geometry hints: a part that floats, sinks, or the leftover default cube
    uses_default_scene: bool = False                        # the plan assumes Blender's default scene (a cube, a camera, a light)
    build_steps: int = 0                                    # steps with exact numbers (add / set)
    geometry_table: list[str] = field(default_factory=list)  # where each part ends up (bounding boxes), for the self-check
    corrected: bool = False                                  # the model was asked to fix its geometry and did
    tokens_in: int = 0
    tokens_out: int = 0


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


_FANCY = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
          "\u201c": '"', "\u201d": '"', "\u00a0": " ", "\u202f": " "}
_COMPOUND = re.compile(r"\bthen\b|;|\band then\b|\b(?:press|click|choose|select)\b.*\b(?:press|click|choose|select)\b", re.I)


def _ascii(text: str) -> str:
    """Models like fancy dashes and quotes; plain text is safer for speech, consoles and logs."""
    for k, v in _FANCY.items():
        text = text.replace(k, v)
    return text


def _clean_target(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    t = raw.strip().strip(".\"'")
    if not t or len(t) > 32 or len(t.split()) > 4 or not any(c.isalpha() for c in t):
        return None
    return t


def _click_step(label: str, skip_in_do: bool = False) -> dict:
    d = {"instruction": f"Click {label}.", "spoken": f"Now click {label}.", "why": "It opens the next list of choices.",
            "target": {"text": label}, "shortcut": None, "check": {"kind": "clicked_target"}, "docs_query": f"{label} menu",
            "hint_if_stuck": f"Look for {label} in the menu that just opened."}
    if skip_in_do:
        d["do"] = {"skip_in_do": True}        # Do it adds the shape directly, so opening the menus is not needed
    return d


def repair_menu_order(steps: list[dict]) -> tuple[list[dict], int]:
    """Items inside a menu are only on screen after the menu is opened. If a step points at such an item and the step before
    it did not open that menu, insert the missing opening steps (known hierarchy, see vocabulary.MENU_PARENT)."""
    out: list[dict] = []
    added = 0
    prev_target: str | None = None
    for st in steps:
        tgt = st["target"]["text"] if st.get("target") else None
        if tgt:
            canon = next((k for k in MENU_PARENT if k.lower() == tgt.lower()), None)
            chain = opening_chain(canon) if canon else []
            if tgt.lower() == "add modifier" and not any("wrench" in o["instruction"].lower() for o in out):
                out.append(dict(WRENCH_STEP, check={"kind": "none"}, shortcut=None, docs_query="Modifiers tab",
                                hint_if_stuck=WRENCH_STEP["hint"]))              # the Add Modifier button is on the wrench tab
                added += 1
            if chain:
                have = 0                                                       # how much of the chain is already open
                if prev_target:
                    for i, label in enumerate(chain):
                        if label.lower() == prev_target.lower():
                            have = i + 1
                for label in chain[have:]:
                    if label == "Add Modifier" and not any("wrench" in o["instruction"].lower() for o in out):
                        out.append(dict(WRENCH_STEP, check={"kind": "none"}, shortcut=None, docs_query="Modifiers tab",
                                        hint_if_stuck=WRENCH_STEP["hint"]))
                        added += 1
                    out.append(_click_step(label, skip_in_do=bool(st.get("do") and st["do"].get("direct"))))
                    added += 1
        out.append(st)
        prev_target = tgt
    return out, added


def build_lesson(goal: str, data: dict) -> PlanResult:
    if isinstance(data, dict) and data.get("error"):
        raise PlanError(str(data["error"])[:200])
    steps_in = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps_in, list):
        raise PlanError("The plan did not come back in the right shape. Please try again.")
    steps, unverified, dropped, compound, retargeted = [], [], 0, 0, 0
    bstate = BuildState()
    build_count = 0
    for raw in steps_in:
        if isinstance(raw, dict) and str(raw.get("kind", "")).lower() in ("add", "set"):
            spoken = _limit_sentences(_ascii(str(raw.get("spoken") or "")))
            why = _ascii(str(raw.get("why") or "")).strip()[:200] or "It is the next step toward your goal."
            hint = _ascii(str(raw.get("hint") or "")).strip()[:160] or None
            if any(_UNSAFE.search(x or "") for x in (spoken, why, hint or "", str(raw.get("part") or ""))):
                dropped += 1
                continue
            built = build_step(raw, bstate, spoken, why, hint)
            if built is None:
                dropped += 1
                continue
            if built.get("_reuse_default_cube"):
                continue                                              # the first cube is the one already in the scene
            steps.append(built)
            build_count += 1
            continue
        if not isinstance(raw, dict) or not str(raw.get("instruction", "")).strip():
            dropped += 1
            continue
        instruction = _ascii(str(raw["instruction"]).strip())[:140]
        spoken = _limit_sentences(_ascii(str(raw.get("spoken") or instruction)))
        why = _ascii(str(raw.get("why") or "")).strip()[:200] or "It is the next step toward your goal."
        hint = _ascii(str(raw.get("hint") or "")).strip()[:160] or None
        if any(_UNSAFE.search(x or "") for x in (instruction, spoken, why, hint)):
            dropped += 1                                          # never pass on anything about running code
            continue
        target = _clean_target(_ascii(raw.get("target")) if isinstance(raw.get("target"), str) else raw.get("target"))
        if target and (target.lower() not in instruction.lower() or re.search(r"\bicons?\b", instruction, re.I)):
            target, retargeted = None, retargeted + 1                # the pointer must match what the instruction says
        if target and not is_known(target):
            unverified.append(target)
        if _COMPOUND.search(instruction):
            compound += 1
        shortcut = raw.get("shortcut") if isinstance(raw.get("shortcut"), str) else None
        steps.append({"id": f"s{len(steps) + 1}", "instruction": instruction, "spoken": spoken, "why": why,
                      "target": {"text": target} if target else None, "shortcut": shortcut,
                      "check": {"kind": "clicked_target" if target else "none"}, "docs_query": instruction,
                      "hint_if_stuck": hint})
    if len(steps) < MIN_STEPS:
        raise PlanError("I could not make a safe plan for that. Try describing the goal differently.")
    steps, inserted = repair_menu_order(steps)
    steps = steps[:MAX_STEPS]
    warnings: list[str] = []
    if build_count:
        shown = [p for p in bstate.parts if p is not bstate.parts[0] or bstate.default_touched]
        warnings = default_cube_warning(bstate) + geometry_warnings(shown)
    for i, st in enumerate(steps):
        st["id"] = f"s{i + 1}"
    slug = slugify(str(data.get("title") or goal))
    try:
        lesson = Lesson.model_validate({"id": f"custom-{slug}", "title": str(data.get("title") or goal)[:60].strip(),
                                        "tool": "blender", "skills_taught": [f"custom-{slug}"], "prereqs": [],
                                        "steps": steps})
    except ValidationError as e:
        log.warning("planned lesson failed validation: %s", e)
        raise PlanError("The plan did not pass my checks. Please try again.") from e
    return PlanResult(lesson, sorted(set(unverified)), dropped, compound, inserted, retargeted, warnings,
                      uses_default_scene=bool(build_count), build_steps=build_count,
                      geometry_table=parts_table(shown) if build_count else [])


def plan_lesson(client: ChatClient | None, model: str, goal: str, timeout: float = 40, on_wait=None) -> PlanResult:
    goal = " ".join(goal.split())[:200]
    if len(goal) < 3:
        raise PlanError("Tell me what you want to make or learn, for example: a coffee mug.")
    if client is None:
        raise PlanError("The planning model is not set up (no Groq key), so I can only run the built-in lessons.")
    seen, std = known_labels()
    messages = [{"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": json.dumps({"goal": goal, "labels_seen_on_real_screens": seen,
                                                        "other_standard_labels": std}, ensure_ascii=False)}]
    last_problem = "no answer"
    tokens_in = tokens_out = 0
    fixed_once = False
    for attempt in range(2):
        try:
            resp = _complete(client, model, messages, timeout, on_wait)
        except Exception as e:
            log.warning("planning call failed: %s", str(e)[:200])
            last_problem = "The planning service did not answer. Check your connection and try again."
            continue
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.text.strip())
            result = build_lesson(goal, json.loads(text))
            result.tokens_in, result.tokens_out = tokens_in, tokens_out
            if result.warnings and not fixed_once and result.geometry_table:
                # self-check: show the model what its own numbers build and ask for a corrected plan, once
                fixed_once = True
                messages = messages + [{"role": "assistant", "content": text[:6000]},
                                       {"role": "user", "content": "Check your geometry. This is what your plan builds:\n"
                                        + "\n".join(result.geometry_table) + "\nProblems found:\n- "
                                        + "\n- ".join(result.warnings)
                                        + "\nFix the numbers so every part sits correctly (keep the same parts and the same JSON format). "
                                          "Return the complete corrected plan as JSON only."}]
                first = result
                try:
                    resp2 = _complete(client, model, messages, timeout, on_wait)
                    tokens_in += resp2.tokens_in
                    tokens_out += resp2.tokens_out
                    text2 = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp2.text.strip())
                    second = build_lesson(goal, json.loads(text2))
                    if len(second.warnings) < len(first.warnings):         # keep the better plan
                        result = second
                        result.corrected = True
                except Exception as e:                                      # a failed second round just keeps the first plan
                    log.info("geometry correction round failed: %s", str(e)[:120])
                result.tokens_in, result.tokens_out = tokens_in, tokens_out
            return result
        except PlanError:
            raise
        except (json.JSONDecodeError, ValueError):
            last_problem = "The plan did not come back as valid JSON. Please try again."
            messages = messages + [{"role": "assistant", "content": resp.text[:500]},
                                   {"role": "user", "content": "Return valid JSON only."}]
    raise PlanError(last_problem)
