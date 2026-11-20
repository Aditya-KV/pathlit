"""The add-on's allow-list of direct actions (addendum FR-27). Self-contained: bpy and the standard library only.

The app validates every request, and this module validates it AGAIN: it is the final authority. Requests are plain data.
Nothing from a request is ever passed to exec or eval. Anything not listed here is refused.
"""
import math
import re

ALLOWED = ("add_primitive", "set_mode", "select_object", "add_modifier", "set_modifier_value", "transform", "set_transform",
           "undo")
PRIMITIVES = {"CUBE", "SPHERE", "ICOSPHERE", "TORUS", "PLANE", "CYLINDER", "CONE", "MONKEY"}
MODES = {"OBJECT", "EDIT", "SCULPT"}
MODIFIERS = {"SUBSURF", "BEVEL", "MIRROR"}
ALIASES = {"SUBDIVISION": "SUBSURF", "SUBDIVISION_SURFACE": "SUBSURF", "SUBSURFACE": "SUBSURF"}
VALUES = {
    "BEVEL": {"width": (0.0001, 10), "segments": (1, 32)},
    "SUBSURF": {"levels": (0, 6), "render_levels": (0, 6)},
    "MIRROR": {"use_axis_x": (0, 1), "use_axis_y": (0, 1), "use_axis_z": (0, 1)},
}
LIMITS = {"move": (-1000, 1000), "rotate": (-3600, 3600), "scale": (0.001, 1000)}
SET_LIMITS = {"location": (-1000, 1000), "rotation": (-3600, 3600), "scale": (-1000, 1000)}
INTEGER_KEYS = {"segments", "levels", "render_levels"}
BOOL_KEYS = {"use_axis_x", "use_axis_y", "use_axis_z"}


class Refused(ValueError):
    pass


def _num(v, lo, hi, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= float(v) <= hi):
        raise Refused("%s must be a number between %s and %s" % (what, lo, hi))
    return float(v)


def validate(action, args):
    """Return cleaned args or raise Refused. Pure Python (no bpy), so it can be tested outside Blender."""
    args = dict(args or {})
    if action not in ALLOWED:
        raise Refused("'%s' is not on the allow-list" % action)
    if action == "add_primitive":
        t = str(args.get("type", "")).upper()
        t = "SPHERE" if t in ("UV_SPHERE", "UVSPHERE") else t
        if t not in PRIMITIVES:
            raise Refused("unknown primitive")
        return {"type": t}
    if action == "set_mode":
        m = str(args.get("mode", "")).upper()
        if m not in MODES:
            raise Refused("unknown mode")
        return {"mode": m}
    if action == "select_object":
        name = str(args.get("name", ""))
        if not name or len(name) > 63 or not re.fullmatch(r"[\w .\-]+", name):
            raise Refused("bad object name")
        return {"name": name}
    if action == "add_modifier":
        t = str(args.get("type", "")).upper().replace(" ", "_")
        t = ALIASES.get(t, t)
        if t not in MODIFIERS:
            raise Refused("unknown modifier")
        return {"type": t}
    if action == "set_modifier_value":
        m = str(args.get("modifier", "")).upper()
        m = ALIASES.get(m, m)
        key = str(args.get("key", ""))
        if m not in VALUES or key not in VALUES[m]:
            raise Refused("cannot set that value")
        lo, hi = VALUES[m][key]
        v = args.get("value")
        if (lo, hi) == (0, 1) and isinstance(v, bool):
            v = int(v)
        return {"modifier": m, "key": key, "value": _num(v, lo, hi, key)}
    if action == "transform":
        op = str(args.get("op", "")).lower()
        vals = args.get("values")
        if op not in LIMITS or not isinstance(vals, (list, tuple)) or len(vals) != 3:
            raise Refused("bad transform")
        lo, hi = LIMITS[op]
        return {"op": op, "values": [_num(x, lo, hi, "value") for x in vals]}
    if action == "set_transform":
        prop = str(args.get("property", "")).lower()
        vals = args.get("values")
        if prop not in SET_LIMITS or not isinstance(vals, (list, tuple)) or len(vals) != 3:
            raise Refused("bad set_transform")
        lo, hi = SET_LIMITS[prop]
        out = [None if v is None else _num(v, lo, hi, "value") for v in vals]
        if all(v is None for v in out) or (prop == "scale" and any(v is not None and v == 0 for v in out)):
            raise Refused("nothing to set, or a zero scale")
        return {"property": prop, "values": out}
    if action == "undo":
        return {"steps": int(_num(args.get("steps", 1), 1, 10, "steps"))}
    raise Refused("not implemented")


def run(bpy, action, args):
    """Run an already validated action. MUST be called on Blender's main thread. Returns a short text for the log."""
    ctx = bpy.context
    obj = ctx.view_layer.objects.active
    if action == "add_primitive":
        if obj is not None and obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        op = {"CUBE": bpy.ops.mesh.primitive_cube_add, "SPHERE": bpy.ops.mesh.primitive_uv_sphere_add,
              "ICOSPHERE": bpy.ops.mesh.primitive_ico_sphere_add, "TORUS": bpy.ops.mesh.primitive_torus_add,
              "PLANE": bpy.ops.mesh.primitive_plane_add, "CYLINDER": bpy.ops.mesh.primitive_cylinder_add,
              "CONE": bpy.ops.mesh.primitive_cone_add, "MONKEY": bpy.ops.mesh.primitive_monkey_add}[args["type"]]
        op()
        return "added " + args["type"].lower()
    if action == "set_mode":
        if obj is None:
            raise Refused("there is no active object")
        bpy.ops.object.mode_set(mode=args["mode"])
        return "mode " + args["mode"]
    if action == "select_object":
        target = bpy.data.objects.get(args["name"])
        if target is None:
            raise Refused("no object with that name")
        for o in ctx.view_layer.objects:
            o.select_set(False)
        target.select_set(True)
        ctx.view_layer.objects.active = target
        return "selected " + target.name
    if obj is None:
        raise Refused("there is no active object")
    if action == "add_modifier":
        obj.modifiers.new(name=args["type"].title(), type=args["type"])
        return "added modifier " + args["type"]
    if action == "set_modifier_value":
        mod = next((m for m in obj.modifiers if m.type == args["modifier"]), None)
        if mod is None:
            raise Refused("the active object has no such modifier")
        v = args["value"]
        key = args["key"]
        setattr(mod, key, bool(v) if key in BOOL_KEYS else (int(v) if key in INTEGER_KEYS else float(v)))
        return "set %s" % key
    if action == "transform":
        x, y, z = args["values"]
        if args["op"] == "move":
            obj.location.x += x
            obj.location.y += y
            obj.location.z += z
        elif args["op"] == "rotate":
            obj.rotation_euler.x += math.radians(x)
            obj.rotation_euler.y += math.radians(y)
            obj.rotation_euler.z += math.radians(z)
        else:
            obj.scale.x *= x
            obj.scale.y *= y
            obj.scale.z *= z
        return args["op"]
    if action == "set_transform":
        for i, v in enumerate(args["values"]):
            if v is None:
                continue
            if args["property"] == "location":
                obj.location[i] = v
            elif args["property"] == "rotation":
                obj.rotation_euler[i] = math.radians(v)
            else:
                obj.scale[i] = v
        return "set " + args["property"]
    if action == "undo":
        # undo needs a window, a 3D view area and a region; a timer callback has none, so borrow the first 3D view
        win = ctx.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        with ctx.temp_override(window=win, screen=win.screen, area=area, region=region):
            for _ in range(args["steps"]):
                bpy.ops.ed.undo()
        return "undid %d" % args["steps"]
    raise Refused("not implemented")
