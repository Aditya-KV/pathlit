"""Typed tasks: the planner turns a goal into a validated, safe lesson (guardrails, labels, checks)."""
import json

import pytest

from pathlit.brain.planner import PlanError, build_lesson, plan_lesson, slugify
from pathlit.brain.teacher import ChatResponse
from pathlit.brain.vocabulary import is_known, known_labels


def good_plan():
    return {"title": "Make a donut", "steps": [
        {"instruction": "Click Add.", "spoken": "Open the Add menu.", "why": "New things start here.", "target": "Add",
         "shortcut": None, "hint": "It is in the top bar."},
        {"instruction": "Click Mesh.", "spoken": "Now click Mesh.", "why": "Meshes are solid shapes.", "target": "Mesh", "hint": "First item."},
        {"instruction": "Click Torus.", "spoken": "Pick Torus.", "why": "A ring, like a donut.", "target": "Torus", "hint": "In the list."},
        {"instruction": "Press Tab to enter Edit mode.", "spoken": "Press Tab.", "why": "Edit mode changes the shape.",
         "target": None, "shortcut": "Tab", "hint": "Hover over the 3D view first."},
    ]}


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def complete(self, model, messages, timeout, effort=None):
        self.calls.append((model, messages, effort))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return ChatResponse(r if isinstance(r, str) else json.dumps(r), 300, 200)


def test_a_good_plan_becomes_a_valid_lesson_with_the_right_checks():
    res = build_lesson("make a donut", good_plan())
    les = res.lesson
    assert les.id == "custom-make-a-donut" and les.title == "Make a donut" and len(les.steps) == 4
    assert [s.check.kind for s in les.steps] == ["clicked_target", "clicked_target", "clicked_target", "none"]
    assert les.steps[0].target.text == "Add" and les.steps[3].target is None and les.steps[3].shortcut == "Tab"
    assert [s.id for s in les.steps] == ["s1", "s2", "s3", "s4"]
    assert les.skills_taught == ["custom-make-a-donut"] and res.unverified_labels == []


def test_labels_that_are_in_neither_list_are_reported_as_unverified_but_kept():
    plan = good_plan()
    plan["steps"][1]["target"] = "Frobnicate Panel"
    plan["steps"][1]["instruction"] = "Click Frobnicate Panel."
    res = build_lesson("x", plan)
    assert res.unverified_labels == ["Frobnicate Panel"] and res.lesson.steps[1].target.text == "Frobnicate Panel"


def test_targets_that_are_not_short_on_screen_text_become_instruction_only_steps():
    plan = good_plan()
    plan["steps"][0]["target"] = "the big blue button in the top left corner of the window"
    plan["steps"][1]["target"] = "   "
    plan["steps"][2]["target"] = 42
    les = build_lesson("x", plan).lesson
    assert [s.target for s in les.steps[:3]] == [None, None, None] and [s.check.kind for s in les.steps[:3]] == ["none"] * 3


def test_steps_about_running_code_are_dropped_and_never_reach_the_learner():
    plan = good_plan()
    plan["steps"].insert(1, {"instruction": "Open the Python console and run bpy.ops.mesh.primitive_torus_add()",
                             "spoken": "Run this script.", "why": "x", "target": "Scripting"})
    plan["steps"].append({"instruction": "Install an add-on for donuts.", "spoken": "Install it.", "why": "x"})
    res = build_lesson("x", plan)
    assert res.dropped_steps == 2 and len(res.lesson.steps) == 4
    assert all("bpy" not in s.instruction and "add-on" not in s.instruction.lower() for s in res.lesson.steps)


def test_a_plan_with_too_few_safe_steps_is_refused():
    with pytest.raises(PlanError):
        build_lesson("x", {"title": "t", "steps": [good_plan()["steps"][0]]})


def test_a_non_blender_goal_gives_the_models_polite_refusal():
    with pytest.raises(PlanError, match="only plan Blender"):
        build_lesson("bake a cake", {"error": "I can only plan Blender tasks."})


def test_garbage_shapes_are_refused_not_crashed_on():
    for bad in ({}, {"steps": "nope"}, {"steps": [None, 5, {}]}, []):
        with pytest.raises(PlanError):
            build_lesson("x", bad)


def test_spoken_lines_are_cut_to_two_sentences_and_thirty_words():
    plan = good_plan()
    plan["steps"][0]["spoken"] = "One. Two. Three. Four."
    plan["steps"][1]["spoken"] = " ".join(["word"] * 80) + "."
    les = build_lesson("x", plan).lesson
    assert les.steps[0].spoken == "One. Two." and len(les.steps[1].spoken.split()) <= 30


def test_the_plan_is_capped_at_forty_five_steps():
    plan = {"title": "long", "steps": [dict(good_plan()["steps"][0], instruction=f"Click item {i}.") for i in range(60)]}
    assert len(build_lesson("x", plan).lesson.steps) == 45


def test_plan_lesson_asks_the_model_with_the_label_lists_and_no_coordinates():
    client = FakeClient([good_plan()])
    res = plan_lesson(client, "big-model", "make a donut")
    model, messages, effort = client.calls[0]
    user = json.loads(messages[1]["content"])
    assert model == "big-model" and effort == "medium" and user["goal"] == "make a donut"
    assert "Add" in user["labels_seen_on_real_screens"] and "Torus" in user["other_standard_labels"]
    assert "coordinates" in messages[0]["content"] and "scripts" in messages[0]["content"]
    assert res.tokens_in == 300 and res.lesson.title == "Make a donut"


def test_invalid_json_is_retried_once_then_reported():
    client = FakeClient(["not json", good_plan()])
    assert plan_lesson(client, "m", "make a donut").lesson.title == "Make a donut"
    assert client.calls[1][1][-1]["content"] == "Return valid JSON only."
    with pytest.raises(PlanError, match="valid JSON"):
        plan_lesson(FakeClient(["nope", "still nope"]), "m", "make a donut")


def test_a_model_that_is_down_gives_a_friendly_error_not_a_crash():
    with pytest.raises(PlanError, match="did not answer"):
        plan_lesson(FakeClient([TimeoutError("slow"), ConnectionError("down")]), "m", "make a donut")


def test_no_model_configured_and_empty_goals_are_explained():
    with pytest.raises(PlanError, match="no Groq key"):
        plan_lesson(None, "m", "make a donut")
    with pytest.raises(PlanError, match="Tell me what"):
        plan_lesson(FakeClient([]), "m", "  ")


def test_json_in_a_code_fence_is_accepted():
    fenced = "```json\n" + json.dumps(good_plan()) + "\n```"
    assert plan_lesson(FakeClient([fenced]), "m", "make a donut").lesson.title == "Make a donut"


def test_vocabulary_lists_cover_the_built_in_lessons_and_never_overlap():
    seen, std = known_labels()
    assert not set(seen) & set(std)
    from pathlib import Path

    from pathlit.lessons.loader import load_all
    lessons = load_all(Path(__file__).resolve().parents[1] / "lessons" / "blender")
    targets = {s.target.text for l in lessons for s in l.steps if s.target}
    assert all(is_known(t) for t in targets), [t for t in targets if not is_known(t)]


def test_slugify_is_safe_for_ids_and_file_names():
    assert slugify("Make a Coffee Mug!!") == "make-a-coffee-mug" and slugify("???") == "task"


def test_a_target_the_instruction_does_not_mention_is_removed_so_the_pointer_matches_the_words():
    plan = good_plan()
    plan["steps"][0]["instruction"] = "Press Shift A to open the menu."          # target says Add, instruction does not
    res = build_lesson("x", plan)
    assert res.lesson.steps[0].target is None and res.lesson.steps[0].check.kind == "none" and res.retargeted == 1


def test_an_icon_step_gets_no_pointer_because_icons_have_no_text_to_find():
    plan = good_plan()
    plan["steps"][1]["instruction"] = "Click the Mesh icon."
    res = build_lesson("x", plan)
    assert res.lesson.steps[1].target is None and res.retargeted == 1


def test_steps_that_still_combine_actions_are_counted_so_the_learner_can_be_told():
    plan = good_plan()
    plan["steps"][0]["instruction"] = "Click Add, then click Mesh."
    plan["steps"][3]["instruction"] = "Press E and press Z."
    assert build_lesson("x", plan).compound_steps == 2


def test_fancy_unicode_is_turned_into_plain_text_for_speech_and_consoles():
    plan = good_plan()
    plan["steps"][0]["spoken"] = "Open the Add‑menu — it’s at the top."
    spoken = build_lesson("x", plan).lesson.steps[0].spoken
    assert spoken == "Open the Add-menu - it's at the top." and spoken.isascii()


# ---------------- menu hierarchy repair ----------------
def step(label, instruction=None):
    return {"instruction": instruction or f"Click {label}.", "spoken": f"Click {label}.", "why": "x", "target": label,
            "hint": "look"}


def targets(res):
    return [s.target.text if s.target else None for s in res.lesson.steps]


def test_a_menu_item_without_its_menu_step_gets_the_missing_step_inserted():
    plan = {"title": "monkey", "steps": [step("Add"), step("Mesh"), step("Monkey"), step("Shade Smooth")]}
    res = build_lesson("x", plan)
    assert targets(res) == ["Add", "Mesh", "Monkey", "Object", "Shade Smooth"] and res.inserted_steps == 1
    assert [s.id for s in res.lesson.steps] == ["s1", "s2", "s3", "s4", "s5"]


def test_a_whole_missing_chain_is_inserted_in_order():
    plan = {"title": "t", "steps": [step("Object Mode"), step("Torus")]}
    assert targets(build_lesson("x", plan)) == ["Object Mode", "Add", "Mesh", "Torus"]


def test_edit_mode_needs_the_mode_dropdown_opened_first():
    res = build_lesson("x", {"title": "t", "steps": [step("Add"), step("Edit Mode")]})
    assert targets(res) == ["Add", "Object Mode", "Edit Mode"]


def test_a_correct_plan_is_left_alone():
    plan = {"title": "t", "steps": [step("Add"), step("Mesh"), step("Cylinder")]}
    res = build_lesson("x", plan)
    assert targets(res) == ["Add", "Mesh", "Cylinder"] and res.inserted_steps == 0


def test_items_from_a_closed_menu_need_the_full_chain_again():
    plan = {"title": "t", "steps": [step("Add"), step("Mesh"), step("Cylinder"), step("Torus")]}
    assert targets(build_lesson("x", plan)) == ["Add", "Mesh", "Cylinder", "Add", "Mesh", "Torus"]


def test_modifier_items_get_the_wrench_step_then_add_modifier_then_the_category():
    res = build_lesson("x", {"title": "t", "steps": [step("Add"), step("Mesh"), step("Subdivision Surface")]})
    assert targets(res) == ["Add", "Mesh", None, "Add Modifier", "Generate", "Subdivision Surface"]
    assert "wrench" in res.lesson.steps[2].instruction and res.lesson.steps[2].check.kind == "none"


def test_a_wrench_step_already_in_the_plan_is_not_added_twice():
    wrench = {"instruction": "Click the wrench icon.", "spoken": "Click it.", "why": "x", "target": None, "hint": "side"}
    res = build_lesson("x", {"title": "t", "steps": [wrench, step("Add Modifier"), step("Generate"), step("Bevel")]})
    assert targets(res) == [None, "Add Modifier", "Generate", "Bevel"]


def test_inserted_steps_are_pointed_steps_with_click_checks_and_obey_the_step_limit():
    res = build_lesson("x", {"title": "t", "steps": [step("Add"), step("Mesh"), step("Monkey"), step("Shade Smooth")]})
    inserted = res.lesson.steps[3]
    assert inserted.target.text == "Object" and inserted.check.kind == "clicked_target" and inserted.instruction == "Click Object."
    long = {"title": "t", "steps": [step("Torus") for _ in range(30)]}
    assert len(build_lesson("x", long).lesson.steps) == 45


def test_ambiguous_labels_are_not_in_the_hierarchy_so_they_are_never_wrongly_repaired():
    from pathlit.brain.vocabulary import MENU_PARENT
    assert "Mirror" not in MENU_PARENT and "Smooth" not in MENU_PARENT and "Remesh" not in MENU_PARENT


def test_a_plan_that_targets_add_modifier_directly_still_gets_the_wrench_step_first():
    res = build_lesson("x", {"title": "t", "steps": [step("Object"), step("Add Modifier"), step("Generate"), step("Bevel")]})
    assert targets(res) == ["Object", None, "Add Modifier", "Generate", "Bevel"]
    assert "wrench" in res.lesson.steps[1].instruction



# ====================================================================== build steps: exact shapes, sizes, positions
def add(shape, part, **kw):
    return {"kind": "add", "shape": shape, "part": part, "spoken": kw.get("spoken", f"Add the {part}."), "why": "w", "hint": "h"}


def setp(prop, values, part, **kw):
    return {"kind": "set", "property": prop, "values": values, "part": part, "spoken": kw.get("spoken", f"Set the {prop}."),
            "why": "w", "hint": "h"}


def house_like():
    return {"title": "A small house", "steps": [
        setp("scale", [1.5, 1.5, 1], "walls"), setp("location", [0, 0, 1], "walls"),
        add("CONE", "roof"), setp("scale", [2.3, 2.3, 1], "roof"), setp("location", [0, 0, 3], "roof"), setp("rotation", [0, 0, 45], "roof"),
        add("CUBE", "door"), setp("scale", [0.35, 0.05, 0.7], "door"), setp("location", [0, -1.52, 0.7], "door")]}


def test_build_steps_become_exact_instructions_and_checks_written_by_the_code():
    res = build_lesson("a house", house_like())
    by = {s.instruction: s for s in res.lesson.steps}
    s = by["Walls: set Scale to X 1.5, Y 1.5, Z 1."]
    assert s.target.text == "Scale" and s.check.kind == "blender_state" and s.check.scale_approx == [1.5, 1.5, 1.0]
    assert s.do.direct == {"action": "set_transform", "args": {"property": "scale", "values": [1.5, 1.5, 1.0]}} and s.do.click is False
    r = by["Roof: set Rotation to X 0, Y 0, Z 45 degrees."]
    assert r.check.rotation_approx == [0.0, 0.0, 45.0] and r.target.text == "Rotation"
    assert res.build_steps == 9 and res.uses_default_scene


def test_the_first_cube_is_the_default_cube_so_no_extra_cube_is_added():
    plan = {"title": "t", "steps": [add("CUBE", "walls"), setp("scale", [1.5, 1.5, 1], "walls"), setp("location", [0, 0, 1], "walls")]}
    res = build_lesson("x", plan)
    assert [s.instruction for s in res.lesson.steps][0].startswith("Walls: set Scale")
    assert not any(s.do and s.do.direct and s.do.direct["action"] == "add_primitive" for s in res.lesson.steps)


def test_adding_a_shape_inserts_the_menu_clicks_and_do_it_skips_them():
    res = build_lesson("x", {"title": "t", "steps": [setp("scale", [1, 1, 1.2], "walls"), add("CONE", "roof"),
                                                     setp("scale", [2, 2, 1], "roof")]})
    steps = res.lesson.steps
    assert [s.target.text for s in steps] == ["Scale", "Add", "Mesh", "Cone", "Scale"]
    assert steps[1].do.skip_in_do and steps[2].do.skip_in_do                      # opening the menus is skipped by Do it
    cone = steps[3]
    assert cone.do.direct["action"] == "add_primitive" and cone.do.direct["args"] == {"type": "CONE"}
    assert cone.check.active_object_name_contains == "Cone" and cone.check.object_count_at_least == 4


def test_every_added_shape_raises_the_expected_object_count_so_the_check_cannot_pass_early():
    res = build_lesson("x", {"title": "t", "steps": [setp("scale", [1, 1, 1], "a"), add("CYLINDER", "b"), add("SPHERE", "c")]})
    counts = [s.check.object_count_at_least for s in res.lesson.steps if s.check.object_count_at_least]
    assert counts == [4, 5]
    assert [s.check.active_object_name_contains for s in res.lesson.steps if s.check.object_count_at_least] == ["Cylinder", "Sphere"]


def test_bad_numbers_and_shapes_are_dropped_not_guessed():
    plan = {"title": "t", "steps": [setp("scale", [1, 1, 1], "a"), setp("scale", [1, 1], "bad"), setp("scale", ["x", 1, 1], "bad"),
                                    setp("scale", [0, 1, 1], "zero"), setp("location", [1e9, 0, 0], "far"), setp("spin", [1, 1, 1], "bad"),
                                    setp("location", [None, None, None], "empty"), add("TEAPOT", "bad"), setp("location", [0, 0, 1], "a")]}
    res = build_lesson("x", plan)
    assert len(res.lesson.steps) == 2 and res.dropped_steps == 7


def test_null_axes_are_left_alone_and_left_out_of_the_instruction():
    res = build_lesson("x", {"title": "t", "steps": [setp("location", [None, None, 2.5], "lamp"), setp("scale", [1, 1, 2], "lamp")]})
    s = res.lesson.steps[0]
    assert s.instruction == "Lamp: set Location to Z 2.5." and s.check.location_approx == [None, None, 2.5]


def test_geometry_warnings_catch_floating_and_sunken_parts():
    floating = build_lesson("x", {"title": "t", "steps": [setp("scale", [1.5, 1.5, 1], "walls"), setp("location", [0, 0, 1], "walls"),
                                                           add("CONE", "roof"), setp("scale", [2, 2, 1], "roof"),
                                                           setp("location", [0, 0, 9], "roof")]})
    assert any("roof" in w and "float" in w for w in floating.warnings)
    sunk = build_lesson("x", {"title": "t", "steps": [setp("scale", [1, 1, 1], "box"), setp("location", [0, 0, 0], "box")]})
    assert any("sinks" in w for w in sunk.warnings)
    good = build_lesson("x", house_like())
    assert good.warnings == [] or all("float" not in w for w in good.warnings)


def test_a_plan_that_never_uses_the_default_cube_is_warned_it_stays_behind():
    res = build_lesson("x", {"title": "t", "steps": [add("CYLINDER", "post"), setp("scale", [0.2, 0.2, 2], "post"),
                                                     setp("location", [4, 0, 2], "post")]})
    assert any("default cube is still in the scene" in w for w in res.warnings)


def test_model_text_about_code_is_dropped_from_build_steps_too():
    plan = {"title": "t", "steps": [setp("scale", [1, 1, 1], "a"), setp("location", [0, 0, 1], "a", spoken="Run import bpy first."),
                                    setp("location", [0, 0, 2], "a")]}
    res = build_lesson("x", plan)
    assert res.dropped_steps == 1 and all("bpy" not in s.spoken for s in res.lesson.steps)


def test_plain_ui_steps_still_work_next_to_build_steps():
    plan = {"title": "t", "steps": [setp("scale", [1, 1, 1], "a"), setp("location", [0, 0, 1], "a"),
                                    {"instruction": "Click Object.", "target": "Object", "spoken": "Open Object.", "why": "w", "hint": "h"},
                                    {"instruction": "Click Shade Smooth.", "target": "Shade Smooth", "spoken": "Smooth.", "why": "w", "hint": "h"}]}
    kinds = [s.check.kind for s in build_lesson("x", plan).lesson.steps]
    assert kinds == ["blender_state", "blender_state", "clicked_target", "clicked_target"]


def test_the_system_prompt_teaches_the_geometry_and_demands_numbers():
    from pathlit.brain.planner import PLAN_SYSTEM
    for phrase in ("2 units across", "Location Z = its Scale Z", "Do the arithmetic", "FIRST part", "null", "Never give pixel coordinates"):
        assert phrase in PLAN_SYSTEM, phrase


# ====================================================================== geometry self-check
def buried_roof_plan():
    return {"title": "house", "steps": [setp("scale", [2, 1.5, 1.25], "walls"), setp("location", [0, 0, 1.25], "walls"), add("CONE", "roof"),
                                        setp("scale", [2, 1.5, 0.75], "roof"), setp("location", [0, 0, 2], "roof")]}   # roof sunk into the walls


def fixed_roof_plan():
    p = buried_roof_plan()
    p["steps"][-1] = setp("location", [0, 0, 3.25], "roof")
    return p


def test_a_roof_buried_in_the_walls_is_detected_with_the_numbers_to_fix_it():
    res = build_lesson("x", buried_roof_plan())
    assert any("roof" in w and "inside the walls" in w and "2.50" in w for w in res.warnings), res.warnings
    assert any(line.startswith("roof (cone): x -2.00 to 2.00") and "z 1.25 to 2.75" in line for line in res.geometry_table)


def test_a_correctly_stacked_roof_has_no_warnings():
    res = build_lesson("x", fixed_roof_plan())
    assert res.warnings == [] and any("z 2.50 to 4.00" in line for line in res.geometry_table)


def test_doors_and_windows_on_the_outside_face_are_not_flagged_as_buried():
    plan = fixed_roof_plan()
    plan["steps"] += [add("CUBE", "door"), setp("scale", [0.2, 0.05, 0.9], "door"), setp("location", [0, 1.55, 0.9], "door")]
    assert build_lesson("x", plan).warnings == []


class Seq:
    """A model that gives the planned replies in order and records what it was asked."""
    def __init__(self, replies):
        self.replies, self.asked = list(replies), []

    def complete(self, model, messages, timeout, effort=None):
        self.asked.append(messages)
        r = self.replies.pop(0)
        return ChatResponse(r if isinstance(r, str) else json.dumps(r), 100, 50)


def test_the_model_is_shown_its_own_geometry_and_asked_to_fix_it_once():
    client = Seq([buried_roof_plan(), fixed_roof_plan()])
    res = plan_lesson(client, "m", "a house")
    assert res.corrected and res.warnings == []
    assert len(client.asked) == 2
    ask = client.asked[1][-1]["content"]
    assert "Check your geometry" in ask and "roof (cone)" in ask and "inside the walls" in ask
    assert res.tokens_in == 200


def test_if_the_correction_is_no_better_the_first_plan_is_kept_and_a_broken_reply_is_harmless():
    res = plan_lesson(Seq([buried_roof_plan(), buried_roof_plan()]), "m", "a house")
    assert not res.corrected and res.warnings
    res = plan_lesson(Seq([buried_roof_plan(), "not json at all"]), "m", "a house")
    assert not res.corrected and res.lesson.steps


def test_a_clean_plan_costs_only_one_model_call():
    client = Seq([fixed_roof_plan()])
    assert plan_lesson(client, "m", "a house").warnings == [] and len(client.asked) == 1


def test_the_prompt_has_the_stacking_recipe_with_a_worked_number():
    from pathlit.brain.planner import PLAN_SYSTEM
    assert "STACKING RECIPE" in PLAN_SYSTEM and "2.5 + 0.75 = 3.25" in PLAN_SYSTEM


def test_rotation_is_part_of_the_geometry_an_upright_plane_door_is_not_flat():
    from pathlit.brain.builder import Part, _box
    door = Part("door", "PLANE", [0, 2.0, 1.0], [90, 0, 0], [0.5, 1, 1])
    lo, hi = _box(door)
    assert abs((hi[2] - lo[2]) - 2.0) < 1e-6 and (hi[1] - lo[1]) < 1e-6 and abs((hi[0] - lo[0]) - 1.0) < 1e-6   # tall, thin, 1 wide


def test_a_flat_door_on_the_wall_face_is_not_called_buried_in_the_roof():
    plan = fixed_roof_plan()
    plan["steps"] += [add("PLANE", "door"), setp("rotation", [90, 0, 0], "door"), setp("scale", [0.5, 0.9, 1], "door"),
                      setp("location", [0, 1.52, 0.9], "door")]
    res = build_lesson("x", plan)
    assert not any("door" in w for w in res.warnings), res.warnings
    assert any("door (plane)" in line and "z 0.00 to 1.80" in line for line in res.geometry_table)


def test_a_plane_hanging_flat_in_the_air_is_flagged_as_an_invisible_sliver():
    plan = fixed_roof_plan()
    plan["steps"] += [add("PLANE", "door"), setp("scale", [0.5, 0.01, 1], "door"), setp("location", [0, 1.51, 1], "door")]
    assert any("door" in w and "invisible sliver" in w and "CUBE" in w for w in build_lesson("x", plan).warnings)


def test_a_chimney_floating_above_the_tip_of_a_cone_roof_is_flagged_but_one_starting_inside_it_is_not():
    float_plan = fixed_roof_plan() | {}
    float_plan["steps"] = list(float_plan["steps"]) + [add("CYLINDER", "chimney"), setp("scale", [0.2, 0.2, 0.75], "chimney"),
                                                      setp("location", [0.3, 0, 4.75], "chimney")]        # bottom at 4.0, roof tip 4.0
    ok_plan = fixed_roof_plan() | {}
    ok_plan["steps"] = list(ok_plan["steps"]) + [add("CYLINDER", "chimney"), setp("scale", [0.2, 0.2, 0.75], "chimney"),
                                                setp("location", [0.8, 0, 3.4], "chimney")]               # bottom 2.65, inside the roof
    assert any("chimney" in w and "floats" in w for w in build_lesson("x", float_plan).warnings)
    assert not any("chimney" in w and "floats" in w for w in build_lesson("x", ok_plan).warnings)


def test_the_prompt_forbids_planes_for_doors_and_windows_and_gives_a_cube_recipe():
    from pathlit.brain.planner import PLAN_SYSTEM
    assert "NEVER use PLANE" in PLAN_SYSTEM and "scale [0.5, 0.06, 0.9]" in PLAN_SYSTEM



# ====================================================================== free-tier rate limit
class RateLimited(Exception):
    pass


class Flaky:
    """Fails with Groq's rate-limit message the first time, then answers."""
    def __init__(self, replies, message):
        self.replies, self.message, self.calls = list(replies), message, 0

    def complete(self, model, messages, timeout, effort=None):
        self.calls += 1
        if self.calls == 1 or (self.calls == 3 and len(self.replies) == 1):
            raise RateLimited(self.message)
        r = self.replies.pop(0)
        return ChatResponse(r if isinstance(r, str) else json.dumps(r), 10, 10)


def test_retry_after_is_read_from_groqs_message():
    from pathlit.brain.planner import retry_after_seconds
    msg = "Error code: 429 - Rate limit reached ... Please try again in 7.2s. Need more tokens?"
    assert retry_after_seconds(Exception(msg)) == 7.2
    assert retry_after_seconds(Exception("Error code: 429 - ... try again in 830ms")) == pytest.approx(0.83)
    assert retry_after_seconds(Exception("Error code: 429 - ... try again in 2m")) == 120
    assert retry_after_seconds(Exception("Error code: 429 - rate limit, no hint")) == 8.0
    assert retry_after_seconds(Exception("Connection refused")) is None


def test_a_rate_limit_is_waited_out_once_and_the_planner_tells_the_learner(monkeypatch):
    from pathlit.brain import planner
    slept, told = [], []
    monkeypatch.setattr(planner.time, "sleep", lambda s: slept.append(s))
    client = Flaky([fixed_roof_plan()], "Error code: 429 - Please try again in 4.0s")
    res = plan_lesson(client, "m", "a house", on_wait=told.append)
    assert res.lesson.steps and slept == [4.5] and told == [4.0]


def test_a_rate_limit_that_wants_more_than_30_seconds_is_not_waited_for(monkeypatch):
    from pathlit.brain import planner
    monkeypatch.setattr(planner.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("must not sleep")))
    class Always:
        def complete(self, model, messages, timeout, effort=None):
            raise RateLimited("Error code: 429 - Please try again in 90s")
    with pytest.raises(PlanError, match="did not answer"):
        plan_lesson(Always(), "m", "a house")


def test_if_the_correction_round_is_rate_limited_it_waits_then_uses_the_corrected_plan(monkeypatch):
    from pathlit.brain import planner
    monkeypatch.setattr(planner.time, "sleep", lambda s: None)

    class Second:
        def __init__(self):
            self.n = 0

        def complete(self, model, messages, timeout, effort=None):
            self.n += 1
            if self.n == 1:
                return ChatResponse(json.dumps(buried_roof_plan()), 10, 10)
            if self.n == 2:
                raise RateLimited("Error code: 429 - Please try again in 5s")      # the correction round hits the limit
            return ChatResponse(json.dumps(fixed_roof_plan()), 10, 10)
    res = plan_lesson(Second(), "m", "a house")
    assert res.corrected and res.warnings == []
