"""FR-7: lesson loading and validation."""
import json
from pathlib import Path

import pytest

from pathlit.lessons.loader import LessonError, load_all, load_lesson

LESSONS = Path(__file__).resolve().parents[1] / "lessons" / "blender"


def _write(tmp_path, data):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _good():
    return json.loads((LESSONS / "001_donut.json").read_text(encoding="utf-8"))


def test_fr7_donut_lesson_loads():
    lesson = load_lesson(LESSONS / "001_donut.json")
    assert lesson.id == "blender-001-donut" and len(lesson.steps) == 9
    assert lesson.steps[1].check.kind == "screen_text_present" and lesson.steps[2].check.kind == "blender_state"


def test_fr7_all_eight_lessons_load_and_have_unique_ids():
    lessons = load_all(LESSONS)
    assert len(lessons) == 8
    assert len({l.id for l in lessons}) == 8


def test_fr7_missing_field_is_rejected_with_the_step_id(tmp_path):
    data = _good()
    del data["steps"][2]["spoken"]
    with pytest.raises(LessonError) as e:
        load_lesson(_write(tmp_path, data))
    assert "step s3" in str(e.value) and "spoken" in str(e.value)


def test_fr7_unknown_check_kind_is_rejected_with_the_step_id(tmp_path):
    data = _good()
    data["steps"][4]["check"] = {"kind": "magic"}
    with pytest.raises(LessonError) as e:
        load_lesson(_write(tmp_path, data))
    assert "step s5" in str(e.value)


def test_fr7_screen_check_without_text_is_rejected(tmp_path):
    data = _good()
    data["steps"][0]["check"] = {"kind": "screen_text_present"}
    with pytest.raises(LessonError) as e:
        load_lesson(_write(tmp_path, data))
    assert "step s1" in str(e.value) and "needs 'text'" in str(e.value)


def test_fr7_blender_check_without_any_field_is_rejected(tmp_path):
    data = _good()
    data["steps"][1]["check"] = {"kind": "blender_state"}
    with pytest.raises(LessonError) as e:
        load_lesson(_write(tmp_path, data))
    assert "step s2" in str(e.value)


def test_fr7_duplicate_step_ids_are_rejected(tmp_path):
    data = _good()
    data["steps"][1]["id"] = "s1"
    with pytest.raises(LessonError) as e:
        load_lesson(_write(tmp_path, data))
    assert "duplicate" in str(e.value)


def test_fr7_not_json_is_a_clear_error(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(LessonError):
        load_lesson(p)


def test_fr7_prereqs_are_skills_that_an_earlier_lesson_teaches():
    lessons = load_all(LESSONS)
    taught = set()
    for l in lessons:
        assert set(l.prereqs) <= taught, f"{l.id} needs a skill no earlier lesson teaches"
        taught |= set(l.skills_taught)


def test_fr7_targets_are_never_coordinates_and_spoken_lines_are_short():
    for l in load_all(LESSONS):
        for s in l.steps:
            assert s.target is None or not any(ch.isdigit() for ch in s.target.text[:1])
            assert len(s.spoken.split(".")) <= 4, f"{l.id}/{s.id} spoken line is too long"
