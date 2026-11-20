"""The 50-scene plan for the evaluation data set (SRS 12).

Each scene says how to set up Blender, which lesson steps that screenshot proves DONE (True) or NOT DONE (False), and which
labels to draw boxes around for the pointing test. Because the truth comes from how the scene is set up, the step-check
ground truth is recorded at capture time and does not have to be labelled afterwards.
The first 24 scenes are the lesson-driven ones (before/after pairs); the other 26 add crowded or different layouts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

L = {1: "blender-001-donut", 2: "blender-002-edit-mode", 3: "blender-003-workspaces", 4: "blender-004-sculpt-intro",
     5: "blender-005-camera-light", 6: "blender-006-duplicate", 7: "blender-007-properties", 8: "blender-008-render-settings"}


@dataclass
class Scene:
    id: str
    setup: str                                           # how to put Blender in this state
    cases: list[tuple[str, str, bool]] = field(default_factory=list)      # (lesson id, step id, was the step done here?)
    targets: list[str] = field(default_factory=list)     # texts to box for the pointing test (empty = you choose 3 visible ones)


def _c(lesson: int, step: str, done: bool) -> tuple[str, str, bool]:
    return (L[lesson], step, done)


CORE = [
    Scene("p01", "Fresh default scene, Layout workspace, the cube selected, Object Mode, nothing open.",
          [_c(1, "s1", False), _c(2, "s1", False), _c(3, "s1", False), _c(4, "s1", False), _c(5, "s1", False),
           _c(5, "s4", False), _c(6, "s1", False), _c(8, "s1", False)],
          ["Add", "Object", "Layout", "Shading", "Object Mode"]),
    Scene("p02", "Same scene. Click Add so the Add menu is open (do not click anything inside it).",
          [_c(1, "s1", True), _c(1, "s2", False), _c(5, "s1", True), _c(5, "s4", True)],
          ["Mesh", "Light", "Camera", "Speaker", "Add"]),
    Scene("p03", "Add menu open, then hover Mesh so its submenu (Plane, Cube, Torus...) is open.",
          [_c(1, "s2", True), _c(1, "s3", False)], ["Torus", "Cube", "Cylinder", "Mesh", "Monkey"]),
    Scene("p04", "Click Torus. The torus is added and active. No menu open.",
          [_c(1, "s3", True), _c(1, "s4", False), _c(6, "s1", False)], ["Object", "Add"]),
    Scene("p05", "Click Object in the top bar so the Object menu is open (torus selected).",
          [_c(1, "s4", True), _c(6, "s1", True), _c(6, "s3", True)],
          ["Shade Smooth", "Duplicate Objects", "Delete", "Object"]),
    Scene("p06", "Click Shade Smooth. Menu closed, torus selected, Properties panel on its default Object tab.",
          [_c(1, "s6", False)], ["Transform", "Location"]),
    Scene("p07", "Click the blue wrench icon in the Properties panel (Modifiers tab).",
          [_c(1, "s6", True), _c(1, "s7", False)], ["Add Modifier"]),
    Scene("p08", "Click Add Modifier so its menu (Edit, Generate, Deform...) is open.",
          [_c(1, "s7", True), _c(1, "s8", False)], ["Generate", "Deform"]),
    Scene("p09", "Hover Generate so its submenu (Array, Bevel, Subdivision Surface...) is open.",
          [_c(1, "s8", True), _c(1, "s9", False)], ["Subdivision Surface", "Bevel", "Array"]),
    Scene("p10", "Click Subdivision Surface. The modifier is on the torus and its panel is visible.",
          [_c(1, "s9", True)], []),
    Scene("p11", "New default scene. Click the mode dropdown that says Object Mode so its list is open.",
          [_c(2, "s1", True), _c(4, "s1", True), _c(2, "s2", False)], ["Edit Mode", "Sculpt Mode", "Object Mode"]),
    Scene("p12", "Choose Edit Mode. You are in Edit Mode, dropdown closed.",
          [_c(2, "s2", True), _c(2, "s3", False)], ["Edit Mode", "Select"]),
    Scene("p13", "Still in Edit Mode: click the mode dropdown (which now says Edit Mode) so it is open.",
          [_c(2, "s3", True)], ["Object Mode", "Edit Mode"]),
    Scene("p14", "Choose Object Mode. Back in Object Mode, dropdown closed.",
          [_c(2, "s4", True), _c(2, "s2", False)], ["Object Mode"]),
    Scene("p15", "Click the Sculpting workspace tab. Sculpt Mode is active.",
          [_c(3, "s1", True), _c(4, "s2", True), _c(3, "s2", False), _c(4, "s4", False)],
          ["Radius", "Strength", "Sculpt Mode", "Sculpting"]),
    Scene("p16", "In the Sculpting workspace click the mode dropdown (Sculpt Mode) so its list is open.",
          [_c(4, "s4", True)], ["Object Mode", "Sculpt Mode", "Edit Mode"]),
    Scene("p17", "Click the Shading workspace tab.",
          [_c(3, "s2", True), _c(3, "s3", False)], ["Use Nodes", "Layout", "Shading"]),
    Scene("p18", "Click the Layout workspace tab. Back to the normal view.",
          [_c(3, "s3", True), _c(3, "s1", False)], ["Playback", "Layout"]),
    Scene("p19", "Open Add, then hover Light so its submenu (Point, Sun, Spot, Area) is open. Three objects in the scene.",
          [_c(5, "s2", True), _c(5, "s3", False)], ["Point", "Sun", "Spot", "Area", "Light"]),
    Scene("p20", "Click Point. A point light is added (4 objects). No menu open.",
          [_c(5, "s3", True), _c(5, "s5", False)], ["Add"]),
    Scene("p21", "Add > Camera. A second camera is added (5 objects).", [_c(5, "s5", True)], ["Add"]),
    Scene("p22", "New default scene. Select the cube, then Object > Duplicate Objects, move the mouse and click. 4 objects.",
          [_c(6, "s2", True)], ["Object"]),
    Scene("p23", "Click the Render tab in the Properties panel (second icon from the top, a camera back).",
          [_c(8, "s1", True)], ["Render Engine", "Sampling"]),
    Scene("p24", "Properties panel on the Object tab, Transform panel open (a normal Layout workspace).",
          [], ["Transform", "Location", "Rotation", "Scale"]),
]

VARIETY_SETUPS = [
    "Select menu open (top bar of the 3D view).", "View menu open (3D view).", "Render menu open (top of the window).",
    "Window menu open.", "Help menu open.", "File menu open.", "Animation workspace.", "Geometry Nodes workspace.",
    "Compositing workspace.", "Texture Paint workspace.", "UV Editing workspace.", "Scripting workspace.",
    "Rendering workspace.", "Modeling workspace in Edit Mode.", "Outliner with all three objects expanded (click the arrows).",
    "Properties panel on the Material tab.", "Properties panel on the World tab.", "Properties panel on the Scene tab.",
    "Properties panel on the Data (green triangle) tab.", "Viewport Shading popover open (the small arrow next to the sphere icons).",
    "Overlays popover open.", "Add > Curve submenu open.", "Add > Empty submenu open.", "Object > Transform submenu open.",
    "Object > Apply submenu open.", "Edit Mode with a face selected and the Mesh menu open.",
]
VARIETY = [Scene(f"p{25 + i}", s) for i, s in enumerate(VARIETY_SETUPS)]

PLAN: list[Scene] = CORE + VARIETY


def scene_by_id(scene_id: str) -> Scene:
    return next(s for s in PLAN if s.id == scene_id)


def filename(scene: Scene) -> str:
    return f"plan_{scene.id}.png"
