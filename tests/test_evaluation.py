"""Phase 3 tooling: hit test, engine comparison, step-check scoring, caching, the capture plan and the label canvas maths."""
import json
from pathlib import Path

import pytest
from PIL import Image

from pathlit.capture_plan import CORE, L, PLAN, VARIETY, filename, scene_by_id
from pathlit.evaluation import (PointingResult, ReportCache, is_hit, load_labels, pointing_outcome, route_local_first,
                                save_labels, stepcheck_outcome, summarize_pointing, summarize_stepcheck)
from pathlit.lessons.loader import load_all
from pathlit.models import ActiveObject, BlenderState, Element, ScreenReport
from pathlit.ui.label_widget import drag_to_bbox, fit_scale, image_to_view, view_to_image

LESSONS = {l.id: l for l in load_all(Path(__file__).resolve().parents[1] / "lessons" / "blender")}


def report(*items, engine="azure", ms=100):
    """items: (text, x, y, w, h) words, each also its own line."""
    els = []
    for i, (t, x, y, w, h) in enumerate(items):
        els += [Element(text=t, bbox=(x, y, w, h), confidence=0.9, kind="line", line=i),
                Element(text=t, bbox=(x, y, w, h), confidence=0.9, kind="word", line=i)]
    return ScreenReport(engine=engine, image_size=(2880, 1700), elements=els, elapsed_ms=ms)


# ---------------- hit test ----------------
def test_hit_is_inside_the_true_box_with_a_five_pixel_margin():
    box = [100, 100, 50, 20]
    assert is_hit((125, 110), box) and is_hit((96, 96), box) and is_hit((154, 124), box)
    assert not is_hit((94, 110), box) and not is_hit((125, 126), box)


def test_pointing_outcome_hit_miss_and_not_found():
    rep = report(("Add", 500, 110, 52, 22), ("Object", 600, 110, 70, 22))
    assert pointing_outcome(rep, "Add", [498, 108, 56, 26])["hit"]
    wrong = pointing_outcome(rep, "Add", [1000, 1000, 50, 20])
    assert wrong["found"] and not wrong["hit"] and "true box" in wrong["reason"]
    assert pointing_outcome(rep, "Mesh", [0, 0, 10, 10]) == {"found": False, "hit": False, "score": 0.0,
                                                             "reason": "target text not found by the reader"}


def test_the_tip_used_is_the_one_the_overlay_really_draws():
    from pathlit.overlay.arrow import tip_for
    rep = report(("Add", 500, 100, 50, 20))
    tip = tip_for((500, 100, 50, 20))                       # x centre, 55% down
    assert is_hit(tip, [500, 100, 50, 20], 0) and tip == (525, 111)


# ---------------- router experiment ----------------
def test_router_keeps_the_local_answer_when_it_finds_the_target_and_calls_azure_otherwise():
    mir = report(("Add", 500, 100, 50, 20), engine="mirage", ms=2200)
    az = report(("Add", 500, 100, 50, 20), ("Mesh", 500, 140, 50, 20), engine="azure", ms=800)
    rep, used, ms, calls = route_local_first(lambda _i: mir, lambda _i: az, None, "Add")
    assert (rep.engine, used, ms, calls) == ("mirage", "mirage", 2200, 0)
    rep, used, ms, calls = route_local_first(lambda _i: mir, lambda _i: az, None, "Mesh")
    assert (rep.engine, used, ms, calls) == ("azure", "azure", 3000, 1)               # both engines' time counts


def test_summary_per_engine_counts_hits_median_time_and_azure_calls():
    rows = [PointingResult("a.png", "Add", "mirage", True, True, 100, 2000, "mirage", 0),
            PointingResult("b.png", "Add", "mirage", False, False, 0, 2400, "mirage", 0),
            PointingResult("a.png", "Add", "azure", True, True, 100, 700, "azure", 1),
            PointingResult("b.png", "Add", "azure", True, True, 100, 900, "azure", 1)]
    s = summarize_pointing(rows)
    assert s["mirage"]["accuracy"] == 0.5 and s["mirage"]["median_ms"] == 2200 and s["mirage"]["azure_calls"] == 0
    assert s["azure"]["accuracy"] == 1.0 and s["azure"]["azure_calls"] == 2 and s["azure"]["answered_by"] == {"azure": 2}


# ---------------- step checks ----------------
def state(mode="OBJECT", name="Cube", mods=(), count=3):
    return BlenderState(blender_version="4.1.1", mode=mode, object_count=count,
                        active_object=ActiveObject(name=name, type="MESH", modifiers=list(mods)))


def case(step, expected, lesson=1):
    return {"image": "x.png", "lesson": L[lesson], "step": step, "expected": expected}


def test_stepcheck_screen_check_correct_and_wrong():
    les = LESSONS[L[1]]
    done = report(("Mesh", 500, 100, 50, 20))
    assert stepcheck_outcome(case("s1", True), les, done, None).correct is True
    r = stepcheck_outcome(case("s1", False), les, done, None)            # the reader saw Mesh but truth says not done
    assert r.correct is False and r.passed is True
    assert stepcheck_outcome(case("s1", True), les, report(("Add", 1, 1, 5, 5)), None).correct is False


def test_stepcheck_uses_the_recorded_blender_state_and_falls_back_to_screen_text_without_it():
    les = LESSONS[L[1]]
    assert stepcheck_outcome(case("s9", True), les, None, state(mods=["SUBSURF"])).correct is True
    assert stepcheck_outcome(case("s9", False), les, None, state()).correct is True
    # no state: the screen-text fallback ('Subdivision') decides, like the app with the Blender link down
    assert stepcheck_outcome(case("s9", True), les, report(("Subdivision", 1, 1, 50, 20)), None).passed is True


def test_checks_that_do_not_depend_on_the_screen_are_skipped_not_scored():
    r = stepcheck_outcome(case("s5", True), LESSONS[L[1]], report(("Cube", 1, 1, 5, 5)), None)       # s5 is a 'none' check
    assert r.passed is None and r.correct is None


def test_stepcheck_summary_separates_false_passes_from_false_fails():
    les = LESSONS[L[1]]
    rows = [stepcheck_outcome(case("s1", True), les, report(("Mesh", 1, 1, 50, 20)), None),         # correct
            stepcheck_outcome(case("s1", False), les, report(("Mesh", 1, 1, 50, 20)), None),        # false pass
            stepcheck_outcome(case("s1", True), les, report(("Add", 1, 1, 50, 20)), None),          # false fail
            stepcheck_outcome(case("s5", True), les, None, None)]                                   # skipped
    s = summarize_stepcheck(rows)
    assert (s["cases"], s["evaluated"], s["skipped"], s["correct"]) == (4, 3, 1, 1)
    assert (s["false_pass"], s["false_fail"]) == (1, 1) and s["by_kind"]["screen_text_present"] == {"cases": 3, "correct": 1}


def test_an_unknown_step_id_is_an_error_not_a_silent_skip():
    with pytest.raises(ValueError):
        stepcheck_outcome(case("s99", True), LESSONS[L[1]], None, None)


# ---------------- labels and cache ----------------
def test_labels_round_trip_and_bad_boxes_are_rejected(tmp_path):
    p = tmp_path / "labels.json"
    save_labels(p, {"a.png": [{"text": "Add", "bbox": [1, 2, 30, 10]}], "empty.png": []})
    assert load_labels(p) == {"a.png": [{"text": "Add", "bbox": [1, 2, 30, 10]}]}              # empty images are not written
    p.write_text(json.dumps({"b.png": {"targets": [{"text": "X", "bbox": [1, 2, 0, 10]}]}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_labels(p)


def test_the_cache_returns_the_stored_report_without_calling_the_engine_again(tmp_path):
    img = tmp_path / "s.png"
    Image.new("RGB", (8, 8), "white").save(img)
    cache = ReportCache(tmp_path / "cache", tag="t")
    calls = []

    def read():
        calls.append(1)
        return report(("Add", 1, 1, 5, 5))
    rep1, hit1 = cache.get_or_read("azure", img, read)
    rep2, hit2 = cache.get_or_read("azure", img, read)
    assert (hit1, hit2, len(calls)) == (False, True, 1) and rep2 == rep1
    assert cache.get_or_read("mirage", img, read)[1] is False                                  # other engine: separate entry
    assert ReportCache(tmp_path / "cache", tag="other").get_or_read("azure", img, read)[1] is False   # other settings: re-measure


# ---------------- the capture plan ----------------
def test_the_plan_has_fifty_unique_scenes_and_names():
    assert len(PLAN) == 50 and len(CORE) == 24 and len(VARIETY) == 26
    assert len({s.id for s in PLAN}) == 50 and len({filename(s) for s in PLAN}) == 50
    assert scene_by_id("p05").id == "p05"


def test_every_planned_case_names_a_real_lesson_step_and_most_can_be_scored_from_a_screenshot():
    scored = 0
    for sc in PLAN:
        for lesson, step, done in sc.cases:
            les = LESSONS[lesson]
            st = next((x for x in les.steps if x.id == step), None)
            assert st is not None, f"{sc.id}: {lesson} has no step {step}"
            assert isinstance(done, bool)
            scored += st.check.kind in ("screen_text_present", "blender_state")
    assert scored >= 30                                                                        # SRS: at least 30 step-check cases


def test_the_plan_proves_each_screen_check_both_done_and_not_done():
    seen = {}
    for sc in PLAN:
        for lesson, step, done in sc.cases:
            st = next(x for x in LESSONS[lesson].steps if x.id == step)
            if st.check.kind in ("screen_text_present", "blender_state"):
                seen.setdefault((lesson, step), set()).add(done)
    both = [k for k, v in seen.items() if v == {True, False}]
    assert len(both) >= 15, f"only {len(both)} checks are tested in both directions"


def test_planned_targets_are_texts_the_lessons_or_menus_really_use():
    from pathlit.brain.vocabulary import is_known
    for sc in PLAN:
        for t in sc.targets:
            assert is_known(t), f"{sc.id}: {t!r} is not a known Blender label"


# ---------------- label canvas maths ----------------
def test_view_and_image_coordinates_round_trip_at_any_scale():
    sc = fit_scale((2880, 1700), (1000, 700))
    off = ((1000 - 2880 * sc) / 2, (700 - 1700 * sc) / 2)
    for pt in [(0, 0), (1440, 850), (2880, 1700), (123.5, 77.25)]:
        back = view_to_image(image_to_view(pt, sc, off), sc, off)
        assert back == pytest.approx(pt)


def test_dragging_a_box_works_in_any_direction_and_is_clipped_to_the_image():
    assert drag_to_bbox((50, 40), (10, 10), (100, 100)) == [10, 10, 40, 30]
    assert drag_to_bbox((-20, -20), (30, 30), (100, 100)) == [0, 0, 30, 30]
    assert drag_to_bbox((90, 90), (200, 200), (100, 100)) == [90, 90, 10, 10]
    assert drag_to_bbox((10, 10), (12, 11), (100, 100)) is None                                # a stray click


# ---------------- session log keeps one consistent layout ----------------
def test_a_session_csv_with_an_old_header_is_set_aside_not_mixed_with_new_rows(tmp_path):
    from pathlit.logging_utils import COLUMNS, SessionCsv
    p = tmp_path / "session.csv"
    p.write_text("ts,old_column\n2026-01-01,1\n", encoding="utf-8")
    log = SessionCsv(p)
    log.write({"ts": "now", "status": "ok"})
    assert p.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLUMNS)
    old = list(tmp_path.glob("session.old-*.csv"))
    assert len(old) == 1 and "old_column" in old[0].read_text(encoding="utf-8")
    SessionCsv(p).write({"ts": "later"})                                   # same layout: appended, nothing moved
    assert len(list(tmp_path.glob("session.old-*.csv"))) == 1 and len(p.read_text(encoding="utf-8").splitlines()) == 3
