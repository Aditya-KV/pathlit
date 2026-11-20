"""Build steps for typed tasks: add a shape, then set its exact scale, location and rotation.

The model supplies the shape, the numbers and a short spoken line. THIS CODE writes the instruction text and the step check from
those numbers, so what the learner reads, what Do it performs and what is verified can never disagree.

  {"kind": "add", "shape": "CONE", "part": "roof", ...}                      -> click the shape in Add > Mesh (menus are inserted)
  {"kind": "set", "property": "scale", "values": [2.3, 2.3, 1], "part": "roof"}  -> set that property of the active object

The scene is assumed to be Blender's default scene (a cube, a camera, a light), 3 objects. The default cube starts selected, so
a plan may use it as its first part without adding anything.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# shape -> (label in the Add > Mesh menu, default name Blender gives the new object, half-size of its bounding box at scale 1)
SHAPES: dict[str, tuple[str, str, tuple[float, float, float]]] = {
    "CUBE": ("Cube", "Cube", (1, 1, 1)), "SPHERE": ("UV Sphere", "Sphere", (1, 1, 1)),
    "ICOSPHERE": ("Ico Sphere", "Icosphere", (1, 1, 1)), "CYLINDER": ("Cylinder", "Cylinder", (1, 1, 1)),
    "CONE": ("Cone", "Cone", (1, 1, 1)), "TORUS": ("Torus", "Torus", (1.25, 1.25, 0.25)),
    "PLANE": ("Plane", "Plane", (1, 1, 0)), "MONKEY": ("Monkey", "Suzanne", (1.37, 0.99, 0.85)),
}
PROPS = {"location": "Location", "rotation": "Rotation", "scale": "Scale"}
LIMITS = {"location": (-100.0, 100.0), "rotation": (-360.0, 360.0), "scale": (0.01, 100.0)}
DEFAULT_OBJECTS = 3                              # the default scene: Cube, Camera, Light
GROUND_TOLERANCE = 0.05


@dataclass
class Part:
    name: str
    shape: str
    location: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])


@dataclass
class BuildState:
    adds: int = 0
    parts: list[Part] = field(default_factory=lambda: [Part("default cube", "CUBE")])       # the cube that is already there
    default_touched: bool = False                  # has the plan used the cube that is already in the scene?

    @property
    def active(self) -> Part:
        return self.parts[-1]


def _fmt(v: float) -> str:
    return f"{v:g}"


def _clean_numbers(prop: str, values) -> list[float | None] | None:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return None
    lo, hi = LIMITS[prop]
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        elif prop == "scale" and not (lo <= float(v) <= hi):
            return None
        elif not (-hi <= float(v) <= hi):
            return None
        else:
            out.append(round(float(v), 3))
    return None if all(v is None for v in out) else out


def build_step(raw: dict, state: BuildState, spoken: str, why: str, hint: str | None) -> dict | None:
    """One 'add' or 'set' step as a lesson-step dict, or None if it is invalid. Updates `state` as the plan is built."""
    kind = str(raw.get("kind", "")).lower()
    part = str(raw.get("part") or "").strip()[:30] or "this part"
    part_cap = part[0].upper() + part[1:]
    if kind == "add":
        shape = str(raw.get("shape", "")).upper()
        shape = {"UV_SPHERE": "SPHERE", "ICO_SPHERE": "ICOSPHERE"}.get(shape, shape)
        if shape not in SHAPES:
            return None
        label, default_name, _ = SHAPES[shape]
        if shape == "CUBE" and state.adds == 0 and not state.default_touched and len(state.parts) == 1:
            state.parts[0].name = part                 # the first cube IS the default cube: no need to add another
            state.default_touched = True
            return {"_reuse_default_cube": True}
        state.adds += 1
        state.parts.append(Part(part, shape))
        return {"instruction": f"{part_cap}: click {label}.", "spoken": spoken or f"Add a {label.lower()} for the {part}.",
                "why": why, "target": {"text": label}, "shortcut": None,
                "check": {"kind": "blender_state", "active_object_name_contains": default_name,
                          "object_count_at_least": DEFAULT_OBJECTS + state.adds},
                "docs_query": f"add {label} mesh", "hint_if_stuck": hint or f"{label} is in the Mesh list of the Add menu.",
                "do": {"direct": {"action": "add_primitive", "args": {"type": shape}}}}
    if kind == "set":
        prop = str(raw.get("property", "")).lower()
        if prop not in PROPS:
            return None
        values = _clean_numbers(prop, raw.get("values"))
        if values is None:
            return None
        label = PROPS[prop]
        if state.active is state.parts[0]:
            state.default_touched = True
            if state.parts[0].name == "default cube":
                state.parts[0].name = part                 # the plan's own name for the cube that was already there
        cur = getattr(state.active, prop)
        for i, v in enumerate(values):
            if v is not None:
                cur[i] = v
        unit = " degrees" if prop == "rotation" else ""
        nums = ", ".join(f"{'XYZ'[i]} {_fmt(v)}" for i, v in enumerate(values) if v is not None)
        return {"instruction": f"{part_cap}: set {label} to {nums}{unit}.",
                "spoken": spoken or f"Set the {label.lower()} so the {part} has the right {'size' if prop == 'scale' else 'place'}.",
                "why": why,
                "target": {"text": label}, "shortcut": None,
                "check": {"kind": "blender_state", f"{prop}_approx": values},
                "docs_query": f"object {prop} transform",
                "hint_if_stuck": hint or f"Properties panel, Object tab, Transform: type the numbers into the {label} boxes.",
                "do": {"click": False, "direct": {"action": "set_transform", "args": {"property": prop, "values": values}}}}
    return None


# ------------------------------------------------------------------ geometry sanity (approximate, rotation ignored)
def _rotation_matrix(rx: float, ry: float, rz: float) -> list[list[float]]:
    """Blender's default XYZ Euler order: rotate about X first, then Y, then Z (angles in degrees)."""
    ax, ay, az = math.radians(rx), math.radians(ry), math.radians(rz)
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def _box(p: Part) -> tuple[list[float], list[float]]:
    """World-space bounding box of the part, including its rotation (so an upright door made from a plane is upright)."""
    half = SHAPES[p.shape][2]
    h = [half[i] * abs(p.scale[i]) for i in range(3)]
    R = _rotation_matrix(*p.rotation)
    xs = [[], [], []]
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                v = (sx * h[0], sy * h[1], sz * h[2])
                for i in range(3):
                    xs[i].append(p.location[i] + R[i][0] * v[0] + R[i][1] * v[1] + R[i][2] * v[2])
    return [min(c) for c in xs], [max(c) for c in xs]


def _touch(a: Part, b: Part, tol: float = 0.06) -> bool:
    (alo, ahi), (blo, bhi) = _box(a), _box(b)
    return all(alo[i] - tol <= bhi[i] and blo[i] - tol <= ahi[i] for i in range(3))


def _volume(lo: list[float], hi: list[float]) -> float:
    dims = [max(hi[i] - lo[i], 0.0) for i in range(3)]
    return dims[0] * dims[1] * dims[2]


def _overlap_fraction(a: Part, b: Part) -> float:
    """How much of part a's bounding box lies inside part b's (0 to 1). Flat parts (planes) use their area."""
    (alo, ahi), (blo, bhi) = _box(a), _box(b)
    inter = [max(0.0, min(ahi[i], bhi[i]) - max(alo[i], blo[i])) for i in range(3)]
    dims = [max(ahi[i] - alo[i], 1e-9) for i in range(3)]
    flat = [i for i in range(3) if dims[i] < 1e-6 or (ahi[i] - alo[i]) < 1e-6]
    if flat:
        for i in flat:                                     # a flat part must lie WITHIN the other part's range on its thin axis
            if not (blo[i] + 0.05 <= alo[i] <= bhi[i] - 0.05):     # resting ON the surface is not "inside"
                return 0.0
        keep = [i for i in range(3) if i not in flat]
        num = 1.0
        den = 1.0
        for i in keep:
            num *= inter[i]
            den *= dims[i]
        return num / den if den else 0.0
    return (inter[0] * inter[1] * inter[2]) / (dims[0] * dims[1] * dims[2])


def parts_table(parts: list[Part]) -> list[str]:
    """One line per part: where its box ends up. The model reads this to check its own arithmetic."""
    out = []
    for p in parts:
        lo, hi = _box(p)
        out.append(f"{p.name} ({p.shape.lower()}): x {lo[0]:.2f} to {hi[0]:.2f}, y {lo[1]:.2f} to {hi[1]:.2f}, "
                   f"z {lo[2]:.2f} to {hi[2]:.2f}")
    return out


BURIED_FRACTION = 0.7


def _cone_surface_z(cone: Part, x: float, y: float) -> float | None:
    """Height of the cone's sloping surface above (x, y), or None if (x, y) is outside its footprint. Upright cones only."""
    if any(abs(r) > 1 for r in cone.rotation[:2]):
        return None
    rx, ry = abs(cone.scale[0]), abs(cone.scale[1])
    r = math.hypot((x - cone.location[0]) / rx, (y - cone.location[1]) / ry)
    if r >= 1:
        return None
    base = cone.location[2] - abs(cone.scale[2])
    return base + 2 * abs(cone.scale[2]) * (1 - r)


def _cone_warnings(parts: list[Part]) -> list[str]:
    """Parts that should sit on a cone (a roof) but hang in the air above its sloping surface."""
    out = []
    for cone in (p for p in parts if p.shape == "CONE"):
        for p in parts:
            if p is cone or p.shape == "CONE":
                continue
            lo, hi = _box(p)
            surface = _cone_surface_z(cone, (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
            if surface is not None and lo[2] > surface + 0.12 and lo[2] >= _box(cone)[0][2]:
                out.append(f"the {p.name} floats {lo[2] - surface:.2f} above the {cone.name} (the {cone.name} surface there is at z "
                           f"{surface:.2f}); lower it so its bottom is at or below z {surface:.2f}")
    return out


def geometry_warnings(parts: list[Part]) -> list[str]:
    """Plain-language warnings about parts that look wrong: below the ground, or floating clear of everything else.
    Approximate (bounding boxes, rotation ignored), so these are hints, never errors."""
    out = []
    real = parts
    for p in real:
        lo, _ = _box(p)
        if lo[2] < -GROUND_TOLERANCE:
            out.append(f"the {p.name} sinks {abs(lo[2]):.1f} below the ground")
    for p in real:                                        # a plane is flat: in the air it is an invisible sliver
        lo, hi = _box(p)
        if p.shape == "PLANE" and (hi[2] - lo[2]) < 0.05 and p.location[2] > 0.3:
            out.append(f"the {p.name} is a flat plane lying sideways in the air (it will be an invisible sliver); use a thin CUBE "
                       f"instead (for example scale [0.5, 0.06, 0.9]), or rotate the plane 90 degrees about X to stand it up")
    out += _cone_warnings(real)
    if len(real) > 1:
        for i, p in enumerate(real):
            if not any(_touch(p, q) for j, q in enumerate(real) if j != i):
                out.append(f"the {p.name} does not touch any other part (it may float)")
        for i, p in enumerate(real):                       # a part mostly hidden inside a bigger one is almost always a mistake
            for j, q in enumerate(real):
                if i == j or _volume(*_box(p)) >= _volume(*_box(q)):
                    continue
                f = _overlap_fraction(p, q)
                if f >= BURIED_FRACTION:
                    lo_q, hi_q = _box(q)
                    out.append(f"the {p.name} is {f:.0%} inside the {q.name} (the {q.name} reaches z {hi_q[2]:.2f}); "
                               f"if the {p.name} should sit on top, its Location Z should be {hi_q[2]:.2f} plus its own half-height")
    return out


def default_cube_warning(state: BuildState) -> list[str]:
    """If the plan never uses the cube that is already in the scene, it stays there as an extra object."""
    if state.default_touched or len(state.parts) == 1:
        return []
    return ["the default cube is still in the scene at the centre; use it as a part, or delete it (Object > Delete)"]
