"""Auto-advance: the lesson follows the learner's clicks in Blender instead of waiting for the hotkey."""
import csv
import time
from pathlib import Path

from test_controller import (DONUT, LESSONS, FakeBridge, FakeDocs, FakeOverlay, FakeReader, FakeSpeaker, FakeTeacher, _grab,
                             rep, st)

from pathlit.controller import Controller
from pathlit.logging_utils import SessionCsv
from pathlit.skillmap import SkillMap


def build(tmp_path, reports, states=(None,), lessons=None, auto=True, settle=0.05, idle=0.0, focus=None, skillmap=None,
          overlay=None, second_look=0.1, fast=0.02, on_state=None):
    sm = skillmap or SkillMap(":memory:")
    ov, sp = overlay or FakeOverlay(), FakeSpeaker()
    c = Controller(lessons or [DONUT], sm, _grab, FakeReader(reports), FakeBridge(states), FakeTeacher(), FakeDocs(), sp, ov,
                   SessionCsv(tmp_path / "s.csv"), hide_settle_s=0, auto_advance=auto, settle_s=settle, idle_hint_s=idle,
                   foreground_ok=focus, fast_settle_s=fast, second_look_s=second_look, on_state=on_state)
    return c, ov, sp, sm, tmp_path / "s.csv"


def rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def start(c):
    c.on_hotkey()
    c.wait()


def click(c):
    c.on_activity()
    c.wait()


def test_a_click_that_finishes_the_step_moves_the_lesson_on_by_itself(tmp_path):
    c, ov, sp, _, path = build(tmp_path, [rep("File Edit Add"), rep("Mesh", "Curve", "Add")])
    start(c)                                    # F8 starts the lesson: s1 (Add)
    click(c)                                    # the learner opened the Add menu
    rs = rows(path)
    assert [r["trigger"] for r in rs] == ["manual", "auto"]
    assert rs[1]["check_passed"] == "1" and rs[1]["step_id"] == "s2" and rs[1]["decision"] == "present"
    assert len(ov.arrows) == 2 and len(sp.said) == 2


def test_a_click_in_the_middle_of_a_step_says_nothing_and_does_not_count_as_a_failure(tmp_path):
    c, ov, sp, sm, path = build(tmp_path, [rep("File Edit Add"), rep("Camera", "Light")])     # Mesh never appears
    start(c)
    said_before, arrows_before = len(sp.said), len(ov.arrows)
    click(c)
    rs = rows(path)
    assert rs[1]["status"] == "auto_wait" and rs[1]["decision"] == "wait"
    assert len(sp.said) == said_before and len(ov.arrows) == arrows_before           # quiet, pointer stays put
    assert sm.recent_results(DONUT.id) == []                                         # not logged as a failed try
    assert c.engine.current_step.id == "s1"


def test_clicks_before_a_lesson_is_started_are_ignored(tmp_path):
    c, ov, sp, _, path = build(tmp_path, [rep("Add")])
    click(c)
    assert not path.exists() or rows(path) == []
    assert sp.said == [] and ov.arrows == []


def test_nothing_is_read_unless_blender_has_the_focus(tmp_path):
    focused = {"on": True}
    c, ov, sp, _, path = build(tmp_path, [rep("File Edit Add"), rep("Mesh", "Add")], focus=lambda: focused["on"])
    start(c)
    focused["on"] = False                       # the learner switched to another app
    reader = c.reader
    calls = reader.calls
    click(c)
    assert reader.calls == calls                # no screenshot was taken
    assert [r["trigger"] for r in rows(path)] == ["manual"]


def test_a_burst_of_clicks_is_checked_once(tmp_path):
    c, _, _, _, path = build(tmp_path, [rep("File Edit Add"), rep("Mesh", "Add")], settle=0.15)
    start(c)
    for _ in range(6):
        c.on_activity()
        time.sleep(0.02)
    c.wait()
    assert [r["trigger"] for r in rows(path)].count("auto") == 1


def test_a_click_during_a_cycle_is_looked_at_afterwards_not_lost(tmp_path):
    class Slow(FakeReader):
        def read(self, img):
            time.sleep(0.3)
            return super().read(img)
    c, _, _, _, path = build(tmp_path, [rep("File Edit Add")])
    c.reader = Slow([rep("File Edit Add"), rep("Mesh", "Add"), rep("Mesh", "Torus")])
    c.on_hotkey()
    time.sleep(0.1)
    c.on_activity()                             # arrives while the first cycle is still running
    c.wait()
    time.sleep(0.4)
    c.wait()
    assert "auto" in [r["trigger"] for r in rows(path)]


def test_when_the_learner_stalls_the_step_is_explained_again(tmp_path):
    c, ov, sp, sm, path = build(tmp_path, [rep("File Edit Add"), rep("Camera")], idle=0.25)
    start(c)
    click(c)                                    # waiting: Mesh not visible
    time.sleep(0.9)                             # the learner does nothing for a long while
    c.wait()
    rs = rows(path)
    assert [r["trigger"] for r in rs].count("idle") == 1                        # nudged once, not every few seconds
    assert rs[-1]["trigger"] == "idle" and rs[-1]["decision"] == "retry"
    assert sm.recent_results(DONUT.id) == [("s1", False, 0)]


def test_the_hotkey_still_explains_a_failed_step_at_once(tmp_path):
    c, _, sp, _, path = build(tmp_path, [rep("File Edit Add"), rep("Camera")])
    start(c)
    c.on_hotkey()
    c.wait()
    assert rows(path)[1]["decision"] == "retry" and rows(path)[1]["trigger"] == "manual"


def test_with_auto_advance_off_clicks_do_nothing(tmp_path):
    c, _, _, _, path = build(tmp_path, [rep("File Edit Add"), rep("Mesh", "Add")], auto=False)
    start(c)
    click(c)
    assert len(rows(path)) == 1


# ---------------- the learner runs ahead ----------------
def test_a_learner_who_runs_ahead_is_caught_up_instead_of_getting_stuck(tmp_path):
    """Add, Mesh and Torus clicked quickly: the Torus exists although the lesson is still on s1."""
    reports = [rep("File Edit Add"), rep("Object", "Add")]
    c, ov, _, sm, path = build(tmp_path, reports, states=[None, st(name="Torus")])
    start(c)
    click(c)
    r = rows(path)[1]
    assert r["check_passed"] == "1" and "caught up" in r["check_reason"] and r["step_id"] == "s4"
    assert [x[0] for x in sm.recent_results(DONUT.id, 10)] == ["s1", "s2", "s3"]           # skipped steps are logged as done


def test_catch_up_does_not_trust_mode_only_checks(tmp_path):
    """Lesson 4's last step is 'mode is OBJECT', which is already true at the start, so it must not cause a skip."""
    lesson4 = LESSONS[3]
    sm = SkillMap(":memory:")
    sm.complete_lesson(DONUT)
    sm.complete_lesson(LESSONS[1])
    c, _, _, _, path = build(tmp_path, [rep("Object Mode"), rep("Add")], states=[None, st(mode="OBJECT")], lessons=[lesson4],
                             skillmap=sm)
    start(c)
    click(c)
    assert rows(path)[1]["status"] == "auto_wait" and c.engine.current_step.id == "s1"


def test_catch_up_needs_the_blender_link(tmp_path):
    c, _, _, _, path = build(tmp_path, [rep("File Edit Add"), rep("Object", "Add")], states=[None])
    start(c)
    click(c)
    assert rows(path)[1]["status"] == "auto_wait"


# ---------------- the pointer can stay on screen ----------------
def test_when_the_overlay_is_invisible_to_capture_it_is_not_hidden_for_each_check(tmp_path):
    ov = FakeOverlay()
    ov.excluded_from_capture = True
    c, ov, *_ = build(tmp_path, [rep("File Edit Add")], overlay=ov)
    start(c)
    assert ov.hides == 0


def test_when_the_overlay_can_be_captured_it_is_hidden_first(tmp_path):
    c, ov, *_ = build(tmp_path, [rep("File Edit Add")])
    start(c)
    assert ov.hides == 1


# ---------------- lag and lingering fixes ----------------
from pathlit.lessons.loader import Lesson  # noqa: E402


def custom(*targets, check="clicked_target"):
    """A learner-requested lesson: one click per target."""
    steps = [{"id": f"s{i + 1}", "instruction": f"Click {t}.", "spoken": f"Click {t}.", "why": "because",
              "target": {"text": t} if t else None, "check": {"kind": check if t else "none"}} for i, t in enumerate(targets)]
    return Lesson.model_validate({"id": "custom-test", "title": "My task", "tool": "blender",
                                  "skills_taught": ["custom-test"], "steps": steps})


def test_the_pointer_is_cleared_when_the_next_step_has_nothing_to_point_at(tmp_path):
    lesson = custom("Add", None)                                   # step 2 has no text target (an icon, say)
    c, ov, sp, _, path = build(tmp_path, [rep("File Edit Add")], lessons=[lesson])
    start(c)
    click_pos = c._target_bbox
    c.on_activity(click_pos[0] + 5, click_pos[1] + 5)               # click the pointed target
    c.wait()
    assert ov.clears >= 1 and rows(path)[-1]["step_id"] == "s2"


def test_the_pointer_is_cleared_when_the_lesson_completes(tmp_path):
    lesson = custom("Add")
    c, ov, sp, _, path = build(tmp_path, [rep("File Edit Add")], lessons=[lesson])
    start(c)
    b = c._target_bbox
    c.on_activity(b[0] + 5, b[1] + 5)
    c.wait()
    assert rows(path)[-1]["status"] == "lesson_complete" and ov.clears >= 1


def test_clicking_the_pointed_target_dismisses_the_pointer_immediately(tmp_path):
    c, ov, *_ = build(tmp_path, [rep("File Edit Add")], lessons=[custom("Add", "Mesh")])
    start(c)
    b = c._target_bbox
    c.on_activity(b[0] + b[2] / 2, b[1] + b[3] / 2)
    assert ov.dismissed == 1 and c._clicked_target
    c.wait()


def test_a_click_elsewhere_does_not_dismiss_the_pointer(tmp_path):
    c, ov, *_ = build(tmp_path, [rep("File Edit Add")], lessons=[custom("Add", "Mesh")])
    start(c)
    c.on_activity(5, 5)
    assert ov.dismissed == 0 and not c._clicked_target
    c.wait()


def test_click_positions_are_understood_in_screen_pixels_or_scaled_screen_pixels(tmp_path):
    c, ov, *_ = build(tmp_path, [rep("File Edit Add")], lessons=[custom("Add", "Mesh")])
    start(c)
    b = c._target_bbox                                              # real pixels; the capture is 2880 wide, the fake screen 1440
    assert c._click_hit(b[0] + 3, b[1] + 3)
    assert c._click_hit((b[0] + 3) / 2, (b[1] + 3) / 2)             # the same spot in half-size (logical) coordinates
    assert not c._click_hit(b[0] + 400, b[1] + 400)
    c.wait()


def test_a_clicked_target_step_advances_on_the_right_click_without_reading_for_the_check(tmp_path):
    reports = [rep("File Edit Add"), rep("Mesh", "Curve")]
    c, ov, sp, _, path = build(tmp_path, reports, lessons=[custom("Add", "Mesh")])
    start(c)
    reads = c.reader.calls
    c.on_activity(5, 5)                                             # a wrong click
    c.wait()
    assert c.reader.calls == reads and rows(path)[-1]["status"] == "auto_wait"     # no Vision call spent on a wrong click
    b = c._target_bbox
    c.on_activity(b[0] + 5, b[1] + 5)                               # the right click
    c.wait()
    r = rows(path)[-1]
    assert r["check_passed"] == "1" and r["step_id"] == "s2" and r["decision"] == "present"
    assert len(ov.arrows) == 2


def test_the_hotkey_moves_a_clicked_target_step_on_even_without_a_click(tmp_path):
    c, ov, sp, _, path = build(tmp_path, [rep("File Edit Add"), rep("Mesh", "Curve")], lessons=[custom("Add", "Mesh")])
    start(c)
    c.on_hotkey()                                                   # "I did it, move on"
    c.wait()
    assert rows(path)[-1]["step_id"] == "s2"


def test_a_second_look_catches_a_screen_that_changed_a_moment_late(tmp_path):
    reports = [rep("File Edit Add"), rep("Camera"), rep("Mesh", "Curve", "Add")]       # the menu is not open at the first look
    c, ov, sp, _, path = build(tmp_path, reports, second_look=0.15)
    start(c)
    c.on_activity()
    c.wait()
    rs = rows(path)
    assert [r["status"] for r in rs[1:]] == ["auto_wait", "ok"] and rs[-1]["step_id"] == "s2"
    assert [r["trigger"] for r in rs] == ["manual", "auto", "auto"]


def test_the_second_look_happens_only_once_per_click(tmp_path):
    c, *_, path = build(tmp_path, [rep("File Edit Add"), rep("Camera")], second_look=0.1)
    start(c)
    c.on_activity()
    c.wait()
    time.sleep(0.5)
    c.wait()
    assert len(rows(path)) == 3                                     # manual, first look, one second look


# ---------------- a task the learner asked for ----------------
def test_a_learner_requested_lesson_is_queued_listed_and_followed(tmp_path):
    seen = []
    c, ov, sp, sm, path = build(tmp_path, [rep("File Edit Add"), rep("Mesh", "Curve")], lessons=[DONUT],
                                on_state=seen.append)
    lesson = custom("Add", "Mesh")
    c.queue_lesson(lesson)
    assert seen[-1] == {"title": "My task", "steps": ["Click Add.", "Click Mesh."], "index": -1, "complete": False,
                        "custom": True}
    start(c)                                                        # F8 begins the queued lesson, not lesson 1
    assert rows(path)[0]["lesson_id"] == "custom-test" and seen[-1]["index"] == 0
    b = c._target_bbox
    c.on_activity(b[0] + 5, b[1] + 5)
    c.wait()
    assert seen[-1]["index"] == 1


def test_finishing_a_requested_lesson_does_not_change_the_skill_map(tmp_path):
    seen = []
    c, ov, sp, sm, path = build(tmp_path, [rep("File Edit Add")], lessons=[DONUT], on_state=seen.append)
    c.queue_lesson(custom("Add"))
    start(c)
    b = c._target_bbox
    c.on_activity(b[0] + 5, b[1] + 5)
    c.wait()
    assert seen[-1]["complete"] is True and sm.completed_skills() == set()
