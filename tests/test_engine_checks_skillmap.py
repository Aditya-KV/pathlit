"""FR-8 (step loop), step checks, FR-13 (skill map)."""
from pathlib import Path

import pytest

from pathlit.lessons.checks import run_check
from pathlit.lessons.engine import STUCK_AFTER, LessonEngine
from pathlit.lessons.loader import Check, load_all
from pathlit.models import ActiveObject, BlenderState, Element, ScreenReport
from pathlit.skillmap import SkillMap

LESSONS = load_all(Path(__file__).resolve().parents[1] / "lessons" / "blender")


def _report(*words):
    els = [Element(text=w, bbox=(10, 10 + 30 * i, 50, 20), confidence=0.9, kind="word", line=i) for i, w in enumerate(words)]
    return ScreenReport(engine="t", image_size=(1000, 1000), elements=els, elapsed_ms=1)


def _state(mode="OBJECT", name="Torus", mods=(), count=1):
    return BlenderState(blender_version="4.1.1", mode=mode, object_count=count, selected_count=1,
                        active_object=ActiveObject(name=name, type="MESH", modifiers=list(mods)) if name else None)


# ---- checks ----
def test_check_none_always_passes():
    assert run_check(Check(kind="none"), None, None).passed


def test_check_screen_text_present_pass_and_fail():
    c = Check(kind="screen_text_present", text="Mesh")
    assert run_check(c, _report("Add", "Mesh"), None).passed
    assert not run_check(c, _report("Add", "Remesh"), None).passed       # Remesh must not count as Mesh
    assert not run_check(c, None, None).passed


def test_check_blender_state_all_fields_must_match():
    c = Check(kind="blender_state", mode="OBJECT", active_object_name_contains="torus", modifier_present="SUBSURF",
              object_count_at_least=1)
    assert run_check(c, None, _state(mods=["SUBSURF"])).passed
    assert not run_check(c, None, _state(mods=[])).passed
    assert not run_check(c, None, _state(mode="EDIT_MESH", mods=["SUBSURF"])).passed
    assert not run_check(c, None, _state(name="Cube", mods=["SUBSURF"])).passed
    assert not run_check(c, None, _state(count=0, mods=["SUBSURF"])).passed
    assert not run_check(c, None, _state(name=None)).passed


def test_fr10_bridge_down_uses_screen_fallback_or_says_unverified():
    with_fb = Check(kind="blender_state", active_object_name_contains="Torus", fallback_text="Torus")
    assert run_check(with_fb, _report("Torus"), None).passed
    assert not run_check(with_fb, _report("Cube"), None).passed
    no_fb = Check(kind="blender_state", mode="OBJECT")
    r = run_check(no_fb, None, None)
    assert r.passed and not r.verified


# ---- engine ----
def _engine():
    lesson = LESSONS[0]
    return LessonEngine(lesson, SkillMap(":memory:")), lesson


def test_fr8_first_press_presents_step_one():
    eng, lesson = _engine()
    d = eng.begin()
    assert d.kind == "present" and d.step.id == lesson.steps[0].id and d.previous_passed is None


def test_fr8_wrong_action_does_not_advance_and_repeats_the_step():
    eng, lesson = _engine()
    eng.begin()
    d = eng.resolve(False)
    assert d.kind == "retry" and d.step.id == lesson.steps[0].id and d.attempt == 1 and not d.stuck
    assert eng.current_step.id == lesson.steps[0].id


def test_fr8_right_action_advances():
    eng, lesson = _engine()
    eng.begin()
    d = eng.resolve(True)
    assert d.kind == "present" and d.step.id == lesson.steps[1].id and d.previous_passed


def test_fr8_two_failures_mark_the_learner_as_stuck():
    eng, _ = _engine()
    eng.begin()
    last = None
    for _ in range(STUCK_AFTER):
        last = eng.resolve(False)
    assert last.stuck and last.attempt == STUCK_AFTER
    assert eng.resolve(True).stuck is False            # progress clears it


def test_fr8_finishing_the_last_step_completes_the_lesson_and_saves_skills():
    eng, lesson = _engine()
    eng.begin()
    d = None
    for _ in lesson.steps:
        d = eng.resolve(True)
    assert d.kind == "complete" and d.step is None
    assert set(lesson.skills_taught) <= eng.skillmap.completed_skills()


# ---- skill map ----
def test_fr13_finishing_lesson_1_changes_the_suggested_next_lesson():
    sm = SkillMap(":memory:")
    assert sm.next_lesson(LESSONS).id == LESSONS[0].id
    sm.complete_lesson(LESSONS[0])
    nxt = sm.next_lesson(LESSONS)
    assert nxt.id == LESSONS[1].id and nxt.id != LESSONS[0].id


def test_fr13_lessons_with_unmet_prereqs_are_skipped():
    sm = SkillMap(":memory:")
    by_id = {l.id: l for l in LESSONS}
    # nothing done: lesson 2 needs add-mesh, so the first suggestion must not be it
    assert sm.next_lesson([by_id["blender-002-edit-mode"], by_id["blender-003-workspaces"]]).id == "blender-003-workspaces"


def test_fr13_skillmap_survives_restart(tmp_path):
    db = tmp_path / "s.db"
    sm = SkillMap(db)
    sm.complete_lesson(LESSONS[0])
    assert set(LESSONS[0].skills_taught) <= SkillMap(db).completed_skills()


def test_fr13_step_log_records_results():
    sm = SkillMap(":memory:")
    sm.log_step("L", "s1", False, 0)
    sm.log_step("L", "s1", True, 1)
    assert sm.recent_results("L") == [("s1", False, 0), ("s1", True, 1)]



# ---------------- numeric transform checks ----------------
def _obj_state(location=(0, 0, 1), rotation=(0, 0, 0), scale=(1.5, 1.5, 1)):
    return BlenderState(blender_version="4.1.1", mode="OBJECT", object_count=4,
                        active_object=ActiveObject(name="Cube", type="MESH", location=list(location), rotation=list(rotation),
                                                   scale=list(scale)))


def test_numeric_checks_compare_each_axis_within_the_tolerance():
    c = Check(kind="blender_state", scale_approx=[1.5, 1.5, 1.0], location_approx=[None, None, 1.0])
    assert run_check(c, None, _obj_state()).passed
    assert run_check(c, None, _obj_state(scale=(1.54, 1.5, 1))).passed                 # within 0.05
    r = run_check(c, None, _obj_state(scale=(1.5, 1.5, 2.0)))
    assert not r.passed and "Z is 2, want 1" in r.reason
    assert not run_check(c, None, _obj_state(location=(0, 0, 3))).passed


def test_null_axes_are_ignored_and_rotation_has_a_wider_tolerance():
    c = Check(kind="blender_state", rotation_approx=[None, None, 45.0])
    assert run_check(c, None, _obj_state(rotation=(80, -20, 45.8))).passed             # other axes ignored; 0.8 degrees is fine
    assert not run_check(c, None, _obj_state(rotation=(0, 0, 50))).passed


def test_an_old_addon_that_does_not_report_transforms_gives_a_clear_reason_not_a_crash():
    old = BlenderState(blender_version="4.1.1", mode="OBJECT", object_count=3, active_object=ActiveObject(name="Cube", type="MESH"))
    r = run_check(Check(kind="blender_state", scale_approx=[1, 1, 1]), None, old)
    assert not r.passed and "did not report the scale" in r.reason


def test_a_numeric_only_check_is_a_valid_check_and_an_empty_one_is_not():
    Check(kind="blender_state", location_approx=[0, 0, 1])
    with pytest.raises(Exception):
        Check(kind="blender_state")
