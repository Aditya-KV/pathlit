"""What "Show me" and "Do it" are allowed to do (addendum FR-27, FR-29). Everything is validated here before anything runs.

Direct actions run INSIDE Blender through the add-on, from a fixed allow-list. Cursor actions are clicks on text the screen
reader found. Anything not on these lists is refused. Nothing here ever types text or presses keys.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

ALLOWED_DIRECT = ("add_primitive", "set_mode", "select_object", "add_modifier", "set_modifier_value", "transform",
                  "set_transform", "undo")
PRIMITIVES = {"CUBE", "SPHERE", "ICOSPHERE", "TORUS", "PLANE", "CYLINDER", "CONE", "MONKEY"}
MODES = {"OBJECT", "EDIT", "SCULPT"}
MODIFIERS = {"SUBSURF", "BEVEL", "MIRROR"}
MODIFIER_ALIASES = {"SUBDIVISION": "SUBSURF", "SUBDIVISION_SURFACE": "SUBSURF", "SUBSURFACE": "SUBSURF"}
# modifier -> {setting: (min, max)} ; booleans use (0, 1)
MODIFIER_VALUES: dict[str, dict[str, tuple[float, float]]] = {
    "BEVEL": {"width": (0.0001, 10), "segments": (1, 32)},
    "SUBSURF": {"levels": (0, 6), "render_levels": (0, 6)},
    "MIRROR": {"use_axis_x": (0, 1), "use_axis_y": (0, 1), "use_axis_z": (0, 1)},
}
TRANSFORM_LIMITS = {"move": (-1000, 1000), "rotate": (-3600, 3600), "scale": (0.001, 1000)}
SET_LIMITS = {"location": (-1000, 1000), "rotation": (-3600, 3600), "scale": (-1000, 1000)}

# Clicking these could lose work or leave the app (FR-29). Refused unless the lesson step explicitly allows it.
DANGEROUS_WORDS = ("save", "save as", "save copy", "export", "import", "quit", "exit", "delete", "delete global", "revert",
                   "recover", "new", "open", "open recent", "load factory settings", "overwrite", "purge", "install")


class ActionRefused(ValueError):
    """The action is not allowed. The message is safe to speak and to log."""


class Action(BaseModel):
    kind: Literal["direct", "click", "move"]          # move = point with the real cursor but do not click
    action: str | None = None                          # direct actions only
    target_text: str | None = None                     # cursor actions: named by on-screen text, never by pixels
    args: dict[str, Any] = {}


def _num(v: Any, lo: float, hi: float, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= float(v) <= hi):
        raise ActionRefused(f"{what} must be a number between {lo} and {hi}")
    return float(v)


def validate_direct(action: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Return normalised args, or raise ActionRefused. The add-on repeats this check: it is the final authority."""
    args = dict(args or {})
    if action not in ALLOWED_DIRECT:
        raise ActionRefused(f"'{action}' is not on the allow-list")
    if action == "add_primitive":
        t = str(args.get("type", "")).upper()
        t = "SPHERE" if t in ("UV_SPHERE", "UVSPHERE") else t
        if t not in PRIMITIVES:
            raise ActionRefused(f"primitive must be one of {sorted(PRIMITIVES)}")
        return {"type": t}
    if action == "set_mode":
        m = str(args.get("mode", "")).upper()
        if m not in MODES:
            raise ActionRefused(f"mode must be one of {sorted(MODES)}")
        return {"mode": m}
    if action == "select_object":
        name = str(args.get("name", ""))
        if not name or len(name) > 63 or not re.fullmatch(r"[\w .\-]+", name):
            raise ActionRefused("object name is missing or has odd characters")
        return {"name": name}
    if action == "add_modifier":
        t = str(args.get("type", "")).upper().replace(" ", "_")
        t = MODIFIER_ALIASES.get(t, t)
        if t not in MODIFIERS:
            raise ActionRefused(f"modifier must be one of {sorted(MODIFIERS)}")
        return {"type": t}
    if action == "set_modifier_value":
        t = MODIFIER_ALIASES.get(str(args.get("modifier", "")).upper(), str(args.get("modifier", "")).upper())
        key = str(args.get("key", ""))
        if t not in MODIFIER_VALUES or key not in MODIFIER_VALUES[t]:
            raise ActionRefused(f"cannot set '{key}' on '{t}'")
        lo, hi = MODIFIER_VALUES[t][key]
        v = args.get("value")
        if (lo, hi) == (0, 1) and isinstance(v, bool):
            v = int(v)
        return {"modifier": t, "key": key, "value": _num(v, lo, hi, key)}
    if action == "transform":
        op = str(args.get("op", "")).lower()
        if op not in TRANSFORM_LIMITS:
            raise ActionRefused("transform op must be move, rotate or scale")
        vals = args.get("values")
        if not isinstance(vals, (list, tuple)) or len(vals) != 3:
            raise ActionRefused("transform needs three values [x, y, z]")
        lo, hi = TRANSFORM_LIMITS[op]
        return {"op": op, "values": [_num(x, lo, hi, "value") for x in vals]}
    if action == "set_transform":
        prop = str(args.get("property", "")).lower()
        vals = args.get("values")
        if prop not in SET_LIMITS or not isinstance(vals, (list, tuple)) or len(vals) != 3:
            raise ActionRefused("set_transform needs a property (location, rotation, scale) and three values")
        lo, hi = SET_LIMITS[prop]
        out = [None if v is None else _num(v, lo, hi, "value") for v in vals]       # null = leave that axis alone
        if all(v is None for v in out) or (prop == "scale" and any(v is not None and v == 0 for v in out)):
            raise ActionRefused("nothing to set, or a scale of zero")
        return {"property": prop, "values": out}
    if action == "undo":
        return {"steps": int(_num(args.get("steps", 1), 1, 10, "steps"))}
    raise ActionRefused(f"'{action}' is not implemented")        # unreachable, kept as a safe default


def is_dangerous(text: str) -> bool:
    low = re.sub(r"[^a-z ]", " ", text.lower()).strip()
    low = re.sub(r"\s+", " ", low)
    return any(low == w or low.startswith(w + " ") for w in DANGEROUS_WORDS)


def describe(a: Action) -> str:
    if a.kind == "click":
        return f"click {a.target_text}"
    if a.kind == "move":
        return f"point at {a.target_text}"
    names = {"add_primitive": lambda g: f"add a {g['type'].lower()}", "set_mode": lambda g: f"switch to {g['mode'].lower()} mode",
             "select_object": lambda g: f"select {g['name']}", "add_modifier": lambda g: f"add a {g['type'].lower()} modifier",
             "set_modifier_value": lambda g: f"set {g['key']} on the {g['modifier'].lower()} modifier",
             "transform": lambda g: f"{g['op']} the selected object",
             "set_transform": lambda g: f"set the {g['property']} of the active object", "undo": lambda g: f"undo {g['steps']} step(s)"}
    try:
        return names[a.action or ""](validate_direct(a.action or "", a.args))
    except (ActionRefused, KeyError):
        return "do something that is not allowed"
