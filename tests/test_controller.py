"""The hotkey cycle with fakes: FR-1, FR-5, FR-8, FR-10, FR-11, FR-12, FR-13, FR-17, FR-19 (no screen, Blender or network)."""
import csv
import time
from pathlib import Path
from types import SimpleNamespace as NS

from PIL import Image

from pathlit.brain.docs_search import Snippet
from pathlit.brain.teacher import Teacher, TeacherResult
from pathlit.controller import BRIDGE_NOTICE, Controller
from pathlit.lessons.loader import load_all
from pathlit.logging_utils import SessionCsv
from pathlit.models import ActiveObject, BlenderState, Element, ScreenReport
from pathlit.skillmap import SkillMap

LESSONS = load_all(Path(__file__).resolve().parents[1] / "lessons" / "blender")
DONUT = LESSONS[0]


def rep(*lines: str) -> ScreenReport:
    """One line of text per argument; words are laid out left to right."""
    els = []
    for i, text in enumerate(lines):
        words = text.split()
        els.append(Element(text=text, bbox=(500, 100 + 60 * i, 60 * len(words), 20), confidence=0.9, kind="line", line=i))
        for j, w in enumerate(words):
            els.append(Element(text=w, bbox=(500 + 60 * j, 100 + 60 * i, 55, 20), confidence=0.9, kind="word", line=i))
    return ScreenReport(engine="fake", image_size=(2880, 1700), elements=els, elapsed_ms=5)


def st(mode="OBJECT", name="Cube", mods=(), count=3):
    return BlenderState(blender_version="4.1.1", mode=mode, object_count=count, selected_count=1,
                        active_object=ActiveObject(name=name, type="MESH", modifiers=list(mods)))


class FakeOverlay:
    logical_width = 1440

    def __init__(self):
        self.arrows, self.hides, self.clears, self.dismissed = [], 0, 0, 0

    def clear(self):
        self.clears += 1

    def dismiss(self):
        self.dismissed += 1

    def hide_and_wait(self):
        self.hides += 1

    def show_arrow(self, bbox, text, size, obstacles=None):
        self.arrows.append((bbox, text, size))
        self.obstacles = obstacles


class FakeSpeaker:
    def __init__(self):
        self.said, self.stops = [], 0

    def speak(self, text, on_first_audio=None):
        self.said.append(text)
        ts = time.perf_counter()
        if on_first_audio:
            on_first_audio(ts)
        return ts

    def stop(self):
        self.stops += 1


class Script:
    """Hands out the next prepared value on each call, repeating the last one."""
    def __init__(self, items):
        self.items, self.i = list(items), 0

    def next(self):
        v = self.items[min(self.i, len(self.items) - 1)]
        self.i += 1
        return v


class FakeReader:
    def __init__(self, reports, fail_on=()):
        self.s, self.fail_on, self.calls = Script(reports), set(fail_on), 0

    def read(self, _img):
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("azure down")
        return self.s.next()


class FakeBridge:
    def __init__(self, states):
        self.s = Script(states)

    def get_state(self):
        return self.s.next()


class FakeTeacher:
    def __init__(self, fail=False):
        self.ctxs, self.fail = [], fail

    def compose(self, ctx):
        self.ctxs.append(ctx)
        if self.fail:
            return TeacherResult(ctx.step.spoken, "fallback", "continue", reason="network off")
        return TeacherResult(f"SAY {ctx.step.id} {ctx.kind}", "model", "continue", "small-model", 10, 5, 20,
                             model_target="Something Else")


class FakeDocs:
    def __init__(self):
        self.queries = []

    def lookup(self, q, top=3):
        self.queries.append(q)
        return [Snippet("Subdivision Surface Modifier", "Options", "text"), Snippet("Modifiers", "Intro", "text")]


def _grab():
    return NS(image=Image.new("RGB", (8, 8)), width=2880, height=1700)


def make(tmp_path, reports, states=(None,), lessons=None, teacher=None, reader=None, skillmap=None, docs=None):
    sm = skillmap or SkillMap(":memory:")
    ov, sp = FakeOverlay(), FakeSpeaker()
    c = Controller(lessons or LESSONS, sm, _grab, reader or FakeReader(reports), FakeBridge(states), teacher or FakeTeacher(),
                   docs or FakeDocs(), sp, ov, SessionCsv(tmp_path / "s.csv"), hide_settle_s=0)
    return c, ov, sp, sm, tmp_path / "s.csv"


def rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def press(c):
    c.on_hotkey()
    c.wait()


# ---------------- FR-1, FR-19 ----------------
def test_fr1_hotkey_logged_within_100ms_even_when_work_is_slow(tmp_path, caplog):
    class SlowReader(FakeReader):
        def read(self, img):
            time.sleep(0.4)
            return super().read(img)
    caplog.set_level("INFO")
    c, *_ = make(tmp_path, [rep("Add")], reader=SlowReader([rep("Add")]))
    c.on_hotkey()
    assert c.last_hotkey_log_ms < 100 and any("event=hotkey_pressed" in r.message for r in caplog.records)
    c.wait()


def test_fr19_one_row_per_press_with_timings_and_model_columns(tmp_path):
    c, *_ , path = make(tmp_path, [rep("Add")])
    for _ in range(3):
        press(c)
    rs = rows(path)
    assert len(rs) == 3
    first = rs[0]
    assert first["lesson_id"] == DONUT.id and first["step_id"] == "s1" and first["decision"] == "present"
    for col in ("capture_ms", "read_ms", "engine", "arrow_ms", "first_audio_ms", "total_ms", "model_source", "tokens_in"):
        assert first[col] != "", col


def test_fr19_press_while_busy_is_logged_not_dropped(tmp_path):
    class SlowReader(FakeReader):
        def read(self, img):
            time.sleep(0.4)
            return super().read(img)
    c, *_, path = make(tmp_path, None, reader=SlowReader([rep("Add")]))
    c.on_hotkey()
    time.sleep(0.05)
    c.on_hotkey()
    c.wait()
    assert sorted(r["status"] for r in rows(path)) == ["ignored_busy", "ok"]


# ---------------- FR-5, FR-17 ----------------
def test_fr5_overlay_hidden_before_capture_and_arrow_at_the_target(tmp_path):
    c, ov, *_ = make(tmp_path, [rep("File Edit Add Object")])
    press(c)
    assert ov.hides == 1 and len(ov.arrows) == 1 and ov.obstacles       # text boxes are passed so the bubble can avoid them
    bbox, text, size = ov.arrows[0]
    assert bbox == (500 + 60 * 2, 100, 55, 20) and size == (2880, 1700) and "Add menu" in text


def test_fr17_target_missing_means_no_arrow_and_a_question(tmp_path):
    c, ov, sp, _, path = make(tmp_path, [rep("Camera Light")])
    press(c)
    assert ov.arrows == []
    assert "Can you see Add?" in sp.said[-1]
    assert rows(path)[0]["status"] == "not_found"


def test_fr17_step_without_a_text_target_gets_no_arrow_and_no_question(tmp_path):
    donut = DONUT
    c, ov, sp, sm, _ = make(tmp_path, [rep("Add Modifier")], lessons=[donut])
    c.engine = None
    # fast-forward the engine to step s5 (index 4), which has no target
    from pathlit.lessons.engine import LessonEngine
    eng = LessonEngine(donut, sm)
    eng.begin()
    for _ in range(4):
        eng.resolve(True)
    c.engine = eng
    # step s5 is shown; its check is 'none', so the next press shows s6 (the wrench icon: no text target)
    press(c)
    assert ov.arrows == [] and "can't find" not in sp.said[-1].lower()


# ---------------- FR-8: whole lesson ----------------
def test_fr8_wrong_action_does_not_advance_and_repeats_the_step(tmp_path):
    reports = [rep("Add"), rep("Camera Light"), rep("Camera Light")]      # 'Mesh' never appears: the learner did not open Add
    teacher = FakeTeacher()
    c, ov, sp, sm, path = make(tmp_path, reports, teacher=teacher)
    press(c)       # shows s1
    press(c)       # check s1 fails -> repeat s1
    rs = rows(path)
    assert rs[1]["decision"] == "retry" and rs[1]["step_id"] == "s1" and rs[1]["check_passed"] == "0"
    assert teacher.ctxs[-1].kind == "retry" and teacher.ctxs[-1].attempt == 1 and not teacher.ctxs[-1].stuck
    press(c)
    assert teacher.ctxs[-1].stuck and teacher.ctxs[-1].attempt == 2        # larger model + hint after two failures
    assert sm.recent_results(DONUT.id)[-1] == ("s1", False, 1)


def test_fr8_lesson_one_runs_start_to_finish_with_step_checks(tmp_path):
    reports = [
        rep("File Edit Add Object"),                     # 1  -> show s1 (Add)
        rep("Mesh", "Curve", "Add"),                     # 2  -> check s1 (Mesh visible) ok, show s2 (Mesh)
        rep("Mesh", "Torus", "Cylinder"),                # 3  -> check s2 (Torus visible) ok, show s3 (Torus)
        rep("Object", "Add"),                            # 4  -> check s3 via Blender state (Torus), show s4 (Object)
        rep("Shade Smooth", "Shade Flat"),               # 5  -> check s4 (Shade Smooth visible), show s5
        rep("Cube"),                                     # 6  -> check s5 (none), show s6 (wrench icon: no text target)
        rep("Add Modifier"),                             # 7  -> check s6 (Add Modifier visible), show s7
        rep("Generate", "Deform"),                       # 8  -> check s7 (Generate visible), show s8
        rep("Subdivision Surface"),                      # 9  -> check s8 (Subdivision Surface visible), show s9
        rep("Cube"),                                     # 10 -> check s9 via Blender state (SUBSURF) -> complete
    ]
    states = [None, None, None, st(name="Torus"), None, None, None, None, None, st(name="Torus", mods=["SUBSURF"])]
    c, ov, sp, sm, path = make(tmp_path, reports, states=states, lessons=LESSONS)
    for _ in range(10):
        press(c)
    rs = rows(path)
    ids = [r["step_id"] for r in rs]
    assert ids == ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s9"], ids
    assert [r["decision"] for r in rs] == ["present"] * 9 + ["complete"]
    assert rs[-1]["status"] == "lesson_complete"
    assert "Lesson complete: Model a donut" in sp.said[-1] and "Next up" in sp.said[-1]
    assert set(DONUT.skills_taught) <= sm.completed_skills()
    assert len(ov.arrows) == 8                                  # s6 has no text target, and the finish has no pointer


def test_fr13_after_finishing_lesson_1_the_next_press_starts_the_suggested_lesson(tmp_path):
    sm = SkillMap(":memory:")
    sm.complete_lesson(DONUT)
    c, ov, sp, _, path = make(tmp_path, [rep("Object Mode")], skillmap=sm)
    press(c)
    r = rows(path)[0]
    assert r["lesson_id"] == LESSONS[1].id and "Lesson: Switch between Object and Edit mode." in sp.said[-1]


def test_all_lessons_done_is_handled(tmp_path):
    sm = SkillMap(":memory:")
    for l in LESSONS:
        sm.complete_lesson(l)
    c, _, sp, _, path = make(tmp_path, [rep("Add")], skillmap=sm)
    press(c)
    assert rows(path)[0]["status"] == "all_done" and "finished every lesson" in sp.said[-1]


# ---------------- FR-10, FR-11, FR-12 ----------------
def test_fr10_blender_link_down_uses_screen_fallback_and_tells_the_learner_once(tmp_path):
    reports = [rep("Add"), rep("Mesh Torus"), rep("Object Torus")]
    c, ov, sp, _, path = make(tmp_path, reports, states=[None])
    for _ in range(3):
        press(c)
    assert sum(BRIDGE_NOTICE in s for s in sp.said) == 1
    rs = rows(path)
    assert rs[1]["blender_ok"] == "0" and rs[2]["check_passed"] == "1"       # s2 passed via fallback text 'Torus'


def test_fr10_blender_state_is_used_when_available(tmp_path):
    reports = [rep("Add"), rep("Mesh"), rep("Object")]
    c, _, sp, _, path = make(tmp_path, reports, states=[st(name="Cube")])    # Torus never becomes active
    for _ in range(3):
        press(c)
    rs = rows(path)
    assert rs[2]["check_passed"] == "0" and "Torus" in rs[2]["check_reason"]
    assert all(BRIDGE_NOTICE not in s for s in sp.said)


def test_fr11_with_the_model_down_the_lesson_still_runs_on_its_own_text(tmp_path):
    reports = [rep("Add"), rep("Mesh")]
    c, _, sp, _, path = make(tmp_path, reports, teacher=FakeTeacher(fail=True))
    press(c)
    press(c)
    assert DONUT.steps[0].spoken in sp.said[0]
    assert rows(path)[1]["step_id"] == "s2" and rows(path)[1]["model_source"] == "fallback"


def test_fr11_azure_reading_failure_does_not_crash_and_is_not_held_against_the_learner(tmp_path):
    reader = FakeReader([rep("Add"), rep("Mesh")], fail_on={2})
    c, ov, sp, sm, path = make(tmp_path, None, reader=reader)
    press(c)
    press(c)                      # reading fails on this press
    rs = rows(path)
    assert rs[1]["status"] == "read_failed" and sm.recent_results(DONUT.id) == []
    assert "press the key again" in sp.said[-1]
    press(c)                      # works again and the learner is judged now
    assert rows(path)[2]["decision"] == "present" and rows(path)[2]["step_id"] == "s2"


def test_fr12_manual_page_titles_are_logged_and_given_to_the_teacher(tmp_path):
    teacher, docs = FakeTeacher(), FakeDocs()
    c, _, _, _, path = make(tmp_path, [rep("Add")], teacher=teacher, docs=docs)
    press(c)
    assert DONUT.steps[0].docs_query in docs.queries
    assert [s.title for s in teacher.ctxs[0].snippets] == ["Subdivision Surface Modifier", "Modifiers"]
    assert rows(path)[0]["docs_titles"] == "Modifiers; Subdivision Surface Modifier"


def test_the_arrow_never_comes_from_the_model_target(tmp_path):
    c, ov, *_ = make(tmp_path, [rep("File Add Something Else")])
    press(c)
    assert ov.arrows[0][0] == (500 + 60, 100, 55, 20)        # 'Add' (the lesson's target), not the model's 'Something Else'


def test_speech_and_bubble_never_contain_the_target_coordinates(tmp_path):
    c, ov, sp, _, _ = make(tmp_path, [rep("File Add")])
    press(c)
    bbox = ov.arrows[0][0]
    for number in map(str, bbox):
        assert number not in sp.said[0].replace("SAY s1 present", "") and number not in ov.arrows[0][1]


def test_the_arrow_prefers_the_target_nearest_the_previous_one(tmp_path):
    """Lesson 5: Add, then Light. The screen shows 'Light' twice (Outliner object, and the Add menu item)."""
    sm = SkillMap(":memory:")
    sm.complete_lesson(DONUT)
    cam = LESSONS[4]                                  # blender-005-camera-light (needs add-mesh, done)
    sm.complete_lesson(LESSONS[1])
    reports = [rep("Add"), rep("Light", "Add", "Light")]
    c, ov, *_ = make(tmp_path, reports, lessons=[cam], skillmap=sm)
    press(c)                                          # s1: points at Add (500,100)
    first = ov.arrows[0][0]
    # build a report with an Outliner 'Light' far away and a menu 'Light' close to the Add button
    far = Element(text="Light", bbox=(2500, 80, 50, 20), confidence=0.9, kind="line", line=0)
    near = Element(text="Light", bbox=(first[0], first[1] + 300, 50, 20), confidence=0.9, kind="line", line=1)
    farw = Element(text="Light", bbox=far.bbox, confidence=0.9, kind="word", line=0)
    nearw = Element(text="Light", bbox=near.bbox, confidence=0.9, kind="word", line=1)
    addl = Element(text="Mesh Light", bbox=(500, 400, 50, 20), confidence=0.9, kind="line", line=2)
    meta = Element(text="Metaball", bbox=(500, 440, 60, 20), confidence=0.9, kind="line", line=3)    # lesson 5 s1 check text
    metaw = Element(text="Metaball", bbox=(500, 440, 60, 20), confidence=0.9, kind="word", line=3)
    c.reader = FakeReader([ScreenReport(engine="fake", image_size=(2880, 1700),
                                        elements=[far, farw, near, nearw, addl, meta, metaw], elapsed_ms=1)])
    press(c)                                          # check s1 (needs 'Light' on screen): ok; s2 target 'Light'
    assert ov.arrows[1][0] == near.bbox
