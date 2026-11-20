"""Blender 4.1 labels the planner may use as pointer targets.

SEEN_ON_SCREEN: labels that appeared on the owner's real Blender 4.1 screenshots (menus, tabs, panels).
STANDARD: labels that exist in the standard Blender 4.1 interface but have NOT yet been seen on a screenshot here.
A planned step whose target is in neither list is still allowed (the lists are incomplete), but it is reported to the
learner as unverified, and at run time Pathlit asks "Can you see X?" if the text is not found (FR-17).
"""
from __future__ import annotations

SEEN_ON_SCREEN = [
    # top bar and workspaces
    "File", "Edit", "Render", "Window", "Help", "View", "Select", "Add", "Object", "Layout", "Modeling", "Sculpting",
    "UV Editing", "Texture Paint", "Shading", "Animation", "Rendering", "Compositing", "Geometry Nodes", "Scripting",
    # modes
    "Object Mode", "Edit Mode", "Sculpt Mode",
    # Add menu
    "Mesh", "Curve", "Surface", "Metaball", "Text", "Volume", "Grease Pencil", "Armature", "Lattice", "Empty", "Image",
    "Light", "Light Probe", "Camera", "Speaker", "Force Field", "Collection Instance",
    # Object menu
    "Transform", "Set Origin", "Mirror", "Clear", "Apply", "Snap", "Duplicate Objects", "Duplicate Linked", "Join",
    "Copy Objects", "Paste Objects", "Asset", "Collection", "Library Override", "Relations", "Parent", "Constraints",
    "Track", "Link/Transfer Data", "Shade Smooth", "Shade Smooth by Angle", "Shade Flat", "Rigid Body", "Quick Effects",
    "Convert", "Show/Hide", "Clean Up", "Delete", "Delete Global",
    # Edit menu
    "Undo", "Redo", "Undo History", "Adjust Last Operation", "Repeat Last", "Repeat History", "Menu Search",
    "Rename Active Item", "Batch Rename", "Lock Object Modes", "Preferences",
    # Properties editor
    "Delta Transform", "Collections", "Instancing", "Motion Paths", "Visibility", "Viewport Display", "Line Art",
    "Custom Properties", "Location", "Rotation", "Scale", "Render Engine", "Sampling", "Ambient Occlusion", "Bloom",
    "Depth of Field", "Subsurface Scattering", "Motion Blur", "Volumetrics", "Performance", "Shadows", "Film",
    # sculpt mode header
    "Brush", "Texture", "Stroke", "Falloff", "Cursor", "Dyntopo", "Remesh", "Radius", "Strength",
    # timeline
    "Playback", "Keying", "Marker",
]

STANDARD = [
    # Add > Mesh
    "Plane", "Cube", "Circle", "UV Sphere", "Ico Sphere", "Cylinder", "Cone", "Torus", "Grid", "Monkey",
    # Add > Light
    "Point", "Sun", "Spot", "Area",
    # Properties editor and modifiers
    "Add Modifier", "Generate", "Deform", "Normals", "Physics", "Array", "Bevel", "Boolean", "Build", "Decimate",
    "Edge Split", "Mask", "Multiresolution", "Screw", "Skin", "Solidify", "Subdivision Surface", "Triangulate", "Weld",
    "Wireframe", "Smooth", "Simple Deform", "Displace",
    # Edit mode menus
    "Vertex", "Edge", "Face",
    # shading and materials
    "New", "Use Nodes", "Surface", "Base Color", "Roughness", "Metallic",
]


def known_labels() -> tuple[list[str], list[str]]:
    seen = list(dict.fromkeys(SEEN_ON_SCREEN))
    std = [x for x in dict.fromkeys(STANDARD) if x not in seen]
    return seen, std


def is_known(label: str) -> bool:
    seen, std = known_labels()
    low = label.strip().lower()
    return any(low == x.lower() for x in seen + std)


# ---------------- menu hierarchy ----------------
# child label -> the label that must be clicked first to open it. Built from the owner's real Blender 4.1 screenshots
# (Add, Object and mode menus) plus the standard Mesh, Light and Add Modifier lists. Labels that appear in more than one
# menu in Blender (Mirror, Smooth, Remesh) are left out on purpose: a label-keyed map cannot tell them apart.
_MENUS: dict[str, list[str]] = {
    "Add": ["Mesh", "Curve", "Surface", "Metaball", "Text", "Volume", "Grease Pencil", "Armature", "Lattice", "Empty", "Image",
            "Light", "Light Probe", "Camera", "Speaker", "Force Field", "Collection Instance"],
    "Mesh": ["Plane", "Cube", "Circle", "UV Sphere", "Ico Sphere", "Cylinder", "Cone", "Torus", "Grid", "Monkey"],
    "Light": ["Point", "Sun", "Spot", "Area"],
    "Object": ["Transform", "Set Origin", "Clear", "Apply", "Snap", "Duplicate Objects", "Duplicate Linked", "Join",
               "Copy Objects", "Paste Objects", "Asset", "Collection", "Library Override", "Relations", "Parent",
               "Constraints", "Track", "Link/Transfer Data", "Shade Smooth", "Shade Smooth by Angle", "Shade Flat",
               "Rigid Body", "Quick Effects", "Convert", "Show/Hide", "Clean Up", "Delete", "Delete Global"],
    "Object Mode": ["Edit Mode", "Sculpt Mode"],                      # the mode dropdown at the left of the 3D view header
    "Add Modifier": ["Generate", "Deform", "Normals", "Physics"],
    "Generate": ["Subdivision Surface", "Bevel", "Array", "Boolean", "Build", "Decimate", "Edge Split", "Mask",
                 "Multiresolution", "Screw", "Skin", "Solidify", "Triangulate", "Weld", "Wireframe"],
    "Edit": ["Undo", "Redo", "Undo History", "Adjust Last Operation", "Repeat Last", "Repeat History", "Menu Search",
             "Rename Active Item", "Batch Rename", "Lock Object Modes", "Preferences"],
}
MENU_PARENT: dict[str, str] = {child: parent for parent, kids in _MENUS.items() for child in kids}
# "Add Modifier" only exists on the Modifiers tab, which is a wrench ICON (no text to point at)
WRENCH_STEP = {"instruction": "Click the blue wrench icon in the Properties panel (Modifiers tab).",
               "spoken": "Find the blue wrench icon in the panel on the right. That is the Modifiers tab.",
               "why": "Modifiers change a shape without destroying it.", "target": None,
               "hint": "The wrench is in the column of small icons on the right edge."}


def opening_chain(label: str) -> list[str]:
    """Labels to click, outermost first, before `label` is visible. [] for a top-level label."""
    chain: list[str] = []
    cur = label
    while cur in MENU_PARENT:
        cur = MENU_PARENT[cur]
        chain.append(cur)
    return list(reversed(chain))
